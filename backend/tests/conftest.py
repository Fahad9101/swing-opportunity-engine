import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "sqlite:///./.soe_test.db"
os.environ["PROVIDER_NAME"] = "fixture"

from app.core.config import load_rules  # noqa: E402
from app.domain.enums import AssetType  # noqa: E402
from app.domain.schemas import Instrument, MarketSnapshot  # noqa: E402


@pytest.fixture(scope="session")
def rules():
    return load_rules()


@pytest.fixture
def instrument():
    return Instrument(ticker="TEST", company_name="Test Co", exchange="NASDAQ", sector="Industrials", industry="Tools", asset_type=AssetType.COMMON_STOCK, market_cap=500_000_000)


def market_factory(**overrides):
    now = datetime.now(UTC)
    values = dict(ticker="TEST", price=20, previous_close=19.5, volume=1_000_000, avg_volume_20d=1_000_000, avg_dollar_volume_20d=20_000_000, relative_volume=1.0, sma20=19, sma50=18, sma200=16, sma50_slope_20d=0.03, sma200_slope_20d=0.02, rsi14=50, atr14=1, high20d=22, high50d=22, high52w=25, low52w=10, return1d=0.02, return3d=0.03, return5d=0.04, return20d=0.08, distance_from_sma20_pct=0.05, distance_from_sma50_pct=0.11, distance_from_sma200_pct=0.25, pullback_from_50d_high_pct=0.10, trading_days=252, source="test", as_of=now, fetched_at=now, stale=False)
    values.update(overrides)
    return MarketSnapshot(**values)


@pytest.fixture
def market():
    return market_factory()

