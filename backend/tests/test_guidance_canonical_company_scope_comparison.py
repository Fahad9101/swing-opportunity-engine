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


T1 = datetime(2026, 7, 2, tzinfo=UTC)
T2 = datetime(2026, 8, 6, tzinfo=UTC)
RULES_HASH = "company-scope-comparison-test"


def rules() -> dict:
    with open("config/soe_v1_1_rules.yaml", "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def provenance(ts: datetime) -> GuidanceProvenance:
    return GuidanceProvenance(
        document_id=f"doc-{ts.date().isoformat()}",
        source="SEC EDGAR",
        source_url=f"https://www.sec.gov/{ts.date().isoformat()}.htm",
        source_accession=f"accession-{ts.date().isoformat()}",
        source_timestamp=ts,
        source_document_hash=f"hash-{ts.date().isoformat()}",
        evidence=EvidenceBinding(full_text="opaque canonical company guidance evidence"),
    )


def company_revenue_fact(*, ts: datetime, scope_label: str | None) -> CanonicalGuidanceFact:
    return CanonicalGuidanceFact(
        ticker="IOVA",
        metric=GuidanceMetric.REVENUE,
        fiscal_period="FY2026",
        period_kind=GuidancePeriodKind.FULL_YEAR,
        accounting_basis="UNSPECIFIED",
        scope_kind=GuidanceScopeKind.COMPANY,
        scope_label=scope_label,
        value_kind=GuidanceValueKind.ABSOLUTE_LEVEL,
        role=GuidanceFactRole.CURRENT,
        low=350_000_000.0,
        high=370_000_000.0,
        unit=GuidanceUnit.USD,
        explicit_action=GuidanceAction.NONE,
        provenance=[provenance(ts)],
    )


def test_company_scope_labels_do_not_split_comparable_guidance_chronology():
    july = company_revenue_fact(ts=T1, scope_label=None)
    august = company_revenue_fact(ts=T2, scope_label="total revenue")

    ledger = CanonicalGuidanceLedger([july, august])
    view = ledger.current_and_prior("IOVA", as_of=T2)

    assert not view.conflicts
    assert len(view.current) == 1
    assert len(view.prior) == 1
    assert view.current[0].available_at == T2
    assert view.prior[0].available_at == T1
    assert view.current[0].comparison_key == view.prior[0].comparison_key

    assessment = ledger.assess("IOVA", rules(), rules_hash=RULES_HASH, as_of=T2)
    assert assessment.classification is GuidanceClassification.NOT_DETERIORATED
    assert assessment.rule_path == "guidance_v1_1.comparable_set_within_tolerance"


def test_company_scope_label_is_preserved_on_canonical_fact():
    august = company_revenue_fact(ts=T2, scope_label="total product revenue")
    ledger = CanonicalGuidanceLedger([august])

    assert ledger.facts[0].scope_label == "total product revenue"
    assert ledger.observations[0].comparison_key[4] == ""
