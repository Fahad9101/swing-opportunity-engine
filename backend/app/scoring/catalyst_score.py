from datetime import date

from app.domain.enums import CatalystGrade
from app.domain.schemas import Catalyst, ScoreComponent


def _timing_score(days: int | None) -> int:
    if days is None or days < 1 or days > 56: return 0
    if days <= 3: return 3
    if days <= 35: return 5
    return 3


def score_catalyst(catalysts: list[Catalyst]) -> ScoreComponent:
    verified = [item for item in catalysts if item.verified]
    if not verified:
        return ScoreComponent(score=None, maximum=25, available=False, components={"reason": None})
    candidates: list[tuple[int, dict]] = []
    for item in verified:
        event_day = item.event_date or item.window_start
        days = (event_day - date.today()).days if event_day else None
        timing = _timing_score(days)
        confidence = {CatalystGrade.A: 5, CatalystGrade.B: 3, CatalystGrade.C: 0}[item.grade]
        total = item.materiality + timing + confidence + item.surprise_potential
        candidates.append((total, {"type": item.type, "title": item.title, "materiality": item.materiality, "timing": timing, "date_confidence": confidence, "surprise": item.surprise_potential, "days": days}))
    total, components = max(candidates, key=lambda value: value[0])
    return ScoreComponent(score=total, maximum=25, components=components)

