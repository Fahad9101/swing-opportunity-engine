from datetime import UTC, datetime, timedelta

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.distress_v1_1 import DistressHardFlag
from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceMetric, GuidanceMetricRecord, SourceDocument
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_evidence_hygiene_round3_patch_v1_1 import (
    dedupe_guidance_records_round3_patched as dedupe_guidance_records_round3,
    extract_hard_distress_flags_round3,
    extract_sec_catalyst_candidates_round3,
    tighten_guidance_record_round3_patched as tighten_guidance_record_round3,
)

NOW = datetime(2026, 9, 4, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def _doc(ticker: str, text: str, *, filename: str = "ex99-1.htm", form: str = "8-K") -> SourceDocument:
    return SourceDocument(
        document_id=f"{ticker}-doc",
        rules_hash=RULES_HASH,
        ticker=ticker,
        cik="0000000001",
        accession="0000000001-26-000001",
        form=form,
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/000000000126000001/{filename}",
        source_timestamp=NOW,
        fetched_at=NOW,
        content_hash="a" * 64,
        content=text,
    )


def _record(
    ticker: str,
    metric: GuidanceMetric,
    value: float,
    *,
    when: datetime,
    evidence: str,
    period: str = "FY2026",
    action: GuidanceAction = GuidanceAction.INITIATE,
    basis: str = "UNSPECIFIED",
) -> GuidanceMetricRecord:
    if metric is GuidanceMetric.EPS:
        unit = "USD/share"
    elif metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        unit = "fraction"
    else:
        unit = "USD"
    return GuidanceMetricRecord(
        rules_hash=RULES_HASH,
        ticker=ticker,
        fiscal_period=period,
        metric=metric,
        accounting_basis=basis,
        low=value,
        high=value,
        unit=unit,
        source="SEC EDGAR",
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/ex99-{ticker.lower()}.htm",
        source_accession="0000000001-26-000001",
        source_timestamp=when,
        explicit_action=action,
        verified=True,
        extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
        evidence_span=evidence,
        source_document_hash="b" * 64,
        as_of=when,
        fetched_at=when,
    )


def _assess(ticker: str, records: list[GuidanceMetricRecord]):
    ledger = GuidanceLedger(dedupe_guidance_records_round3(records))
    return ledger.assess(ticker, RULES, rules_hash=RULES_HASH, as_of=NOW)


def test_voyg_reported_actual_is_not_forward_guidance():
    row = _record("VOYG", GuidanceMetric.REVENUE, 900_000_000, when=NOW, evidence="FY2025 Results. Revenue was $900 million for the year.")
    assert tighten_guidance_record_round3(row) is None


def test_cdns_raised_same_period_eps_rebinds_to_current_value():
    prior = _record("CDNS", GuidanceMetric.EPS, 7.90, when=NOW - timedelta(days=90), evidence="FY2026 guidance. The company expects adjusted EPS of $7.90.", basis="ADJUSTED")
    current = _record("CDNS", GuidanceMetric.EPS, 7.00, when=NOW, evidence="Raises FY2026 guidance. The company now expects adjusted EPS of $8.10.", action=GuidanceAction.RAISE, basis="ADJUSTED")
    assert _assess("CDNS", [prior, current]).guidance_deterioration is False


def test_ttmi_q2_and_q3_guidance_are_not_same_period():
    prior = _record("TTMI", GuidanceMetric.REVENUE, 700_000_000, when=NOW - timedelta(days=90), evidence="Q2 FY2026 guidance. The company expects revenue of $700 million.")
    current = _record("TTMI", GuidanceMetric.REVENUE, 710_000_000, when=NOW, evidence="Q3 FY2026 guidance. The company expects revenue of $710 million.")
    assert _assess("TTMI", [prior, current]).guidance_deterioration is None


def test_kmt_fy2026_and_fy2027_are_not_comparable():
    prior = _record("KMT", GuidanceMetric.REVENUE, 2_000_000_000, when=NOW - timedelta(days=90), evidence="FY2026 guidance. The company expects revenue of $2.0 billion.")
    current = _record("KMT", GuidanceMetric.REVENUE, 2_100_000_000, when=NOW, evidence="FY2027 guidance. The company expects revenue of $2.1 billion.")
    assert _assess("KMT", [prior, current]).guidance_deterioration is None


def test_duol_higher_fy2026_revenue_is_not_a_cut():
    prior = _record("DUOL", GuidanceMetric.REVENUE, 1_205_000_000, when=NOW - timedelta(days=90), evidence="FY2026 guidance. The company expects revenue of $1.205 billion.")
    current = _record("DUOL", GuidanceMetric.REVENUE, 1_000_000_000, when=NOW, evidence="Raises FY2026 guidance. The company now expects revenue of $1.207 billion.", action=GuidanceAction.RAISE)
    assert _assess("DUOL", [prior, current]).guidance_deterioration is False


def test_ktb_long_term_target_is_not_annual_guidance():
    row = _record("KTB", GuidanceMetric.EBITDA, 800_000_000, when=NOW, evidence="Long-term target for 2030: adjusted EBITDA of $800 million.", period="FY2026")
    assert tighten_guidance_record_round3(row) is None


def test_myrg_historical_results_are_not_numeric_guidance():
    row = _record("MYRG", GuidanceMetric.REVENUE, 3_600_000_000, when=NOW, evidence="Full year 2025 results. Revenue was $3.6 billion and increased year over year.")
    assert tighten_guidance_record_round3(row) is None


def test_tvtx_historical_product_sales_are_not_forward_revenue_guidance():
    row = _record("TVTX", GuidanceMetric.REVENUE, 500_000_000, when=NOW, evidence="FY2025 results. Product sales were $500 million for the year.")
    assert tighten_guidance_record_round3(row) is None


def test_dash_q1_and_q2_outlooks_are_not_comparable():
    prior = _record("DASH", GuidanceMetric.EBITDA, 600_000_000, when=NOW - timedelta(days=90), evidence="Q1 FY2026 outlook. The company expects adjusted EBITDA of $600 million.", basis="ADJUSTED")
    current = _record("DASH", GuidanceMetric.EBITDA, 650_000_000, when=NOW, evidence="Q2 FY2026 outlook. The company expects adjusted EBITDA of $650 million.", basis="ADJUSTED")
    assert _assess("DASH", [prior, current]).guidance_deterioration is None


def test_dy_hypothetical_customer_contract_default_is_not_registrant_covenant_breach():
    doc = _doc("DY", "Many of our contracts may be cancelled by our customers regardless of whether or not we are in default. We were in compliance with all financial covenants under our credit facility at quarter end.", form="10-Q", filename="dy-20260801.htm")
    flags = extract_hard_distress_flags_round3(doc)
    assert not any(item["flag"] == DistressHardFlag.UNRESOLVED_COVENANT_BREACH.value for item in flags)


def test_mir_reaffirmed_same_period_revenue_rebinds_to_current_value():
    prior = _record("MIR", GuidanceMetric.REVENUE, 3_000_000_000, when=NOW - timedelta(days=90), evidence="FY2026 guidance. The company expects revenue of $3.0 billion.")
    current = _record("MIR", GuidanceMetric.REVENUE, 2_500_000_000, when=NOW, evidence="Reaffirms FY2026 guidance. The company expects revenue of $3.0 billion.", action=GuidanceAction.REAFFIRM)
    assert _assess("MIR", [prior, current]).guidance_deterioration is False


def test_mwh_raised_same_period_revenue_rebinds_to_higher_value():
    prior = _record("MWH", GuidanceMetric.REVENUE, 3_770_000_000, when=NOW - timedelta(days=90), evidence="FY2026 guidance. The company expects revenue of $3.77 billion.")
    current = _record("MWH", GuidanceMetric.REVENUE, 3_000_000_000, when=NOW, evidence="Raises FY2026 guidance. The company now expects revenue of $3.92 billion.", action=GuidanceAction.RAISE)
    assert _assess("MWH", [prior, current]).guidance_deterioration is False


def test_cvna_historical_actual_plus_qualitative_outlook_cannot_be_numeric_prior():
    prior = _record("CVNA", GuidanceMetric.EBITDA, 2_237_000_000, when=NOW - timedelta(days=90), evidence="FY2025 results. Adjusted EBITDA was $2.237 billion. In full year 2026 we expect significant growth in adjusted EBITDA.", period="FY2026", basis="ADJUSTED")
    current = _record("CVNA", GuidanceMetric.EBITDA, 2_850_000_000, when=NOW, evidence="FY2026 outlook. The company expects adjusted EBITDA of $2.7 billion to $3.0 billion.", basis="ADJUSTED")
    assert tighten_guidance_record_round3(prior) is None
    assert _assess("CVNA", [prior, current]).guidance_deterioration is None


def test_roku_fy2025_and_fy2026_guidance_are_not_comparable():
    prior = _record("ROKU", GuidanceMetric.REVENUE, 4_610_000_000, when=NOW - timedelta(days=90), evidence="Full year 2025 guidance. The company expects revenue of $4.61 billion.", period="FY2026")
    current = _record("ROKU", GuidanceMetric.REVENUE, 5_500_000_000, when=NOW, evidence="Full year 2026 guidance. The company expects revenue of $5.5 billion.")
    assert _assess("ROKU", [prior, current]).guidance_deterioration is None


def test_zg_q2_and_q3_outlooks_are_not_comparable():
    prior = _record("ZG", GuidanceMetric.REVENUE, 700_000_000, when=NOW - timedelta(days=90), evidence="Q2 FY2026 outlook. The company expects revenue of $700 million.")
    current = _record("ZG", GuidanceMetric.REVENUE, 690_000_000, when=NOW, evidence="Q3 FY2026 outlook. The company expects revenue of $690 million.")
    assert _assess("ZG", [prior, current]).guidance_deterioration is None


def test_auph_fy2025_and_initial_fy2026_guidance_are_not_comparable():
    prior = _record("AUPH", GuidanceMetric.REVENUE, 250_000_000, when=NOW - timedelta(days=90), evidence="FY2025 guidance. The company expects revenue of $250 million.", period="FY2026")
    current = _record("AUPH", GuidanceMetric.REVENUE, 300_000_000, when=NOW, evidence="Initial FY2026 guidance. The company expects revenue of $300 million.")
    assert _assess("AUPH", [prior, current]).guidance_deterioration is None


def test_brze_future_results_scheduling_notice_is_not_completed_earnings_evidence():
    doc = _doc("BRZE", "Braze Announces Date of Second Quarter Fiscal 2027 Financial Results. Braze will release its second quarter fiscal 2027 financial results on September 8, 2026 after market close.", filename="dp245711_ex9901.htm")
    candidates = extract_sec_catalyst_candidates_round3(doc)
    assert not any(candidate.input.event_type == "quarterly_earnings" for candidate in candidates)


def test_dell_raised_fy2027_eps_rebinds_to_current_value():
    prior = _record("DELL", GuidanceMetric.EPS, 17.90, when=NOW - timedelta(days=90), evidence="FY2027 guidance. The company expects adjusted EPS of $17.90.", basis="ADJUSTED")
    current = _record("DELL", GuidanceMetric.EPS, 15.00, when=NOW, evidence="Raises FY2027 guidance. The company now expects adjusted EPS of $25.50.", action=GuidanceAction.RAISE, basis="ADJUSTED")
    assert _assess("DELL", [prior, current]).guidance_deterioration is False


def test_alab_q2_and_q3_gross_margin_guidance_are_not_comparable():
    prior = _record("ALAB", GuidanceMetric.GROSS_MARGIN, 0.73, when=NOW - timedelta(days=90), evidence="Q2 FY2026 guidance. The company expects gross margin of 73%.")
    current = _record("ALAB", GuidanceMetric.GROSS_MARGIN, 0.72, when=NOW, evidence="Q3 FY2026 guidance. The company expects gross margin of 72%.")
    assert _assess("ALAB", [prior, current]).guidance_deterioration is None
