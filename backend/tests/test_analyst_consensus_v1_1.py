from datetime import UTC, datetime

from app.domain.catalyst_surprise_v1_1 import SurpriseExpectationMetric
from app.providers.analyst_consensus_v1_1 import normalize_yahoo_surprise_consensus


NOW = datetime(2026, 9, 3, tzinfo=UTC)


def payload():
    return {
        "quoteSummary": {
            "result": [
                {
                    "earningsTrend": {
                        "trend": [
                            {
                                "period": "0q",
                                "earningsEstimate": {
                                    "avg": {"raw": 2.0},
                                    "high": {"raw": 2.4},
                                    "low": {"raw": 1.8},
                                    "numberOfAnalysts": {"raw": 21},
                                },
                                "revenueEstimate": {
                                    "avg": {"raw": 10_000.0},
                                    "high": {"raw": 10_600.0},
                                    "low": {"raw": 9_400.0},
                                    "numberOfAnalysts": {"raw": 18},
                                },
                                "epsTrend": {
                                    "current": {"raw": 2.0},
                                    "90daysAgo": {"raw": 1.7},
                                },
                            },
                            {
                                "period": "0y",
                                "earningsEstimate": {
                                    "avg": {"raw": 8.0},
                                    "high": {"raw": 8.8},
                                    "low": {"raw": 7.2},
                                    "numberOfAnalysts": {"raw": 24},
                                },
                                "revenueEstimate": {
                                    "avg": {"raw": 40_000.0},
                                    "high": {"raw": 42_000.0},
                                    "low": {"raw": 38_000.0},
                                    "numberOfAnalysts": {"raw": 22},
                                },
                                "epsTrend": {
                                    "current": {"raw": 8.0},
                                    "90daysAgo": {"raw": 7.5},
                                },
                            },
                        ]
                    }
                }
            ],
            "error": None,
        }
    }


def test_quarterly_earnings_uses_current_quarter_consensus_context():
    eps, revenue = normalize_yahoo_surprise_consensus(
        "TEST", payload(), event_type="quarterly_earnings", fetched_at=NOW
    )
    assert eps is not None and revenue is not None
    assert eps.period == "0q"
    assert eps.metric == SurpriseExpectationMetric.EPS
    assert eps.average == 2.0
    assert eps.high == 2.4
    assert eps.low == 1.8
    assert eps.current_estimate == 2.0
    assert eps.estimate_90d_ago == 1.7
    assert eps.field_provenance["high"].endswith("earningsEstimate.high")
    assert revenue.metric == SurpriseExpectationMetric.REVENUE
    assert revenue.average == 10_000.0


def test_full_year_guidance_uses_current_year_consensus_context():
    eps, revenue = normalize_yahoo_surprise_consensus(
        "TEST", payload(), event_type="formal_full_year_guidance_update", fetched_at=NOW
    )
    assert eps is not None and revenue is not None
    assert eps.period == "0y"
    assert eps.average == 8.0
    assert eps.estimate_90d_ago == 7.5
    assert revenue.average == 40_000.0


def test_parser_preserves_missing_ranges_for_deterministic_null_or_fallback_logic():
    data = payload()
    estimate = data["quoteSummary"]["result"][0]["earningsTrend"]["trend"][0]["earningsEstimate"]
    estimate.pop("high")
    estimate.pop("low")
    eps, _ = normalize_yahoo_surprise_consensus(
        "TEST", data, event_type="earnings", fetched_at=NOW
    )
    assert eps is not None
    assert eps.high is None
    assert eps.low is None
    assert eps.current_estimate == 2.0
    assert eps.estimate_90d_ago == 1.7


def test_unsupported_event_does_not_repurpose_consensus_data():
    eps, revenue = normalize_yahoo_surprise_consensus(
        "TEST", payload(), event_type="major_contract_customer_award", fetched_at=NOW
    )
    assert eps is None
    assert revenue is None
