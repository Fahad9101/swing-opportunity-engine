from __future__ import annotations

import html
import re
from dataclasses import dataclass

from app.domain.catalyst_v1_1 import (
    CatalystEventFamily,
    CatalystExtractionMethod,
    CatalystMaterialityInput,
)
from app.domain.soe_v1_1 import SourceDocument


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.I | re.S)
_WS_RE = re.compile(r"\s+")

_EARNINGS_PATTERNS = [
    re.compile(r"\b(?:reports?|announces?)\b.{0,90}\b(?:first|second|third|fourth|quarterly|fiscal|Q[1-4]|FY\s*20\d{2})\b.{0,100}\b(?:financial\s+)?results\b", re.I | re.S),
    re.compile(r"\bfinancial\s+results\s+for\s+(?:the\s+)?(?:quarter|three\s+months|six\s+months|nine\s+months)\b", re.I),
    re.compile(r"\bquarter\s+ended\b.{0,180}\b(?:net\s+sales|revenue|revenues|earnings|income)\b", re.I | re.S),
]
_GUIDANCE_ACTION = r"(?:raises?|raised|reaffirms?|reaffirmed|maintains?|maintained|lowers?|lowered|reduces?|reduced|cuts?|cut|updates?|updated|withdraws?|withdrew|initiates?|initiated)"
_ANNUAL_PERIOD = r"(?:full[- ]year|fiscal(?:\s+year)?\s+20\d{2}|FY\s*20\d{2}|annual)"
_GUIDANCE_TERM = r"(?:guidance|outlook)"
_GUIDANCE_PATTERNS = [
    re.compile(rf"\b{_GUIDANCE_ACTION}\b.{{0,140}}\b{_ANNUAL_PERIOD}\b.{{0,100}}\b{_GUIDANCE_TERM}\b", re.I | re.S),
    re.compile(rf"\b{_ANNUAL_PERIOD}\b.{{0,100}}\b{_GUIDANCE_TERM}\b.{{0,140}}\b{_GUIDANCE_ACTION}\b", re.I | re.S),
    re.compile(rf"\b{_GUIDANCE_ACTION}\b.{{0,100}}\b{_GUIDANCE_TERM}\b.{{0,100}}\b{_ANNUAL_PERIOD}\b", re.I | re.S),
]
_MERGER_PATTERNS = [
    re.compile(r"\bagreement\s+and\s+plan\s+of\s+merger\b", re.I),
    re.compile(r"\bmerger\s+agreement\b", re.I),
]
_REGULATORY_PATTERNS = [
    re.compile(r"\b(?:FDA|Food\s+and\s+Drug\s+Administration)\b.{0,160}\b(?:approved?|approval|complete\s+response\s+letter|CRL|PDUFA|advisory\s+committee)\b", re.I | re.S),
]
_PHASE3_PATTERNS = [
    re.compile(r"\bphase\s*3\b.{0,220}\bprimary\s+endpoint\b.{0,160}\b(?:met|meet|did\s+not\s+meet|failed|achieved)\b", re.I | re.S),
]
_PHASE2_PATTERNS = [
    re.compile(r"\bphase\s*2\b.{0,220}\b(?:proof[- ]of[- ]concept|primary\s+endpoint|efficacy)\b", re.I | re.S),
]
_REFINANCING_PATTERNS = [
    re.compile(r"\b(?:refinancing|refinanced|amended\s+and\s+restated\s+credit\s+agreement|new\s+credit\s+facility|covenant\s+amendment)\b", re.I),
]
_CONTRACT_PATTERNS = [
    re.compile(r"\b(?:awarded|award|entered\s+into)\b.{0,100}\b(?:material\s+)?contract\b", re.I | re.S),
]
_ADMIN_PATTERNS = [
    re.compile(r"\bitem\s+5\.02\b", re.I),
    re.compile(r"\bdeparture\s+of\s+directors?\s+or\s+certain\s+officers?\b", re.I),
]


@dataclass(frozen=True)
class ExtractedCatalystCandidate:
    input: CatalystMaterialityInput
    matched_text: str


def _plain_text(raw: str) -> str:
    value = _SCRIPT_STYLE_RE.sub(" ", raw)
    value = _TAG_RE.sub(" ", value)
    value = html.unescape(value)
    return _WS_RE.sub(" ", value).strip()


def _first_match(text: str, patterns: list[re.Pattern[str]]) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            start = max(0, match.start() - 180)
            end = min(len(text), match.end() + 240)
            return text[start:end]
    return None


def _make_input(
    document: SourceDocument,
    *,
    suffix: str,
    event_family: CatalystEventFamily,
    event_type: str,
    evidence_span: str,
    company_wide: bool | None = None,
    is_biotech: bool = False,
    formal_guidance_action: bool | None = None,
) -> CatalystMaterialityInput:
    return CatalystMaterialityInput(
        ticker=document.ticker,
        event_id=f"{document.accession}:{suffix}",
        event_family=event_family,
        event_type=event_type,
        source=document.source,
        source_url=document.source_url,
        source_timestamp=document.source_timestamp,
        event_date=document.filing_date,
        verified=True,
        company_wide=company_wide,
        is_biotech=is_biotech,
        formal_guidance_action=formal_guidance_action,
        extraction_method=CatalystExtractionMethod.DETERMINISTIC_TEXT,
        evidence_spans=[evidence_span],
        structured_provenance={
            "accession": document.accession,
            "form": document.form,
            "document_id": document.document_id,
            "content_hash": document.content_hash,
            "filing_date": document.filing_date.isoformat() if document.filing_date else None,
        },
    )


def extract_sec_catalyst_candidates(
    document: SourceDocument,
    *,
    is_biotech: bool = False,
) -> list[ExtractedCatalystCandidate]:
    """Extract conservative event facts from one official SEC filing/exhibit.

    The function does not assign a materiality score. It only emits event facts
    when explicit event language is present. Economic exposure is deliberately
    populated only for event families with frozen company-wide defaults
    (quarterly earnings and formal annual guidance) or when a later enrichment
    step supplies verified exposure evidence.
    """
    raw = document.content or ""
    if not raw.strip():
        return []
    text = _plain_text(raw)
    if not text:
        return []

    candidates: list[ExtractedCatalystCandidate] = []

    earnings_span = _first_match(text, _EARNINGS_PATTERNS)
    guidance_span = _first_match(text, _GUIDANCE_PATTERNS)
    if earnings_span:
        inp = _make_input(
            document,
            suffix="earnings",
            event_family=CatalystEventFamily.EARNINGS_GUIDANCE,
            event_type="quarterly_earnings",
            evidence_span=earnings_span,
            company_wide=True,
            is_biotech=is_biotech,
            formal_guidance_action=bool(guidance_span),
        )
        candidates.append(ExtractedCatalystCandidate(inp, earnings_span))

    if guidance_span:
        inp = _make_input(
            document,
            suffix="guidance",
            event_family=CatalystEventFamily.EARNINGS_GUIDANCE,
            event_type="formal_full_year_guidance_update",
            evidence_span=guidance_span,
            company_wide=True,
            is_biotech=is_biotech,
            formal_guidance_action=True,
        )
        candidates.append(ExtractedCatalystCandidate(inp, guidance_span))

    for suffix, family, event_type, patterns in (
        ("merger", CatalystEventFamily.TRANSACTION_LEGAL_FINANCING, "merger_approval_or_close", _MERGER_PATTERNS),
        ("regulatory", CatalystEventFamily.CLINICAL_REGULATORY, "regulatory_decision", _REGULATORY_PATTERNS),
        ("phase3", CatalystEventFamily.CLINICAL_REGULATORY, "pivotal_phase3_readout", _PHASE3_PATTERNS),
        ("phase2", CatalystEventFamily.CLINICAL_REGULATORY, "phase2_poc_readout", _PHASE2_PATTERNS),
        ("refinancing", CatalystEventFamily.TRANSACTION_LEGAL_FINANCING, "material_refinancing_covenant_event", _REFINANCING_PATTERNS),
        ("contract", CatalystEventFamily.CORPORATE_STRATEGIC, "major_contract_customer_award", _CONTRACT_PATTERNS),
    ):
        span = _first_match(text, patterns)
        if not span:
            continue
        inp = _make_input(
            document,
            suffix=suffix,
            event_family=family,
            event_type=event_type,
            evidence_span=span,
            company_wide=None,
            is_biotech=is_biotech,
        )
        candidates.append(ExtractedCatalystCandidate(inp, span))

    # A narrow negative-control classification is allowed only when an explicit
    # Item 5.02 administrative filing is present and no recognized economic
    # catalyst was extracted from the same document.
    if not candidates:
        admin_span = _first_match(text, _ADMIN_PATTERNS)
        if admin_span:
            inp = _make_input(
                document,
                suffix="administrative",
                event_family=CatalystEventFamily.CORPORATE_STRATEGIC,
                event_type="administrative_or_unverifiable",
                evidence_span=admin_span,
                company_wide=False,
                is_biotech=is_biotech,
            )
            candidates.append(ExtractedCatalystCandidate(inp, admin_span))

    return candidates
