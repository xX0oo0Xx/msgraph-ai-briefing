from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from .prompts import SYSTEM_PROMPT, build_user_message
from .sanitize import EmailItem, EventItem
from .schema import BRIEFING_TOOL, Briefing


class LLMError(RuntimeError):
    pass


@dataclass
class TriageResult:
    briefing: Briefing
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    attempts: int = 0
    latency_s: float = 0.0


class AnthropicTriager:
    """Forces a single tool call so the output is structured, then validates it with Pydantic."""

    def __init__(self, api_key: str, model: str, max_tokens: int = 4096, max_attempts: int = 2):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self._max_tokens = max_tokens
        self._max_attempts = max_attempts

    def triage(
        self, emails: list[EmailItem], events: list[EventItem], now: datetime
    ) -> TriageResult:
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": build_user_message(emails, events, now)}
        ]
        result = TriageResult(briefing=Briefing(headline=""), model=self.model)
        started = time.perf_counter()
        last_error = ""

        for attempt in range(1, self._max_attempts + 1):
            result.attempts = attempt
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                tools=[BRIEFING_TOOL],
                tool_choice={"type": "tool", "name": BRIEFING_TOOL["name"]},
                messages=messages,
            )
            result.input_tokens += resp.usage.input_tokens
            result.output_tokens += resp.usage.output_tokens

            block = next((b for b in resp.content if b.type == "tool_use"), None)
            if block is None:
                raise LLMError(f"Model did not call {BRIEFING_TOOL['name']}")
            try:
                result.briefing = Briefing.model_validate(block.input)
                result.latency_s = round(time.perf_counter() - started, 2)
                return result
            except ValidationError as exc:
                last_error = str(exc)
                messages += [
                    {"role": "assistant", "content": resp.content},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": f"Schema validation failed:\n{exc}\n"
                                "Call submit_briefing again with corrected input.",
                            }
                        ],
                    },
                ]

        raise LLMError(f"Invalid output after {self._max_attempts} attempts: {last_error}")
