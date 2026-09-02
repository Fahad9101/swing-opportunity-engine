from __future__ import annotations

import re
from typing import Any

from app.domain.distress_v1_1 import DistressHardFlag, DistressRawFacts
from app.domain.soe_v1_1 import SourceDocument
from app.services.fact_extraction_service import html_to_text


_NEGATED_GOING_CONCERN = re.compile(
    r"\b(?:no substantial doubt|does not raise substantial doubt|did not raise substantial doubt|without substantial doubt)\b",
    re.I,
)
_CURED_DEFAULT = re.compile(r"\b(?:cured|remedied|waived|paid in full|no longer in default)\b", re.I)


def _window(text: str, start: int, end: int, radius: int = 320) -> str:
    return re.sub(r"\s+", " ", text[max(0, start - radius) : min(len(text), end + radius)]).strip()


def _evidence(flag: DistressHardFlag, document: SourceDocument, span: str, reason: str) -> dict[str, Any]:
    return {
        "flag": flag.value,
        "source": document.source,
        "source_url": document.source_url,
        "source_timestamp": document.source_timestamp.isoformat(),
        "accession": document.accession,
        "evidence_span": span[:1200],
        "reason": reason,
    }


def extract_hard_distress_flags(document: SourceDocument) -> list[dict[str, Any]]:
    """Extract only explicit universal hard-distress facts from primary SEC text.

    The extractor is intentionally narrow. Absence of a match is never safety,
    and generic risk-factor language is not converted into a hard flag.
    """
    text = html_to_text(document.content or "")
    results: list[dict[str, Any]] = []
    seen: set[DistressHardFlag] = set()

    going_patterns = [
        re.compile(r"substantial\s+doubt.{0,180}?ability.{0,120}?continue\s+as\s+a\s+going\s+concern", re.I | re.S),
        re.compile(r"ability\s+to\s+continue\s+as\s+a\s+going\s+concern.{0,180}?substantial\s+doubt", re.I | re.S),
    ]
    for pattern in going_patterns:
        match = pattern.search(text)
        if match:
            span = _window(text, match.start(), match.end())
            if not _NEGATED_GOING_CONCERN.search(span):
                results.append(_evidence(DistressHardFlag.GOING_CONCERN, document, span, "SEC text explicitly states substantial doubt about ability to continue as a going concern."))
                seen.add(DistressHardFlag.GOING_CONCERN)
                break

    bankruptcy_patterns = [
        re.compile(r"filed\s+(?:a\s+)?(?:voluntary\s+)?petition(?:s)?[^.]{0,180}?chapter\s+(?:7|11)\b", re.I | re.S),
        re.compile(r"commenced\s+(?:voluntary\s+)?cases?[^.]{0,180}?chapter\s+11\b", re.I | re.S),
        re.compile(r"filed\s+for\s+bankruptcy\b", re.I),
    ]
    for pattern in bankruptcy_patterns:
        match = pattern.search(text)
        if match:
            span = _window(text, match.start(), match.end())
            results.append(_evidence(DistressHardFlag.BANKRUPTCY_OR_RESTRUCTURING, document, span, "Primary filing explicitly records a bankruptcy/reorganization filing."))
            seen.add(DistressHardFlag.BANKRUPTCY_OR_RESTRUCTURING)
            break

    default_patterns = [
        re.compile(r"\b(?:is|remains)\s+in\s+(?:payment\s+)?default\b[^.]{0,180}?(?:debt|loan|notes?|credit|indenture|principal|interest)", re.I | re.S),
        re.compile(r"failed\s+to\s+make\s+(?:a\s+)?(?:scheduled|required)?\s*(?:principal|interest|debt)\s+payment", re.I),
    ]
    for pattern in default_patterns:
        match = pattern.search(text)
        if match:
            span = _window(text, match.start(), match.end())
            if not _CURED_DEFAULT.search(span):
                results.append(_evidence(DistressHardFlag.PAYMENT_DEFAULT, document, span, "Primary filing explicitly states a current payment default."))
                seen.add(DistressHardFlag.PAYMENT_DEFAULT)
                break

    covenant_patterns = [
        re.compile(r"\b(?:uncured|unwaived|unresolved)\b.{0,100}?\b(?:covenant\s+)?(?:breach|default|noncompliance)\b", re.I | re.S),
        re.compile(r"\b(?:covenant\s+)?(?:breach|noncompliance|default)\b.{0,180}?\b(?:has\s+not|have\s+not|not\s+been|without)\b.{0,80}?\b(?:waiv|cure)", re.I | re.S),
    ]
    for pattern in covenant_patterns:
        match = pattern.search(text)
        if match:
            span = _window(text, match.start(), match.end())
            results.append(_evidence(DistressHardFlag.UNRESOLVED_COVENANT_BREACH, document, span, "Primary filing explicitly states an unresolved/unwaived covenant breach or default."))
            seen.add(DistressHardFlag.UNRESOLVED_COVENANT_BREACH)
            break

    reliability = re.search(r"financial\s+statements?.{0,220}?should\s+no\s+longer\s+be\s+relied\s+upon", text, re.I | re.S)
    if reliability:
        span = _window(text, reliability.start(), reliability.end(), 500)
        if re.search(r"\b(?:solvency|liquidity|ability\s+to\s+meet\s+obligations)\b", span, re.I):
            results.append(_evidence(DistressHardFlag.UNRESOLVED_SOLVENCY_RELIABILITY_ISSUE, document, span, "Primary filing states financial statements cannot be relied upon in connection with an unresolved solvency/liquidity issue."))
            seen.add(DistressHardFlag.UNRESOLVED_SOLVENCY_RELIABILITY_ISSUE)

    shortfall = re.search(
        r"(?:do|does|will)\s+not\s+have\s+sufficient\s+(?:cash|liquidity|resources).{0,240}?(?:next|following)\s+(?:12|twelve)\s+months",
        text,
        re.I | re.S,
    )
    if shortfall:
        span = _window(text, shortfall.start(), shortfall.end(), 600)
        if re.search(
            r"(?:additional\s+financing|additional\s+capital|capital\s+raise|financing).{0,180}?(?:not\s+committed|not\s+assured|no\s+assurance|may\s+not\s+be\s+available)",
            span,
            re.I | re.S,
        ):
            results.append(_evidence(DistressHardFlag.EXPLICIT_12M_OBLIGATION_SHORTFALL_WITHOUT_COMMITTED_FINANCING, document, span, "Primary filing explicitly states a 12-month liquidity shortfall with financing not committed/assured."))
            seen.add(DistressHardFlag.EXPLICIT_12M_OBLIGATION_SHORTFALL_WITHOUT_COMMITTED_FINANCING)

    # Keep one evidence item per hard flag per document.
    deduped: list[dict[str, Any]] = []
    emitted: set[str] = set()
    for item in results:
        if item["flag"] in emitted:
            continue
        emitted.add(item["flag"])
        deduped.append(item)
    return deduped


def merge_hard_distress_evidence(facts: DistressRawFacts, evidence: list[dict[str, Any]]) -> DistressRawFacts:
    flags = list(facts.hard_distress_flags)
    sources = list(facts.sources)
    for item in evidence:
        flag = DistressHardFlag(item["flag"])
        if flag not in flags:
            flags.append(flag)
        source_url = str(item.get("source_url") or "")
        if source_url and source_url not in sources:
            sources.append(source_url)
    audit = dict(facts.audit)
    audit["hard_distress_evidence"] = evidence
    return facts.model_copy(update={"hard_distress_flags": flags, "sources": sorted(set(sources)), "audit": audit})
