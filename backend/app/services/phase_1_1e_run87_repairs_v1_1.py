from __future__ import annotations

import re

from app.domain.soe_v1_1 import GuidanceExtractionResult, GuidanceMetric, GuidanceMetricRecord, SourceDocument
from app.services.phase_1_1e_run85_repairs_v1_1 import extract_guidance_facts_run85


# Run-87 manual-audit repair: reject historical/reconciliation margin actuals that
# happened to sit near an unrelated full-year guidance sentence. This changes
# evidence binding only; no frozen threshold, score, scanner, or classifier rule.
_RECONCILIATION = re.compile(
    r"(?:R\s*EC\s*O\s*N\s*C\s*ILIA\s*TIO\s*N|RECONCILIATION)\s+O\s*F\s+G\s*A\s*A\s*P",
    re.I,
)
_HISTORICAL_TWO_COLUMN = re.compile(
    r"\b20\d{2}\s+20\d{2}\s+Revenues?\b.{0,220}?\bGross\s+profit(?:\s+margin)?\b",
    re.I | re.S,
)
_PERIOD_ENDED = re.compile(
    r"\b(?:Quarter|Three\s+Months|Six\s+Months|Nine\s+Months|Year)\s+Ended\b",
    re.I,
)


def _historical_margin_actual(record: GuidanceMetricRecord) -> bool:
    if record.metric not in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        return False
    evidence = record.evidence_span or ""
    if "phase_1_1e_run85" not in evidence:
        return False
    return bool(
        _RECONCILIATION.search(evidence)
        or _HISTORICAL_TWO_COLUMN.search(evidence)
        or _PERIOD_ENDED.search(evidence)
    )


def extract_guidance_facts_run87(
    document: SourceDocument,
    *,
    rules_hash: str,
) -> GuidanceExtractionResult:
    """Remove historical margin actuals misbound as guidance in Run 87.

    The Run-85 extractor remains authoritative for true forward margins. This
    narrow wrapper only removes structured supplemental margin records whose own
    evidence span identifies a historical/reconciliation results table.
    """
    result = extract_guidance_facts_run85(document, rules_hash=rules_hash)
    rejected_actuals = [record for record in result.records if _historical_margin_actual(record)]
    if not rejected_actuals:
        return result

    records = [record for record in result.records if not _historical_margin_actual(record)]
    rejected = list(result.rejected_candidates)
    rejected.append(
        {
            "reason": "phase_1_1e_run87_historical_margin_actual_rejected",
            "rejected_record_count": len(rejected_actuals),
            "rejected_metrics": sorted({record.metric.value for record in rejected_actuals}),
        }
    )
    return result.model_copy(update={"records": records, "rejected_candidates": rejected})
