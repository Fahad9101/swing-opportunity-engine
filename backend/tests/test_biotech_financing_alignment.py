import asyncio
from datetime import UTC, date, datetime

from app.domain.schemas import FundamentalSnapshot
from app.providers.sec_biotech_fallback import SecBiotechLiquidityFallbackProvider
from app.providers.sec_biotech_validated import SecBiotechValidatedProvider


def test_financing_review_realigns_to_effective_runway_period(monkeypatch):
    now = datetime.now(UTC)
    base = FundamentalSnapshot(
        ticker="BIO",
        cash_runway_months=24.0,
        financing_secured=False,
        source="test",
        as_of=now,
        fetched_at=now,
        raw={"biotech_runway": {"as_of": "2026-06-30", "cash_runway_months": 24.0}},
    )

    async def fake_parent(self, ticker, fundamental):
        return base

    monkeypatch.setattr(SecBiotechLiquidityFallbackProvider, "enrich_fundamental", fake_parent)

    class FakeSec:
        async def ticker_map(self):
            return {"BIO": "0000000001"}

    provider = object.__new__(SecBiotechValidatedProvider)
    provider.sec = FakeSec()
    captured = {}

    async def fake_assess(ticker, cik, balance_sheet_date):
        captured["date"] = balance_sheet_date
        return False, {
            "status": "NO_COMPLETED_FINANCING_AFTER_BALANCE_SHEET",
            "balance_sheet_date": balance_sheet_date.isoformat(),
        }, now

    provider.assess_post_period_financing = fake_assess
    result = asyncio.run(provider.enrich_fundamental("BIO", base))
    assert captured["date"] == date(2026, 6, 30)
    assert result.financing_secured is False
    assert result.raw["biotech_financing"]["balance_sheet_date"] == "2026-06-30"
