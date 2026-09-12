from __future__ import annotations

from app.domain.soe_v1_1 import GuidanceExtractionResult, GuidanceMetricRecord, SourceDocument
from app.services.phase_1_1e_evidence_hygiene_round3_patch_v1_1 import _metric_occurrences
from app.services.phase_1_1e_evidence_hygiene_round4_v1_1 import (
    _direct_metric_forward_relation,
    _metric_bound_period,
    dedupe_guidance_records_round4,
    extract_guidance_facts_round4,
    tighten_guidance_record_round4,
)

# Round 6 repairs one evidence-binding defect discovered by the independent
# full-market audit: a reported historical metric must not borrow forward
# guidance language that belongs to a different metric elsewhere in the same
# SEC earnings release/evidence window.
#
# This is evidence hygiene only. It does not alter any SOE threshold, score,
# scanner, classification rule, penalty, technical rule, or model weight.


def _has_metric_bound_forward_evidence(record: GuidanceMetricRecord, text: str) -> bool:
    """Require forward language to be grammatically bound to this metric.

    Accepted constructions are deliberately conservative:
    - direct metric guidance/expectation wording (relation >= 4), e.g.
      "revenue guidance", "expects revenue", or "revenue is expected"; or
    - a local guidance/outlook header (relation == 3) only when the fiscal period
      is itself grammatically attached to that metric guidance, e.g.
      "FY2027 Guidance ... Revenue".

    A generic guidance phrase elsewhere in the evidence span is insufficient.
    This prevents historical rows such as "Revenue $4.6 billion" from becoming
    guidance merely because the same release separately says "increased EBITDA
    guidance".
    """
    for start, end in _metric_occurrences(text, record.metric):
        relation = _direct_metric_forward_relation(text, start, end)
        if relation >= 4:
            return True
        if relation == 3 and _metric_bound_period(text, start, end) is not None:
            return True
    return False


def tighten_guidance_record_round6(record: GuidanceMetricRecord) -> GuidanceMetricRecord | None:
    base = tighten_guidance_record_round4(record)
    if base is None:
        return None

    text = (record.evidence_span or "").strip()
    if not text or base.midpoint is None:
        # Structured/manual evidence and qualitative explicit actions retain the
        # already hardened Round-4 behavior.
        return base

    if not _has_metric_bound_forward_evidence(base, text):
        return None
    return base


def dedupe_guidance_records_round6(records: list[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    # Filter first; the Round-4 deduper cannot reintroduce rejected records.
    tightened = [
        item
        for record in records
        if (item := tighten_guidance_record_round6(record)) is not None
    ]
    return dedupe_guidance_records_round4(tightened)


def extract_guidance_facts_round6(
    document: SourceDocument,
    *,
    rules_hash: str,
) -> GuidanceExtractionResult:
    base = extract_guidance_facts_round4(document, rules_hash=rules_hash)
    records = [
        item
        for record in base.records
        if (item := tighten_guidance_record_round6(record)) is not None
    ]
    records = dedupe_guidance_records_round6(records)

    policy = base.policy_evidence
    if any(record.midpoint is not None for record in records):
        policy = None

    return base.model_copy(update={"records": records, "policy_evidence": policy})
