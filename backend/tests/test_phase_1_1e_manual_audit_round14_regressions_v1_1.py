from datetime import UTC, datetime

import pytest

from app.core.config import SOE_1_1_RULES_PATH, load_rules_for_version, rules_hash
from app.domain.soe_v1_1 import SourceDocument
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.phase_1_1e_guidance_table_normalizer_v1_1 import (
    extract_guidance_facts_table_normalized,
    normalize_eps_reconciliation_guidance_rows,
)

RULES = load_rules_for_version(SOE_1_1_RULES_PATH, "SOE-1.1.0")
HASH = rules_hash(RULES)
HEADER = "Reconciliation of GAAP vs Adjusted EPS Guidance - Full Year 2026 2026 Full-Year Guidance Low High "


def document(text, month=5):
    when = datetime(2026, month, 6, tzinfo=UTC)
    return SourceDocument(
        document_id=f"ITT-{month}", rules_hash=HASH, ticker="ITT", cik="216228",
        accession=f"216228-26-{month:06}", form="8-K",
        source_url=f"https://www.sec.gov/Archives/itt-{month}.htm",
        source_timestamp=when, fetched_at=when, content_hash="a" * 64, content=text,
    )


def table(gaap="4.15 $ 4.45", adjusted="7.70 $ 8.00"):
    return HEADER + f"EPS from Continuing Operations - GAAP $ {gaap} " \
        "Intangible amortization 2.91 2.91 Acquisition-related costs 1.29 1.29 " \
        f"EPS from Continuing Operations - Adjusted $ {adjusted} Note: other disclosures"


def test_itt_preserves_both_endpoints_and_basis():
    records = extract_guidance_facts_table_normalized(document(table()), rules_hash=HASH).records
    assert {(r.accounting_basis, r.low, r.high) for r in records} == {
        ("GAAP", 4.15, 4.45), ("ADJUSTED", 7.70, 8.00),
    }


@pytest.mark.parametrize("adjusted, expected", [
    ("8.12 $ 8.32", "NOT_DETERIORATED"),
    ("6.00 $ 6.20", "DETERIORATED"),
])
def test_adjusted_cut_is_detected_even_when_gaap_increases(adjusted, expected):
    prior = extract_guidance_facts_table_normalized(document(table()), rules_hash=HASH)
    current = extract_guidance_facts_table_normalized(
        document(table("4.47 $ 4.67", adjusted), 8), rules_hash=HASH,
    )
    assessment = GuidanceLedger([*prior.records, *current.records]).assess(
        "ITT", RULES, rules_hash=HASH, as_of=datetime(2026, 9, 7, tzinfo=UTC),
    )
    assert assessment.classification.value == expected


@pytest.mark.parametrize("text", [
    table().replace("Guidance", "Results"),
    table().replace("Low High", "High Low"),
    table().replace("4.15 $ 4.45", "4.45 $ 4.15").replace("7.70 $ 8.00", "8.00 $ 7.70"),
])
def test_ambiguous_or_reported_rows_are_not_normalized(text):
    assert normalize_eps_reconciliation_guidance_rows(document(text), rules_hash=HASH) == []
