import pytest

from app.services.universe_service import passes_universal_gate
from conftest import market_factory


@pytest.mark.parametrize("price,passed", [(6.99, False), (7.00, True)])
def test_price_boundary(instrument, rules, price, passed):
    assert passes_universal_gate(instrument, market_factory(price=price), rules).passed is passed


@pytest.mark.parametrize("cap,passed", [(499_999_999, False), (500_000_000, True)])
def test_normal_market_cap_boundary(instrument, market, rules, cap, passed):
    assert passes_universal_gate(instrument.model_copy(update={"market_cap": cap}), market, rules).passed is passed


@pytest.mark.parametrize("cap,passed", [(299_999_999, False), (300_000_000, True)])
def test_biotech_market_cap_boundary(instrument, rules, cap, passed):
    bio = instrument.model_copy(update={"market_cap": cap, "is_biotech": True})
    assert passes_universal_gate(bio, market_factory(avg_dollar_volume_20d=5_000_000), rules).passed is passed


@pytest.mark.parametrize("adv,passed", [(9_999_999, False), (10_000_000, True)])
def test_normal_adv_boundary(instrument, rules, adv, passed):
    assert passes_universal_gate(instrument, market_factory(avg_dollar_volume_20d=adv), rules).passed is passed


def test_gate_returns_structured_rejections(instrument, rules):
    result = passes_universal_gate(instrument, market_factory(price=5, avg_dollar_volume_20d=1), rules)
    assert result.passed is False
    assert "PRICE_TOO_LOW" in result.rejection_codes
    assert "LIQUIDITY_TOO_LOW" in result.rejection_codes

