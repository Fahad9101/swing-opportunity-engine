from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.domain.enums import CatalystGrade
from app.domain.schemas import CorporateEvent, FundamentalSnapshot
from app.providers.sec_biotech import (
    SecBiotechIntelligenceProvider,
    classify_financing_document,
    derive_biotech_runway,
    derive_operating_cashflow_quarters,
    normalize_recent_filings,
)
from app.providers.sec_edgar import SecEdgarProvider
from app.services.biotech_validation_service import build_biotech_validation, classify_runway_status
from app.services.cache_service import JsonFileCache


def _facts(rows, unit="USD"):
    return {"units": {unit: rows}}


def _runway_payload():
    return {
        "facts": {
            "us-gaap": {
                "CashAndCashEquivalentsAtCarryingValue": _facts([
                    {"end": "2025-12-31", "filed": "2026-02-15", "form": "10-K", "val": 100.0}
                ]),
                "ShortTermInvestments": _facts([
                    {"end": "2025-12-31", "filed": "2026-02-15", "form": "10-K", "val": 50.0}
                ]),
                "NetCashProvidedByUsedInOperatingActivities": _facts([
                    {"start": "2025-01-01", "end": "2025-03-31", "filed": "2025-05-01", "form": "10-Q", "fy": 2025, "fp": "Q1", "val": -30.0},
                    {"start": "2025-01-01", "end": "2025-06-30", "filed": "2025-08-01", "form": "10-Q", "fy": 2025, "fp": "Q2", "val": -70.0},
                    {"start": "2025-01-01", "end": "2025-09-30", "filed": "2025-11-01", "form": "10-Q", "fy": 2025, "fp": "Q3", "val": -105.0},
                    {"start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-15", "form": "10-K", "fy": 2025, "fp": "FY", "val": -150.0},
                ]),
            }
        }
    }


def test_operating_cashflow_ytd_is_decomposed_into_discrete_quarters():
    quarters, concept = derive_operating_cashflow_quarters(_runway_payload())
    assert concept == "us-gaap:NetCashProvidedByUsedInOperatingActivities:USD"
    assert [row["val"] for row in quarters] == pytest.approx([-30.0, -40.0, -35.0, -45.0])
    assert [row["fp"] for row in quarters] == ["Q1", "Q2", "Q3", "Q4"]


def test_biotech_runway_includes_non_overlapping_marketable_securities_and_uses_conservative_burn():
    result = derive_biotech_runway(_runway_payload())
    assert result["liquidity"] == pytest.approx(150.0)
    assert result["marketable_securities"] == pytest.approx(50.0)
    assert result["trailing_negative_monthly_burn"] == pytest.approx(12.5)
    assert result["latest_quarter_monthly_burn"] == pytest.approx(15.0)
    assert result["conservative_monthly_burn"] == pytest.approx(15.0)
    assert result["cash_runway_months"] == pytest.approx(10.0)


def test_biotech_runway_requires_at_least_two_reported_burn_quarters():
    payload = _runway_payload()
    payload["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]["units"]["USD"] = [
        {"start": "2025-10-01", "end": "2025-12-31", "filed": "2026-02-15", "form": "10-K", "fy": 2025, "fp": "Q4", "val": -45.0}
    ]
    result = derive_biotech_runway(payload)
    assert result["cash_runway_months"] is None
    assert result["status"] == "INSUFFICIENT_REPORTED_BURN_HISTORY"


def test_financing_document_requires_closed_or_completed_evidence():
    completed = classify_financing_document(
        "The Company completed its underwritten public offering and received net proceeds of approximately $110 million."
    )
    assert completed["secured"] is True
    assert completed["proceeds"] == pytest.approx(110_000_000)

    announced = classify_financing_document(
        "The Company announced the pricing of its public offering and expects to close the offering next week."
    )
    assert announced["secured"] is False
    assert announced["status"] == "CAPACITY_OR_ANNOUNCED_FINANCING_NOT_CLOSED"

    shelf = classify_financing_document(
        "This prospectus supplement relates to an at-the-market sales agreement under which we may offer common stock."
    )
    assert shelf["secured"] is False


def test_recent_submissions_are_normalized_without_inventing_fields():
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["0001-26-000001"],
                "filingDate": ["2026-08-20"],
                "form": ["8-K"],
                "primaryDocument": ["form8k.htm"],
                "items": ["1.01,3.02,9.01"],
            }
        }
    }
    rows = normalize_recent_filings(payload)
    assert rows[0]["form"] == "8-K"
    assert rows[0]["primaryDocDescription"] is None
    assert rows[0]["items"] == "1.01,3.02,9.01"


def test_post_balance_sheet_completed_financing_is_secured(tmp_path, rules):
    balance_date = date(2026, 6, 30)
    submissions = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000000001-26-000001"],
                "filingDate": ["2026-08-20"],
                "reportDate": ["2026-08-20"],
                "acceptanceDateTime": ["20260820120000"],
                "form": ["8-K"],
                "primaryDocument": ["form8k.htm"],
                "primaryDocDescription": ["Current report"],
                "items": ["1.01,3.02,9.01"],
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "submissions" in str(request.url):
            return httpx.Response(200, json=submissions, request=request)
        return httpx.Response(
            200,
            text="<html><body>The Company closed the registered direct offering and received net proceeds of approximately $75 million.</body></html>",
            request=request,
        )

    cache = JsonFileCache(tmp_path / "cache")
    sec = SecEdgarProvider(cache=cache, zip_path=tmp_path / "missing.zip", user_agent="test@example.com", rules=rules, transport=httpx.MockTransport(handler))
    provider = SecBiotechIntelligenceProvider(
        sec=sec,
        cache=cache,
        submissions_zip_path=tmp_path / "missing-submissions.zip",
        user_agent="test@example.com",
        rules=rules,
        transport=httpx.MockTransport(handler),
    )
    secured, evidence, _ = asyncio.run(provider.assess_post_period_financing("BIO", "0000000001", balance_date))
    assert secured is True
    assert evidence["status"] == "COMPLETED_FINANCING_AFTER_BALANCE_SHEET"
    assert evidence["matched_filing"]["proceeds"] == pytest.approx(75_000_000)


def _fundamental(runway: float, financing: bool | None) -> FundamentalSnapshot:
    now = datetime.now(UTC)
    return FundamentalSnapshot(
        ticker="BIO",
        cash_runway_months=runway,
        financing_secured=financing,
        source="test",
        as_of=now,
        fetched_at=now,
    )


def _event(*, scoring_ready: bool, candidate: bool = True, grade: CatalystGrade = CatalystGrade.A) -> CorporateEvent:
    now = datetime.now(UTC)
    return CorporateEvent(
        ticker="BIO",
        type="CLINICAL_DATA" if candidate else "CLINICAL_TRIAL_PRIMARY_COMPLETION",
        title="Test event",
        event_date=date.today() + timedelta(days=10),
        verified=True,
        date_confidence=grade,
        date_precision="DAY",
        window_start=date.today() + timedelta(days=10),
        window_end=date.today() + timedelta(days=10),
        catalyst_candidate=candidate,
        materiality=8 if scoring_ready else None,
        surprise_potential=3 if scoring_ready else None,
        scoring_ready=scoring_ready,
        missing_score_fields=[] if scoring_ready else ["materiality", "surprise_potential"],
        source="test",
        as_of=now,
        fetched_at=now,
    )


def test_frozen_runway_thresholds_are_only_classified_not_changed(rules):
    assert classify_runway_status(_fundamental(8.9, False), rules) == "AUTO_REJECT_BELOW_9M"
    assert classify_runway_status(_fundamental(8.9, True), rules) == "FINANCING_EXCEPTION"
    assert classify_runway_status(_fundamental(12.0, False), rules) == "ELIGIBLE_12_TO_18M"
    assert classify_runway_status(_fundamental(18.0, False), rules) == "PREFERRED_18M_PLUS"


def test_date_evidence_does_not_become_biotech_scanner_eligible_until_frozen_score_inputs_exist(rules):
    incomplete = build_biotech_validation(_fundamental(18.0, False), [_event(scoring_ready=False)], rules)
    assert incomplete["catalyst"]["status"] == "A_B_DATE_EVIDENCE_SCORE_INPUTS_INCOMPLETE"
    assert incomplete["catalyst"]["scanner_catalyst_eligible"] is False

    complete = build_biotech_validation(_fundamental(18.0, False), [_event(scoring_ready=True)], rules)
    assert complete["catalyst"]["status"] == "SCORING_READY_A_B_CATALYST"
    assert complete["catalyst"]["scanner_catalyst_eligible"] is True
    assert complete["catalyst"]["grade_a_exception_date_eligible"] is True


def test_trial_completion_milestone_remains_not_a_readout(rules):
    validation = build_biotech_validation(_fundamental(18.0, False), [_event(scoring_ready=False, candidate=False)], rules)
    assert validation["catalyst"]["status"] == "TRIAL_MILESTONE_ONLY_NOT_A_READOUT"
    assert validation["catalyst"]["scanner_catalyst_eligible"] is False
