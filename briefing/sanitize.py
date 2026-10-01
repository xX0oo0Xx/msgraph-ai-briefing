from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MAX_SUBJECT_CHARS = 200
MAX_PREVIEW_CHARS = 600

FLAG_INJECTION = "possible_prompt_injection"

# Applied in order: longer digit runs first so a card number is not half-matched as a phone.
_REDACTIONS = [
    ("CARD", re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")),
    ("SIN", re.compile(r"(?<!\d)\d{3}[ -]\d{3}[ -]\d{3}(?!\d)")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]\d{4}(?!\d)")),
]

_INJECTION_PATTERNS = [
    re.compile(
        r"\b(ignore|disregard|forget|override)\b.{0,40}\b(instructions?|prompts?|rules)\b", re.I
    ),
    re.compile(r"\byou are now\b", re.I),
    re.compile(r"\b(system prompt|developer mode|admin mode|jailbreak)\b", re.I),
    re.compile(
        r"\b(note|message|instructions?)\s+(to|for)\s+(the\s+|any\s+)?"
        r"(ai|llm|assistant|chatbot|copilot)s?\b",
        re.I,
    ),
    re.compile(r"</?\s*(system|instructions?|untrusted_data|email|emails|calendar)\b", re.I),
]


@dataclass
class EmailItem:
    id: str
    sender_name: str
    sender_address: str
    subject: str
    received: str
    preview: str
    importance: str = "normal"
    has_attachments: bool = False
    graph_id: str | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class EventItem:
    subject: str
    start: str
    end: str
    is_all_day: bool = False
    location: str = ""
    organizer: str = ""
    is_online: bool = False

    def when(self) -> str:
        if self.is_all_day:
            return "all day"
        return f"{_hhmm(self.start)}-{_hhmm(self.end)}"


def _hhmm(graph_datetime: str) -> str:
    # Graph returns e.g. "2026-09-29T09:00:00.0000000" in the Prefer timezone.
    return graph_datetime[11:16] if len(graph_datetime) >= 16 else graph_datetime


def clean_text(text: str, max_len: int) -> str:
    collapsed = re.sub(r"\s+", " ", text or "").strip()
    if len(collapsed) > max_len:
        return collapsed[: max_len - 1].rstrip() + "…"
    return collapsed


def redact(text: str) -> str:
    for label, pattern in _REDACTIONS:
        text = pattern.sub(f"[REDACTED-{label}]", text)
    return text


def detect_injection(text: str) -> bool:
    return any(p.search(text) for p in _INJECTION_PATTERNS)


def normalize_message(raw: dict[str, Any], index: int) -> EmailItem:
    address = (raw.get("from") or raw.get("sender") or {}).get("emailAddress") or {}
    subject = clean_text(raw.get("subject") or "(no subject)", MAX_SUBJECT_CHARS)
    preview = clean_text(raw.get("bodyPreview") or "", MAX_PREVIEW_CHARS)
    flags = [FLAG_INJECTION] if detect_injection(f"{subject}\n{preview}") else []
    return EmailItem(
        id=f"e{index}",
        sender_name=clean_text(address.get("name") or "", 100),
        sender_address=(address.get("address") or "").strip().lower(),
        subject=redact(subject),
        received=raw.get("receivedDateTime") or "",
        preview=redact(preview),
        importance=raw.get("importance") or "normal",
        has_attachments=bool(raw.get("hasAttachments")),
        graph_id=raw.get("id"),
        flags=flags,
    )


def normalize_event(raw: dict[str, Any]) -> EventItem:
    organizer = ((raw.get("organizer") or {}).get("emailAddress") or {}).get("name") or ""
    return EventItem(
        subject=redact(clean_text(raw.get("subject") or "(no title)", MAX_SUBJECT_CHARS)),
        start=(raw.get("start") or {}).get("dateTime", ""),
        end=(raw.get("end") or {}).get("dateTime", ""),
        is_all_day=bool(raw.get("isAllDay")),
        location=clean_text((raw.get("location") or {}).get("displayName") or "", 100),
        organizer=clean_text(organizer, 100),
        is_online=bool(raw.get("isOnlineMeeting")),
    )


def normalize_all(
    messages: list[dict[str, Any]], events: list[dict[str, Any]]
) -> tuple[list[EmailItem], list[EventItem]]:
    emails = [normalize_message(m, i) for i, m in enumerate(messages, start=1)]
    return emails, [normalize_event(e) for e in events]
