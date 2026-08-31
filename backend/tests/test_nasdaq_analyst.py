import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from app.core.config import load_rules
from app.providers.nasdaq_analyst import NasdaqAnalystEstimateProvider, normalize_analyst_forecast
from app.services.cache_service import JsonFileCache


def _payload(first="5.00", second="6.00"):
    return {
        "data": {
            "yearlyForecast": {
                "rows": [
                    {
                        "fiscalEnd": "Dec 2026",
                        "consensusEPSForecast": first,
                        "numOfEstimates": "20",
                        "highEPSForecast": "5.50",
                        "lowEPSForecast": "4.50",
                    },
                    {
                        "fiscalEnd": "Dec 2027",
                        "consensusEPSForecast": second,
                        "numOfEstimates": "18",
                        "highEPSForecast": "6.50",
                        "lowEPSForecast": "5.50",
                    },
                ]
            }
        },
        "status": {"rCode": 200},
    }


def test_nasdaq_analyst_forecast_normalizes_forward_eps_growth_without_inventing_revisions():
    now = datetime.now(UTC)
    result = normalize_analyst_forecast("TEST", _payload(), fetched_at=now)
    assert result is not None
    assert result.forward_eps_growth == pytest.approx(0.20)
    assert result.analyst_count == 20
    assert result.eps_up_revisions is None
    assert result.eps_down_revisions is None
    assert result.revenue_revision_30d is None
    assert result.forward_revenue is None


def test_nasdaq_analyst_forecast_leaves_loss_to_profit_growth_unavailable():
    result = normalize_analyst_forecast("LOSS", _payload(first="-0.25", second="0.10"), fetched_at=datetime.now(UTC))
    assert result is not None
    assert result.forward_eps_growth is None


def test_nasdaq_analyst_provider_uses_cache_and_preserves_missing_fields(tmp_path):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        assert request.url.path == "/api/analyst/TEST/forecast"
        return httpx.Response(200, json=_payload(), request=request)

    provider = NasdaqAnalystEstimateProvider(
        cache=JsonFileCache(tmp_path),
        rules=load_rules(),
        transport=httpx.MockTransport(handler),
    )
    first = asyncio.run(provider.get_estimates("TEST"))
    second = asyncio.run(provider.get_estimates("TEST"))
    assert first is not None and second is not None
    assert first.forward_eps_growth == pytest.approx(0.20)
    assert second.forward_eps_growth == pytest.approx(0.20)
    assert calls == 1
