from datetime import UTC, date, datetime

from app.domain.enums import CatalystGrade
from app.domain.schemas import CorporateEvent
from app.providers.clinical_trials import normalize_trial_events
from app.services.catalyst_evidence_service import (
    annotate_catalyst_evidence,
    classify_date_confidence,
    parse_public_date,
    promote_scoring_ready_event,
)


def _event(**updates) -> CorporateEvent:
    now = datetime.now(UTC)
    values = {
        "ticker": "TEST",
        "type": "EARNINGS",
        "title": "Test earnings",
        "event_date": date(2026, 9, 15),
        "timing": "AFTER_HOURS",
        "verified": True,
        "source": "public-test",
        "as_of": now,
        "fetched_at": now,
        "stale": False,
    }
    values.update(updates)
    return CorporateEvent(**values)


def test_frozen_date_confidence_definitions_are_operationalized_without_points():
    assert classify_date_confidence(verified=True, date_precision="DAY", timing="AFTER_HOURS") == CatalystGrade.A
    assert classify_date_confidence(verified=True, date_precision="DAY", timing="ESTIMATED") == CatalystGrade.B
    assert classify_date_confidence(verified=True, date_precision="MONTH", timing="ESTIMATED") == CatalystGrade.B
    assert classify_date_confidence(verified=True, date_precision="YEAR", timing="ESTIMATED") == CatalystGrade.C
    assert classify_date_confidence(verified=False, date_precision="DAY", timing=None) == CatalystGrade.C


def test_public_date_parser_preserves_coarse_window():
    anchor, precision, start, end = parse_public_date("2026-09")
    assert anchor == date(2026, 9, 1)
    assert precision == "MONTH"
    assert start == date(2026, 9, 1)
    assert end == date(2026, 9, 30)


def test_verified_earnings_evidence_does_not_fabricate_materiality_or_surprise():
    base = _event()
    evidence = annotate_catalyst_evidence(
        base,
        date_precision="DAY",
        window_start=base.event_date,
        window_end=base.event_date,
        catalyst_candidate=True,
        evidence_status="VERIFIED_EARNINGS_DATE_SCORE_INPUTS_INCOMPLETE",
    )
    assert evidence.date_confidence == CatalystGrade.A
    assert evidence.materiality is None
    assert evidence.surprise_potential is None
    assert evidence.scoring_ready is False
    assert evidence.missing_score_fields == ["materiality", "surprise_potential"]
    assert promote_scoring_ready_event(evidence) is None


def test_only_complete_explicit_score_inputs_can_be_promoted():
    base = _event(materiality=7, surprise_potential=3)
    evidence = annotate_catalyst_evidence(
        base,
        date_precision="DAY",
        window_start=base.event_date,
        window_end=base.event_date,
        catalyst_candidate=True,
        evidence_status="EXPLICIT_SCORE_INPUTS_AVAILABLE",
    )
    promoted = promote_scoring_ready_event(evidence)
    assert evidence.scoring_ready is True
    assert evidence.missing_score_fields == []
    assert promoted is not None
    assert promoted.grade == CatalystGrade.A
    assert promoted.materiality == 7
    assert promoted.surprise_potential == 3


def test_clinical_trials_month_is_guided_window_and_not_a_readout(monkeypatch):
    monkeypatch.setattr(
        "app.providers.clinical_trials.date",
        type("FixedDate", (date,), {"today": classmethod(lambda cls: date(2026, 8, 31))}),
    )
    payload = {
        "studies": [
            {
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT1", "briefTitle": "Phase 2 study"},
                    "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Arrowhead Pharmaceuticals, Inc."}},
                    "statusModule": {
                        "primaryCompletionDateStruct": {"date": "2026-09", "type": "ESTIMATED"}
                    },
                }
            }
        ]
    }
    events = normalize_trial_events(
        "ARWR",
        payload,
        fetched_at=datetime.now(UTC),
        horizon_days=56,
        sponsor="Arrowhead Pharmaceuticals",
    )
    assert len(events) == 1
    event = events[0]
    assert event.date_precision == "MONTH"
    assert event.window_start == date(2026, 9, 1)
    assert event.window_end == date(2026, 9, 30)
    assert event.date_confidence == CatalystGrade.B
    assert event.catalyst_candidate is False
    assert event.scoring_ready is False
    assert event.evidence_status == "TRIAL_MILESTONE_ONLY_NOT_A_READOUT"
    assert promote_scoring_ready_event(event) is None


def test_clinical_trials_rejects_unrelated_lead_sponsor(monkeypatch):
    monkeypatch.setattr(
        "app.providers.clinical_trials.date",
        type("FixedDate", (date,), {"today": classmethod(lambda cls: date(2026, 8, 31))}),
    )
    payload = {
        "studies": [
            {
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT2", "briefTitle": "Unrelated study"},
                    "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Different Biotech LLC"}},
                    "statusModule": {
                        "completionDateStruct": {"date": "2026-09-20", "type": "ESTIMATED"}
                    },
                }
            }
        ]
    }
    assert normalize_trial_events(
        "ARWR",
        payload,
        fetched_at=datetime.now(UTC),
        horizon_days=56,
        sponsor="Arrowhead Pharmaceuticals",
    ) == []
