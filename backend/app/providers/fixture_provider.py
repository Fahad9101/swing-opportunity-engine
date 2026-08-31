from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

from app.domain.enums import AssetType, CatalystGrade
from app.domain.schemas import Catalyst, EstimateSnapshot, FundamentalSnapshot, Instrument, OHLCVBar


def _now() -> datetime:
    return datetime.now(UTC)


def _bars(ticker: str, base: float, drift: float, pullback: float = 0.0, volume: float = 2_000_000) -> list[OHLCVBar]:
    """Generate explicitly synthetic, deterministic regression history."""
    today = date.today()
    bars: list[OHLCVBar] = []
    business_days: list[date] = []
    cursor = today - timedelta(days=380)
    while cursor <= today:
        if cursor.weekday() < 5:
            business_days.append(cursor)
        cursor += timedelta(days=1)
    business_days = business_days[-260:]
    for index, day in enumerate(business_days):
        trend = base * (1 + drift * index / 260)
        wave = 1 + 0.015 * math.sin(index / 7)
        close = trend * wave
        if index >= 240:
            close *= 1 - pullback * ((index - 239) / 20)
        open_price = close * (0.997 if index % 2 else 1.002)
        bars.append(
            OHLCVBar(
                date=day,
                open=round(open_price, 4),
                high=round(max(open_price, close) * 1.012, 4),
                low=round(min(open_price, close) * 0.988, 4),
                close=round(close, 4),
                volume=volume * (1 + (index % 9) / 25),
            )
        )
    return bars


class FixtureProvider:
    """Complete provider used for regression tests and local trial scans.

    All securities and values are synthetic and must never be presented as live data.
    """

    name = "fixture"

    def __init__(self) -> None:
        now = _now()
        self._instruments = [
            Instrument(ticker="RERATE", company_name="Synthetic Recovery Co", exchange="NYSE", sector="Industrials", industry="Airlines", asset_type=AssetType.COMMON_STOCK, market_cap=12_000_000_000),
            Instrument(ticker="GROWTH", company_name="Synthetic Quality Co", exchange="NASDAQ", sector="Industrials", industry="Distribution", asset_type=AssetType.COMMON_STOCK, market_cap=25_000_000_000),
            Instrument(ticker="BIOCAT", company_name="Synthetic Biotech Co", exchange="NASDAQ", sector="Health Care", industry="Biotechnology", asset_type=AssetType.COMMON_STOCK, market_cap=4_000_000_000, is_biotech=True),
            Instrument(ticker="ILLIQ", company_name="Synthetic Illiquid Co", exchange="NYSE", sector="Consumer", industry="Retail", asset_type=AssetType.COMMON_STOCK, market_cap=600_000_000),
        ]
        self._history = {
            "RERATE": _bars("RERATE", 36, 0.35, pullback=0.05, volume=3_500_000),
            "GROWTH": _bars("GROWTH", 42, 0.45, pullback=0.10, volume=4_000_000),
            "BIOCAT": _bars("BIOCAT", 58, 0.30, pullback=0.04, volume=2_000_000),
            "ILLIQ": _bars("ILLIQ", 8, 0.05, pullback=0.02, volume=50_000),
            "SPY": _bars("SPY", 500, 0.20, volume=50_000_000),
            "QQQ": _bars("QQQ", 450, 0.24, volume=40_000_000),
            "IWM": _bars("IWM", 205, 0.10, volume=30_000_000),
        }
        self._fundamentals = {
            "RERATE": FundamentalSnapshot(ticker="RERATE", revenue_growth=0.12, revenue_growth_qoq=0.04, eps_growth=0.18, fcf_growth=0.20, forward_ebitda_growth=0.16, operating_margin=0.12, operating_margin_prior=0.09, operating_margin_expansion_bps=300, fcf=900_000_000, ebitda=1_500_000_000, cash=2_000_000_000, debt=2_300_000_000, institutional_ownership=0.64, short_float=0.07, business_quality_score=4, balance_sheet_distressed=False, guidance_deterioration=False, valuation_discount=True, expected_swing_upside=0.28, fundamental_undervaluation=0.19, source="synthetic_fixture", as_of=now, fetched_at=now),
            "GROWTH": FundamentalSnapshot(ticker="GROWTH", revenue_growth=0.13, revenue_growth_qoq=0.05, eps_growth=0.19, fcf_growth=0.21, forward_ebitda_growth=0.18, operating_margin=0.18, operating_margin_prior=0.16, operating_margin_expansion_bps=200, fcf=1_100_000_000, ebitda=1_400_000_000, cash=1_900_000_000, debt=400_000_000, institutional_ownership=0.72, short_float=0.04, business_quality_score=5, balance_sheet_distressed=False, guidance_deterioration=False, valuation_discount=True, expected_swing_upside=0.24, fundamental_undervaluation=0.12, source="synthetic_fixture", as_of=now, fetched_at=now),
            "BIOCAT": FundamentalSnapshot(ticker="BIOCAT", revenue_growth=None, cash=1_300_000_000, debt=100_000_000, cash_runway_months=26, financing_secured=False, institutional_ownership=0.58, short_float=0.12, clinical_evidence_quality=4, pipeline_event_importance=5, external_validation=4, balance_sheet_distressed=False, expected_swing_upside=0.35, fundamental_undervaluation=None, source="synthetic_fixture", as_of=now, fetched_at=now),
            "ILLIQ": FundamentalSnapshot(ticker="ILLIQ", revenue_growth=0.06, cash=20_000_000, debt=150_000_000, business_quality_score=2, balance_sheet_distressed=True, source="synthetic_fixture", as_of=now, fetched_at=now),
        }
        self._estimates = {
            "RERATE": EstimateSnapshot(ticker="RERATE", forward_eps_growth=0.21, eps_up_revisions=8, eps_down_revisions=2, revenue_up_revisions=7, revenue_down_revisions=3, ebitda_up_revisions=6, ebitda_down_revisions=2, eps_revision_magnitude=0.08, revenue_revision_magnitude=0.03, analyst_count=18, source="synthetic_fixture", as_of=now, fetched_at=now),
            "GROWTH": EstimateSnapshot(ticker="GROWTH", forward_eps_growth=0.18, eps_up_revisions=7, eps_down_revisions=2, revenue_up_revisions=6, revenue_down_revisions=2, ebitda_up_revisions=7, ebitda_down_revisions=2, analyst_count=15, source="synthetic_fixture", as_of=now, fetched_at=now),
            "BIOCAT": EstimateSnapshot(ticker="BIOCAT", analyst_count=12, source="synthetic_fixture", as_of=now, fetched_at=now),
        }
        event_day = date.today() + timedelta(days=21)
        self._catalysts = {
            "RERATE": [Catalyst(ticker="RERATE", type="EARNINGS", title="Synthetic quarterly earnings", event_date=date.today() + timedelta(days=18), grade=CatalystGrade.A, materiality=7, surprise_potential=3, verified=True, source="synthetic_fixture", source_timestamp=now, summary="Regression-only confirmed earnings date.", as_of=now, fetched_at=now)],
            "GROWTH": [Catalyst(ticker="GROWTH", type="EARNINGS", title="Synthetic quarterly earnings", event_date=date.today() + timedelta(days=32), grade=CatalystGrade.A, materiality=7, surprise_potential=3, verified=True, source="synthetic_fixture", source_timestamp=now, summary="Regression-only confirmed earnings date.", as_of=now, fetched_at=now)],
            "BIOCAT": [Catalyst(ticker="BIOCAT", type="CLINICAL_DATA", title="Synthetic Phase 3 readout", event_date=event_day, grade=CatalystGrade.A, materiality=10, surprise_potential=4, verified=True, source="synthetic_fixture", source_timestamp=now, summary="Regression-only clinical catalyst; not a real event.", as_of=now, fetched_at=now)],
        }

    async def list_instruments(self) -> list[Instrument]:
        return list(self._instruments)

    async def get_ohlcv(self, ticker: str, sessions: int = 260) -> list[OHLCVBar]:
        return list(self._history[ticker][-sessions:])

    async def get_fundamentals(self, ticker: str) -> FundamentalSnapshot | None:
        return self._fundamentals.get(ticker)

    async def get_estimates(self, ticker: str) -> EstimateSnapshot | None:
        return self._estimates.get(ticker)

    async def get_catalysts(self, ticker: str) -> list[Catalyst]:
        return list(self._catalysts.get(ticker, []))

    async def get_vix(self) -> float:
        return 18.5

    async def get_breadth_pct(self) -> float:
        return 58.0

