from __future__ import annotations

from calendar import monthrange
from datetime import date

from app.domain.enums import CatalystGrade
from app.domain.schemas import Catalyst, CorporateEvent


_ESTIMATED_TIMINGS = {"ESTIMATED", "ANTICIPATED", "EXPECTED", "GUIDED", "FORECAST", "PROJECTED"}


def parse_public_date(value: str) -> tuple[date, str, date, date]:
    """Normalize a public date string without pretending coarse windows are exact.

    The returned anchor preserves compatibility with the existing CorporateEvent
    schema; callers must use ``date_precision`` and ``window_start/window_end``
    when the public source only supplies a month or year.
    """
    value = value.strip()
    if len(value) == 10:
        exact = date.fromisoformat(value)
        return exact, "DAY", exact, exact
    if len(value) == 7:
        year, month = (int(part) for part in value.split("-"))
        start = date(year, month, 1)
        end = date(year, month, monthrange(year, month)[1])
        return start, "MONTH", start, end
    if len(value) == 4:
        year = int(value)
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        return start, "YEAR", start, end
    raise ValueError(f"Unsupported public date precision: {value}")


def classify_date_confidence(*, verified: bool, date_precision: str | None, timing: str | None = None) -> CatalystGrade:
    """Operationalize the frozen SOE A/B/C catalyst-confidence definitions.

    A = confirmed exact date / narrow window.
    B = high-confidence guided or estimated window.
    C = speculative or too coarse to be a narrow guided window.

    This function changes no score bands or points. It only normalizes public
    source date quality into the pre-existing A/B/C field.
    """
    if not verified:
        return CatalystGrade.C
    precision = (date_precision or "").upper()
    timing_value = (timing or "").upper()
    estimated = timing_value in _ESTIMATED_TIMINGS
    if precision == "DAY" and not estimated:
        return CatalystGrade.A
    if precision in {"DAY", "MONTH"}:
        return CatalystGrade.B
    return CatalystGrade.C


def annotate_catalyst_evidence(
    event: CorporateEvent,
    *,
    date_precision: str,
    window_start: date,
    window_end: date,
    catalyst_candidate: bool,
    evidence_status: str,
    source_url: str | None = None,
) -> CorporateEvent:
    grade = classify_date_confidence(
        verified=event.verified,
        date_precision=date_precision,
        timing=event.timing,
    )
    missing: list[str] = []
    if catalyst_candidate:
        if event.materiality is None:
            missing.append("materiality")
        if event.surprise_potential is None:
            missing.append("surprise_potential")
    scoring_ready = bool(
        catalyst_candidate
        and event.verified
        and not event.stale
        and event.materiality is not None
        and event.surprise_potential is not None
    )
    return event.model_copy(
        update={
            "date_confidence": grade,
            "date_precision": date_precision,
            "window_start": window_start,
            "window_end": window_end,
            "catalyst_candidate": catalyst_candidate,
            "scoring_ready": scoring_ready,
            "missing_score_fields": missing,
            "evidence_status": evidence_status,
            "source_url": source_url,
        }
    )


def promote_scoring_ready_event(event: CorporateEvent) -> Catalyst | None:
    """Promote evidence only when every frozen catalyst-score input exists.

    Free/public events with unknown materiality or surprise remain evidence only;
    missing values are never converted to zero and cannot influence scanners or
    the 25-point catalyst score.
    """
    if not event.scoring_ready or not event.catalyst_candidate:
        return None
    if event.date_confidence is None or event.materiality is None or event.surprise_potential is None:
        return None
    event_date = event.event_date if event.date_precision == "DAY" else None
    return Catalyst(
        ticker=event.ticker,
        type=event.type,
        title=event.title,
        event_date=event_date,
        window_start=event.window_start,
        window_end=event.window_end,
        grade=event.date_confidence,
        materiality=event.materiality,
        surprise_potential=event.surprise_potential,
        verified=event.verified,
        source=event.source,
        source_timestamp=event.fetched_at,
        summary=event.evidence_status or "Verified public catalyst evidence.",
        as_of=event.as_of,
        fetched_at=event.fetched_at,
        stale=event.stale,
    )
