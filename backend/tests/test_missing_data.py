from app.domain.schemas import EstimateSnapshot
from app.scoring.liquidity_score import score_liquidity
from app.scoring.revision_score import score_revisions


def test_unavailable_institutional_ownership_is_not_zero(market):
    score = score_liquidity(market, None)
    assert score.components["institutional_ownership"] is None
    assert score.components["institutional_ownership_available"] is False


def test_zero_revision_denominator_is_null():
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    estimates = EstimateSnapshot(ticker="TEST", eps_up_revisions=0, eps_down_revisions=0, source="test", as_of=now, fetched_at=now)
    score = score_revisions(estimates)
    assert score.components["eps_breadth"] is None
    assert score.components["eps_revisions"] is None

