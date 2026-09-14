from __future__ import annotations

import re
from typing import Any, Iterable

from app.domain.guidance_canonical_v1 import GuidanceUnit
from app.domain.soe_v1_1 import GuidanceAssessment, GuidancePolicyEvidence, SourceDocument
from app.services.fact_extraction_service import html_to_text
from app.services.guidance_canonical_assessment_service import assess_canonicalization_result
from app.services.guidance_canonical_ledger_service import CanonicalGuidanceLedger
from app.services.guidance_canonical_service import CanonicalGuidanceNormalizer, GuidanceInvariantValidator
from app.services.guidance_evidence_binder_v4 import GuidanceEvidenceBinder
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.guidance_raw_canonical_extractor import extract_canonical_typed_guidance_facts


_NO_GUIDANCE_POLICY = re.compile(
    r"\b(?:do(?:es)?\s+not|doesn['’]t|will\s+not)\s+(?:provide|issue|give)\s+"
    r"(?:quantitative\s+)?(?:financial\s+)?guidance\b",
    re.I,
)


def _policy_evidence(document: SourceDocument) -> GuidancePolicyEvidence | None:
    text = html_to_text(document.content or "")
    match = _NO_GUIDANCE_POLICY.search(text)
    if match is None:
        return None
    start = max(0, match.start() - 160)
    end = min(len(text), match.end() + 160)
    return GuidancePolicyEvidence(
        ticker=document.ticker,
        standing_no_guidance_policy=True,
        source=document.source,
        source_url=document.source_url,
        source_timestamp=document.source_timestamp,
        evidence_span=text[start:end].strip(),
    )


def _midpoint(item) -> float | None:
    fact = getattr(item, "fact", None)
    if fact is not None:
        if fact.low is None or fact.high is None:
            return None
        return (fact.low + fact.high) / 2.0
    return item.midpoint


def guidance_comparable_pair_count(ledger, ticker: str) -> int:
    """Count numeric current/prior pairs for legacy or canonical ledgers.

    The coverage contract is unchanged: a name enters the denominator only when
    the latest guidance snapshot has at least one numeric key with a comparable
    prior. Supporting both ledger types keeps the pre-existing test contract
    while the production path moves to the canonical ledger.
    """
    view = ledger.current_and_prior(ticker)
    if hasattr(view, "current"):
        current, prior = list(view.current), list(view.prior)
    else:
        current, prior = view
    prior_keys = {item.comparison_key for item in prior if _midpoint(item) is not None}
    return sum(1 for item in current if _midpoint(item) is not None and item.comparison_key in prior_keys)


def _legacy_audit_unit(unit: GuidanceUnit, low: float | None, high: float | None) -> str:
    if unit is GuidanceUnit.USD:
        return "USD"
    if unit is GuidanceUnit.USD_PER_SHARE:
        return "USD/share"
    if unit is GuidanceUnit.FRACTION:
        return "fraction"
    if unit is GuidanceUnit.UNKNOWN and low is None and high is None:
        return "UNKNOWN"
    return unit.value


def _audit_record(observation, *, rules_hash: str) -> dict[str, Any]:
    """Serialize canonical evidence in the stable legacy audit envelope.

    `ledger_records` is an external validation/replay surface used by older Phase
    1.1E regression tests and artifacts. Keep it round-trippable through
    GuidanceMetricRecord while adding canonical metadata alongside it.
    """
    fact = observation.fact
    provenance = sorted(
        observation.provenance,
        key=lambda item: (item.source_timestamp, item.source_url, item.source_accession or ""),
    )
    primary = provenance[0]
    midpoint = None if fact.low is None or fact.high is None else (fact.low + fact.high) / 2.0
    timestamp = observation.available_at.isoformat()
    return {
        "rules_hash": rules_hash,
        "ticker": fact.ticker,
        "fiscal_period": fact.fiscal_period,
        "metric": fact.metric.value,
        "accounting_basis": fact.accounting_basis,
        "low": fact.low,
        "high": fact.high,
        "midpoint": midpoint,
        "unit": _legacy_audit_unit(fact.unit, fact.low, fact.high),
        "source": primary.source,
        "source_url": primary.source_url,
        "source_accession": primary.source_accession,
        "source_timestamp": timestamp,
        "explicit_action": fact.explicit_action.value,
        "verified": True,
        "extraction_method": "deterministic_text",
        "evidence_span": primary.evidence.full_text,
        "source_document_hash": primary.source_document_hash,
        "as_of": timestamp,
        "fetched_at": timestamp,
        "stale": False,
        "canonical": True,
        "canonical_role": fact.role.value,
        "canonical_scope_kind": fact.scope_kind.value,
        "canonical_scope_label": fact.scope_label,
        "canonical_value_kind": fact.value_kind.value,
    }


def _source_manifest_row(document: SourceDocument) -> dict[str, Any]:
    return {
        "ticker": document.ticker,
        "source_url": document.source_url,
        "source_document_hash": document.content_hash,
        "source_accession": document.accession,
        "source_timestamp": document.source_timestamp.isoformat(),
        "cik": document.cik,
        "form": document.form,
        "document_id": document.document_id,
    }


def _quarantine_summary(item) -> dict[str, Any]:
    return {
        "fact": item.fact.model_dump(mode="json"),
        "violations": [violation.model_dump(mode="json") for violation in item.violations],
    }


def assess_canonical_guidance_documents(
    ticker: str,
    documents: Iterable[SourceDocument],
    rules: dict[str, Any],
    *,
    rules_hash: str,
) -> tuple[GuidanceAssessment | None, dict[str, Any], list[str]]:
    """Run the permanent raw->typed->canonical guidance path for shadow validation.

    Numeric legacy extraction is deliberately absent. The only legacy component
    retained is the frozen classifier itself, reached through CanonicalGuidanceLedger,
    plus the standing no-guidance policy rule when there are no canonical facts.
    Any document-level parser error makes the ticker fail closed rather than
    classifying from a partial evidence set.
    """
    documents = list(documents)
    validator = GuidanceInvariantValidator()
    binder = GuidanceEvidenceBinder()
    validated = []
    binder_rejected_count = 0
    binder_quarantine: list[dict[str, Any]] = []
    policies: list[GuidancePolicyEvidence] = []
    raw_fact_count = 0
    rejected_candidate_count = 0
    extraction_errors: list[str] = []
    source_documents: dict[str, dict[str, Any]] = {}

    for document in documents:
        policy = _policy_evidence(document)
        if policy is not None:
            policies.append(policy)
        try:
            extraction = extract_canonical_typed_guidance_facts(document)
        except Exception as exc:  # parser boundary: preserve coverage, never trust partial evidence
            extraction_errors.append(
                f"GUIDANCE_EXTRACT:{document.accession}:{document.document_id}:{type(exc).__name__}"
            )
            continue

        raw_fact_count += len(extraction.facts)
        rejected_candidate_count += len(extraction.rejected_candidates)
        if extraction.facts:
            source_documents[document.source_url] = _source_manifest_row(document)
        for fact in extraction.facts:
            binding = binder.bind(fact, document)
            if binding.accepted:
                validated.append(validator.validate(fact))
                continue
            binder_rejected_count += 1
            binder_quarantine.append(
                {
                    "ticker": fact.ticker,
                    "metric": fact.metric.value,
                    "fiscal_period": fact.fiscal_period,
                    "accounting_basis": fact.accounting_basis,
                    "dimensions": dict(binding.dimensions),
                    "reasons": list(binding.reasons),
                    "source_url": document.source_url,
                    "source_timestamp": document.source_timestamp.isoformat(),
                    "evidence_span": fact.provenance[0].evidence.full_text,
                }
            )
            validated.append(binding.as_quarantined(fact))

    canonical = CanonicalGuidanceNormalizer().normalize(validated)
    ledger = CanonicalGuidanceLedger(canonical.accepted)
    comparable_pairs = guidance_comparable_pair_count(ledger, ticker) if canonical.accepted else 0
    policy = max(policies, key=lambda item: item.source_timestamp) if policies else None

    assessment: GuidanceAssessment | None = None
    if not extraction_errors and (canonical.accepted or canonical.quarantined):
        assessment = assess_canonicalization_result(
            canonical,
            ticker,
            rules,
            rules_hash=rules_hash,
        )
    elif not extraction_errors and policy is not None:
        assessment = GuidanceLedger([]).assess(
            ticker,
            rules,
            rules_hash=rules_hash,
            policy=policy,
        )

    audit_records = [
        _audit_record(observation, rules_hash=rules_hash)
        for observation in ledger.observations
    ]
    if extraction_errors:
        rule_path = "guidance_v1_1.canonical_extraction_incomplete"
        reasons = ["Canonical guidance extraction was incomplete; classification failed closed."]
        sources: list[str] = []
        classification = "UNKNOWN"
        guidance_deterioration = None
    elif assessment is None:
        rule_path = "guidance_v1_1.no_extracted_primary_guidance"
        reasons = ["No supported primary-source canonical guidance fact extracted."]
        sources = []
        classification = "UNKNOWN"
        guidance_deterioration = None
    else:
        rule_path = assessment.rule_path
        reasons = assessment.reasons
        sources = assessment.sources
        classification = assessment.classification.value
        guidance_deterioration = assessment.guidance_deterioration

    meta = {
        "records": len(audit_records),
        "ledger_records": audit_records,
        "source_documents": sorted(source_documents.values(), key=lambda item: (item["source_timestamp"], item["source_url"])),
        "policy_evidence": policy.model_dump(mode="json") if policy else None,
        "documents": len(documents),
        "raw_typed_facts": raw_fact_count,
        "canonical_accepted_facts": len(canonical.accepted),
        "canonical_quarantined_facts": len(canonical.quarantined),
        "canonical_quarantine": [_quarantine_summary(item) for item in canonical.quarantined],
        "evidence_binder_version": "strict-v4",
        "evidence_binder_rejected_facts": binder_rejected_count,
        "evidence_binder_quarantine": binder_quarantine,
        "rejected_candidates": rejected_candidate_count,
        "extraction_errors": list(extraction_errors),
        "comparable_pairs": comparable_pairs,
        "sufficient_comparable_guidance": comparable_pairs > 0 and guidance_deterioration is not None,
        "classification": classification,
        "guidance_deterioration": guidance_deterioration,
        "rule_path": rule_path,
        "sources": sources,
        "reasons": reasons,
    }
    return assessment, meta, extraction_errors
