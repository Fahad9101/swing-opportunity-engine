from datetime import UTC, datetime

import pytest

from app.domain.distress_v1_1 import DistressHardFlag, DistressRawFacts, DistressSectorAdapter
from app.domain.soe_v1_1 import SourceDocument
from app.services.distress_fact_extraction_service import extract_hard_distress_flags, merge_hard_distress_evidence


NOW = datetime(2026, 9, 2, tzinfo=UTC)


def doc(text: str) -> SourceDocument:
    return SourceDocument(
        document_id="doc",
        rules_hash="1" * 64,
        ticker="TEST",
        cik="0000000001",
        accession="0000000001-26-000001",
        form="10-Q",
        source_url="https://www.sec.gov/Archives/edgar/data/1/000000000126000001/test.htm",
        source_timestamp=NOW,
        fetched_at=NOW,
        content_hash="a" * 64,
        content=text,
    )


def flags(text: str) -> set[DistressHardFlag]:
    return {DistressHardFlag(item["flag"]) for item in extract_hard_distress_flags(doc(text))}


def test_extracts_explicit_going_concern_substantial_doubt():
    found = flags("There is substantial doubt about our ability to continue as a going concern for the next year.")
    assert DistressHardFlag.GOING_CONCERN in found


def test_negated_going_concern_is_not_flagged():
    found = flags("Management concluded there is no substantial doubt about our ability to continue as a going concern.")
    assert DistressHardFlag.GOING_CONCERN not in found


@pytest.mark.parametrize(
    "text",
    [
        "The Company filed a voluntary petition for relief under Chapter 11 of the Bankruptcy Code.",
        "The debtors commenced voluntary cases under chapter 11 of the Bankruptcy Code.",
        "The Company filed for bankruptcy on August 1, 2026.",
    ],
)
def test_extracts_explicit_bankruptcy_filing(text):
    assert DistressHardFlag.BANKRUPTCY_OR_RESTRUCTURING in flags(text)


def test_generic_restructuring_risk_does_not_equal_bankruptcy_filing():
    assert DistressHardFlag.BANKRUPTCY_OR_RESTRUCTURING not in flags("We may consider restructuring alternatives if market conditions worsen.")


def test_extracts_current_payment_default():
    assert DistressHardFlag.PAYMENT_DEFAULT in flags("The Company remains in payment default under its senior secured notes for unpaid interest.")


def test_cured_payment_default_is_not_current_hard_flag():
    assert DistressHardFlag.PAYMENT_DEFAULT not in flags("The Company remains in payment default under its senior notes; the default was cured and paid in full before filing.")


def test_extracts_explicit_unwaived_covenant_breach():
    assert DistressHardFlag.UNRESOLVED_COVENANT_BREACH in flags("The Company has an unwaived covenant breach under the revolving credit agreement.")


def test_generic_covenant_risk_or_waived_breach_is_not_hard_flag():
    assert DistressHardFlag.UNRESOLVED_COVENANT_BREACH not in flags("Future results could cause a covenant breach.")
    assert DistressHardFlag.UNRESOLVED_COVENANT_BREACH not in flags("A covenant breach occurred and the lenders granted a waiver.")


def test_extracts_solvency_related_nonreliance_only_when_linked():
    text = "The financial statements should no longer be relied upon due to unresolved liquidity and ability-to-meet-obligations issues."
    assert DistressHardFlag.UNRESOLVED_SOLVENCY_RELIABILITY_ISSUE in flags(text)
    assert DistressHardFlag.UNRESOLVED_SOLVENCY_RELIABILITY_ISSUE not in flags("The financial statements should no longer be relied upon because of a revenue-recognition error.")


def test_extracts_explicit_12m_shortfall_only_with_uncommitted_financing():
    text = (
        "We do not have sufficient liquidity to meet our obligations over the next twelve months. "
        "Additional financing may not be available and no assurance can be given."
    )
    assert DistressHardFlag.EXPLICIT_12M_OBLIGATION_SHORTFALL_WITHOUT_COMMITTED_FINANCING in flags(text)
    assert DistressHardFlag.EXPLICIT_12M_OBLIGATION_SHORTFALL_WITHOUT_COMMITTED_FINANCING not in flags(
        "We do not have sufficient liquidity to meet our obligations over the next twelve months, but a committed financing facility is available."
    )


def test_merge_preserves_primary_source_provenance_and_evidence():
    document = doc("There is substantial doubt about our ability to continue as a going concern.")
    evidence = extract_hard_distress_flags(document)
    raw = DistressRawFacts(ticker="TEST", sector_adapter=DistressSectorAdapter.CORPORATE, sources=["https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json"])
    merged = merge_hard_distress_evidence(raw, evidence)
    assert DistressHardFlag.GOING_CONCERN in merged.hard_distress_flags
    assert document.source_url in merged.sources
    assert merged.audit["hard_distress_evidence"][0]["evidence_span"]
