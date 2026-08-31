import asyncio

import httpx
import pytest

from app.core.config import load_rules
from app.providers.errors import ProviderError
from app.providers.yahoo_combined import YAHOO_COMBINED_MODULES, YahooCombinedEnrichmentProvider
from app.services.cache_service import JsonFileCache


def _payload():
    return {
        "quoteSummary": {
            "result": [
                {
                    "earningsTrend": {
                        "trend": [
                            {
                                "period": "0y",
                                "earningsEstimate": {"avg": {"raw": 5.0}, "numberOfAnalysts": {"raw": 20}},
                                "epsTrend": {"current": {"raw": 5.0}, "30daysAgo": {"raw": 4.8}, "90daysAgo": {"raw": 4.5}},
                                "epsRevisions": {"upLast30days": {"raw": 8}, "downLast30days": {"raw": 2}},
                            },
                            {
                                "period": "+1y",
                                "earningsEstimate": {"avg": {"raw": 6.0}, "numberOfAnalysts": {"raw": 18}},
                                "revenueEstimate": {"avg": {"raw": 120_000_000_000}},
                            },
                        ]
                    },
                    "financialData": {
                        "targetMeanPrice": {"raw": 125.0},
                        "targetLowPrice": {"raw": 105.0},
                        "targetHighPrice": {"raw": 155.0},
                        "numberOfAnalystOpinions": {"raw": 17},
                    },
                    "majorHoldersBreakdown": {"institutionsPercentHeld": {"raw": 0.62}},
                    "defaultKeyStatistics": {"shortPercentOfFloat": {"raw": 0.31}},
                }
            ],
            "error": None,
        }
    }


def test_combined_provider_uses_one_payload_for_estimates_valuation_and_ownership(tmp_path):
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
            assert request.url.params.get("modules") == YAHOO_COMBINED_MODULES
            assert request.url.params.get("crumb") == "crumb123"
            return httpx.Response(200, json=_payload(), request=request)
        raise AssertionError(f"unexpected URL: {request.url}")

    provider = YahooCombinedEnrichmentProvider(
        cache=JsonFileCache(tmp_path),
        rules=load_rules(),
        transport=httpx.MockTransport(handler),
        min_interval_seconds=0,
    )

    async def run():
        ownership = await provider.get_ownership("TEST")
        estimates = await provider.get_estimates("TEST")
        valuation = await provider.get_valuation_reference("TEST")
        await provider.aclose()
        return ownership, estimates, valuation

    ownership, estimates, valuation = asyncio.run(run())
    assert ownership is not None and ownership.short_float == pytest.approx(0.31)
    assert estimates is not None and estimates.forward_eps_growth == pytest.approx(0.20)
    assert valuation is not None and valuation.target_mean_price == pytest.approx(125.0)
    assert counts == {"fc": 1, "crumb": 1, "quote": 1}


def test_combined_provider_retries_429_with_same_shared_session(tmp_path):
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
            if counts["quote"] == 1:
                return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
            return httpx.Response(200, json=_payload(), request=request)
        raise AssertionError(f"unexpected URL: {request.url}")

    provider = YahooCombinedEnrichmentProvider(
        cache=JsonFileCache(tmp_path),
        rules=load_rules(),
        transport=httpx.MockTransport(handler),
        min_interval_seconds=0,
    )

    async def run():
        result = await provider.get_estimates("TEST")
        await provider.aclose()
        return result

    result = asyncio.run(run())
    assert result is not None
    assert result.forward_eps_growth == pytest.approx(0.20)
    assert counts == {"fc": 1, "crumb": 1, "quote": 2}


def test_combined_provider_reports_rate_limit_explicitly_after_retries(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "fc.yahoo.com":
            return httpx.Response(404, headers={"Set-Cookie": "A3=test; Path=/; Domain=.yahoo.com"}, request=request)
        if request.url.path == "/v1/test/getcrumb":
            return httpx.Response(200, text="crumb123", request=request)
        if request.url.path == "/v10/finance/quoteSummary/TEST":
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        raise AssertionError(f"unexpected URL: {request.url}")

    provider = YahooCombinedEnrichmentProvider(
        cache=JsonFileCache(tmp_path),
        rules=load_rules(),
        transport=httpx.MockTransport(handler),
        min_interval_seconds=0,
    )

    async def run():
        try:
            return await provider.get_ownership("TEST")
        finally:
            await provider.aclose()

    with pytest.raises(ProviderError) as exc:
        asyncio.run(run())
    assert exc.value.code == "PROVIDER_RATE_LIMITED"
    assert exc.value.status_code == 429
