from app.domain.schemas import FundamentalSnapshot, ScoreComponent


def _runway_score(months: float | None) -> int | None:
    if months is None: return None
    if months > 24: return 5
    if months >= 18: return 4
    if months >= 12: return 3
    if months >= 9: return 1
    return 0


def score_biotech_fundamentals(fundamental: FundamentalSnapshot | None) -> ScoreComponent:
    if fundamental is None:
        return ScoreComponent(score=None, maximum=20, available=False)
    parts = {"cash_runway": _runway_score(fundamental.cash_runway_months), "clinical_evidence_quality": fundamental.clinical_evidence_quality, "pipeline_event_importance": fundamental.pipeline_event_importance, "external_validation": fundamental.external_validation}
    known = [value for value in parts.values() if value is not None]
    return ScoreComponent(score=sum(known) if known else None, maximum=20, available=bool(known), available_points=5 * len(known), components=parts)
