from datetime import UTC, datetime, timedelta

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import GuidanceAction, GuidanceMetric, GuidanceMetricRecord, SourceDocument
from app.services.fact_extraction_service import extract_guidance_facts
from app.services.guidance_classifier import classify_guidance
from app.services.guidance_ledger_service import GuidanceLedger


NOW = datetime(2026, 9, 1, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def _record(
    metric: GuidanceMetric,
    midpoint: float | None,
    *,
    when: datetime,
    period: str = "FY2027",
    basis: str = "ADJUSTED",
    action: GuidanceAction = GuidanceAction.NONE,
    evidence: str | None = None,
) -> GuidanceMetricRecord:
    unit = "fraction" if metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN} else "USD"
    if metric is GuidanceMetric.EPS:
        unit = "USD/share"
    return GuidanceMetricRecord(
        rules_hash=RULES_HASH,
        ticker="TEST",
        fiscal_period=period,
        metric=metric,
        accounting_basis=basis,
        midpoint=midpoint,
        unit=unit,
        source="SEC EDGAR",
        source_url=f"https://www.sec.gov/test/{when.timestamp()}/{metric.value}",
        source_timestamp=when,
        explicit_action=action,
        evidence_span=evidence,
        as_of=when,
        fetched_at=when,
    )


def _document(content: str) -> SourceDocument:
    return SourceDocument(
        document_id="doc-live-regression",
        rules_hash=RULES_HASH,
        ticker="TEST",
        cik="0000000001",
        accession="0000000001-26-000001",
        form="8-K",
        source_url="https://www.sec.gov/Archives/edgar/data/1/1/test.htm",
        source_timestamp=NOW,
        fetched_at=NOW,
        content_hash="f" * 64,
        content=content,
    )


def test_arr_is_not_promoted_to_primary_revenue_guidance():
    result = extract_guidance_facts(
        _document("Q3 FY2027 Guidance Full Year FY2027 Guidance Annual recurring revenue $6.18 billion to $6.19 billion"),
        rules_hash=RULES_HASH,
    )
    assert not any(record.metric is GuidanceMetric.REVENUE for record in result.records)


def test_reported_actual_near_reaffirm_headline_is_excluded_from_assessment_view():
    actual = _record(
        GuidanceMetric.REVENUE,
        47_900_000_000.0,
        when=NOW,
        period="Q2FY2026",
        basis="UNSPECIFIED",
        action=GuidanceAction.REAFFIRM,
        evidence=(
            "Reaffirms Fiscal 2026 Guidance. The company reported sales of $47.9 billion "
            "for the second quarter of fiscal 2026, compared with $45.3 billion last year."
        ),
    )
    current, prior = GuidanceLedger([actual]).current_and_prior("TEST", as_of=NOW)
    assert current == []
    assert prior == []


def test_qualitative_raise_without_midpoint_does_not_block_numeric_comparable_pair():
    current = [
        _record(GuidanceMetric.REVENUE, 101.0, when=NOW, basis="UNSPECIFIED"),
        _record(
            GuidanceMetric.EPS,
            None,
            when=NOW,
            action=GuidanceAction.RAISE,
            evidence="Management raised FY2027 EPS guidance.",
        ),
    ]
    prior = [_record(GuidanceMetric.REVENUE, 100.0, when=NOW - timedelta(days=90), basis="UNSPECIFIED")]
    result = classify_guidance(current, prior, RULES, rules_hash=RULES_HASH, as_of=NOW)
    assert result.guidance_deterioration is False


def test_raise_in_one_metric_does_not_conflict_with_material_cut_in_another_metric():
    current = [
        _record(GuidanceMetric.REVENUE, 105.0, when=NOW, basis="UNSPECIFIED", action=GuidanceAction.RAISE),
        _record(GuidanceMetric.EPS, 9.4, when=NOW),
    ]
    prior = [
        _record(GuidanceMetric.REVENUE, 100.0, when=NOW - timedelta(days=90), basis="UNSPECIFIED"),
        _record(GuidanceMetric.EPS, 10.0, when=NOW - timedelta(days=90)),
    ]
    result = classify_guidance(current, prior, RULES, rules_hash=RULES_HASH, as_of=NOW)
    assert result.guidance_deterioration is True
    assert result.rule_path.endswith("material_numeric_cut")


def test_same_metric_raise_and_material_cut_remains_unknown_conflict():
    current = [_record(GuidanceMetric.REVENUE, 95.0, when=NOW, basis="UNSPECIFIED", action=GuidanceAction.RAISE)]
    prior = [_record(GuidanceMetric.REVENUE, 100.0, when=NOW - timedelta(days=90), basis="UNSPECIFIED")]
    result = classify_guidance(current, prior, RULES, rules_hash=RULES_HASH, as_of=NOW)
    assert result.guidance_deterioration is None
    assert result.rule_path.endswith("conflicting_primary_evidence")
