from app.domain.distress_v1_1 import DistressSectorAdapter
from app.domain.schemas import Instrument
from app.services.distress_sector_service import route_distress_sector


def instrument(*, sector: str | None, industry: str | None) -> Instrument:
    return Instrument(
        ticker="TEST",
        company_name="Test Co",
        exchange="NYSE",
        sector=sector,
        industry=industry,
        market_cap=1_000_000_000,
    )


def test_routes_conventional_company_to_corporate():
    assert route_distress_sector(instrument(sector="Technology", industry="Semiconductors")) is DistressSectorAdapter.CORPORATE


def test_routes_utility_from_sector():
    assert route_distress_sector(instrument(sector="Utilities", industry="Electric Utilities")) is DistressSectorAdapter.UTILITY


def test_routes_bank_from_financial_industry():
    assert route_distress_sector(instrument(sector="Finance", industry="Major Banks")) is DistressSectorAdapter.BANK


def test_routes_insurer_from_financial_industry():
    assert route_distress_sector(instrument(sector="Finance", industry="Property-Casualty Insurers")) is DistressSectorAdapter.INSURER


def test_routes_reit_before_generic_real_estate_guard():
    assert route_distress_sector(instrument(sector="Real Estate", industry="Industrial REIT")) is DistressSectorAdapter.REIT


def test_ambiguous_financial_never_falls_back_to_corporate():
    assert route_distress_sector(instrument(sector="Financials", industry="Capital Markets")) is None


def test_ambiguous_real_estate_never_falls_back_to_corporate():
    assert route_distress_sector(instrument(sector="Real Estate", industry="Real Estate Services")) is None


def test_missing_metadata_remains_unclassified():
    assert route_distress_sector(instrument(sector=None, industry=None)) is None
