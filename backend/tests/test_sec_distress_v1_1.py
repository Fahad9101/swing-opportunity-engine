from datetime import UTC, datetime

import pytest

from app.domain.distress_v1_1 import DistressSectorAdapter
from app.providers.sec_distress import normalize_distress_companyfacts
from app.services.distress_metric_service import derive_distress_inputs


FETCHED = datetime(2026, 9, 2, tzinfo=UTC)


def fact(val, end, *, start=None, form="10-Q", filed="2026-08-01"):
    row = {"val": val, "end": end, "form": form, "filed": filed}
    if start:
        row["start"] = start
    return row


def payload(concepts):
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


def normalize(concepts):
    return normalize_distress_companyfacts(
        "TEST",
        payload(concepts),
        sector_adapter=DistressSectorAdapter.CORPORATE,
        fetched_at=FETCHED,
    )


def test_uses_same_balance_sheet_date_for_cash_debt_and_investments():
    facts = normalize(
        {
            "CashAndCashEquivalentsAtCarryingValue": [
                fact(100, "2026-06-30"),
                fact(999, "2026-03-31"),
            ],
            "ShortTermInvestments": [fact(50, "2026-06-30")],
            "LongTermDebtCurrent": [fact(20, "2026-06-30")],
            "LongTermDebtNoncurrent": [fact(180, "2026-06-30")],
        }
    )
    assert facts.cash == 100
    assert facts.marketable_securities == 50
    assert facts.debt == 200
    assert facts.liquid_assets_complete is True
    assert facts.audit["balance_period_end"] == "2026-06-30"


def test_missing_marketable_securities_is_not_assumed_zero():
    facts = normalize(
        {
            "CashAndCashEquivalentsAtCarryingValue": [fact(100, "2026-06-30")],
            "LongTermDebtNoncurrent": [fact(500, "2026-06-30")],
            "OperatingIncomeLoss": [fact(100, "2025-12-31", start="2025-01-01", form="10-K")],
            "DepreciationDepletionAndAmortization": [fact(20, "2025-12-31", start="2025-01-01", form="10-K")],
        }
    )
    assert facts.liquid_assets_complete is False
    metrics = derive_distress_inputs(facts)
    assert metrics.net_debt_to_ebitda is None
    assert metrics.net_cash is None


def test_cash_alone_can_still_prove_net_cash_safety():
    facts = normalize(
        {
            "CashAndCashEquivalentsAtCarryingValue": [fact(200, "2026-06-30")],
            "LongTermDebtNoncurrent": [fact(100, "2026-06-30")],
        }
    )
    metrics = derive_distress_inputs(facts)
    assert metrics.net_cash is True
    assert metrics.net_debt_to_ebitda is None


def test_combined_liquid_assets_tag_supports_complete_leverage_math():
    facts = normalize(
        {
            "CashCashEquivalentsAndShortTermInvestments": [fact(150, "2026-06-30")],
            "LongTermDebtNoncurrent": [fact(450, "2026-06-30")],
            "OperatingIncomeLoss": [fact(80, "2025-12-31", start="2025-01-01", form="10-K")],
            "DepreciationDepletionAndAmortization": [fact(20, "2025-12-31", start="2025-01-01", form="10-K")],
        }
    )
    metrics = derive_distress_inputs(facts)
    assert facts.liquid_assets_complete is True
    assert metrics.net_debt_to_ebitda == pytest.approx(3.0)


def test_total_long_term_debt_is_not_double_counted_with_current_noncurrent_alternatives():
    facts = normalize(
        {
            "CashAndCashEquivalentsAtCarryingValue": [fact(100, "2026-06-30")],
            "ShortTermInvestments": [fact(50, "2026-06-30")],
            "LongTermDebt": [fact(400, "2026-06-30")],
            "LongTermDebtCurrent": [fact(40, "2026-06-30")],
            "LongTermDebtNoncurrent": [fact(360, "2026-06-30")],
            "ShortTermBorrowings": [fact(25, "2026-06-30")],
        }
    )
    assert facts.debt == pytest.approx(425)


def test_annual_ebitda_and_cash_interest_must_share_period_end():
    facts = normalize(
        {
            "CashAndCashEquivalentsAtCarryingValue": [fact(100, "2026-06-30")],
            "ShortTermInvestments": [fact(50, "2026-06-30")],
            "LongTermDebtNoncurrent": [fact(450, "2026-06-30")],
            "OperatingIncomeLoss": [fact(120, "2025-12-31", start="2025-01-01", form="10-K")],
            "DepreciationDepletionAndAmortization": [fact(30, "2025-12-31", start="2025-01-01", form="10-K")],
            "InterestPaidNet": [fact(40, "2025-12-31", start="2025-01-01", form="10-K")],
        }
    )
    assert facts.ebit == 120
    assert facts.ebitda == 150
    assert facts.cash_interest_expense == 40
    metrics = derive_distress_inputs(facts)
    assert metrics.net_debt_to_ebitda == pytest.approx(2.0)
    assert metrics.interest_coverage == pytest.approx(3.0)


def test_companyfacts_does_not_invent_maturities_revolver_or_regulatory_metrics():
    facts = normalize(
        {
            "CashAndCashEquivalentsAtCarryingValue": [fact(100, "2026-06-30")],
            "ShortTermInvestments": [fact(50, "2026-06-30")],
            "LongTermDebtCurrent": [fact(40, "2026-06-30")],
        }
    )
    assert facts.debt_maturities_12m is None
    assert facts.committed_undrawn_revolver is None
    assert facts.cet1_ratio is None
    assert facts.debt_to_ebitdare is None
    assert facts.trailing_fcf is None


def test_source_is_official_sec_companyfacts_endpoint():
    facts = normalize({"CashAndCashEquivalentsAtCarryingValue": [fact(100, "2026-06-30")]})
    assert facts.sources == ["https://data.sec.gov/api/xbrl/companyfacts/CIK0000001234.json"]
