from datetime import date

from app.cli_distress_validation import _safe_input_integrity, _screen_refs, _sufficient_inputs
from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version
from app.domain.distress_v1_1 import DistressAssessment, DistressClassification, DistressInputs, DistressSectorAdapter


RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")


def submissions(forms, dates):
    return {
        "filings": {
            "recent": {
                "form": forms,
                "accessionNumber": [f"0000000001-26-{index:06d}" for index in range(len(forms))],
                "primaryDocument": [f"doc{index}.htm" for index in range(len(forms))],
                "filingDate": dates,
            }
        }
    }


def test_screen_policy_requires_latest_periodic_and_all_newer_events_within_cap():
    payload = submissions(
        ["8-K", "8-K", "10-Q", "8-K", "10-Q"],
        ["2026-08-20", "2026-08-10", "2026-08-01", "2026-07-20", "2026-05-01"],
    )
    refs, required, failures, overflow = _screen_refs(
        payload,
        ticker="TEST",
        cik="0000000001",
        cutoff=date(2026, 1, 1),
        max_event_filings=4,
    )
    assert [item.form for item in refs] == ["10-Q", "8-K", "8-K"]
    assert required == 3
    assert failures == []
    assert overflow == 0


def test_screen_policy_marks_overflow_incomplete_instead_of_silently_skipping():
    payload = submissions(
        ["8-K", "8-K", "8-K", "10-Q"],
        ["2026-08-20", "2026-08-15", "2026-08-10", "2026-08-01"],
    )
    refs, required, failures, overflow = _screen_refs(
        payload,
        ticker="TEST",
        cik="0000000001",
        cutoff=date(2026, 1, 1),
        max_event_filings=2,
    )
    assert len(refs) == 3
    assert required == 4
    assert overflow == 1
    assert failures == ["UNSCREENED_EVENT_OVERFLOW:1"]


def test_no_recent_periodic_cannot_complete_screen():
    payload = submissions(["8-K"], ["2026-08-20"])
    refs, required, failures, overflow = _screen_refs(
        payload,
        ticker="TEST",
        cik="0000000001",
        cutoff=date(2026, 1, 1),
        max_event_filings=4,
    )
    assert refs == []
    assert required == 1
    assert failures == ["NO_RECENT_PERIODIC_FILING"]
    assert overflow == 0


def test_sufficient_inputs_is_adapter_specific_and_does_not_use_financial_corporate_ratios():
    corporate = DistressInputs(
        ticker="TEST",
        sector_adapter=DistressSectorAdapter.CORPORATE,
        as_of="2026-09-02T00:00:00Z",
        net_debt_to_ebitda=2.0,
        interest_coverage=4.0,
    )
    bank = corporate.model_copy(update={"sector_adapter": DistressSectorAdapter.BANK})
    assert _sufficient_inputs(DistressSectorAdapter.CORPORATE, corporate, RULES)[0] is True
    assert _sufficient_inputs(DistressSectorAdapter.BANK, bank, RULES)[0] is False


def test_safe_integrity_rejects_safe_state_without_completed_screen():
    assessment = DistressAssessment(
        rules_hash="1" * 64,
        ticker="TEST",
        sector_adapter=DistressSectorAdapter.CORPORATE,
        as_of="2026-09-02T00:00:00Z",
        hard_flag_screen_complete=False,
        classification=DistressClassification.NOT_DISTRESSED,
        balance_sheet_distressed=False,
        rule_path="balance_sheet_distress_v1_1.corporate.net_cash_safe",
        sector_specific_metrics={"net_cash": True},
        sources=["https://www.sec.gov/Archives/edgar/data/1/test.htm"],
    )
    assert _safe_input_integrity(assessment) is False
