from __future__ import annotations

from datetime import UTC, datetime

import yaml

from app.domain.guidance_canonical_v1 import (
    CanonicalGuidanceFact,
    EvidenceBinding,
    GuidanceFactRole,
    GuidancePeriodKind,
    GuidanceProvenance,
    GuidanceScopeKind,
    GuidanceUnit,
    GuidanceValueKind,
)
from app.domain.soe_v1_1 import GuidanceAction, GuidanceClassification, GuidanceMetric
from app.services.guidance_canonical_ledger_service import CanonicalGuidanceLedger


T1 = datetime(2026, 1, 1, tzinfo=UTC)
T2 = datetime(2026, 4, 1, tzinfo=UTC)
RULES_HASH = "canonical-ledger-test"


def rules() -> dict:
    with open("config/soe_v1_1_rules.yaml", "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def provenance(ts: datetime, text: str = "opaque canonical evidence") -> GuidanceProvenance:
    return GuidanceProvenance(
        document_id=f"doc-{ts.date().isoformat()}",
        source="SEC EDGAR",
        source_url=f"https://www.sec.gov/{ts.date().isoformat()}.htm",
        source_accession=f"accession-{ts.date().isoformat()}",
        source_timestamp=ts,
        source_document_hash=f"hash-{ts.date().isoformat()}",
        evidence=EvidenceBinding(full_text=text),
    )


def fact(
    *,
    ticker: str = "TEST",
    metric: GuidanceMetric = GuidanceMetric.REVENUE,
    period: str = "FY2026",
    low: float = 100.0,
    high: float = 100.0,
    ts: datetime = T1,
    action: GuidanceAction = GuidanceAction.NONE,
    role: GuidanceFactRole = GuidanceFactRole.CURRENT,
    evidence: str = "opaque canonical evidence",
    basis: str = "UNSPECIFIED",
) -> CanonicalGuidanceFact:
    return CanonicalGuidanceFact(
        ticker=ticker,
        metric=metric,
        fiscal_period=period,
        period_kind=GuidancePeriodKind.FULL_YEAR,
        accounting_basis=basis,
        scope_kind=GuidanceScopeKind.COMPANY,
        value_kind=GuidanceValueKind.ABSOLUTE_LEVEL,
        role=role,
        low=low,
        high=high,
        unit=GuidanceUnit.USD_PER_SHARE if metric is GuidanceMetric.EPS else GuidanceUnit.USD,
        explicit_action=action,
        provenance=[provenance(ts, evidence)],
    )


def test_repeated_identical_guidance_preserves_point_in_time_chronology():
    repeated = fact(low=100.0, high=100.0, ts=T1)
    repeated = repeated.model_copy(update={"provenance": [provenance(T1), provenance(T2)]})

    ledger = CanonicalGuidanceLedger([repeated])
    assert len(ledger.observations) == 2
    view = ledger.current_and_prior("TEST", as_of=T2)
    assert len(view.current) == 1
    assert len(view.prior) == 1
    assert view.current[0].available_at == T2
    assert view.prior[0].available_at == T1

    assessment = ledger.assess("TEST", rules(), rules_hash=RULES_HASH, as_of=T2)
    assert assessment.classification is GuidanceClassification.NOT_DETERIORATED


def test_material_canonical_cut_is_classified_without_reparsing_prose():
    prior = fact(low=100.0, high=100.0, ts=T1)
    current = fact(
        low=95.0,
        high=95.0,
        ts=T2,
        evidence=(
            "This intentionally misleading text says Q3 FY2024 bookings were 999 billion. "
            "Canonical metric/period/value fields remain authoritative."
        ),
    )

    assessment = CanonicalGuidanceLedger([prior, current]).assess(
        "TEST", rules(), rules_hash=RULES_HASH, as_of=T2
    )
    assert assessment.classification is GuidanceClassification.DETERIORATED
    assert assessment.rule_path == "guidance_v1_1.material_numeric_cut"


def test_new_metric_without_prior_does_not_block_existing_comparable_metric():
    prior_revenue = fact(metric=GuidanceMetric.REVENUE, low=100.0, high=100.0, ts=T1)
    current_revenue = fact(metric=GuidanceMetric.REVENUE, low=101.0, high=101.0, ts=T2)
    current_eps = fact(
        metric=GuidanceMetric.EPS,
        low=5.0,
        high=5.0,
        ts=T2,
        basis="ADJUSTED",
    )

    assessment = CanonicalGuidanceLedger([prior_revenue, current_revenue, current_eps]).assess(
        "TEST", rules(), rules_hash=RULES_HASH, as_of=T2
    )
    assert assessment.classification is GuidanceClassification.NOT_DETERIORATED


def test_same_snapshot_conflicting_canonical_values_fail_closed():
    current_a = fact(low=100.0, high=100.0, ts=T2)
    current_b = fact(low=80.0, high=80.0, ts=T2)

    assessment = CanonicalGuidanceLedger([current_a, current_b]).assess(
        "TEST", rules(), rules_hash=RULES_HASH, as_of=T2
    )
    assert assessment.classification is GuidanceClassification.UNKNOWN
    assert assessment.rule_path == "guidance_v1_1.canonical_conflict"


def test_same_snapshot_quoted_prior_supports_comparison():
    quoted_prior = fact(
        low=100.0,
        high=100.0,
        ts=T2,
        role=GuidanceFactRole.QUOTED_PRIOR,
    )
    current = fact(low=98.0, high=98.0, ts=T2, role=GuidanceFactRole.CURRENT)

    assessment = CanonicalGuidanceLedger([quoted_prior, current]).assess(
        "TEST", rules(), rules_hash=RULES_HASH, as_of=T2
    )
    assert assessment.classification is GuidanceClassification.DETERIORATED


def test_no_accepted_canonical_guidance_is_unknown():
    assessment = CanonicalGuidanceLedger([]).assess(
        "MISSING", rules(), rules_hash=RULES_HASH, as_of=T2
    )
    assert assessment.classification is GuidanceClassification.UNKNOWN
    assert assessment.rule_path == "guidance_v1_1.no_canonical_guidance"
