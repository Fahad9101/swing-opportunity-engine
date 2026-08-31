from app.domain.schemas import FundamentalSnapshot, ScoreComponent


def _upside_points(value: float | None) -> int | None:
    if value is None: return None
    if value < 0.15: return 0
    if value < 0.20: return 3
    if value < 0.25: return 6
    if value < 0.30: return 8
    if value < 0.40: return 10
    return 12


def _support_points(value: float | None) -> int | None:
    if value is None: return None
    if value < 0: return 0
    if value < 0.10: return 2
    if value < 0.15: return 4
    if value <= 0.25: return 6
    return 8


def score_valuation(fundamental: FundamentalSnapshot | None) -> ScoreComponent:
    if fundamental is None:
        return ScoreComponent(score=None, maximum=20, available=False)
    upside = _upside_points(fundamental.expected_swing_upside)
    support = _support_points(fundamental.fundamental_undervaluation)
    known = [value for value in (upside, support) if value is not None]
    available_points = (12 if upside is not None else 0) + (8 if support is not None else 0)
    return ScoreComponent(score=sum(known) if known else None, maximum=20, available=bool(known), available_points=available_points, components={"expected_swing_upside": upside, "fundamental_valuation_support": support, "upside_input": fundamental.expected_swing_upside, "undervaluation_input": fundamental.fundamental_undervaluation})
