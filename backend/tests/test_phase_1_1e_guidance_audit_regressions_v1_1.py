from datetime import UTC, datetime, timedelta

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import GuidanceAction, GuidanceMetric, SourceDocument
from app.services.guidance_extraction_hardening_v1_1 import (
    dedupe_guidance_records,
    extract_guidance_facts_hardened,
)
from app.services.guidance_ledger_service import GuidanceLedger


NOW = datetime(2026, 9, 4, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def _document(ticker: str, content: str, *, when: datetime = NOW, suffix: str = "001") -> SourceDocument:
    return SourceDocument(
        document_id=f"{ticker}-{suffix}",
        rules_hash=RULES_HASH,
        ticker=ticker,
        cik="0000000001",
        accession=f"0000000001-26-00{suffix}",
        form="8-K",
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-{suffix}.htm",
        source_timestamp=when,
        fetched_at=when,
        content_hash=(ticker.lower() + suffix + "0" * 64)[:64],
        content=content,
    )


def _extract(ticker: str, content: str, *, when: datetime = NOW, suffix: str = "001"):
    return extract_guidance_facts_hardened(
        _document(ticker, content, when=when, suffix=suffix),
        rules_hash=RULES_HASH,
    )


def _assessment(ticker: str, prior_text: str, current_text: str):
    prior = _extract(ticker, prior_text, when=NOW - timedelta(days=90), suffix="001")
    current = _extract(ticker, current_text, when=NOW, suffix="002")
    records = dedupe_guidance_records([*prior.records, *current.records])
    ledger = GuidanceLedger(records)
    policy = current.policy_evidence or prior.policy_evidence
    return ledger.assess(ticker, RULES, rules_hash=RULES_HASH, policy=policy, as_of=NOW), records


def test_coco_increasing_guidance_is_not_misread_as_lowering():
    result = _extract(
        "COCO",
        "Raises Fiscal Year 2026 Guidance. The company is increasing its full year 2026 guidance. "
        "Net sales are expected to be $790 million to $805 million.",
    )
    assert result.records
    assert not any(record.explicit_action in {GuidanceAction.LOWER, GuidanceAction.WITHDRAW} for record in result.records)
    assert any(record.metric is GuidanceMetric.REVENUE for record in result.records)


def test_weav_quantitative_outlook_suppresses_false_no_guidance_policy():
    result = _extract(
        "WEAV",
        "A boilerplate sentence states that the company does not provide financial guidance in some circumstances. "
        "Financial Third Quarter and Full Year 2026 Outlook. Third quarter 2026 total revenue is expected to be "
        "$68.6 million to $69.6 million. Full year 2026 total revenue is expected to be $273 million to $275 million.",
    )
    assert any(record.metric is GuidanceMetric.REVENUE and record.midpoint is not None for record in result.records)
    assert result.policy_evidence is None


def test_crs_fy2027_fcf_is_not_compared_with_fy2026_fcf():
    assessment, records = _assessment(
        "CRS",
        "Increasing adjusted free cash flow outlook to approximately $350 million in fiscal year 2026.",
        "The company expects to generate $400 million to $430 million in adjusted free cash flow in fiscal year 2027.",
    )
    periods = {record.fiscal_period for record in records if record.metric is GuidanceMetric.FCF}
    assert "FY2026" in periods
    assert "FY2027" in periods
    assert assessment.guidance_deterioration is None
    assert not assessment.rule_path.endswith("material_numeric_cut")


def test_hni_lower_volume_growth_expectations_is_not_lower_guidance_action():
    result = _extract(
        "HNI",
        "For full year 2026, lower volume growth expectations reflect a softer demand environment. "
        "The company continues to expect adjusted EPS of $3.10 to $3.30.",
    )
    assert not any(record.explicit_action is GuidanceAction.LOWER for record in result.records)


def test_mux_lower_cost_production_is_not_lower_guidance_action():
    result = _extract(
        "MUX",
        "The 2026 outlook reflects lower-cost gold production and improved mine sequencing. "
        "Management expects adjusted EBITDA of $220 million to $240 million for full year 2026.",
    )
    assert not any(record.explicit_action is GuidanceAction.LOWER for record in result.records)


def test_wdfc_suspended_repurchases_do_not_create_guidance_withdrawal():
    result = _extract(
        "WDFC",
        "The share repurchase program may be modified, suspended or discontinued at any time. "
        "Updated Fiscal Year 2026 Guidance. The company expects net sales of $630 million to $650 million for full year 2026.",
    )
    assert any(record.metric is GuidanceMetric.REVENUE for record in result.records)
    assert not any(record.explicit_action is GuidanceAction.WITHDRAW for record in result.records)


def test_gh_higher_revenue_guidance_is_not_material_cut():
    assessment, records = _assessment(
        "GH",
        "Raises Full Year 2026 Revenue Guidance. Full year 2026 revenue is expected to be $1.30 billion to $1.32 billion.",
        "Raises Full Year 2026 Revenue Guidance. Full year 2026 revenue is expected to be $1.34 billion to $1.36 billion.",
    )
    revenue = [record for record in records if record.metric is GuidanceMetric.REVENUE]
    assert len(revenue) >= 2
    assert assessment.guidance_deterioration is False


def test_bb_higher_fy2027_adjusted_ebitda_is_not_material_cut():
    assessment, records = _assessment(
        "BB",
        "The company expects adjusted EBITDA to be between $110 million and $130 million in fiscal 2027 as a whole.",
        "The company now expects adjusted EBITDA to be between $119 million and $139 million in fiscal 2027 as a whole.",
    )
    ebitda = [record for record in records if record.metric is GuidanceMetric.EBITDA]
    assert len(ebitda) >= 2
    assert {record.fiscal_period for record in ebitda} == {"FY2027"}
    assert assessment.guidance_deterioration is False


def test_dxpe_reported_results_without_outlook_do_not_become_guidance():
    prior = _extract(
        "DXPE",
        "First quarter 2026 results: sales were $510 million and adjusted EBITDA was $48 million. "
        "The company reported strong execution and completed two acquisitions.",
        when=NOW - timedelta(days=90),
        suffix="001",
    )
    current = _extract(
        "DXPE",
        "Second quarter 2026 results: sales were $535 million and adjusted EBITDA was $51 million. "
        "Management discussed market conditions and year-to-date performance.",
        when=NOW,
        suffix="002",
    )
    records = dedupe_guidance_records([*prior.records, *current.records])
    assert records == []


def test_amcr_fcf_cut_is_detected_against_previous_range():
    assessment, records = _assessment(
        "AMCR",
        "Reaffirming Fiscal Year 2026 Guidance. Full year 2026 free cash flow is expected to be $1.8 billion to $1.9 billion.",
        "Updated Fiscal Year 2026 Guidance. Full year 2026 free cash flow is expected to be $1.5 billion to $1.6 billion, "
        "relative to previous guidance of $1.8 billion to $1.9 billion.",
    )
    fcf = [record for record in records if record.metric is GuidanceMetric.FCF]
    assert len(fcf) >= 2
    assert assessment.guidance_deterioration is True
    assert assessment.rule_path.endswith("material_numeric_cut")
