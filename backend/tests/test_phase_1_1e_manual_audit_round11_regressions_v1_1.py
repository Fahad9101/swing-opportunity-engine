from datetime import UTC, datetime

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.distress_v1_1 import DistressHardFlag
from app.domain.soe_v1_1 import GuidanceMetric, SourceDocument
from app.services.phase_1_1e_evidence_hygiene_round3_v1_1 import (
    extract_hard_distress_flags_round3,
)
from app.services.phase_1_1e_guidance_table_normalizer_v1_1 import (
    extract_guidance_facts_table_normalized,
)


NOW = datetime(2026, 9, 7, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def _document(ticker: str, content: str) -> SourceDocument:
    return SourceDocument(
        document_id=f"{ticker}-round11",
        rules_hash=RULES_HASH,
        ticker=ticker,
        cik="0000000001",
        accession="0000000001-26-000001",
        form="10-Q",
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1/"
            f"000000000126000001/{ticker.lower()}-20260630.htm"
        ),
        source_timestamp=NOW,
        fetched_at=NOW,
        content_hash="a" * 64,
        content=content,
    )


def test_sm_hypothetical_covenant_default_is_not_current_payment_default():
    document = _document(
        "SM",
        "The Credit Agreement establishes a maximum permitted ratio of total funded debt. "
        "If we exceeded that ratio, we would be in default. In addition, if we are in "
        "default under our revolving credit facility and are unable to obtain a waiver, "
        "the lenders would be entitled to exercise their remedies for default.",
    )

    flags = extract_hard_distress_flags_round3(document)

    assert not any(item["flag"] == DistressHardFlag.PAYMENT_DEFAULT.value for item in flags)


def test_unconditional_current_payment_default_remains_a_hard_flag():
    document = _document(
        "LIVE",
        "The company is in payment default under its senior notes because it did not make "
        "the required interest payment, and the default remains outstanding.",
    )

    flags = extract_hard_distress_flags_round3(document)

    assert any(item["flag"] == DistressHardFlag.PAYMENT_DEFAULT.value for item in flags)


def test_mod_interest_expense_range_cannot_be_bound_to_adjusted_ebitda():
    extraction = extract_guidance_facts_table_normalized(
        _document(
            "MOD",
            "Fiscal 2027 guidance includes adjusted EBITDA, a non-GAAP financial measure. "
            "The guidance includes estimates for interest expense of approximately "
            "$15 million to $18 million, income taxes of $135 million to $145 million, "
            "and depreciation and amortization of $120 million to $130 million.",
        ),
        rules_hash=RULES_HASH,
    )

    assert not any(
        record.metric is GuidanceMetric.EBITDA
        and record.low == 15_000_000
        and record.high == 18_000_000
        for record in extraction.records
    )
    assert any(
        item["reason"] == "cross_metric_row_range_binding"
        for item in extraction.rejected_candidates
    )
