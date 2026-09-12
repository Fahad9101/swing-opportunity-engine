from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.catalyst_surprise_v1_1 import AnalystConsensusContext, SurpriseExpectationMetric
from app.domain.distress_v1_1 import DistressSectorAdapter
from app.domain.enums import CatalystGrade
from app.domain.schemas import CorporateEvent
from app.domain.soe_v1_1 import GuidanceAction, GuidanceMetric, SourceDocument
from app.services.distress_metric_service import derive_distress_inputs
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_run85_repairs_v1_1 import (
    analyst_consensus_audit_payload,
    candidate_calendar_event_run85,
    extract_guidance_facts_run85,
    normalize_distress_companyfacts_run85,
)


FETCHED = datetime(2026, 9, 10, tzinfo=UTC)


def fact(val, end, *, start=None, form="10-Q", filed="2026-08-01"):
    row = {"val": val, "end": end, "form": form, "filed": filed}
    if start:
        row["start"] = start
    return row


def companyfacts(concepts):
    return {
        "cik": 1234,
        "entityName": "Test Co",
        "facts": {
            "us-gaap": {
                name: {"units": {"USD": rows}}
                for name, rows in concepts.items()
            }
        },
    }


def document(ticker: str, text: str, *, accession: str = "0000000000-26-000001"):
    return SourceDocument(
        document_id=f"{ticker}:{accession}:ex99-1",
        rules_hash="run85-test",
        ticker=ticker,
        cik="0000001234",
        accession=accession,
        form="8-K",
        filing_date=FETCHED.date(),
        source="SEC EDGAR",
        source_url=f"https://www.sec.gov/Archives/edgar/data/1234/{accession}/ex99-1.htm",
        source_timestamp=FETCHED,
        fetched_at=FETCHED,
        content_hash="abc123",
        content_type="text/plain",
        content=text,
    )


def test_interest_coverage_uses_income_statement_interest_expense_not_cash_interest_paid():
    payload = companyfacts(
        {
            "CashAndCashEquivalentsAtCarryingValue": [fact(100, "2026-06-30")],
            "ShortTermInvestments": [fact(50, "2026-06-30")],
            "LongTermDebtNoncurrent": [fact(450, "2026-06-30")],
            "OperatingIncomeLoss": [
                fact(120, "2025-12-31", start="2025-01-01", form="10-K")
            ],
            "DepreciationDepletionAndAmortization": [
                fact(30, "2025-12-31", start="2025-01-01", form="10-K")
            ],
            "InterestPaidNet": [
                fact(10, "2025-12-31", start="2025-01-01", form="10-K")
            ],
            "InterestExpenseNonoperating": [
                fact(40, "2025-12-31", start="2025-01-01", form="10-K")
            ],
        }
    )
    facts = normalize_distress_companyfacts_run85(
        "TEST",
        payload,
        sector_adapter=DistressSectorAdapter.CORPORATE,
        fetched_at=FETCHED,
    )
    metrics = derive_distress_inputs(facts)
    assert facts.cash_interest_expense == 40
    assert metrics.interest_coverage == pytest.approx(3.0)
    assert facts.audit["cash_interest_paid_used_for_interest_coverage"] is False
    assert facts.audit["interest_coverage_period_end"] == "2025-12-31"


def test_interest_coverage_fails_closed_when_only_cash_interest_paid_exists():
    payload = companyfacts(
        {
            "OperatingIncomeLoss": [
                fact(120, "2025-12-31", start="2025-01-01", form="10-K")
            ],
            "DepreciationDepletionAndAmortization": [
                fact(30, "2025-12-31", start="2025-01-01", form="10-K")
            ],
            "InterestPaid": [
                fact(10, "2025-12-31", start="2025-01-01", form="10-K")
            ],
        }
    )
    facts = normalize_distress_companyfacts_run85(
        "TEST",
        payload,
        sector_adapter=DistressSectorAdapter.CORPORATE,
        fetched_at=FETCHED,
    )
    assert facts.cash_interest_expense is None
    assert derive_distress_inputs(facts).interest_coverage is None


def test_humana_revised_gaap_eps_is_linked_and_classified_as_deteriorated():
    text = (
        "Humana revises its GAAP EPS guidance for the year ending December 31, 2026 "
        "(FY 2026) to 'at least $6.52' from 'at least $8.36', while affirming its "
        "Adjusted EPS guidance of 'at least $9.00'."
    )
    rules = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    rhash = rules_hash(rules)
    result = extract_guidance_facts_run85(document("HUM", text), rules_hash=rhash)
    gaap = [
        r for r in result.records
        if r.metric is GuidanceMetric.EPS
        and r.fiscal_period == "FY2026"
        and r.accounting_basis == "GAAP"
    ]
    assert sorted(r.low for r in gaap) == [6.52, 8.36]
    current = next(r for r in gaap if r.low == 6.52)
    assert current.explicit_action is GuidanceAction.LOWER
    assert current.supersedes_record_id is not None

    assessment = GuidanceLedger(result.records).assess(
        "HUM", rules, rules_hash=rhash
    )
    assert assessment.guidance_deterioration is True
    assert assessment.classification.value == "DETERIORATED"


def test_evolus_long_term_outlook_stays_bound_to_2028():
    text = (
        "Raises Full-Year 2026 Financial Outlook. 2026 full-year guidance: "
        "Total Net Revenue expected to be in the range of $330 million to $337 million. "
        "Reaffirms 2028 Long-Term Financial Outlook Reflecting Total Net Revenue "
        "Between $450 million and $500 million."
    )
    result = extract_guidance_facts_run85(
        document("EOLS", text),
        rules_hash="run85-test",
    )
    long_term = [
        r for r in result.records
        if r.metric is GuidanceMetric.REVENUE
        and r.low == 450_000_000
        and r.high == 500_000_000
    ]
    assert long_term
    assert {r.fiscal_period for r in long_term} == {"FY2028"}


@pytest.mark.parametrize(
    ("ticker", "text", "metric", "expected"),
    [
        (
            "DXCM",
            "2026 Annual Guidance. Non-GAAP Gross Profit Margin approximately 64%; "
            "Non-GAAP Operating Margin approximately 23.5% to 24%.",
            GuidanceMetric.OPERATING_MARGIN,
            (0.235, 0.24, "ADJUSTED"),
        ),
        (
            "WDFC",
            "Fiscal Year 2026 Guidance. Gross margin is now expected to be between "
            "54.5 percent and 55.5 percent.",
            GuidanceMetric.GROSS_MARGIN,
            (0.545, 0.555, "UNSPECIFIED"),
        ),
        (
            "GRMN",
            "Fiscal Year 2026 Guidance: revenue approximately $8.05 billion and pro forma "
            "EPS $10.00 based on gross margin of 59.7%, operating margin of 27.0%.",
            GuidanceMetric.OPERATING_MARGIN,
            (0.27, 0.27, "UNSPECIFIED"),
        ),
    ],
)
def test_forward_margin_guidance_is_captured(ticker, text, metric, expected):
    result = extract_guidance_facts_run85(
        document(ticker, text),
        rules_hash="run85-test",
    )
    matches = [
        r for r in result.records
        if r.metric is metric
        and r.fiscal_period == "FY2026"
        and r.accounting_basis == expected[2]
        and r.low == pytest.approx(expected[0])
        and r.high == pytest.approx(expected[1])
    ]
    assert matches


def test_bbnx_previous_margin_range_is_linked_to_current_range():
    text = (
        "2026 Full Year Guidance. Estimated gross margin of 58.5% to 59.5% "
        "(previously 57.5% to 59.5%)."
    )
    result = extract_guidance_facts_run85(
        document("BBNX", text),
        rules_hash="run85-test",
    )
    rows = [
        r for r in result.records
        if r.metric is GuidanceMetric.GROSS_MARGIN
        and r.fiscal_period == "FY2026"
    ]
    current = next(r for r in rows if r.low == pytest.approx(0.585))
    prior = next(r for r in rows if r.low == pytest.approx(0.575))
    assert current.supersedes_record_id == prior.record_id
    assert current.explicit_action is GuidanceAction.RAISE


def test_mwh_updated_previous_margin_table_is_bound_in_column_order():
    text = (
        "Full-Year 2026 Guidance. Updated Guidance Previous Guidance "
        "Adjusted Gross Margin 16.0% - 16.6% 16.4% - 17.0%."
    )
    result = extract_guidance_facts_run85(
        document("MWH", text),
        rules_hash="run85-test",
    )
    rows = [
        r for r in result.records
        if r.metric is GuidanceMetric.GROSS_MARGIN
        and r.fiscal_period == "FY2026"
        and r.accounting_basis == "ADJUSTED"
    ]
    current = next(
        r for r in rows
        if r.low == pytest.approx(0.16) and r.high == pytest.approx(0.166)
    )
    prior = next(
        r for r in rows
        if r.low == pytest.approx(0.164) and r.high == pytest.approx(0.17)
    )
    assert current.supersedes_record_id == prior.record_id
    assert current.explicit_action is GuidanceAction.LOWER


def test_consensus_audit_payload_preserves_raw_dispersion_inputs():
    context = AnalystConsensusContext(
        ticker="TEST",
        period="0q",
        metric=SurpriseExpectationMetric.EPS,
        average=1.10,
        high=1.30,
        low=0.90,
        current_estimate=1.10,
        estimate_90d_ago=1.00,
        analyst_count=12,
        source="Yahoo Finance",
        source_timestamp=FETCHED,
        stale=False,
        field_provenance={"average": {"raw_field": "avg"}},
    )
    payload = analyst_consensus_audit_payload(context)
    assert payload["average"] == 1.10
    assert payload["high"] == 1.30
    assert payload["low"] == 0.90
    assert payload["analyst_count"] == 12
    assert payload["source_timestamp"] == FETCHED.isoformat().replace("+00:00", "Z")


def test_nasdaq_calendar_day_is_candidate_only_grade_b_not_confirmed_grade_a():
    event = CorporateEvent(
        ticker="TEST",
        type="EARNINGS",
        title="Test earnings",
        event_date=FETCHED.date(),
        timing="AFTER_HOURS",
        verified=True,
        date_confidence=CatalystGrade.A,
        date_precision="DAY",
        window_start=FETCHED.date(),
        window_end=FETCHED.date(),
        catalyst_candidate=True,
        source="Nasdaq Earnings Calendar",
        source_url="https://www.nasdaq.com/market-activity/earnings",
        as_of=FETCHED,
        fetched_at=FETCHED,
        stale=False,
    )
    repaired = candidate_calendar_event_run85(event)
    assert event.date_confidence is CatalystGrade.A
    assert repaired.date_confidence is CatalystGrade.B
    assert repaired.timing == "ESTIMATED"
    assert repaired.evidence_status == "PUBLIC_CALENDAR_DAY_UNCONFIRMED_ESTIMATE"
