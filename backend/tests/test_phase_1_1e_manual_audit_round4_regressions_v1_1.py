from datetime import UTC, datetime, timedelta

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceMetric, GuidanceMetricRecord
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_evidence_hygiene_round4_v1_1 import (
    dedupe_guidance_records_round4,
    tighten_guidance_record_round4,
)

NOW = datetime(2026, 9, 4, tzinfo=UTC)
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
    action: GuidanceAction = GuidanceAction.INITIATE,
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
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/ex99-{ticker.lower()}.htm",
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
    ledger = GuidanceLedger(dedupe_guidance_records_round4(records))
    return ledger.assess(ticker, RULES, rules_hash=RULES_HASH, as_of=NOW)


def test_atro_metric_bound_year_overrides_nearby_historical_results_year():
    prior = _record(
        "ATRO",
        GuidanceMetric.REVENUE,
        850_000_000,
        when=NOW - timedelta(days=180),
        period="FY2026",  # deliberately wrong incoming binding
        action=GuidanceAction.RAISE,
        evidence=(
            "Second Quarter 2025 Results. 2025 Outlook. Astronics is raising the lower end of its "
            "2025 revenue guidance to approximately $840 million to $860 million, up from previous guidance."
        ),
    )
    current = _record(
        "ATRO",
        GuidanceMetric.REVENUE,
        970_000_000,
        when=NOW,
        period="FY2025",  # deliberately wrong incoming binding from nearby results header
        action=GuidanceAction.REAFFIRM,
        evidence=(
            "Preliminary Fiscal 2025 Full Year Financial Results. Maintains initial 2026 revenue guidance "
            "of $950 million to $990 million, an increase of 10% to 15% over 2025."
        ),
    )

    prior_fixed = tighten_guidance_record_round4(prior)
    current_fixed = tighten_guidance_record_round4(current)
    assert prior_fixed is not None and prior_fixed.fiscal_period == "FY2025"
    assert current_fixed is not None and current_fixed.fiscal_period == "FY2026"
    assert _assess("ATRO", [prior, current]).guidance_deterioration is None


def test_vg_reported_revenue_cannot_borrow_distant_ebitda_guidance_context():
    false_revenue = _record(
        "VG",
        GuidanceMetric.REVENUE,
        4_578_000_000,
        when=NOW,
        action=GuidanceAction.NONE,
        evidence=(
            "2026 Outlook Updated guidance for 2026. Consolidated Adjusted EBITDA guidance is $8.7-$9.1 billion. "
            "Summary and Review of Financial Results Revenue $4.578 billion for the three months ended June 30, 2026."
        ),
    )
    assert tighten_guidance_record_round4(false_revenue) is None


def test_vg_explicit_same_period_ebitda_raise_remains_not_deteriorated():
    prior = _record(
        "VG",
        GuidanceMetric.EBITDA,
        8_350_000_000,
        when=NOW - timedelta(days=90),
        action=GuidanceAction.RAISE,
        basis="ADJUSTED",
        evidence=(
            "2026 Outlook. Increased Consolidated Adjusted EBITDA guidance to $8.2 billion - $8.5 billion, "
            "up from $5.2 billion - $5.8 billion."
        ),
    )
    current = _record(
        "VG",
        GuidanceMetric.EBITDA,
        8_900_000_000,
        when=NOW,
        action=GuidanceAction.RAISE,
        basis="ADJUSTED",
        evidence=(
            "2026 Outlook. Increased Consolidated Adjusted EBITDA guidance to $8.7 billion - $9.1 billion, "
            "up from $8.2 billion - $8.5 billion."
        ),
    )
    assessment = _assess("VG", [prior, current])
    assert assessment.guidance_deterioration is False


def test_explicit_raise_with_lower_same_period_binding_fails_closed():
    prior = _record(
        "GENERIC",
        GuidanceMetric.REVENUE,
        1_000_000_000,
        when=NOW - timedelta(days=90),
        evidence="FY2026 guidance. The company expects revenue of $1.0 billion.",
    )
    impossible = _record(
        "GENERIC",
        GuidanceMetric.REVENUE,
        900_000_000,
        when=NOW,
        action=GuidanceAction.RAISE,
        evidence="FY2026 guidance. The company raised revenue guidance to $900 million.",
    )
    selected = dedupe_guidance_records_round4([prior, impossible])
    assert all(not (row.source_timestamp == NOW and row.midpoint == 900_000_000) for row in selected)
    assert _assess("GENERIC", [prior, impossible]).guidance_deterioration is None
