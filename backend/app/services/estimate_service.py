from app.domain.schemas import EstimateSnapshot


def revision_breadth(up: int | None, down: int | None) -> float | None:
    if up is None or down is None or up + down == 0:
        return None
    return up / (up + down)


def has_positive_revision_trend(estimates: EstimateSnapshot | None) -> bool | None:
    if estimates is None:
        return None
    breadths = [
        revision_breadth(estimates.eps_up_revisions, estimates.eps_down_revisions),
        revision_breadth(estimates.revenue_up_revisions, estimates.revenue_down_revisions),
        revision_breadth(estimates.ebitda_up_revisions, estimates.ebitda_down_revisions),
    ]
    known = [value for value in breadths if value is not None]
    return max(known) >= 0.55 if known else None


def has_strong_negative_revision_trend(estimates: EstimateSnapshot | None) -> bool | None:
    if estimates is None:
        return None
    breadths = [
        revision_breadth(estimates.eps_up_revisions, estimates.eps_down_revisions),
        revision_breadth(estimates.revenue_up_revisions, estimates.revenue_down_revisions),
        revision_breadth(estimates.ebitda_up_revisions, estimates.ebitda_down_revisions),
    ]
    known = [value for value in breadths if value is not None]
    return min(known) < 0.25 if known else None

