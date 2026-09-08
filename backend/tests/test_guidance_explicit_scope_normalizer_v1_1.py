from datetime import UTC, datetime

import pytest

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import SourceDocument
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_guidance_table_normalizer_v1_1 import (
    extract_guidance_facts_table_normalized,
)
from app.services.guidance_explicit_scope_normalizer_v1_1 import (
    normalize_explicit_guidance_scopes,
)

RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
HASH = rules_hash(RULES)


def doc(text, month=5):
    when = datetime(2026, month, 6, tzinfo=UTC)
    return SourceDocument(
        document_id=f"audit-{month}",
        rules_hash=HASH,
        ticker="TEST",
        cik="123",
        accession=f"123-26-{month:06}",
        form="8-K",
        source_url=f"https://www.sec.gov/Archives/test-{month}.htm",
        source_timestamp=when,
        fetched_at=when,
        content_hash="a" * 64,
        content=text,
    )


def extract(text):
    return extract_guidance_facts_table_normalized(doc(text), rules_hash=HASH).records


def values(records):
    return {
        (r.metric.value, r.fiscal_period, r.accounting_basis, r.low, r.high)
        for r in records
    }


def test_rock_accompanying_eps_keeps_annual_scope_and_detects_multiple_small_cuts():
    prior = (
        "Guidance for continuing operations for the full year 2025. "
        "Consolidated net sales are expected to range between $1.15 billion and $1.20 billion. "
        "This compares to GAAP net sales of $1.02 billion and adjusted net sales of $1.01 billion in 2024. "
        "GAAP EPS is expected to range between $3.67 and $3.91, compared to $4.58 in 2024, "
        "and adjusted EPS is expected to range between $4.20 and $4.45, compared to $3.82 in 2024."
    )
    current = (
        prior.replace("$1.20 billion", "$1.175 billion")
        .replace("$3.91", "$3.77")
        .replace("$4.45", "$4.30")
    )
    records = [
        *extract(prior),
        *extract_guidance_facts_table_normalized(
            doc(current, 8), rules_hash=HASH
        ).records,
    ]
    assessment = GuidanceLedger(records).assess(
        "TEST", RULES, rules_hash=HASH, as_of=datetime(2026, 9, 8, tzinfo=UTC)
    )
    assert assessment.classification.value == "DETERIORATED"
    assert assessment.rule_path == "guidance_v1_1.multi_metric_small_cut"
    assert all(r.fiscal_period == "FY2025" for r in records)


def test_fabrinet_different_quarters_cannot_form_an_annual_pair():
    text = (
        "Reported results for fiscal year 2025. Business Outlook Based on information available as of May 4, 2026, "
        "Fabrinet is issuing guidance for its fourth fiscal quarter ending June 26, 2026, as follows: "
        "Fabrinet expects fourth quarter revenue to be in the range of $1.25 billion to $1.29 billion. "
        "GAAP net income per diluted share is expected to be in the range of $3.48 to $3.63. "
        "Non-GAAP net income per diluted share is expected to be in the range of $3.72 to $3.87. "
        "Forward-Looking Statements regarding the fourth quarter of fiscal year 2026."
    )
    result = extract(text)
    assert len(result) == 3
    assert {r.fiscal_period for r in result} == {"Q4FY2026"}


def test_quarter_and_annual_columns_keep_units_and_eps_basis():
    text = (
        "Financial Outlook Metric (in millions, except per share amounts) FY 2027 Q1 Guidance FY 2027 Guidance "
        "Revenue $204.5 - 205.5 $884.0 - 889.0 Non-GAAP operating income $10.0 - 11.0 $69.0 - 73.0 "
        "Non-GAAP net income $11.0 - 12.0 $69.0 - 73.0 "
        "Non-GAAP net income per share, diluted $0.10 - 0.11 $0.61 - 0.65"
    )
    assert values(extract(text)) == {
        ("revenue", "Q1FY2027", "UNSPECIFIED", 204500000, 205500000),
        ("revenue", "FY2027", "UNSPECIFIED", 884000000, 889000000),
        ("eps", "Q1FY2027", "ADJUSTED", 0.10, 0.11),
        ("eps", "FY2027", "ADJUSTED", 0.61, 0.65),
    }


def test_multi_year_table_does_not_attach_next_year_ebitda_to_prior_year():
    text = (
        "Updated Fiscal Year 2025 and 2026 Guidance ($ in millions, except percentages) "
        "2024 As Reported 2025 2026(1) Prior Guidance as of November 6, 2025 Updated Guidance Δ YoY Growth Guidance Δ YoY Growth "
        "Revenue $345.3 $461 - $463 $470 - $471 +36% $700 - $715 +50% "
        "Adjusted EBITDA $106.1 $142 - $143 $144.5 - $144.9 +36% ~$205 - $215 +45%"
    )
    assert values(extract(text)) == {
        ("revenue", "FY2025", "UNSPECIFIED", 470e6, 471e6),
        ("revenue", "FY2026", "UNSPECIFIED", 700e6, 715e6),
        ("ebitda", "FY2025", "ADJUSTED", 144.5e6, 144.9e6),
        ("ebitda", "FY2026", "ADJUSTED", 205e6, 215e6),
    }


def test_point_guidance_does_not_borrow_following_historical_year():
    result = extract(
        "Announces 2026 revenue guidance of $40 million. Full Year 2025 Financial Highlights Revenue of $32.5 million."
    )
    assert values(result) == {("revenue", "FY2026", "UNSPECIFIED", 40e6, 40e6)}


def test_point_normalizer_does_not_truncate_a_range():
    result = normalize_explicit_guidance_scopes(
        doc("Full-year 2026 revenue guidance of $212 million to $216 million"),
        rules_hash=HASH,
    )
    assert not any(r.low == 212e6 and r.high == 212e6 for r in result)


def test_zebra_annual_eps_is_not_the_adjacent_quarter_eps():
    result = extract(
        "Outlook Second Quarter 2026 The Company expects growth. "
        "Non-GAAP diluted earnings per share are expected to be in the range of $4.20 to $4.50. "
        "Full Year 2026 The Company expects sales growth. "
        "Non-GAAP diluted earnings per share are expected to be in the range of $18.30 to $18.70."
    )
    assert values(result) == {
        ("eps", "Q2FY2026", "ADJUSTED", 4.2, 4.5),
        ("eps", "FY2026", "ADJUSTED", 18.3, 18.7),
    }


@pytest.mark.parametrize(
    "text",
    [
        "Full Year 2026 Financial Results. GAAP EPS was between $3.00 and $4.00.",
        "Full Year 2026 outlook. GAAP EPS is expected to range between $4.00 and $3.00.",
        "Full Year 2026 outlook. Product revenue guidance raised to $750 to $850 million.",
        "Full Year 2026 outlook. Revenue is expected to range between $1 billion and $900 million.",
    ],
)
def test_ambiguous_reported_and_nonprimary_rows_are_not_normalized(text):
    assert normalize_explicit_guidance_scopes(doc(text), rules_hash=HASH) == []


def test_inline_styling_preserves_total_revenue_digits_without_combining_cells():
    result = extract(
        "<p>PTC Updates Full-Year 2026 Financial Guidance</p>"
        "<p>Expected total revenue increased to $1.1<span>8</span> to $1.2<span>8</span> billion, "
        "with t<span>otal</span> product revenue guidance raised to $850 to $950 million.</p>"
    )
    assert values(result) == {("revenue", "FY2026", "UNSPECIFIED", 1.18e9, 1.28e9)}
    assert (
        normalize_explicit_guidance_scopes(
            doc("<p>2026 revenue guidance of $4</p><p>0 million</p>"), rules_hash=HASH
        )
        == []
    )


def test_calendar_end_date_does_not_determine_fiscal_year():
    text = (
        "Guidance for its first fiscal quarter ending June 26, 2026: "
        "GAAP EPS is expected to range between $3.48 and $3.63. "
        "Forward-Looking Statements regarding the first quarter of fiscal year 2027."
    )
    records = normalize_explicit_guidance_scopes(doc(text), rules_hash=HASH)
    assert {r.fiscal_period for r in records} == {"Q1FY2027"}
    assert (
        normalize_explicit_guidance_scopes(
            doc(text.split("Forward-Looking")[0]), rules_hash=HASH
        )
        == []
    )


def test_forward_verb_before_annual_scope_binds_accompanying_ebitda():
    result = extract(
        "2026 Guidance For the full year 2026, CareDx now expects revenue to be in the range of $447 million to $465 million. "
        "The Company now expects full year 2026 adjusted EBITDA to be in the range of $43 million to $57 million."
    )
    assert ("ebitda", "FY2026", "ADJUSTED", 43e6, 57e6) in values(result)


def test_explicit_margin_accompanying_annual_guidance_is_retained_as_fraction():
    result = extract(
        "Full Year 2026 Outlook: Revenue between $1.463 billion and $1.467 billion. "
        "Non-GAAP operating income between $125.0 million and $135.0 million, representing a "
        "non-GAAP operating margin of 9% at the midpoint of the range."
    )
    assert ("operating_margin", "FY2026", "ADJUSTED", 0.09, 0.09) in values(result)


def test_block_styled_spans_and_scripts_cannot_supply_numeric_guidance():
    result = normalize_explicit_guidance_scopes(
        doc(
            "<script>2026 revenue guidance of $40 million</script>"
            '<span style="display:block">2026 revenue guidance of $4</span>'
            '<span style="display:block">0 million</span>'
        ),
        rules_hash=HASH,
    )
    assert result == []
