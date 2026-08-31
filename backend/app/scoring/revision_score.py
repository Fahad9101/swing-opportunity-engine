from app.domain.schemas import EstimateSnapshot, ScoreComponent
from app.services.estimate_service import revision_breadth


def breadth_points(value: float | None) -> int | None:
    if value is None: return None
    if value >= 0.80: return 5
    if value >= 0.65: return 4
    if value >= 0.55: return 3
    if value >= 0.45: return 2
    if value >= 0.25: return 1
    return 0


def _contradiction_adjust(points: int | None, breadth: float | None, magnitude: float | None) -> int | None:
    if points is None or breadth is None or magnitude is None: return points
    contradictory = (breadth >= 0.55 and magnitude < 0) or (breadth < 0.45 and magnitude > 0)
    return max(0, points - 1) if contradictory else points


def score_revisions(estimates: EstimateSnapshot | None) -> ScoreComponent:
    if estimates is None:
        return ScoreComponent(score=None, maximum=10, available=False)
    eps_breadth = revision_breadth(estimates.eps_up_revisions, estimates.eps_down_revisions)
    revenue_breadth = revision_breadth(estimates.revenue_up_revisions, estimates.revenue_down_revisions)
    ebitda_breadth = revision_breadth(estimates.ebitda_up_revisions, estimates.ebitda_down_revisions)
    secondary_breadth = max([value for value in (revenue_breadth, ebitda_breadth) if value is not None], default=None)
    eps = _contradiction_adjust(breadth_points(eps_breadth), eps_breadth, estimates.eps_revision_magnitude)
    secondary = _contradiction_adjust(breadth_points(secondary_breadth), secondary_breadth, estimates.revenue_revision_magnitude)
    parts = {"eps_revisions": eps, "revenue_ebitda_revisions": secondary, "eps_breadth": eps_breadth, "revenue_breadth": revenue_breadth, "ebitda_breadth": ebitda_breadth}
    known = [value for value in (eps, secondary) if value is not None]
    return ScoreComponent(score=sum(known) if known else None, maximum=10, available=bool(known), available_points=5 * len(known), components=parts)
