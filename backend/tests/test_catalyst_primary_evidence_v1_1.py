from datetime import UTC, date, datetime

from app.domain.soe_v1_1 import SourceDocument
from app.services.catalyst_primary_evidence_service import extract_sec_catalyst_candidates


def _doc(text: str, *, form: str = "8-K") -> SourceDocument:
    return SourceDocument(
        document_id="doc-1",
        rules_hash="rules",
        ticker="TEST",
        cik="0000000001",
        accession="0000000001-26-000001",
        form=form,
        filing_date=date(2026, 8, 1),
        source_url="https://www.sec.gov/Archives/edgar/data/1/000000000126000001/ex991.htm",
        source_timestamp=datetime(2026, 8, 1, tzinfo=UTC),
        fetched_at=datetime(2026, 8, 1, tzinfo=UTC),
        content_hash="abc",
        content=text,
    )


def test_earnings_and_formal_guidance_are_separate_primary_evidence_candidates():
    doc = _doc(
        "<html><body>Company Reports Second Quarter 2026 Financial Results. "
        "Revenue increased 12 percent. The company raises full-year 2026 guidance for revenue and EPS.</body></html>"
    )
    candidates = extract_sec_catalyst_candidates(doc)
    by_type = {candidate.input.event_type: candidate.input for candidate in candidates}
    assert "quarterly_earnings" in by_type
    assert "formal_full_year_guidance_update" in by_type
    assert by_type["quarterly_earnings"].company_wide is True
    assert by_type["quarterly_earnings"].formal_guidance_action is True
    assert any("raises full-year 2026 guidance" in span for span in by_type["quarterly_earnings"].evidence_spans)
    assert by_type["formal_full_year_guidance_update"].company_wide is True
    assert by_type["quarterly_earnings"].structured_provenance["accession"] == doc.accession


def test_common_reports_q3_results_title_is_recognized():
    doc = _doc("Adobe Reports Q3 FY2026 Results. Revenue was $6.2 billion for the quarter ended August 29, 2026.")
    candidates = extract_sec_catalyst_candidates(doc)
    assert any(item.input.event_type == "quarterly_earnings" for item in candidates)


def test_past_tense_announced_earnings_is_recognized():
    doc = _doc("UPS today announced second quarter 2026 financial results. Revenue was $22.8 billion.")
    candidates = extract_sec_catalyst_candidates(doc)
    assert any(item.input.event_type == "quarterly_earnings" for item in candidates)


def test_standalone_quarterly_results_heading_is_recognized():
    doc = _doc("Second Quarter Fiscal 2027 Financial Results. Revenue was $49.0 billion.")
    candidates = extract_sec_catalyst_candidates(doc)
    assert any(item.input.event_type == "quarterly_earnings" for item in candidates)


def test_annual_outlook_language_is_formal_guidance_evidence():
    doc = _doc("The company raises its fiscal year 2026 outlook and now expects revenue of approximately $10 billion.")
    candidates = extract_sec_catalyst_candidates(doc)
    assert any(item.input.event_type == "formal_full_year_guidance_update" for item in candidates)


def test_fy_shorthand_targets_are_formal_guidance_evidence():
    doc = _doc(
        "Adobe Reports Record Q2 Results. Adobe Raises FY26 Total Revenue and Non-GAAP EPS Targets."
    )
    candidates = extract_sec_catalyst_candidates(doc)
    by_type = {candidate.input.event_type: candidate.input for candidate in candidates}
    assert "formal_full_year_guidance_update" in by_type
    assert by_type["quarterly_earnings"].formal_guidance_action is True


def test_disclosure_reporting_guidance_format_change_is_not_guidance_action():
    doc = _doc(
        "Disclosure Updates Beginning in FY2026, we will implement reporting and guidance changes. "
        "Our reporting and guidance will focus on customer group subscription revenue."
    )
    assert extract_sec_catalyst_candidates(doc) == []


def test_provides_full_year_guidance_is_recognized():
    doc = _doc("The company provides fiscal year 2027 guidance for revenue and adjusted EPS.")
    candidates = extract_sec_catalyst_candidates(doc)
    assert any(item.input.event_type == "formal_full_year_guidance_update" for item in candidates)


def test_phase3_readout_does_not_become_company_wide_without_exposure_evidence():
    doc = _doc("Phase 3 study met its primary endpoint with a statistically significant result.")
    candidates = extract_sec_catalyst_candidates(doc, is_biotech=True)
    assert len(candidates) == 1
    inp = candidates[0].input
    assert inp.event_type == "pivotal_phase3_readout"
    assert inp.is_biotech is True
    assert inp.company_wide is None
    assert inp.dominant_single_asset is None
    assert inp.biotech_pipeline_value_fraction is None


def test_item_502_is_admin_control_only_when_no_material_event_is_found():
    doc = _doc("Item 5.02 Departure of Directors or Certain Officers. A new director was appointed.")
    candidates = extract_sec_catalyst_candidates(doc)
    assert len(candidates) == 1
    assert candidates[0].input.event_type == "administrative_or_unverifiable"


def test_admin_language_cannot_override_real_earnings_event():
    doc = _doc(
        "Item 5.02 Departure of Directors or Certain Officers. Company Reports Third Quarter Financial Results. Revenue was $2 billion."
    )
    candidates = extract_sec_catalyst_candidates(doc)
    assert [item.input.event_type for item in candidates] == ["quarterly_earnings"]


def test_hypothetical_risk_factor_does_not_create_regulatory_candidate():
    doc = _doc("If the FDA does not approve a future product candidate, our business could be harmed.", form="10-Q")
    assert extract_sec_catalyst_candidates(doc, is_biotech=True) == []


def test_explicit_fda_approval_is_regulatory_candidate_but_exposure_stays_missing():
    doc = _doc("The FDA has approved the Company's application for the new indication.")
    candidates = extract_sec_catalyst_candidates(doc, is_biotech=True)
    assert len(candidates) == 1
    assert candidates[0].input.event_type == "regulatory_decision"
    assert candidates[0].input.biotech_pipeline_value_fraction is None


def test_merger_language_is_fact_only_and_exposure_remains_missing():
    doc = _doc("The Company entered into an Agreement and Plan of Merger dated July 1, 2026.")
    candidates = extract_sec_catalyst_candidates(doc)
    assert len(candidates) == 1
    inp = candidates[0].input
    assert inp.event_type == "merger_approval_or_close"
    assert inp.company_wide is None
    assert inp.economic_exposure_fraction is None


def test_generic_indentures_permitted_refinancing_language_is_not_event():
    doc = _doc(
        "Any refinancing or replacement of any mortgages permitted by the foregoing clauses shall be of the type referred to in such clauses."
    )
    assert extract_sec_catalyst_candidates(doc) == []


def test_explicit_new_credit_facility_is_refinancing_event():
    doc = _doc("The Company entered into a new credit facility to refinance existing debt.")
    candidates = extract_sec_catalyst_candidates(doc)
    assert any(item.input.event_type == "material_refinancing_covenant_event" for item in candidates)
