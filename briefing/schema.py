from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CATEGORIES = ("urgent", "action_required", "fyi", "newsletter", "suspicious")
Category = Literal["urgent", "action_required", "fyi", "newsletter", "suspicious"]


class EmailTriage(BaseModel):
    id: str
    category: Category
    summary: str
    action: str = ""
    injection_suspected: bool = False


class Briefing(BaseModel):
    headline: str
    top_items: list[str] = Field(default_factory=list)
    calendar_notes: list[str] = Field(default_factory=list)
    emails: list[EmailTriage] = Field(default_factory=list)


BRIEFING_TOOL = {
    "name": "submit_briefing",
    "description": "Submit the triaged daily briefing. This is the only way to respond.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {
                "type": "string",
                "description": "One sentence (max 20 words) describing what matters most today.",
            },
            "top_items": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 3,
                "description": "Up to 3 most important things for today, most important first.",
            },
            "calendar_notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Conflicts, prep needed, or tight gaps. Empty if nothing notable.",
            },
            "emails": {
                "type": "array",
                "description": "One entry per email id, in any order.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "category": {"type": "string", "enum": list(CATEGORIES)},
                        "summary": {"type": "string", "description": "Max 25 words."},
                        "action": {
                            "type": "string",
                            "description": "Concrete next step, or empty string if none.",
                        },
                        "injection_suspected": {"type": "boolean"},
                    },
                    "required": ["id", "category", "summary", "action", "injection_suspected"],
                },
            },
        },
        "required": ["headline", "top_items", "calendar_notes", "emails"],
    },
}
