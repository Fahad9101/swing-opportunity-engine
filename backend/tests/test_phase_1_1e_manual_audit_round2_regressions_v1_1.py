from datetime import UTC, datetime, timedelta

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceMetric,
    GuidanceMetricRecord,
    SourceDocument,
)
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_evidence_hygiene_v1_1 import (
    dedupe_guidance_records_hygienic,
    earnings_document_admissible,
    extract_guidance_facts_hygienic,
    extract_sec_catalyst_candidates_hygienic,
)


NOW = datetime(2026, 9, 4, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def _document(
    ticker: str,
    content: str,
    *,
    when: datetime = NOW,
    suffix: str = "001",
    form: str = "8-K",
    filename: str | None = None,
) -> SourceDocument:
    filename = filename or f"ex99-{ticker.lower()}-{suffix}.htm"
    return SourceDocument(
        document_id=f"{ticker}-{suffix}",
        rules_hash=RULES_HASH,
        ticker=ticker,
        cik="0000000001",
        accession=f"0000000001-26-00{suffix}",
        form=form,
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/00000000012600{suffix}/{filename}",
        source_timestamp=when,
        fetched_at=when,
        content_hash=(ticker.lower() + suffix + "0" * 64)[:64],
        content=content,
    )


def _record(
    ticker: str,
    metric: GuidanceMetric,
    midpoint: float,
    *,
    when: datetime,
    action: GuidanceAction,
    fiscal_period: str = "FY2026",
    basis: str = "UNSPECIFIED",
    source_url: str | None = None,
    evidence: str | None = None,
) -> GuidanceMetricRecord:
    return GuidanceMetricRecord(
        rules_hash=RULES_HASH,
        ticker=ticker,
        fiscal_period=fiscal_period,
        metric=metric,
        accounting_basis=basis,
        low=midpoint,
        high=midpoint,
        unit="USD/share" if metric is GuidanceMetric.EPS else "USD",
        source="SEC EDGAR",
        source_url=source_url or f"https://www.sec.gov/Archives/edgar/data/1/ex99-{ticker.lower()}.htm",
        source_accession="0000000001-26-000001",
        source_timestamp=when,
        explicit_action=action,
        verified=True,
        extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
        evidence_span=evidence or f"Raises full year 2026 guidance. The company expects {metric.value} of ${midpoint}.",
        source_document_hash="a" * 64,
        as_of=when,
        fetched_at=when,
    )


def _assess(ticker: str, records: list[GuidanceMetricRecord]):
    ledger = GuidanceLedger(dedupe_guidance_records_hygienic(records))
    return ledger.assess(ticker, RULES, rules_hash=RULES_HASH, as_of=NOW)


def test_cls_raise_resolution_uses_current_higher_revenue_and_eps_not_old_values():
    prior_time = NOW - timedelta(days=90)
    current = NOW
    records = [
        _record("CLS", GuidanceMetric.REVENUE, 19_000_000_000, when=prior_time, action=GuidanceAction.INITIATE),
        _record("CLS", GuidanceMetric.EPS, 10.15, when=prior_time, action=GuidanceAction.INITIATE, basis="ADJUSTED"),
        _record("CLS", GuidanceMetric.REVENUE, 19_000_000_000, when=current, action=GuidanceAction.RAISE),
        _record("CLS", GuidanceMetric.REVENUE, 20_500_000_000, when=current, action=GuidanceAction.RAISE),
        _record("CLS", GuidanceMetric.EPS, 10.15, when=current, action=GuidanceAction.RAISE, basis="ADJUSTED"),
        _record("CLS", GuidanceMetric.EPS, 11.30, when=current, action=GuidanceAction.RAISE, basis="ADJUSTED"),
    ]
    assessment = _assess("CLS", records)
    assert assessment.guidance_deterioration is False


def test_ttmi_quarter_evidence_cannot_be_admitted_as_full_year_comparable_guidance():
    bad = _record(
        "TTMI",
        GuidanceMetric.REVENUE,
        700_000_000,
        when=NOW - timedelta(days=90),
        action=GuidanceAction.INITIATE,
        fiscal_period="FY2026",
        evidence="Third Quarter FY2026 Guidance. The company expects revenue of $700 million.",
    )
    assert dedupe_guidance_records_hygienic([bad]) == []


def test_pr_reconciliation_disclaimer_is_not_company_wide_no_guidance_policy():
    result = extract_guidance_facts_hygienic(
        _document(
            "PR",
            "Updated Full Year 2026 Guidance. The company expects revenue of $4.1 billion to $4.3 billion. "
            "The company does not provide financial guidance for certain non-GAAP reconciliation items because "
            "a reconciliation is not possible without unreasonable effort.",
        ),
        rules_hash=RULES_HASH,
    )
    assert result.policy_evidence is None
    assert any(record.metric is GuidanceMetric.REVENUE for record in result.records)


def test_hpe_historical_actual_near_generic_guidance_heading_is_rejected():
    result = extract_guidance_facts_hygienic(
        _document(
            "HPE",
            "Financial guidance and outlook discussion. For the quarter ended July 31, 2026, revenue was $9.2 billion "
            "and adjusted EPS was $0.44. These reported results reflect acquisition accounting guidance under GAAP.",
            form="10-Q",
            filename="hpe-20260731.htm",
        ),
        rules_hash=RULES_HASH,
    )
    assert result.records == []


def test_cpay_explicit_raise_prefers_higher_current_revenue_range():
    prior_time = NOW - timedelta(days=90)
    current = NOW
    records = [
        _record("CPAY", GuidanceMetric.REVENUE, 5_290_000_000, when=prior_time, action=GuidanceAction.INITIATE),
        _record("CPAY", GuidanceMetric.REVENUE, 5_290_000_000, when=current, action=GuidanceAction.RAISE),
        _record("CPAY", GuidanceMetric.REVENUE, 5_310_000_000, when=current, action=GuidanceAction.RAISE),
    ]
    assessment = _assess("CPAY", records)
    assert assessment.guidance_deterioration is False


def test_mwh_raise_resolution_does_not_turn_higher_revenue_and_ebitda_into_cut():
    prior_time = NOW - timedelta(days=90)
    records = [
        _record("MWH", GuidanceMetric.REVENUE, 3_770_000_000, when=prior_time, action=GuidanceAction.INITIATE),
        _record("MWH", GuidanceMetric.EBITDA, 445_000_000, when=prior_time, action=GuidanceAction.INITIATE, basis="ADJUSTED"),
        _record("MWH", GuidanceMetric.REVENUE, 3_770_000_000, when=NOW, action=GuidanceAction.RAISE),
        _record("MWH", GuidanceMetric.REVENUE, 3_920_000_000, when=NOW, action=GuidanceAction.RAISE),
        _record("MWH", GuidanceMetric.EBITDA, 445_000_000, when=NOW, action=GuidanceAction.RAISE, basis="ADJUSTED"),
        _record("MWH", GuidanceMetric.EBITDA, 495_000_000, when=NOW, action=GuidanceAction.RAISE, basis="ADJUSTED"),
    ]
    assert _assess("MWH", records).guidance_deterioration is False


def test_vg_raise_resolution_prefers_higher_current_ebitda():
    records = [
        _record("VG", GuidanceMetric.EBITDA, 8_350_000_000, when=NOW - timedelta(days=90), action=GuidanceAction.INITIATE, basis="ADJUSTED"),
        _record("VG", GuidanceMetric.EBITDA, 8_350_000_000, when=NOW, action=GuidanceAction.RAISE, basis="ADJUSTED"),
        _record("VG", GuidanceMetric.EBITDA, 8_900_000_000, when=NOW, action=GuidanceAction.RAISE, basis="ADJUSTED"),
    ]
    assert _assess("VG", records).guidance_deterioration is False


def test_smci_10k_actual_revenue_is_not_new_forward_guidance():
    result = extract_guidance_facts_hygienic(
        _document(
            "SMCI",
            "Fiscal 2026 Results and Outlook. For the year ended June 30, 2026, net sales were $39.063 billion. "
            "The company reported record annual revenue and discussed future strategy.",
            form="10-K",
            filename="smci-20260630.htm",
        ),
        rules_hash=RULES_HASH,
    )
    assert not any(record.metric is GuidanceMetric.REVENUE for record in result.records)


def test_duol_raise_resolution_prefers_higher_current_adjusted_ebitda():
    records = [
        _record("DUOL", GuidanceMetric.EBITDA, 310_000_000, when=NOW - timedelta(days=90), action=GuidanceAction.INITIATE, basis="ADJUSTED"),
        _record("DUOL", GuidanceMetric.EBITDA, 310_000_000, when=NOW, action=GuidanceAction.RAISE, basis="ADJUSTED"),
        _record("DUOL", GuidanceMetric.EBITDA, 320_000_000, when=NOW, action=GuidanceAction.RAISE, basis="ADJUSTED"),
    ]
    assert _assess("DUOL", records).guidance_deterioration is False


def test_iesc_historical_revenue_results_plus_qualitative_outlook_do_not_create_numeric_guidance():
    result = extract_guidance_facts_hygienic(
        _document(
            "IESC",
            "First Quarter Fiscal 2026 Results. Revenue was $812 million for the quarter and increased year over year. "
            "Management remains optimistic about the outlook and expects continued strong demand.",
        ),
        rules_hash=RULES_HASH,
    )
    assert not any(record.metric is GuidanceMetric.REVENUE and record.midpoint is not None for record in result.records)


def test_ilmn_credit_agreement_exhibit_cannot_supply_primary_earnings_evidence():
    document = _document(
        "ILMN",
        "CREDIT AGREEMENT dated as of August 13, 2026. The Borrower represents that for the quarter ended June 30, "
        "2026 consolidated revenue was $1.1 billion and income was positive. Financial results are referenced solely "
        "for covenant calculations under this Credit Agreement.",
        filename="ex10-1.htm",
    )
    assert earnings_document_admissible(document) is False
    candidates = extract_sec_catalyst_candidates_hygienic(document)
    assert not any(candidate.input.event_type == "quarterly_earnings" for candidate in candidates)
