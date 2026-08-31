from __future__ import annotations

from datetime import date
from typing import Any

from app.domain.enums import CatalystGrade
from app.domain.schemas import CorporateEvent, FundamentalSnapshot


def classify_runway_status(fundamental: FundamentalSnapshot | None, rules: dict[str, Any]) -> str:
    if fundamental is None or fundamental.cash_runway_months is None:
        return "DATA_INCOMPLETE"
    runway = fundamental.cash_runway_months
    financing = fundamental.financing_secured
    biotech = rules["biotech"]
    if runway < biotech["automatic_reject_cash_runway_months"]:
        if financing is True:
            return "FINANCING_EXCEPTION"
        if financing is False:
            return "AUTO_REJECT_BELOW_9M"
        return "DATA_INCOMPLETE_FINANCING"
    if runway < biotech["standard_min_cash_runway_months"]:
        return "FINANCING_EXCEPTION" if financing is True else "BELOW_STANDARD_9_TO_12M"
    if runway >= biotech["preferred_cash_runway_months"]:
        return "PREFERRED_18M_PLUS"
    return "ELIGIBLE_12_TO_18M"


def classify_catalyst_eligibility(events: list[CorporateEvent], rules: dict[str, Any]) -> dict[str, Any]:
    today = date.today()
    horizon = rules["catalyst"]["max_horizon_days"]
    grade_a_exception_days = rules["biotech"]["catalyst_exception_days"]

    in_horizon: list[CorporateEvent] = []
    for event in events:
        start = event.window_start or event.event_date
        end = event.window_end or event.event_date
        if (end - today).days < 0 or (start - today).days > horizon:
            continue
        in_horizon.append(event)

    scored_ab = [
        event for event in in_horizon
        if event.catalyst_candidate and event.scoring_ready and event.verified and event.date_confidence in {CatalystGrade.A, CatalystGrade.B}
    ]
    date_only_ab = [
        event for event in in_horizon
        if event.catalyst_candidate and not event.scoring_ready and event.verified and event.date_confidence in {CatalystGrade.A, CatalystGrade.B}
    ]
    milestone_only = [event for event in in_horizon if not event.catalyst_candidate and event.type.startswith("CLINICAL_TRIAL_")]
    grade_a_exception = [
        event for event in scored_ab
        if event.date_confidence == CatalystGrade.A
        and 0 <= ((event.event_date - today).days) <= grade_a_exception_days
    ]

    if scored_ab:
        status = "SCORING_READY_A_B_CATALYST"
    elif date_only_ab:
        status = "A_B_DATE_EVIDENCE_SCORE_INPUTS_INCOMPLETE"
    elif milestone_only:
        status = "TRIAL_MILESTONE_ONLY_NOT_A_READOUT"
    elif in_horizon:
        status = "PUBLIC_EVENT_NOT_SCANNER_ELIGIBLE"
    else:
        status = "NO_PUBLIC_CATALYST_EVIDENCE_IN_HORIZON"

    return {
        "status": status,
        "scanner_catalyst_eligible": bool(scored_ab),
        "grade_a_exception_date_eligible": bool(grade_a_exception),
        "scoring_ready_a_b_count": len(scored_ab),
        "date_evidence_a_b_incomplete_count": len(date_only_ab),
        "trial_milestone_only_count": len(milestone_only),
        "in_horizon_event_count": len(in_horizon),
        "events": [
            {
                "type": event.type,
                "title": event.title,
                "date_confidence": event.date_confidence.value if event.date_confidence else None,
                "date_precision": event.date_precision,
                "window_start": (event.window_start or event.event_date).isoformat(),
                "window_end": (event.window_end or event.event_date).isoformat(),
                "catalyst_candidate": event.catalyst_candidate,
                "scoring_ready": event.scoring_ready,
                "missing_score_fields": event.missing_score_fields,
                "evidence_status": event.evidence_status,
                "source": event.source,
            }
            for event in in_horizon
        ],
    }


def build_biotech_validation(
    fundamental: FundamentalSnapshot | None,
    events: list[CorporateEvent],
    rules: dict[str, Any],
) -> dict[str, Any]:
    runway_status = classify_runway_status(fundamental, rules)
    catalyst = classify_catalyst_eligibility(events, rules)
    return {
        "runway_status": runway_status,
        "cash_runway_months": None if fundamental is None else fundamental.cash_runway_months,
        "financing_secured": None if fundamental is None else fundamental.financing_secured,
        "financing_evidence": None if fundamental is None else fundamental.raw.get("biotech_financing"),
        "runway_evidence": None if fundamental is None else fundamental.raw.get("biotech_runway"),
        "catalyst": catalyst,
    }
