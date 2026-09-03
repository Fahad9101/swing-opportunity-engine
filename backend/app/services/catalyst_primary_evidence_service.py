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
    re.compile(
        r"\b(?:reports?|reported|announces?|announced)\b.{0,90}"
        r"\b(?:first|second|third|fourth|quarterly|fiscal|Q[1-4]|FY\s*(?:20)?\d{2})\b"
        r".{0,100}\b(?:financial\s+)?results\b",
        re.I | re.S,
    ),
    re.compile(
        r"\b(?:first|second|third|fourth)\s+quarter(?:\s+fiscal\s+(?:20)?\d{2})?\s+"
        r"(?:financial\s+)?results\b",
        re.I,
    ),
    re.compile(r"\bfinancial\s+results\s+for\s+(?:the\s+)?(?:quarter|three\s+months|six\s+months|nine\s+months)\b", re.I),
    re.compile(r"\bquarter\s+ended\b.{0,180}\b(?:net\s+sales|revenue|revenues|earnings|income)\b", re.I | re.S),
]
_GUIDANCE_ACTION = (
    r"(?:raises?|raised|reaffirms?|reaffirmed|maintains?|maintained|lowers?|lowered|"
    r"reduces?|reduced|cuts?|cut|updates?|updated|withdraws?|withdrew|initiates?|initiated|"
    r"provides?|provided)"
)
_ANNUAL_PERIOD = r"(?:full[- ]year|fiscal(?:\s+year)?\s+(?:20)?\d{2}|FY\s*(?:20)?\d{2}|annual)"
_GUIDANCE_TERM = r"(?:guidance|outlook|targets?)"
_GUIDANCE_PATTERNS = [
    re.compile(rf"\b{_GUIDANCE_ACTION}\b.{{0,140}}\b{_ANNUAL_PERIOD}\b.{{0,100}}\b{_GUIDANCE_TERM}\b", re.I | re.S),
    # When the annual period appears before the guidance term, keep the linkage tight.
    # A wider window let narrative phrases such as "into fiscal year 2026 ... Financial Outlook"
    # bridge into a following quarterly-guidance section and masquerade as full-year guidance.
    re.compile(rf"\b{_ANNUAL_PERIOD}\b.{{0,48}}\b{_GUIDANCE_TERM}\b.{{0,140}}\b{_GUIDANCE_ACTION}\b", re.I | re.S),
    re.compile(rf"\b{_GUIDANCE_ACTION}\b.{{0,100}}\b{_GUIDANCE_TERM}\b.{{0,100}}\b{_ANNUAL_PERIOD}\b", re.I | re.S),
]
_MERGER_PATTERNS = [
    re.compile(r"\bagreement\s+and\s+plan\s+of\s+merger\b", re.I),
    re.compile(r"\bmerger\s+agreement\b", re.I),
]
_REGULATORY_PATTERNS = [
    re.compile(
        r"\b(?:FDA|Food\s+and\s+Drug\s+Administration)\b.{0,180}"
        r"\b(?:has\s+approved|approved|granted\s+(?:accelerated\s+)?approval|"
        r"issued\s+(?:a\s+)?complete\s+response\s+letter|received\s+(?:a\s+)?complete\s+response\s+letter|"
        r"set\s+(?:a\s+)?PDUFA|advisory\s+committee\s+(?:voted|recommended))\b",
        re.I | re.S,
    ),
]
_PHASE3_PATTERNS = [
    re.compile(r"\bphase\s*3\b.{0,220}\bprimary\s+endpoint\b.{0,160}\b(?:was\s+met|met|did\s+not\s+meet|failed|achieved)\b", re.I | re.S),
    re.compile(r"\bphase\s*3\b.{0,180}\b(?:met|did\s+not\s+meet|failed|achieved)\b.{0,100}\b(?:its\s+|the\s+)?primary\s+endpoint\b", re.I | re.S),
]
_PHASE2_PATTERNS = [
    re.compile(r"\bphase\s*2\b.{0,220}\b(?:proof[- ]of[- ]concept|primary\s+endpoint|efficacy)\b", re.I | re.S),
]
_REFINANCING_PATTERNS = [
    re.compile(
        r"\b(?:the\s+company|company|we|registrant|borrower)\b.{0,80}"
        r"\b(?:entered\s+into|completed|closed|obtained|executed|amended\s+and\s+restated)\b"
        r".{0,140}\b(?:credit\s+agreement|credit\s+facility|term\s+loan|revolver|covenant)\b",
        re.I | re.S,
    ),
    re.compile(r"\b(?:entered\s+into|completed|closed|obtained|executed)\b.{0,100}\bnew\s+credit\s+facility\b", re.I | re.S),
    re.compile(r"\bamended\s+and\s+restated\s+credit\s+agreement\b", re.I),
    re.compile(r"\bnew\s+credit\s+facility\b", re.I),
    re.compile(r"\bcovenant\s+amendment\b", re.I),
    re.compile(r"\brefinanced\b.{0,120}\b(?:debt|notes?|loans?|facility|credit\s+agreement)\b", re.I | re.S),
    re.compile(r"\brefinancing\b.{0,120}\b(?:debt|notes?|loans?|facility|credit\s+agreement)\b", re.I | re.S),
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


def _context(text: str, start: int, end: int) -> str:
    return text[max(0, start - 180) : min(len(text), end + 240)]


def _first_match(text: str, patterns: list[re.Pattern[str]]) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return _context(text, match.start(), match.end())
    return None


def _first_earnings_match(text: str) -> str | None:
    """Return current-period earnings evidence, not a call/webcast scheduling notice."""
    for pattern in _EARNINGS_PATTERNS:
        for match in pattern.finditer(text):
            surrounding = text[max(0, match.start() - 180) : min(len(text), match.end() + 220)]
            scheduling = re.search(r"\b(?:conference\s+call|webcast)\b", surrounding, re.I) and re.search(
                r"\b(?:to\s+discuss|will\s+discuss|will\s+host|scheduled|replay)\b",
                surrounding,
                re.I,
            )
            if scheduling:
                continue
            return _context(text, match.start(), match.end())
    return None


def _first_guidance_match(text: str) -> str | None:
    """Return explicit annual financial guidance evidence while rejecting policy/compensation wording."""
    for pattern in _GUIDANCE_PATTERNS:
        for match in pattern.finditer(text):
            core = match.group(0)
            surrounding = text[max(0, match.start() - 220) : min(len(text), match.end() + 260)]
            if re.search(r"\bdisclosure\s+updates?\b", surrounding, re.I):
                continue
            if re.search(r"\bupdates?\s+beginning\s+in\b", core, re.I) and re.search(
                r"\bguidance\s+changes?\b", core, re.I
            ):
                continue
            if re.search(r"\breporting\s+and\s+guidance\s+changes?\b", surrounding, re.I):
                continue
            if re.search(
                r"\b(?:incentive\s+compensation|target\s+incentive|eligible\s+executive|"
                r"change\s+in\s+control|severance|termination\s+of\s+employment|employment\s+agreement|"
                r"equity\s+award|compensation\s+plan)\b",
                surrounding,
                re.I,
            ):
                continue
            # Do not promote an annualized/run-rate calculation that merely references
            # quarterly guidance into a formal full-year guidance update. This appeared
            # in PANW investor material as "Annual Revenue run rate based on Q4 ... guidance".
            if re.search(
                r"\bannual(?:ized)?\s+(?:revenue\s+)?run[- ]?rate\s+based\s+on\b",
                surrounding,
                re.I,
            ):
                continue
            if re.search(r"\btargets?\b", core, re.I) and not re.search(
                r"\b(?:revenue|sales|EPS|earnings|income|margin|ARR|cash\s+flow|free\s+cash\s+flow|"
                r"operating\s+profit|EBITDA|bookings|billings|RPO|cRPO)\b",
                surrounding,
                re.I,
            ):
                continue
            return _context(text, match.start(), match.end())
    return None


def _make_input(
    document: SourceDocument,
    *,
    suffix: str,
    event_family: CatalystEventFamily,
    event_type: str,
    evidence_span: str,
    additional_evidence_spans: list[str] | None = None,
    company_wide: bool | None = None,
    is_biotech: bool = False,
    formal_guidance_action: bool | None = None,
) -> CatalystMaterialityInput:
    evidence_spans = [evidence_span]
    for span in additional_evidence_spans or []:
        if span and span not in evidence_spans:
            evidence_spans.append(span)
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
        evidence_spans=evidence_spans,
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

    earnings_span = _first_earnings_match(text)
    guidance_span = _first_guidance_match(text)
    if earnings_span:
        inp = _make_input(
            document,
            suffix="earnings",
            event_family=CatalystEventFamily.EARNINGS_GUIDANCE,
            event_type="quarterly_earnings",
            evidence_span=earnings_span,
            additional_evidence_spans=[guidance_span] if guidance_span else None,
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
