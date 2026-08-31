import asyncio
from datetime import UTC, datetime

from app.domain.schemas import FundamentalSnapshot
from app.providers.errors import ProviderError
from app.providers.free_public_provider import FreePublicProvider
from app.providers.yahoo_ownership import OwnershipSnapshot


class _Sec:
    async def get_fundamentals(self, ticker):
        now = datetime.now(UTC)
        return FundamentalSnapshot(ticker=ticker, revenue=1_000_000, source="sec", as_of=now, fetched_at=now)


class _Ownership:
    async def get_ownership(self, ticker):
        now = datetime.now(UTC)
        return OwnershipSnapshot(ticker=ticker, institutional_ownership=0.70, short_float=0.10, source="ownership", as_of=now, fetched_at=now)


class _FailingOwnership:
    async def get_ownership(self, ticker):
        raise ProviderError("ownership", "PUBLIC_OWNERSHIP_DATA_UNAVAILABLE", "Unavailable.", retryable=True, ticker=ticker)


def _provider(ownership):
    return FreePublicProvider(
        symbol_directory=object(),
        market=object(),
        sec=_Sec(),
        analyst=object(),
        ownership=ownership,
        calendar=object(),
        clinical_trials=object(),
        vix=object(),
        rules={},
    )


def test_free_public_provider_merges_optional_ownership_into_sec_fundamentals():
    provider = _provider(_Ownership())
    result = asyncio.run(provider.get_fundamentals("TEST"))
    assert result is not None
    assert result.revenue == 1_000_000
    assert result.institutional_ownership == 0.70
    assert result.short_float == 0.10


def test_ownership_failure_does_not_discard_valid_sec_fundamentals():
    provider = _provider(_FailingOwnership())
    result = asyncio.run(provider.get_fundamentals("TEST"))
    assert result is not None
    assert result.revenue == 1_000_000
    assert result.institutional_ownership is None
    errors = provider.drain_provider_errors()
    assert len(errors) == 1
    assert errors[0]["code"] == "PUBLIC_OWNERSHIP_DATA_UNAVAILABLE"
