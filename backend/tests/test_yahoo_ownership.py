import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from app.core.config import load_rules
from app.domain.schemas import FundamentalSnapshot
from app.providers.free_public_provider import merge_ownership_into_fundamentals
from app.providers.yahoo_ownership import YahooOwnershipProvider, normalize_yahoo_ownership
from app.scoring.penalties import build_penalties
from app.services.cache_service import JsonFileCache


def _payload(institutional=0.62, short_float=0.31):
    return {
        "quoteSummary": {
            "result": [
                {
                    "majorHoldersBreakdown": {
                        "institutionsPercentHeld": {"raw": institutional},
                    },
                    "defaultKeyStatistics": {
                        "shortPercentOfFloat": {"raw": short_float},
                    },
                }
            ],
            "error": None,
        }
    }


def test_yahoo_ownership_normalizes_fractional_fields_without_rescaling():
    result = normalize_yahoo_ownership("TEST", _payload(), fetched_at=datetime.now(UTC))
    assert result is not None
    assert result.institutional_ownership == pytest.approx(0.62)
    assert result.short_float == pytest.approx(0.31)
    assert result.field_provenance["institutional_ownership"].raw_field == "majorHoldersBreakdown.institutionsPercentHeld"
    assert result.field_provenance["short_float"].raw_field == "defaultKeyStatistics.shortPercentOfFloat"


def test_yahoo_ownership_rejects_implausible_ranges_instead_of_clipping():
    result = normalize_yahoo_ownership("BAD", _payload(institutional=2.5, short_float=1.2), fetched_at=datetime.now(UTC))
    assert result is None


def test_yahoo_ownership_provider_bootstraps_crumb_and_caches(tmp_path):
    counts = {"fc": 0, "crumb": 0, "quote": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fc.yahoo.com":
            counts["fc"] += 1
            return httpx.Response(404, headers={"Set-Cookie": "A3=test; Path=/; Domain=.yahoo.com"}, request=request)
        if request.url.path == "/v1/test/getcrumb":
            counts["crumb"] += 1
            return httpx.Response(200, text="crumb123", request=request)
        if request.url.path == "/v10/finance/quoteSummary/TEST":
            counts["quote"] += 1
            assert request.url.params.get("modules") == "majorHoldersBreakdown,defaultKeyStatistics"
            assert request.url.params.get("crumb") == "crumb123"
            return httpx.Response(200, json=_payload(), request=request)
        raise AssertionError(f"unexpected URL: {request.url}")

    provider = YahooOwnershipProvider(
        cache=JsonFileCache(tmp_path),
        rules=load_rules(),
        transport=httpx.MockTransport(handler),
    )
    first = asyncio.run(provider.get_ownership("TEST"))
    second = asyncio.run(provider.get_ownership("TEST"))
    assert first is not None and second is not None
    assert first.short_float == pytest.approx(0.31)
    assert second.institutional_ownership == pytest.approx(0.62)
    assert counts == {"fc": 1, "crumb": 1, "quote": 1}


def _fundamental() -> FundamentalSnapshot:
    now = datetime.now(UTC)
    return FundamentalSnapshot(
        ticker="TEST",
        revenue=1_000_000,
        source="SEC EDGAR companyfacts",
        as_of=now,
        fetched_at=now,
    )


def test_ownership_enrichment_activates_existing_short_float_penalty_only_above_25pct():
    ownership = normalize_yahoo_ownership("TEST", _payload(short_float=0.31), fetched_at=datetime.now(UTC))
    assert ownership is not None
    enriched = merge_ownership_into_fundamentals(_fundamental(), ownership)
    assert enriched.institutional_ownership == pytest.approx(0.62)
    assert enriched.short_float == pytest.approx(0.31)
    flags = enriched.raw["penalty_flags"]
    assert [flag["code"] for flag in flags] == ["short_float_over_25"]
    penalties = build_penalties(flags, load_rules())
    assert len(penalties) == 1
    assert penalties[0].points == -2


def test_short_float_at_frozen_25pct_threshold_does_not_trigger_penalty():
    ownership = normalize_yahoo_ownership("TEST", _payload(short_float=0.25), fetched_at=datetime.now(UTC))
    assert ownership is not None
    enriched = merge_ownership_into_fundamentals(_fundamental(), ownership)
    assert enriched.short_float == pytest.approx(0.25)
    assert enriched.raw.get("penalty_flags") is None
