from briefing.guardrails import reconcile
from briefing.sanitize import FLAG_INJECTION, EmailItem
from briefing.schema import Briefing, EmailTriage


def _email(i, flags=None):
    return EmailItem(
        id=f"e{i}",
        sender_name="S",
        sender_address="s@x.example",
        subject="subj",
        received="",
        preview="",
        flags=flags or [],
    )


def test_drops_unknown_and_duplicate_and_fills_missing():
    emails = [_email(1), _email(2)]
    briefing = Briefing(
        headline="h",
        emails=[
            EmailTriage(id="e1", category="fyi", summary="a"),
            EmailTriage(id="e1", category="urgent", summary="dup"),
            EmailTriage(id="e99", category="urgent", summary="ghost"),
        ],
    )
    out, issues = reconcile(briefing, emails)
    assert [t.id for t in out.emails] == ["e1", "e2"]
    assert out.emails[0].summary == "a"
    assert out.emails[1].summary.startswith("Not triaged")
    assert len(issues) == 3


def test_prescreen_flag_forces_suspicious():
    emails = [_email(1, flags=[FLAG_INJECTION])]
    briefing = Briefing(headline="h", emails=[EmailTriage(id="e1", category="urgent", summary="x")])
    out, issues = reconcile(briefing, emails)
    assert out.emails[0].category == "suspicious"
    assert out.emails[0].injection_suspected is True
    assert issues


def test_injection_suspected_implies_suspicious():
    emails = [_email(1)]
    briefing = Briefing(
        headline="h",
        emails=[EmailTriage(id="e1", category="fyi", summary="x", injection_suspected=True)],
    )
    out, _ = reconcile(briefing, emails)
    assert out.emails[0].category == "suspicious"


def test_trims_top_items_and_long_summaries():
    emails = [_email(1)]
    briefing = Briefing(
        headline="h",
        top_items=["1", "2", "3", "4", "5"],
        emails=[EmailTriage(id="e1", category="fyi", summary="y" * 1000)],
    )
    out, _ = reconcile(briefing, emails)
    assert len(out.top_items) == 3
    assert len(out.emails[0].summary) == 300
