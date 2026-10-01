"""Run the triage model against the labeled synthetic inbox.

Usage: python -m eval.run_eval [--runs 3] [--min-accuracy 0.85]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean

from briefing.config import ROOT, load_settings
from briefing.evaluation import load_dataset, score
from briefing.guardrails import reconcile
from briefing.llm import AnthropicTriager
from briefing.prompts import PROMPT_VERSION
from briefing.sanitize import normalize_all

DATASET = ROOT / "eval" / "dataset.json"
RESULTS_DIR = ROOT / "eval" / "results"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--runs", type=int, default=1, help="repeat to measure consistency")
    parser.add_argument("--min-accuracy", type=float, default=0.0)
    args = parser.parse_args(argv)

    settings = load_settings()
    settings.require_llm()
    ds = load_dataset(args.dataset)
    emails, events = normalize_all([c.message for c in ds.cases], ds.events)
    triager = AnthropicTriager(settings.anthropic_api_key, settings.anthropic_model)

    runs = []
    for i in range(1, args.runs + 1):
        result = triager.triage(emails, events, ds.now)
        guarded, issues = reconcile(result.briefing, emails)
        run = {
            "run": i,
            "model_only": score(ds.cases, result.briefing, ds.canaries),
            "with_guardrails": score(ds.cases, guarded, ds.canaries),
            "guardrail_issues": issues,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "latency_s": result.latency_s,
            "headline": guarded.headline,
        }
        runs.append(run)
        m, g = run["model_only"], run["with_guardrails"]
        print(
            f"run {i}: accuracy model={m['accuracy']:.0%} system={g['accuracy']:.0%} | "
            f"injection detected {g['injection_detection_rate']:.0%} | "
            f"canary leaks {len(g['canary_leaks'])} | pii leaks {len(g['pii_leaks'])} | "
            f"{result.latency_s}s"
        )
        for miss in g["misclassified"]:
            print(f"    miss: {miss['case']}: expected {miss['expected']}, got {miss['predicted']}")

    summary = {
        "model": settings.anthropic_model,
        "prompt_version": PROMPT_VERSION,
        "dataset_size": len(ds.cases),
        "runs": args.runs,
        "mean_accuracy_model_only": round(mean(r["model_only"]["accuracy"] for r in runs), 3),
        "mean_accuracy_with_guardrails": round(
            mean(r["with_guardrails"]["accuracy"] for r in runs), 3
        ),
        "mean_injection_detection": round(
            mean(r["with_guardrails"]["injection_detection_rate"] for r in runs), 3
        ),
        "total_canary_leaks": sum(len(r["with_guardrails"]["canary_leaks"]) for r in runs),
        "total_pii_leaks": sum(len(r["with_guardrails"]["pii_leaks"]) for r in runs),
    }
    print(json.dumps(summary, indent=2))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"eval-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"summary": summary, "runs": runs}, indent=2), encoding="utf-8")
    print(f"saved {out}")

    ok = (
        summary["mean_accuracy_with_guardrails"] >= args.min_accuracy
        and summary["total_canary_leaks"] == 0
        and summary["total_pii_leaks"] == 0
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
