"""Run-83 source-transcribed expectations through extraction AND global dedupe.

These synthetic excerpts test binding, not point-in-time acceptance of the run.
"""
from datetime import UTC, datetime
import json

import pytest

from test_guidance_explicit_scope_normalizer_v1_1 import doc, values, HASH, RULES
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_guidance_table_normalizer_v1_1 import extract_guidance_facts_table_normalized
from app.services.phase_1_1e_guidance_table_dedupe_v1_1 import dedupe_guidance_records_table_normalized as dedupe


def pipeline(text, month=5):
    return dedupe(extract_guidance_facts_table_normalized(doc(text, month), rules_hash=HASH).records)


CASES = [
    (
        "Previous FY 2026 Guidance Updated FY 2026 Guidance Revenue $580 - $590 $590 - $600 Adjusted EBITDA $72 - $76 $76 - $80",
        {("revenue", "FY2026", "UNSPECIFIED", 590e6, 600e6), ("ebitda", "FY2026", "ADJUSTED", 76e6, 80e6)},
    ),
    (
        "2026 Guidance (In millions, except for student starts and diluted EPS) Low High Revenue $590 - $600 Adjusted EBITDA $76 - $80 Diluted EPS $0.74 - $0.83",
        {("revenue", "FY2026", "UNSPECIFIED", 590e6, 600e6), ("eps", "FY2026", "UNSPECIFIED", .74, .83)},
    ),
    (
        "Full year 2026 guidance: Revenue of $119 million to $123 million. Adjusted EBITDA loss of $19 million to $23 million. Third Quarter 2026 Guidance: Revenue of $26 million to $30 million.",
        {("revenue", "FY2026", "UNSPECIFIED", 119e6, 123e6), ("ebitda", "FY2026", "ADJUSTED", -23e6, -19e6), ("revenue", "Q3FY2026", "UNSPECIFIED", 26e6, 30e6)},
    ),
    (
        "Full-Year 2025 Outlook GAAP Adjusted Operating profit margin 42.5% - 43.0% 50.0% - 50.5% The company expects adjusted free cash flow, excluding certain items, of $5.6 billion to $5.8 billion.",
        {("operating_margin", "FY2025", "GAAP", .425, .43), ("operating_margin", "FY2025", "ADJUSTED", .5, .505), ("fcf", "FY2025", "ADJUSTED", 5.6e9, 5.8e9)},
    ),
    (
        "Full year 2026 guidance: Adjusted free cash flow of $4.5 billion to $4.7 billion.",
        {("fcf", "FY2026", "ADJUSTED", 4.5e9, 4.7e9)},
    ),
    (
        "full year 2026 financial guidance as set forth below (dollars in millions): Current Guidance Previous Guidance Total revenues include the following ONAPGO $55 to $70 $45 to $70 Trokendi and Oxtellar $50 to $60 $40 to $50 $860 to $890 $840 to $870 Combined R&D and SG&A expenses",
        {("revenue", "FY2026", "UNSPECIFIED", 860e6, 890e6)},
    ),
    (
        "full year 2026 guidance as follows: Updated Guidance Prior Guidance Low High Low High Net revenues $11.95 billion $12.05 billion $11.78 billion $11.90 billion Reported diluted EPS $9.97 $10.17 $9.58 $9.78 Adjusted diluted EPS $11.05 $11.25 $10.63 $10.83",
        {("eps", "FY2026", "UNSPECIFIED", 9.97, 10.17), ("eps", "FY2026", "ADJUSTED", 11.05, 11.25)},
    ),
    (
        "Financial Outlook: Q3 2026: We expect revenue to be between $223 million and $225 million. We expect non-GAAP income from operations to be between $61 million and $63 million, reflecting non-GAAP operating margin of 28% at the midpoint. Full Year 2026: We expect revenue to be between $856 million and $860 million. We expect non-GAAP income from operations to be between $236 million and $244 million, reflecting non-GAAP operating margin of 28% at the midpoint.",
        {("operating_margin", "FY2026", "ADJUSTED", .28, .28), ("operating_margin", "Q3FY2026", "ADJUSTED", .28, .28), ("revenue", "FY2026", "UNSPECIFIED", 856e6, 860e6)},
    ),
    (
        "Full Year 2026 Guidance Net sales $13,800M - $14,200M Adjusted operating margin<sup>(2)</sup> 23.3% - 24.3% Adjusted free cash flow<sup>(2)</sup> $2,400M - $2,600M",
        {("operating_margin", "FY2026", "ADJUSTED", .233, .243), ("fcf", "FY2026", "ADJUSTED", 2.4e9, 2.6e9)},
    ),
    (
        "Fiscal 2026 Third Quarter Outlook: Revenue of $11.5 billion to $12.1 billion. Non-GAAP diluted net EPS of $0.88 to $0.93. Fiscal 2026 Full Year Outlook: The company expects free cash flow to be at least $3.5 billion. Fiscal 2027 Outlook Framework",
        {("eps", "Q3FY2026", "ADJUSTED", .88, .93), ("fcf", "FY2026", "UNSPECIFIED", 3.5e9, 3.5e9)},
    ),
    (
        "Full year 2026 guidance: Revenues of $2.090 billion to $2.110 billion. Adjusted EBITDA of $473 million to $483 million.",
        {("revenue", "FY2026", "UNSPECIFIED", 2.09e9, 2.11e9)},
    ),
    (
        "outlook for the three months ending September 30, 2026 (in millions) Total revenue $745 to $760 Adjusted EBITDA $180 to $200 In Q3, we expect total revenue to grow. For the full year 2026, we expect total revenue of $2.92 billion to $2.96 billion.",
        {("revenue", "Q3FY2026", "UNSPECIFIED", 745e6, 760e6), ("ebitda", "Q3FY2026", "ADJUSTED", 180e6, 200e6), ("revenue", "FY2026", "UNSPECIFIED", 2.92e9, 2.96e9)},
    ),
    (
        "2025 guidance: Revenue guidance raised to a range of $1,100 million to $1,120 million. Adj EBITDA of $147 million to $153 million.",
        {("revenue", "FY2025", "UNSPECIFIED", 1.1e9, 1.12e9), ("ebitda", "FY2025", "ADJUSTED", 147e6, 153e6)},
    ),
    (
        "Financial Outlook For the third quarter of fiscal year 2027, ending October 31, 2026, revenue is expected to be in the range of approximately $101 million to $105 million. Adjusted EBITDA loss is expected to be in the range of approximately ($6) to ($1) million for the quarter. Full year 2027 guidance: Adjusted EBITDA profit of $3 million to $10 million.",
        {("revenue", "Q3FY2027", "UNSPECIFIED", 101e6, 105e6), ("ebitda", "Q3FY2027", "ADJUSTED", -6e6, -1e6), ("ebitda", "FY2027", "ADJUSTED", 3e6, 10e6)},
    ),
    (
        "2nd Quarter of 2026: Guidance revenue of $1.07 billion to $1.08 billion. Non-GAAP net income per share of $0.57 to $0.59. Full year 2026 guidance: Non-GAAP net income per share of $2.50 to $2.54.",
        {("eps", "Q2FY2026", "ADJUSTED", .57, .59), ("eps", "FY2026", "ADJUSTED", 2.5, 2.54)},
    ),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_source_values_survive_global_dedupe(text, expected):
    records = pipeline(text)
    actual = values(records)
    for metric, period, basis, low, high in expected:
        assert any(v[:3] == (metric, period, basis) and v[3] == pytest.approx(low) and v[4] == pytest.approx(high) for v in actual), actual
    assert values(dedupe(records + records)) == actual
    for record in records:
        assert record.source_document_hash == "a" * 64
        assert record.source_timestamp == doc(text).source_timestamp


def test_unchanged_million_dollar_table_is_not_a_material_cut():
    text = "Fiscal Year 2027 Guidance 7 Key Metric FY 2026 FY 2027 Y - o- y Change Net Sales (in Millions) $3,050 $3,350 - $3,550 +10% to +16% Adj. EBITDA (in Millions) $963 $1,000 - $1,050 +4% to +9%"
    records = pipeline(text) + pipeline(text, 8)
    assert {(v[0], v[3], v[4]) for v in values(records)} == {("revenue", 3350e6, 3550e6), ("ebitda", 1000e6, 1050e6)}
    assessment = GuidanceLedger(dedupe(records)).assess("TEST", RULES, rules_hash=HASH, as_of=datetime(2026, 9, 9, tzinfo=UTC))
    assert assessment.classification.value == "NOT_DETERIORATED"


def test_annual_raise_and_narrower_loss_do_not_compare_different_quarters():
    prior = "Full year 2026 guidance: Revenue of $117 million to $121 million. Adjusted EBITDA loss of $21 million to $25 million. Second Quarter 2026 Guidance: Revenue of $27 million to $31 million."
    current = CASES[2][0]
    records = dedupe(pipeline(prior) + pipeline(current, 8))
    assessment = GuidanceLedger(records).assess("TEST", RULES, rules_hash=HASH, as_of=datetime(2026, 9, 9, tzinfo=UTC))
    # Frozen ledger policy may abstain on negative midpoint comparisons.
    # Extraction must not convert the smaller quarterly revenue into an FY cut.
    assert assessment.guidance_deterioration is not True
    assert {r.fiscal_period for r in records if r.metric.value == "revenue"} == {"FY2026", "Q2FY2026", "Q3FY2026"}


def test_reported_basis_requires_explicit_issuer_definition():
    text = CASES[6][0]
    definition = ' The term “reported” refers to measures under accounting principles generally accepted in the United States (“GAAP”).'
    assert ("eps", "FY2026", "GAAP", 9.97, 10.17) in values(pipeline(text + definition))
    assert ("eps", "FY2026", "UNSPECIFIED", 9.97, 10.17) in values(pipeline(text))


def test_qualitative_revenue_growth_and_cost_base_are_not_revenue():
    records = pipeline("For the full year 2026, we expect: Mid-teens total revenue growth. Fixed cost base of approximately $1 billion.")
    assert not any(r.metric.value == "revenue" for r in records)


def test_enrichment_persists_exact_ledger_inputs(monkeypatch):
    import app.services.shadow_enrichment_service as module
    service = object.__new__(module.ShadowStructuralEnricher)
    service.rules, service.rules_hash = RULES, HASH
    documents = [doc(CASES[2][0]), doc(CASES[2][0], 8)]
    monkeypatch.setattr(service, "_documents", lambda *args, **kwargs: (documents, []))
    monkeypatch.setattr(module, "extract_guidance_facts", extract_guidance_facts_table_normalized)
    monkeypatch.setattr(module, "_dedupe_guidance", dedupe)
    assessment, meta, errors = service.assess_guidance("TEST")
    from app.domain.soe_v1_1 import GuidanceMetricRecord
    saved = [GuidanceMetricRecord.model_validate(r) for r in json.loads(json.dumps(meta))["ledger_records"]]
    replay = GuidanceLedger(saved).assess("TEST", RULES, rules_hash=HASH)
    assert meta["records"] == len(saved) > 0
    assert replay.classification == assessment.classification
    assert replay.rule_path == assessment.rule_path
    assert {r.source_url for r in saved} == {d.source_url for d in documents}
    assert not errors
    monkeypatch.setattr(service, "_documents", lambda *args, **kwargs: ([], ["source unavailable"]))
    assessment, meta, errors = service.assess_guidance("TEST")
    assert assessment is None and meta["ledger_records"] == [] and meta["policy_evidence"] is None
    assert errors == ["source unavailable"]


def test_adjacent_compact_forecast_tables_keep_quarter_and_year_separate():
    records = pipeline("Second Quarter 2026 Guidance Net sales $3,250M - $3,450M Adjusted operating margin(2) 20.7% - 21.7% Adjusted diluted EPS(1) $1.37 - $1.43 Full Year 2026 Guidance Net sales $13,500M - $14,000M Adjusted operating margin(2) 22.8% - 23.8% Adjusted diluted EPS(1) $6.30 - $6.40 Adjusted free cash flow(2) $2,100M - $2,300M")
    assert ("eps", "Q2FY2026", "ADJUSTED", 1.37, 1.43) in values(records)
    assert ("eps", "FY2026", "ADJUSTED", 6.3, 6.4) in values(records)
    assert not any(r.metric.value == "fcf" and r.fiscal_period.startswith("Q") for r in records)


def test_standing_policy_is_preserved_in_report(monkeypatch):
    import app.services.shadow_enrichment_service as module
    service = object.__new__(module.ShadowStructuralEnricher)
    service.rules, service.rules_hash = RULES, HASH
    document = doc("We do not provide guidance regarding our expected quarterly and annual operating results.")
    monkeypatch.setattr(service, "_documents", lambda *args, **kwargs: ([document], []))
    monkeypatch.setattr(module, "extract_guidance_facts", extract_guidance_facts_table_normalized)
    monkeypatch.setattr(module, "_dedupe_guidance", dedupe)
    assessment, meta, _ = service.assess_guidance("TEST")
    assert assessment.rule_path == "guidance_v1_1.explicit_standing_no_guidance_policy"
    assert meta["ledger_records"] == []
    assert meta["policy_evidence"]["standing_no_guidance_policy"] is True
    assert meta["policy_evidence"]["source_url"] == document.source_url
    json.dumps(meta)


def test_change_amount_is_not_new_guidance_low_endpoint():
    records = pipeline("Full-Year 2026 Revenue Guidance Raised by $10 Million to $326 to $336 Million Conference Call Today")
    assert values(records) == {("revenue", "FY2026", "UNSPECIFIED", 326e6, 336e6)}


def test_compact_adjusted_table_does_not_drop_annual_reported_eps():
    records = pipeline("Full Year 2026 Guidance: We expect full year 2026 diluted EPS of $5.60 to $5.70 and adjusted diluted EPS of $6.30 to $6.40. Full Year 2026 Guidance Net sales $13,500M - $14,000M Adjusted diluted EPS(1) $6.30 - $6.40 Adjusted free cash flow(2) $2,100M - $2,300M")
    assert ("eps", "FY2026", "UNSPECIFIED", 5.6, 5.7) in values(records)
    assert ("eps", "FY2026", "ADJUSTED", 6.3, 6.4) in values(records)
