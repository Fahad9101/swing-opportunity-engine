from app.domain.schemas import FundamentalSnapshot, ScoreComponent


def _trajectory(value: float | None) -> int | None:
    if value is None: return None
    if value >= 0.25: return 5
    if value >= 0.15: return 4
    if value >= 0.08: return 3
    if value > 0: return 2
    if value == 0: return 1
    return 0


def score_fundamentals(fundamental: FundamentalSnapshot | None) -> ScoreComponent:
    if fundamental is None:
        return ScoreComponent(score=None, maximum=20, available=False)
    revenue = _trajectory(fundamental.revenue_growth)
    margin_delta = None
    if fundamental.operating_margin is not None and fundamental.operating_margin_prior is not None:
        margin_delta = fundamental.operating_margin - fundamental.operating_margin_prior
    margin = _trajectory(margin_delta * 5 if margin_delta is not None else None)
    trajectory_values = [value for value in (fundamental.eps_growth, fundamental.fcf_growth) if value is not None]
    eps_fcf = _trajectory(max(trajectory_values)) if trajectory_values else None
    quality = fundamental.business_quality_score
    parts = {"revenue_trajectory": revenue, "margin_trajectory": margin, "eps_fcf_trajectory": eps_fcf, "business_quality": quality}
    known = [value for value in parts.values() if value is not None]
    if not known:
        return ScoreComponent(score=None, maximum=20, available=False, components=parts)
    return ScoreComponent(score=sum(known), maximum=20, available_points=5 * len(known), components=parts)
