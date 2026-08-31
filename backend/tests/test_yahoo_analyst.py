import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from app.core.config import load_rules
from app.providers.yahoo_analyst import (
    YahooAnalystEstimateProvider,
    normalize_yahoo_earnings_trend,
    normalize_yahoo_valuation_reference,
)
from app.services.cache_service import JsonFileCache


def _payload(current_eps=5.0, next_eps=6.0):
    return {
        "quoteSummary": {
            "result": [
                {
                    "earningsTrend": {
                        "trend": [
                            {
                                "period": "0y",
                                "earningsEstimate": {
                                    "avg": {"raw": current_eps},
                                    "numberOfAnalysts": {"raw": 20},
                                },
                                "revenueEstimate": {"avg": {"raw": 100_000_000_000}},
                                "epsTrend": {
                                    "current": {"raw": 5.0},
                                    "30daysAgo": {"raw": 4.8},
                                    "90daysAgo": {"raw": 4.5},
                                },
                                "epsRevisions": {
                                    "upLast30days": {"raw": 8},
                                    "downLast30days": {"raw": 2},
                                },
                            },
                            {
                                "period": "+1y",
                                "earningsEstimate": {
                                    "avg": {"raw": next_eps},
                                    "numberOfAnalysts": {"raw": 18},
                                },
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
                }
            ],
            "error": None,
        }
    }


def test_yahoo_earnings_trend_normalizes_forward_growth_and_revision_breadth_inputs():
    result = normalize_yahoo_earnings_trend("TEST", _payload(), fetched_at=datetime.now(UTC))
    assert result is not None
    assert result.forward_eps_growth == pytest.approx(0.20)
    assert result.eps_up_revisions == 8
    assert result.eps_down_revisions == 2
    assert result.eps_revision_30d == pytest.approx(5.0 / 4.8 - 1)
    assert result.eps_revision_90d == pytest.approx(5.0 / 4.5 - 1)
    assert result.forward_revenue == pytest.approx(120_000_000_000)
    assert result.analyst_count == 20
    assert result.revenue_up_revisions is None
    assert result.revenue_down_revisions is None
    assert result.ebitda_up_revisions is None
    assert result.ebitda_down_revisions is None


def test_yahoo_valuation_reference_normalizes_positive_targets_only():
    result = normalize_yahoo_valuation_reference("TEST", _payload(), fetched_at=datetime.now(UTC))
    assert result is not None
    assert result.target_mean_price == 125.0
    assert result.target_low_price == 105.0
    assert result.target_high_price == 155.0
    assert result.analyst_opinions == 17
    assert result.field_provenance["target_mean_price"].raw_field == "financialData.targetMeanPrice"

    payload = _payload()
    payload["quoteSummary"]["result"][0]["financialData"]["targetMeanPrice"] = {"raw": -10}
    invalid = normalize_yahoo_valuation_reference("TEST", payload, fetched_at=datetime.now(UTC))
    assert invalid is not None
    assert invalid.target_mean_price is None


def test_yahoo_earnings_trend_does_not_invent_growth_from_negative_base_eps():
    result = normalize_yahoo_earnings_trend("LOSS", _payload(current_eps=-0.25, next_eps=0.10), fetched_at=datetime.now(UTC))
    assert result is not None
    assert result.forward_eps_growth is None


def test_yahoo_provider_bootstraps_crumb_and_shares_cache_between_estimates_and_valuation(tmp_path):
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
            assert request.url.params.get("modules") == "earningsTrend,financialData"
            assert request.url.params.get("crumb") == "crumb123"
            return httpx.Response(200, json=_payload(), request=request)
        raise AssertionError(f"unexpected URL: {request.url}")

    provider = YahooAnalystEstimateProvider(
        cache=JsonFileCache(tmp_path),
        rules=load_rules(),
        transport=httpx.MockTransport(handler),
    )
    first = asyncio.run(provider.get_estimates("TEST"))
    valuation = asyncio.run(provider.get_valuation_reference("TEST"))
    second = asyncio.run(provider.get_estimates("TEST"))
    assert first is not None and second is not None and valuation is not None
    assert first.forward_eps_growth == pytest.approx(0.20)
    assert second.forward_eps_growth == pytest.approx(0.20)
    assert valuation.target_mean_price == 125.0
    assert counts == {"fc": 1, "crumb": 1, "quote": 1}
