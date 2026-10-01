from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("briefing")


class RunLogger:
    """Collects per-run metrics and appends one JSON line per run to logs/runs.jsonl."""

    def __init__(self, log_dir: Path, price_in_per_mtok: float, price_out_per_mtok: float):
        self._path = log_dir / "runs.jsonl"
        self._price_in = price_in_per_mtok
        self._price_out = price_out_per_mtok
        self.run_id = uuid.uuid4().hex[:8]
        self.record: dict[str, Any] = {
            "run_id": self.run_id,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "running",
            "stages_ms": {},
            "errors": [],
        }

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        log.info("[%s] %s: start", self.run_id, name)
        try:
            yield
        except Exception as exc:
            self.record["errors"].append(
                {"stage": name, "type": type(exc).__name__, "msg": str(exc)}
            )
            raise
        finally:
            elapsed = round((time.perf_counter() - started) * 1000)
            self.record["stages_ms"][name] = elapsed
            log.info("[%s] %s: %d ms", self.run_id, name, elapsed)

    def set(self, **fields: Any) -> None:
        self.record.update(fields)

    def record_llm(self, model: str, input_tokens: int, output_tokens: int, attempts: int) -> None:
        cost = input_tokens / 1e6 * self._price_in + output_tokens / 1e6 * self._price_out
        self.record["llm"] = {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "attempts": attempts,
            "est_cost_usd": round(cost, 5),
        }

    def finish(self, status: str) -> dict[str, Any]:
        self.record["status"] = status
        self.record["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(self.record, ensure_ascii=False) + "\n")
        log.info("[%s] finished: %s", self.run_id, status)
        return self.record
