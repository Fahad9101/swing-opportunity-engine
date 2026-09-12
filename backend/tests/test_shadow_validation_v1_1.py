from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.config import SOE_1_1_RULES_PATH, load_rules, load_rules_for_version
from app.domain.enums import CatalystGrade
from app.domain.schemas import CorporateEvent, EstimateSnapshot, FundamentalSnapshot
from app.services.shadow_validation_service import (
    CatalystStructuralOverride,
    apply_structural_inputs,
    assert_frozen_rule_equivalence,
    catalyst_event_key,
    evaluate_captured_candidate,
    scanner_delta_violations,
    snapshot_fingerprint,
)


def provenance() -> dict:
    now = datetime.now(UTC)
    return {"source": "test", "as_of": now, "fetched_at": now, "stale": False}


def fundamental(**updates) -> FundamentalSnapshot:
    values = dict(
        ticker="TEST",
        revenue_growth=0.20,
        fcf_growth=0.20,
        forward_ebitda_growth=0.20,
        operating_margin=0.14,
        operating_margin_prior=0.12,
        operating_margin_expansion_bps=200,
        cash=200,
        debt=20,
        valuation_discount=True,
        guidance_deterioration=None,
        balance_sheet_distressed=None,
        **provenance(),
    )
    values.update(updates)
    return FundamentalSnapshot(**values)


def estimates(**updates) -> EstimateSnapshot:
    values = dict(
        ticker="TEST",
        forward_eps_growth=0.20,
        eps_up_revisions=8,
        eps_down_revisions=2,
        revenue_up_revisions=7,
        revenue_down_revisions=2,
        ebitda_up_revisions=6,
        ebitda_down_revisions=2,
        **provenance(),
    )
    values.update(updates)
    return EstimateSnapshot(**values)


def candidate_event() -> CorporateEvent:
    now = datetime.now(UTC)
    event_date = date.today() + timedelta(days=14)
    return CorporateEvent(
        ticker="TEST",
        type="EARNINGS",
        title="Quarterly earnings",
        event_date=event_date,
        verified=True,
        date_confidence=CatalystGrade.A,
        date_precision="DAY",
        window_start=event_date,
        window_end=event_date,
        catalyst_candidate=True,
        materiality=None,
        surprise_potential=None,
        scoring_ready=False,
        missing_score_fields=["materiality", "surprise_potential"],
        evidence_status="verified",
        source_url="https://www.sec.gov/example",
        **provenance(),
    )


def test_candidate_rules_preserve_every_frozen_v1_section():
    baseline = load_rules()
    candidate = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    assert_frozen_rule_equivalence(baseline, candidate)


def test_frozen_rule_guard_fails_closed_on_any_threshold_change():
    baseline = load_rules()
    candidate = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    changed = {**candidate, "growth": {**candidate["growth"], "normal_min_revenue_growth": 0.149}}
    with pytest.raises(ValueError, match="growth"):
        assert_frozen_rule_equivalence(baseline, changed)


def test_snapshot_fingerprint_is_order_independent_but_data_sensitive():
    rows = [
        {"ticker": "BBB", "market": {"price": 20.0}},
        {"ticker": "AAA", "market": {"price": 10.0}},
    ]
    assert snapshot_fingerprint(rows) == snapshot_fingerprint(list(reversed(rows)))
    changed = [dict(rows[0]), {"ticker": "AAA", "market": {"price": 10.01}}]
    assert snapshot_fingerprint(rows) != snapshot_fingerprint(changed)


def test_structural_injection_preserves_nulls_and_promotes_only_complete_event():
    event = candidate_event()
    key = catalyst_event_key(event)

    enriched, catalysts, promoted = apply_structural_inputs(
        fundamental(),
        [event],
        guidance_deterioration=False,
        balance_sheet_distressed=False,
        catalyst_overrides={key: CatalystStructuralOverride(materiality=8, surprise_potential=None)},
    )
    assert enriched is not None
    assert enriched.guidance_deterioration is False
    assert enriched.balance_sheet_distressed is False
    assert catalysts is None
    assert promoted == 0

    enriched, catalysts, promoted = apply_structural_inputs(
        fundamental(),
        [event],
        guidance_deterioration=False,
        balance_sheet_distressed=False,
        catalyst_overrides={key: CatalystStructuralOverride(materiality=8, surprise_potential=3)},
    )
    assert catalysts is not None and len(catalysts) == 1
    assert catalysts[0].materiality == 8
    assert catalysts[0].surprise_potential == 3
    assert promoted == 1


def test_growth_replay_changes_only_the_two_structural_conditions(instrument, market, rules):
    baseline = evaluate_captured_candidate(
        instrument,
        market,
        fundamental(),
        estimates(),
        None,
        rules,
    )
    enriched, catalysts, promoted = apply_structural_inputs(
        fundamental(),
        [],
        guidance_deterioration=False,
        balance_sheet_distressed=False,
    )
    candidate = evaluate_captured_candidate(
        instrument,
        market,
        enriched,
        estimates(),
        catalysts,
        rules,
        promoted_catalysts=promoted,
    )

    growth_before = baseline.scanner_matches["GROWTH_PULLBACK"]
    growth_after = candidate.scanner_matches["GROWTH_PULLBACK"]
    assert growth_before["qualified"] is False
    assert growth_before["evaluation_status"] == "DATA_INCOMPLETE"
    assert growth_after["qualified"] is True
    changed = {
        key
        for key in growth_before["conditions"]
        if growth_before["conditions"].get(key) != growth_after["conditions"].get(key)
    }
    assert changed == {"no_guidance_deterioration", "balance_sheet_not_distressed"}
    assert scanner_delta_violations(baseline, candidate) == []
    assert baseline.scanner_matches["RERATING"]["conditions"] == candidate.scanner_matches["RERATING"]["conditions"]


def test_biotech_replay_can_resolve_only_catalyst_presence(instrument, market, rules):
    bio = instrument.model_copy(update={"is_biotech": True, "market_cap": 1_000_000_000})
    base_fundamental = fundamental(
        cash_runway_months=18,
        financing_secured=False,
        guidance_deterioration=False,
        balance_sheet_distressed=False,
    )
    event = candidate_event()
    baseline = evaluate_captured_candidate(bio, market, base_fundamental, estimates(), None, rules)
    enriched, catalysts, promoted = apply_structural_inputs(
        base_fundamental,
        [event],
        guidance_deterioration=False,
        balance_sheet_distressed=False,
        catalyst_overrides={
            catalyst_event_key(event): CatalystStructuralOverride(materiality=9, surprise_potential=4)
        },
    )
    candidate = evaluate_captured_candidate(
        bio,
        market,
        enriched,
        estimates(),
        catalysts,
        rules,
        promoted_catalysts=promoted,
    )
    assert baseline.scanner_matches["BIOTECH_CATALYST"]["qualified"] is False
    assert candidate.scanner_matches["BIOTECH_CATALYST"]["qualified"] is True
    changed = {
        key
        for key in baseline.scanner_matches["BIOTECH_CATALYST"]["conditions"]
        if baseline.scanner_matches["BIOTECH_CATALYST"]["conditions"].get(key)
        != candidate.scanner_matches["BIOTECH_CATALYST"]["conditions"].get(key)
    }
    assert changed == {"verified_grade_a_or_b_catalyst"}
    assert scanner_delta_violations(baseline, candidate) == []
