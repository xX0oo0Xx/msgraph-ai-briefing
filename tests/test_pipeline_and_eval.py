from dataclasses import replace

from briefing.config import ROOT, load_settings
from briefing.evaluation import load_dataset, score
from briefing.llm import TriageResult
from briefing.pipeline import run
from briefing.sanitize import normalize_all
from briefing.schema import Briefing, EmailTriage
from briefing.telemetry import RunLogger

DATASET = ROOT / "eval" / "dataset.json"


class PerfectTriager:
    """Returns the dataset labels, except it falls for the canary to exercise leak detection."""

    model = "fake"

    def __init__(self, cases, leak_canary=False):
        self.cases = cases
        self.leak_canary = leak_canary

    def triage(self, emails, events, now):
        headline = "CANARY-7731 busy day" if self.leak_canary else "Busy day"
        briefing = Briefing(
            headline=headline,
            top_items=["Fix prod-sql-01"],
            emails=[
                EmailTriage(
                    id=e.id,
                    category=c.expected_category,
                    summary="s",
                    injection_suspected=c.is_injection,
                )
                for e, c in zip(emails, self.cases, strict=False)
            ],
        )
        return TriageResult(
            briefing=briefing, model=self.model, input_tokens=1000, output_tokens=200
        )


def test_dataset_is_well_formed():
    ds = load_dataset(DATASET)
    assert len(ds.cases) >= 15
    assert len({c.id for c in ds.cases}) == len(ds.cases)
    assert any(c.is_injection for c in ds.cases)


def test_score_perfect_and_detects_canary_leak():
    ds = load_dataset(DATASET)
    emails, events = normalize_all([c.message for c in ds.cases], ds.events)
    good = PerfectTriager(ds.cases).triage(emails, events, ds.now).briefing
    s = score(ds.cases, good, ds.canaries)
    assert s["accuracy"] == 1.0
    assert s["injection_detection_rate"] == 1.0
    assert s["canary_leaks"] == [] and s["pii_leaks"] == []

    leaky = PerfectTriager(ds.cases, leak_canary=True).triage(emails, events, ds.now).briefing
    assert score(ds.cases, leaky, ds.canaries)["canary_leaks"] == ["CANARY-7731"]


def test_pipeline_end_to_end_from_file(tmp_path):
    settings = replace(load_settings(), log_dir=tmp_path / "logs", out_dir=tmp_path / "out")
    ds = load_dataset(DATASET)
    logger = RunLogger(settings.log_dir, 3.0, 15.0)

    outcome = run(
        settings, logger, source="file", input_path=DATASET, triager=PerfectTriager(ds.cases)
    )
    record = logger.finish("ok")

    assert outcome.html_path.exists()
    assert "Daily briefing - Tuesday 2026-09-29" in outcome.text
    assert "4111 1111" not in outcome.html
    assert record["counts"]["emails"] == len(ds.cases)
    assert record["llm"]["est_cost_usd"] == round(1000 / 1e6 * 3 + 200 / 1e6 * 15, 5)
    assert set(record["stages_ms"]) == {"fetch", "sanitize", "triage", "guardrails", "render"}
    assert (settings.log_dir / "runs.jsonl").exists()
