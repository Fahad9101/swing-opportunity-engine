from __future__ import annotations

from datetime import UTC, datetime

from app.domain.distress_v1_1 import DistressInputs, DistressSectorAdapter
from app.domain.soe_v1_1 import GuidanceMetricRecord, GuidanceMetric
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.shadow_enrichment_service import (
    guidance_comparable_pair_count,
    nonfinancial_distress_decision_evidence,
)


def test_guidance_comparable_denominator_requires_same_period_metric_and_basis():
    older = datetime(2026, 1, 1, tzinfo=UTC)
    newer = datetime(2026, 4, 1, tzinfo=UTC)
    common = dict(
        rules_hash="x",
        ticker="TEST",
        fiscal_period="FY2026",
        metric=GuidanceMetric.REVENUE,
        accounting_basis="UNSPECIFIED",
        unit="USD",
        source="SEC EDGAR",
        source_url="https://www.sec.gov/test",
        verified=True,
    )
    prior = GuidanceMetricRecord(low=100, high=110, source_timestamp=older, **common)
    current = GuidanceMetricRecord(low=105, high=115, source_timestamp=newer, **common)
    assert guidance_comparable_pair_count(GuidanceLedger([prior, current]), "TEST") == 1

    changed_period = current.model_copy(update={"fiscal_period": "FY2027"})
    assert guidance_comparable_pair_count(GuidanceLedger([prior, changed_period]), "TEST") == 0


def test_corporate_net_cash_is_sufficient_decision_evidence(rules):
    inputs = DistressInputs(
        ticker="TEST",
        sector_adapter=DistressSectorAdapter.CORPORATE,
        as_of=datetime.now(UTC),
        net_cash=True,
        debt_outstanding=10,
        sources=["https://data.sec.gov/test"],
    )
    sufficient, reasons = nonfinancial_distress_decision_evidence(inputs, rules | {
        "balance_sheet_distress_v1_1": __import__("app.core.config", fromlist=["load_rules_for_version", "SOE_1_1_RULES_PATH"]).load_rules_for_version(
            __import__("app.core.config", fromlist=["SOE_1_1_RULES_PATH"]).SOE_1_1_RULES_PATH,
            "SOE-1.1.0",
        )["balance_sheet_distress_v1_1"]
    })
    assert sufficient is True
    assert "net_cash_safe_path" in reasons


def test_corporate_gray_zone_is_not_a_coverage_failure_candidate():
    from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version

    rules = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
    inputs = DistressInputs(
        ticker="TEST",
        sector_adapter=DistressSectorAdapter.CORPORATE,
        as_of=datetime.now(UTC),
        net_cash=False,
        debt_outstanding=100,
        net_debt_to_ebitda=4.0,
        interest_coverage=2.5,
        sources=["https://data.sec.gov/test"],
    )
    sufficient, reasons = nonfinancial_distress_decision_evidence(inputs, rules)
    assert sufficient is False
    assert reasons == []
