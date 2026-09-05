from datetime import UTC, datetime

import pytest

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceMetric,
    GuidanceMetricRecord,
    SourceDocument,
)
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_guidance_table_dedupe_v1_1 import (
    dedupe_guidance_records_table_normalized,
)
from app.services.phase_1_1e_guidance_table_normalizer_v1_1 import (
    extract_guidance_facts_table_normalized,
    normalize_comparative_guidance_tables,
)

NOW = datetime(2026, 8, 3, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)

ALSN_TABLE = """
Full Year 2026 Guidance Update ($ in millions)
Prior Guide Updated Guide (May 4, 2026) (August 3, 2026)
$5,575 to $5,925 $5,800 to $6,000 Net Sales $5,750 Midpoint $5,900 Midpoint
$600 to $750 $600 to $700 Net Income $675 Midpoint $650 Midpoint
$1,365 to $1,515 $1,465 to $1,575 Adjusted EBITDA $1,440 Midpoint $1,520 Midpoint
Net Cash Provided by $970 to $1,100 $1,025 to $1,125 Operating Activities $1,035 Midpoint $1,075 Midpoint
$295 to $315 $260 to $280 Capital Expenditures $305 Midpoint $270 Midpoint
$655 to $805 $745 to $865 Adjusted Free Cash Flow $730 Midpoint $805 Midpoint
"""


def _document(text: str = ALSN_TABLE) -> SourceDocument:
    return SourceDocument(
        document_id="alsn-table",
        rules_hash=RULES_HASH,
        ticker="ALSN",
        cik="0001411207",
        accession="0001193125-26-330544",
        form="8-K",
        source="SEC EDGAR",
        source_url="https://www.sec.gov/Archives/edgar/data/1411207/000119312526330544/d95413dex992.htm",
        source_timestamp=NOW,
        fetched_at=NOW,
        content_hash="a" * 64,
        content_type="text/html",
        content=text,
    )


def test_alsn_table_level_millions_and_transposed_rows_are_normalized():
    records = normalize_comparative_guidance_tables(_document(), rules_hash=RULES_HASH)
    by_metric = {}
    for record in records:
        if record.source_timestamp == NOW:
            by_metric[record.metric] = record

    revenue = by_metric[GuidanceMetric.REVENUE]
    assert revenue.fiscal_period == "FY2026"
    assert revenue.low == pytest.approx(5_800_000_000)
    assert revenue.high == pytest.approx(6_000_000_000)
    assert revenue.midpoint == pytest.approx(5_900_000_000)
    assert revenue.explicit_action is GuidanceAction.RAISE
    assert revenue.extraction_method is ExtractionMethod.STRUCTURED

    ebitda = by_metric[GuidanceMetric.EBITDA]
    assert ebitda.low == pytest.approx(1_465_000_000)
    assert ebitda.high == pytest.approx(1_575_000_000)
    assert ebitda.explicit_action is GuidanceAction.RAISE

    fcf = by_metric[GuidanceMetric.FCF]
    assert fcf.low == pytest.approx(745_000_000)
    assert fcf.high == pytest.approx(865_000_000)
    assert fcf.explicit_action is GuidanceAction.RAISE


def test_alsn_normalized_revenue_does_not_bind_next_net_income_row():
    records = normalize_comparative_guidance_tables(_document(), rules_hash=RULES_HASH)
    revenue = next(
        record
        for record in records
        if record.metric is GuidanceMetric.REVENUE
        and record.explicit_action is GuidanceAction.RAISE
    )
    assert revenue.low != pytest.approx(600_000_000)
    assert revenue.high != pytest.approx(700_000_000)
    assert revenue.low == pytest.approx(5_800_000_000)
    assert revenue.high == pytest.approx(6_000_000_000)


def test_alsn_full_extraction_overrides_conflicting_generic_table_record():
    extraction = extract_guidance_facts_table_normalized(_document(), rules_hash=RULES_HASH)
    revenue = [
        record
        for record in extraction.records
        if record.metric is GuidanceMetric.REVENUE and record.fiscal_period == "FY2026"
    ]
    assert len(revenue) == 2
    current = next(record for record in revenue if record.explicit_action is GuidanceAction.RAISE)
    prior = next(record for record in revenue if record.record_id == current.supersedes_record_id)
    assert prior.source_timestamp == NOW
    assert current.source_timestamp == NOW
    assert prior.low == pytest.approx(5_575_000_000)
    assert prior.high == pytest.approx(5_925_000_000)
    assert current.low == pytest.approx(5_800_000_000)
    assert current.high == pytest.approx(6_000_000_000)
    assert "row_version=prior" in (prior.evidence_span or "")
    assert "row_version=updated" in (current.evidence_span or "")


def test_global_dedupe_preserves_normalized_table_record_over_bogus_generic_row():
    normalized = next(
        record
        for record in normalize_comparative_guidance_tables(_document(), rules_hash=RULES_HASH)
        if record.metric is GuidanceMetric.REVENUE
        and record.explicit_action is GuidanceAction.RAISE
    )
    bogus = normalized.model_copy(
        update={
            "low": 600.0,
            "high": 700.0,
            "midpoint": 650.0,
            "explicit_action": GuidanceAction.NONE,
            "extraction_method": ExtractionMethod.DETERMINISTIC_TEXT,
            "evidence_span": "Net Sales $5,750 Midpoint $5,900 Midpoint $600 to $750 $600 to $700 Net Income",
        }
    )
    deduped = dedupe_guidance_records_table_normalized([bogus, normalized])
    revenue = [record for record in deduped if record.metric is GuidanceMetric.REVENUE]
    assert len(revenue) == 1
    assert revenue[0].low == pytest.approx(5_800_000_000)
    assert revenue[0].high == pytest.approx(6_000_000_000)
    assert revenue[0].extraction_method is ExtractionMethod.STRUCTURED


def test_global_dedupe_preserves_linked_prior_and_updated_table_pair():
    normalized = normalize_comparative_guidance_tables(_document(), rules_hash=RULES_HASH)
    deduped = dedupe_guidance_records_table_normalized(normalized)
    revenue = [record for record in deduped if record.metric is GuidanceMetric.REVENUE]
    assert len(revenue) == 2
    current = next(record for record in revenue if record.explicit_action is GuidanceAction.RAISE)
    prior = next(record for record in revenue if record.record_id == current.supersedes_record_id)
    assert prior.low == pytest.approx(5_575_000_000)
    assert current.low == pytest.approx(5_800_000_000)
    assessment = GuidanceLedger(deduped).assess("ALSN", RULES, rules_hash=RULES_HASH, as_of=NOW)
    assert assessment.classification.value == "NOT_DETERIORATED"


def test_alsn_prior_to_updated_revenue_is_not_deteriorated_under_frozen_rules():
    records = normalize_comparative_guidance_tables(_document(), rules_hash=RULES_HASH)
    ledger = GuidanceLedger(records)
    assessment = ledger.assess("ALSN", RULES, rules_hash=RULES_HASH, as_of=NOW)
    assert assessment.guidance_deterioration is False
    assert assessment.classification.value == "NOT_DETERIORATED"


def test_same_document_prior_pair_does_not_leak_before_primary_source_timestamp():
    records = normalize_comparative_guidance_tables(_document(), rules_hash=RULES_HASH)
    ledger = GuidanceLedger(records)
    current, prior = ledger.current_and_prior("ALSN", as_of=datetime(2026, 8, 2, tzinfo=UTC))
    assert current == []
    assert prior == []


def test_ambiguous_comparative_header_does_not_invent_prior_timestamp():
    text = """
    Full Year 2026 Guidance Update ($ in millions)
    Prior Guide Updated Guide
    $5,575 to $5,925 $5,800 to $6,000 Net Sales
    """
    records = normalize_comparative_guidance_tables(_document(text), rules_hash=RULES_HASH)
    revenue = [record for record in records if record.metric is GuidanceMetric.REVENUE]
    assert len(revenue) == 1
    assert revenue[0].source_timestamp == NOW
    assert "row_version=updated" in (revenue[0].evidence_span or "")


def test_table_scale_is_not_applied_to_eps_per_share_ranges():
    text = """
    Full Year 2026 Guidance Update ($ in millions, except per share amounts)
    Prior Guide Updated Guide
    $5,575 to $5,925 $5,800 to $6,000 Net Sales
    $6.50 to $7.00 $6.80 to $7.20 Adjusted Diluted EPS
    """
    records = normalize_comparative_guidance_tables(_document(text), rules_hash=RULES_HASH)
    eps = next(record for record in records if record.metric is GuidanceMetric.EPS)
    assert eps.low == pytest.approx(6.80)
    assert eps.high == pytest.approx(7.20)
    assert eps.unit == "USD/share"
