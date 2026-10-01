from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .auth import AuthError, GraphAuth
from .config import GRAPH_SCOPES, ConfigError, load_settings
from .graph_client import GraphError
from .llm import LLMError
from .pipeline import run
from .telemetry import RunLogger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m briefing", description="AI daily briefing over Microsoft Graph."
    )
    parser.add_argument("--source", choices=["graph", "file"], default="graph")
    parser.add_argument("--input", type=Path, help="JSON file when --source file")
    parser.add_argument("--send", action="store_true", help="email the briefing via Graph")
    parser.add_argument("--sign-out", action="store_true", help="clear the local token cache")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    settings = load_settings()

    if args.sign_out:
        settings.require_graph()
        GraphAuth(
            settings.client_id, settings.authority, GRAPH_SCOPES, settings.token_cache_path
        ).sign_out()
        print("Signed out; token cache removed.")
        return 0

    logger = RunLogger(settings.log_dir, settings.price_in_per_mtok, settings.price_out_per_mtok)
    try:
        outcome = run(settings, logger, source=args.source, input_path=args.input, send=args.send)
    except (ConfigError, AuthError, GraphError, LLMError, ValueError, OSError) as exc:
        logger.finish("failed")
        print(f"error: {exc}", file=sys.stderr)
        return 1

    record = logger.finish("ok")
    print(outcome.text)
    if outcome.guardrail_issues:
        print("Guardrail notes:", *(f"  - {i}" for i in outcome.guardrail_issues), sep="\n")
    llm = record.get("llm", {})
    print(
        f"\n[run {logger.run_id}] html: {outcome.html_path}"
        + (f" | sent to {outcome.sent_to}" if outcome.sent_to else "")
        + (
            f" | tokens {llm['input_tokens']}/{llm['output_tokens']} ~${llm['est_cost_usd']}"
            if llm
            else ""
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
