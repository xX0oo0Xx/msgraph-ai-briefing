from __future__ import annotations

from .sanitize import EmailItem
from .schema import Briefing, EmailTriage

MAX_TOP_ITEMS = 3
MAX_SUMMARY_CHARS = 300


def reconcile(briefing: Briefing, emails: list[EmailItem]) -> tuple[Briefing, list[str]]:
    """Enforce output invariants the model is asked for but cannot be trusted to guarantee."""
    known = {e.id: e for e in emails}
    issues: list[str] = []
    seen = set()
    kept: list[EmailTriage] = []

    for t in briefing.emails:
        if t.id not in known:
            issues.append(f"dropped triage for unknown id {t.id!r}")
            continue
        if t.id in seen:
            issues.append(f"dropped duplicate triage for {t.id}")
            continue
        seen.add(t.id)

        update = {}
        if known[t.id].flags and t.category != "suspicious":
            issues.append(f"{t.id}: pre-screen flagged injection, model said {t.category!r}")
            update = {"category": "suspicious", "injection_suspected": True}
        elif t.injection_suspected and t.category != "suspicious":
            issues.append(f"{t.id}: injection suspected but category {t.category!r}")
            update = {"category": "suspicious"}
        if len(t.summary) > MAX_SUMMARY_CHARS:
            update["summary"] = t.summary[: MAX_SUMMARY_CHARS - 1] + "…"
        kept.append(t.model_copy(update=update) if update else t)

    for e in emails:
        if e.id not in seen:
            issues.append(f"{e.id}: missing from model output, added for manual review")
            kept.append(
                EmailTriage(id=e.id, category="fyi", summary="Not triaged; review manually.")
            )

    order = {e.id: i for i, e in enumerate(emails)}
    kept.sort(key=lambda t: order[t.id])

    top_items = briefing.top_items
    if len(top_items) > MAX_TOP_ITEMS:
        issues.append(f"trimmed top_items from {len(top_items)} to {MAX_TOP_ITEMS}")
        top_items = top_items[:MAX_TOP_ITEMS]

    return briefing.model_copy(update={"emails": kept, "top_items": top_items}), issues
