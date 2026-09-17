from __future__ import annotations

from datetime import UTC, datetime

import yaml

from app.domain.guidance_canonical_v1 import (
    EvidenceBinding,
    GuidanceFactRole,
    GuidancePeriodKind,
    GuidanceProvenance,
    GuidanceScopeKind,
    GuidanceUnit,
    GuidanceValueKind,
    TypedGuidanceFact,
)
from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceClassification, GuidanceMetric
from app.services.guidance_canonical_assessment_service import assess_canonicalization_result
from app.services.guidance_canonical_service import CanonicalGuidanceNormalizer, GuidanceInvariantValidator


T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 4, 1, tzinfo=UTC)


def _rules() -> dict:
    with open("config/soe_v1_1_rules.yaml", "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _fact(*, ts: datetime, low: float, high: float, unit: GuidanceUnit, kind: GuidanceValueKind):
    return TypedGuidanceFact(
        ticker="TEST",
        metric=GuidanceMetric.REVENUE,
        raw_metric_label="revenue",
        fiscal_period="FY2026",
        authoritative_period="FY2026",
        period_kind=GuidancePeriodKind.FULL_YEAR,
        accounting_basis="UNSPECIFIED",
        scope_kind=GuidanceScopeKind.COMPANY,
        value_kind=kind,
        role=GuidanceFactRole.CURRENT,
        low=low,
        high=high,
        unit=unit,
        explicit_action=GuidanceAction.NONE,
        extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
        provenance=[
            GuidanceProvenance(
                document_id=f"doc-{ts.date().isoformat()}-{kind.value}",
                source="SEC EDGAR",
                source_url=f"https://www.sec.gov/{ts.date().isoformat()}-{kind.value}.htm",
                source_timestamp=ts,
                source_document_hash=f"hash-{ts.date().isoformat()}-{kind.value}",
                evidence=EvidenceBinding(full_text="opaque typed evidence", metric_text="revenue"),
            )
        ],
    )


def _canonicalize(facts):
    validator = GuidanceInvariantValidator()
    return CanonicalGuidanceNormalizer().normalize(validator.validate(fact) for fact in facts)


def test_same_snapshot_growth_is_supplementary_when_absolute_guidance_is_accepted():
    result = _canonicalize(
        [
            _fact(ts=T1, low=90.0, high=90.0, unit=GuidanceUnit.USD, kind=GuidanceValueKind.ABSOLUTE_LEVEL),
            _fact(ts=T2, low=100.0, high=100.0, unit=GuidanceUnit.USD, kind=GuidanceValueKind.ABSOLUTE_LEVEL),
            _fact(ts=T2, low=20.0, high=20.0, unit=GuidanceUnit.PERCENT, kind=GuidanceValueKind.GROWTH_RATE),
        ]
    )
    assert len(result.quarantined) == 1
    assessment = assess_canonicalization_result(
        result, "TEST", _rules(), rules_hash="test", as_of=T2
    )
    assert assessment.classification is GuidanceClassification.NOT_DETERIORATED
    assert assessment.rule_path != "guidance_v1_1.canonical_unresolved_latest_evidence"


def test_newer_growth_only_guidance_still_blocks_stale_absolute_fallback():
    result = _canonicalize(
        [
            _fact(ts=T1, low=90.0, high=90.0, unit=GuidanceUnit.USD, kind=GuidanceValueKind.ABSOLUTE_LEVEL),
            _fact(ts=T2, low=20.0, high=20.0, unit=GuidanceUnit.PERCENT, kind=GuidanceValueKind.GROWTH_RATE),
        ]
    )
    assessment = assess_canonicalization_result(
        result, "TEST", _rules(), rules_hash="test", as_of=T2
    )
    assert assessment.classification is GuidanceClassification.UNKNOWN
    assert assessment.rule_path == "guidance_v1_1.canonical_unresolved_latest_evidence"
