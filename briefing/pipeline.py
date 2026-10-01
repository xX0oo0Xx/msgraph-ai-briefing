from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from .auth import GraphAuth
from .config import GRAPH_SCOPES, Settings
from .graph_client import GraphClient
from .guardrails import reconcile
from .llm import AnthropicTriager, TriageResult
from .prompts import PROMPT_VERSION
from .render import to_html, to_text
from .sanitize import EmailItem, EventItem, normalize_all
from .schema import Briefing
from .telemetry import RunLogger


class Triager(Protocol):
    model: str

    def triage(
        self, emails: list[EmailItem], events: list[EventItem], now: datetime
    ) -> TriageResult: ...


@dataclass
class Outcome:
    briefing: Briefing
    text: str
    html: str
    html_path: Path
    guardrail_issues: list[str] = field(default_factory=list)
    sent_to: str | None = None


def load_input_file(
    path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], datetime | None]:
    """Accepts saved Graph output ({messages, events}) or the eval dataset ({cases})."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if "cases" in data:
        messages = [c["message"] for c in data["cases"]]
    else:
        messages = data.get("messages") or []
    now = datetime.fromisoformat(data["now"]) if data.get("now") else None
    return messages, data.get("events") or [], now


def make_graph_client(settings: Settings) -> GraphClient:
    settings.require_graph()
    auth = GraphAuth(
        settings.client_id, settings.authority, GRAPH_SCOPES, settings.token_cache_path
    )
    return GraphClient(auth.get_token, outlook_timezone=settings.outlook_timezone)


def run(
    settings: Settings,
    logger: RunLogger,
    source: str = "graph",
    input_path: Path | None = None,
    send: bool = False,
    triager: Triager | None = None,
    graph: GraphClient | None = None,
    now: datetime | None = None,
) -> Outcome:
    logger.set(source=source, prompt_version=PROMPT_VERSION)

    with logger.stage("fetch"):
        if source == "file":
            if input_path is None:
                raise ValueError("--input is required when --source file")
            raw_messages, raw_events, file_now = load_input_file(input_path)
            now = now or file_now
        else:
            graph = graph or make_graph_client(settings)
            now = now or datetime.now().astimezone()
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            raw_messages = graph.unread_messages(
                since=now - timedelta(hours=settings.lookback_hours), limit=settings.max_emails
            )
            raw_events = graph.events_between(day_start, day_start + timedelta(days=1))
        now = now or datetime.now().astimezone()

    with logger.stage("sanitize"):
        emails, events = normalize_all(raw_messages, raw_events)
        logger.set(
            counts={
                "emails": len(emails),
                "events": len(events),
                "prescreen_flagged": sum(1 for e in emails if e.flags),
            }
        )

    with logger.stage("triage"):
        if not emails and not events:
            briefing = Briefing(headline="Inbox clear and nothing on the calendar today.")
        else:
            if triager is None:
                settings.require_llm()
                triager = AnthropicTriager(settings.anthropic_api_key, settings.anthropic_model)
            result = triager.triage(emails, events, now)
            logger.record_llm(
                result.model, result.input_tokens, result.output_tokens, result.attempts
            )
            briefing = result.briefing

    with logger.stage("guardrails"):
        briefing, issues = reconcile(briefing, emails)
        logger.set(guardrail_issues=issues)

    with logger.stage("render"):
        text = to_text(briefing, emails, events, now)
        html = to_html(briefing, emails, events, now)
        settings.out_dir.mkdir(parents=True, exist_ok=True)
        html_path = settings.out_dir / f"briefing-{now:%Y-%m-%d}-{logger.run_id}.html"
        html_path.write_text(html, encoding="utf-8")

    outcome = Outcome(briefing, text, html, html_path, issues)

    if send:
        with logger.stage("send"):
            graph = graph or make_graph_client(settings)
            recipient = settings.recipient
            if not recipient:
                me = graph.me()
                recipient = me.get("mail") or me.get("userPrincipalName")
            graph.send_mail(recipient, f"Daily briefing - {now:%a %b %d}", html)
            outcome.sent_to = recipient
            logger.set(sent=True)

    return outcome
