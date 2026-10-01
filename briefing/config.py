from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Delegated permissions only; offline_access is added by MSAL automatically.
GRAPH_SCOPES: tuple[str, ...] = ("User.Read", "Mail.Read", "Calendars.Read", "Mail.Send")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    client_id: str
    authority: str
    token_cache_path: Path
    anthropic_api_key: str
    anthropic_model: str
    price_in_per_mtok: float
    price_out_per_mtok: float
    recipient: str | None
    outlook_timezone: str
    lookback_hours: int
    max_emails: int
    log_dir: Path
    out_dir: Path

    def require_graph(self) -> None:
        if not self.client_id:
            raise ConfigError("MS_CLIENT_ID is not set. Copy .env.example to .env and fill it in.")

    def require_llm(self) -> None:
        if not self.anthropic_api_key:
            raise ConfigError(
                "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
            )


def load_settings() -> Settings:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    env = os.environ.get
    return Settings(
        client_id=env("MS_CLIENT_ID", "").strip(),
        authority=env("MS_AUTHORITY", "https://login.microsoftonline.com/consumers").strip(),
        token_cache_path=ROOT / ".token_cache.json",
        anthropic_api_key=env("ANTHROPIC_API_KEY", "").strip(),
        anthropic_model=env("ANTHROPIC_MODEL", "claude-sonnet-4-5").strip(),
        price_in_per_mtok=float(env("LLM_PRICE_IN_PER_MTOK", "3.0")),
        price_out_per_mtok=float(env("LLM_PRICE_OUT_PER_MTOK", "15.0")),
        recipient=env("BRIEFING_RECIPIENT", "").strip() or None,
        outlook_timezone=env("OUTLOOK_TIMEZONE", "Pacific Standard Time").strip(),
        lookback_hours=int(env("LOOKBACK_HOURS", "24")),
        max_emails=int(env("MAX_EMAILS", "25")),
        log_dir=ROOT / "logs",
        out_dir=ROOT / "out",
    )
