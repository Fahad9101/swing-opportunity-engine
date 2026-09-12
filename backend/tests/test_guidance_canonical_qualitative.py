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


NOW = datetime(2026, 9, 12, tzinfo=UTC)


def rules() -> dict:
    with open("config/soe_v1_1_rules.yaml", "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def qualitative(action: GuidanceAction) -> CanonicalGuidanceFact:
    return CanonicalGuidanceFact(
        ticker="QUAL",
        metric=GuidanceMetric.REVENUE,
        fiscal_period="FY2026",
        period_kind=GuidancePeriodKind.FULL_YEAR,
        accounting_basis="UNSPECIFIED",
        scope_kind=GuidanceScopeKind.COMPANY,
        value_kind=GuidanceValueKind.QUALITATIVE,
        role=GuidanceFactRole.CURRENT,
        low=None,
        high=None,
        unit=GuidanceUnit.UNKNOWN,
        explicit_action=action,
        provenance=[
            GuidanceProvenance(
                source="SEC EDGAR",
                source_url="https://www.sec.gov/qual.htm",
                source_timestamp=NOW,
                evidence=EvidenceBinding(full_text="opaque evidence retained only for provenance"),
            )
        ],
    )


def test_qualitative_lower_with_unknown_unit_reaches_frozen_classifier():
    assessment = CanonicalGuidanceLedger([qualitative(GuidanceAction.LOWER)]).assess(
        "QUAL", rules(), rules_hash="qualitative-test", as_of=NOW
    )
    assert assessment.classification is GuidanceClassification.DETERIORATED
    assert assessment.rule_path == "guidance_v1_1.explicit_lower_or_withdrawal"


def test_qualitative_reaffirm_with_unknown_unit_does_not_crash():
    assessment = CanonicalGuidanceLedger([qualitative(GuidanceAction.REAFFIRM)]).assess(
        "QUAL", rules(), rules_hash="qualitative-test", as_of=NOW
    )
    assert assessment.classification is GuidanceClassification.UNKNOWN
