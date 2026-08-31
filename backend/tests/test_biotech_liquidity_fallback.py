from datetime import date

import pytest

from app.providers.sec_biotech_fallback import apply_filing_liquidity_fallback, extract_periodic_filing_liquidity


def test_periodic_filing_fallback_recovers_explicit_arrowhead_style_liquidity():
    document = """
    <html><body>
    <p>As of June 30, 2026, the Company had $54.8 million in cash, cash equivalents and restricted cash
    and $1,547.2 million in available-for-sale securities to fund operations.</p>
    <p>The Company is eligible to receive up to $16.2 billion in potential collaboration milestone payments.</p>
    </body></html>
    """
    result = extract_periodic_filing_liquidity(document, date(2026, 6, 30))
    assert result["cash"] == pytest.approx(54_800_000)
    assert result["marketable_securities"] == pytest.approx(1_547_200_000)
    assert result["combined_liquidity"] is None


def test_milestone_or_collaboration_amount_is_never_treated_as_liquidity():
    document = """
    <html><body>
    <p>As of June 30, 2026, cash and cash equivalents were $75.0 million.</p>
    <p>The Company may receive up to $16.2 billion in development and commercial milestone payments.</p>
    </body></html>
    """
    result = extract_periodic_filing_liquidity(document, date(2026, 6, 30))
    assert result["marketable_securities"] is None
    assert result["combined_liquidity"] is None
    assert result["cash"] == pytest.approx(75_000_000)


def test_unscaled_sec_table_amounts_are_not_guessed_as_dollars_or_thousands():
    document = """
    <html><body>
    <table><tr><td>Available-for-sale securities</td><td>$1,547,201</td></tr></table>
    <p>(amounts in thousands)</p>
    </body></html>
    """
    result = extract_periodic_filing_liquidity(document, date(2026, 6, 30))
    assert result["marketable_securities"] is None


def test_filing_marketables_recompute_runway_without_changing_burn_method():
    runway = {
        "cash_runway_months": 1.8,
        "status": "DERIVED",
        "cash": 69_400_000.0,
        "marketable_securities": None,
        "liquidity": 69_400_000.0,
        "conservative_monthly_burn": 38_472_222.22,
        "method": "liquidity / max(latest-quarter burn, trailing negative-quarter burn)",
    }
    filing = {
        "cash": 54_800_000.0,
        "marketable_securities": 1_547_200_000.0,
        "combined_liquidity": None,
    }
    result = apply_filing_liquidity_fallback(runway, filing)
    assert result["liquidity"] == pytest.approx(1_602_000_000)
    assert result["cash_runway_months"] > 40
    assert result["status"] == "DERIVED_WITH_PERIODIC_FILING_LIQUIDITY_FALLBACK"


def test_existing_companyfacts_marketables_are_not_overridden_by_filing_parser():
    runway = {
        "cash_runway_months": 20.0,
        "cash": 100_000_000.0,
        "marketable_securities": 500_000_000.0,
        "liquidity": 600_000_000.0,
        "conservative_monthly_burn": 30_000_000.0,
    }
    filing = {"cash": 90_000_000.0, "marketable_securities": 550_000_000.0, "combined_liquidity": None}
    assert apply_filing_liquidity_fallback(runway, filing) is runway
