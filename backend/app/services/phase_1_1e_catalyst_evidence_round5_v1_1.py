from __future__ import annotations

import re

from app.domain.soe_v1_1 import SourceDocument
from app.services.catalyst_primary_evidence_service import ExtractedCatalystCandidate
from app.services.phase_1_1e_evidence_hygiene_round3_v1_1 import (
    extract_sec_catalyst_candidates_round3,
)

# Phase 1.1E Round-5 evidence repair only. No SOE thresholds, scores, scanner
# conditions, rankings, or classifications are changed here.
#
# A filing can legitimately contain formal guidance while merely scheduling a
# future earnings release. The guidance fact may remain valid, but the same
# filing must not be used as *completed quarterly earnings* evidence. Filtering
# the extracted earnings candidate itself is more robust than classifying the
# whole document, because phrases such as "announced today that it will release
# its financial results" otherwise contain both an "announced" token and a
# future-results clause.

_FUTURE_RESULTS_ACTION = re.compile(
    r"\b(?:will|plans?\s+to|expects?\s+to|scheduled\s+to|intends?\s+to|is\s+scheduled\s+to)\s+"
    r"(?:report|release|announce|publish)\b.{0,220}\b(?:quarterly|quarter|financial|fiscal|results?)\b",
    re.I | re.S,
)
_TO_REPORT_RESULTS = re.compile(
    r"\bto\s+(?:report|release|announce|publish)\b.{0,180}\b(?:quarterly|quarter|financial|fiscal)?\s*results\b",
    re.I | re.S,
)
_DATE_OF_RESULTS_NOTICE = re.compile(
    r"\bannounces?\s+(?:the\s+)?date\s+(?:of|for)\b.{0,180}\b(?:financial\s+)?results\b",
    re.I | re.S,
)


def _is_future_results_notice(candidate: ExtractedCatalystCandidate) -> bool:
    if candidate.input.event_type != "quarterly_earnings":
        return False
    span = " ".join(
        part for part in [candidate.matched_text, *list(candidate.input.evidence_spans or [])] if part
    )
    return bool(
        _FUTURE_RESULTS_ACTION.search(span)
        or _TO_REPORT_RESULTS.search(span)
        or _DATE_OF_RESULTS_NOTICE.search(span)
    )


def extract_sec_catalyst_candidates_round5(
    document: SourceDocument,
    *,
    is_biotech: bool = False,
) -> list[ExtractedCatalystCandidate]:
    """Reject scheduling notices as completed earnings evidence, fail-closed.

    Non-earnings candidates from the same filing (for example a genuine formal
    annual guidance reaffirmation) are preserved. Only the invalid quarterly
    earnings evidence candidate is removed.
    """
    candidates = extract_sec_catalyst_candidates_round3(document, is_biotech=is_biotech)
    return [candidate for candidate in candidates if not _is_future_results_notice(candidate)]
