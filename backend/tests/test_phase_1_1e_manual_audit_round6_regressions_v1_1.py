from datetime import UTC, datetime, timedelta

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import (
    ExtractionMethod,
    GuidanceAction,
    GuidanceMetric,
    GuidanceMetricRecord,
)
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_guidance_actual_guard_round6_v1_1 import (
    dedupe_guidance_records_round6,
    tighten_guidance_record_round6,
)

NOW = datetime(2026, 9, 5, tzinfo=UTC)
RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
RULES_HASH = rules_hash(RULES)


def _record(
    ticker: str,
    metric: GuidanceMetric,
    value: float,
    *,
    when: datetime,
    evidence: str,
    period: str = "FY2026",
    action: GuidanceAction = GuidanceAction.NONE,
    basis: str = "UNSPECIFIED",
) -> GuidanceMetricRecord:
    unit = "USD/share" if metric is GuidanceMetric.EPS else "USD"
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
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-ex99.htm",
        source_accession="0000000001-26-000001",
        source_timestamp=when,
        explicit_action=action,
        verified=True,
        extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
        evidence_span=evidence,
        source_document_hash="c" * 64,
        as_of=when,
        fetched_at=when,
    )


def _assess(ticker: str, records: list[GuidanceMetricRecord]):
    ledger = GuidanceLedger(dedupe_guidance_records_round6(records))
    return ledger.assess(ticker, RULES, rules_hash=RULES_HASH, as_of=NOW)


def test_vg_q1_reported_revenue_cannot_borrow_ebitda_guidance_context():
    row = _record(
        "VG",
        GuidanceMetric.REVENUE,
        4_600_000_000,
        when=NOW - timedelta(days=90),
        evidence=(
            "Venture Global Reports First Quarter 2026 Results. Summary Financial Highlights. "
            "Revenue $4.6 billion. Generated revenue of $4.6 billion. "
            "Increased Consolidated Adjusted EBITDA guidance to $8.2 - $8.5 billion, "
            "up from $5.2 - $5.8 billion."
        ),
        action=GuidanceAction.RAISE,
    )
    assert tighten_guidance_record_round6(row) is None


def test_vg_q2_reported_revenue_cannot_borrow_raised_ebitda_guidance_context():
    row = _record(
        "VG",
        GuidanceMetric.REVENUE,
        4_578_000_000,
        when=NOW,
        evidence=(
            "Venture Global Reports Second Quarter 2026 Results. Summary Financial Highlights. "
            "Revenue $4.6 billion. Generated strong second quarter 2026 financial results: "
            "Revenue of $4.6 billion. Increased Consolidated Adjusted EBITDA guidance to "
            "$8.7 - $9.1 billion, up from $8.2 - $8.5 billion."
        ),
        action=GuidanceAction.RAISE,
    )
    assert tighten_guidance_record_round6(row) is None


def test_vg_verified_ebitda_raise_is_not_guidance_deterioration():
    prior_revenue_actual = _record(
        "VG",
        GuidanceMetric.REVENUE,
        4_600_000_000,
        when=NOW - timedelta(days=90),
        evidence=(
            "First Quarter 2026 Results. Revenue $4.6 billion. "
            "Increased Consolidated Adjusted EBITDA guidance to $8.2 - $8.5 billion."
        ),
        action=GuidanceAction.RAISE,
    )
    current_revenue_actual = _record(
        "VG",
        GuidanceMetric.REVENUE,
        4_578_000_000,
        when=NOW,
        evidence=(
            "Second Quarter 2026 Results. Revenue $4.6 billion. "
            "Increased Consolidated Adjusted EBITDA guidance to $8.7 - $9.1 billion."
        ),
        action=GuidanceAction.RAISE,
    )
    prior_ebitda = _record(
        "VG",
        GuidanceMetric.EBITDA,
        8_350_000_000,
        when=NOW - timedelta(days=90),
        evidence=(
            "2026 Outlook. Consolidated Adjusted EBITDA guidance for the full year 2026 "
            "is $8.2 billion - $8.5 billion."
        ),
        basis="ADJUSTED",
    )
    current_ebitda = _record(
        "VG",
        GuidanceMetric.EBITDA,
        8_900_000_000,
        when=NOW,
        evidence=(
            "2026 Outlook. Increased Consolidated Adjusted EBITDA guidance for the full year 2026 "
            "to $8.7 billion - $9.1 billion, up from $8.2 billion - $8.5 billion."
        ),
        action=GuidanceAction.RAISE,
        basis="ADJUSTED",
    )

    assessment = _assess(
        "VG",
        [prior_revenue_actual, current_revenue_actual, prior_ebitda, current_ebitda],
    )
    assert assessment.guidance_deterioration is False


def test_compact_period_bound_revenue_guidance_still_survives():
    row = _record(
        "POS",
        GuidanceMetric.REVENUE,
        897_000_000,
        when=NOW,
        period="FY2027",
        evidence="FY2027 Guidance Revenue $895 million - $899 million.",
    )
    tightened = tighten_guidance_record_round6(row)
    assert tightened is not None
    assert tightened.fiscal_period == "FY2027"
    assert tightened.midpoint == 897_000_000
