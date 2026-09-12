from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.domain.guidance_canonical_v1 import CanonicalizationResult
from app.domain.soe_v1_1 import GuidanceClassification, SourceDocument
from app.services.guidance_canonical_assessment_service import assess_canonicalization_result
from app.services.guidance_canonical_service import CanonicalGuidanceNormalizer, GuidanceInvariantValidator
from app.services.guidance_raw_typed_extractor import extract_typed_guidance_facts


_SEC_URL = re.compile(
    r"^https://(?:www\.)?sec\.gov/Archives/edgar/data/(?P<cik>\d+)/(?P<path>[^?#]+)$",
    re.I,
)


@dataclass(frozen=True)
class RawReplaySource:
    ticker: str
    source_url: str
    source_document_hash: str
    source_accession: str | None
    source_timestamp: datetime
    cik: str


@dataclass(frozen=True)
class VerifiedDocumentContent:
    content: str
    content_hash: str
    content_type: str | None = None


def _guidance_payloads(validation: dict[str, Any]):
    for row in validation.get("per_name_deltas") or []:
        ticker = str(row.get("ticker") or "").upper()
        guidance = ((row.get("structural_inputs") or {}).get("guidance") or {})
        if ticker and guidance:
            yield ticker, guidance


def build_raw_replay_manifest(validation: dict[str, Any]) -> list[RawReplaySource]:
    """Build a unique immutable SEC source manifest from the acceptance artifact."""
    by_url: dict[str, RawReplaySource] = {}
    conflicts: list[str] = []

    for ticker, payload in _guidance_payloads(validation):
        for record in payload.get("ledger_records") or []:
            url = str(record.get("source_url") or "").strip()
            expected_hash = str(record.get("source_document_hash") or "").strip().lower()
            timestamp_raw = record.get("source_timestamp")
            if not url or not expected_hash or not timestamp_raw:
                continue
            match = _SEC_URL.match(url)
            if match is None:
                conflicts.append(f"Non-SEC archive source in guidance ledger: {url}")
                continue
            timestamp = datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00"))
            source = RawReplaySource(
                ticker=ticker,
                source_url=url,
                source_document_hash=expected_hash,
                source_accession=record.get("source_accession"),
                source_timestamp=timestamp,
                cik=match.group("cik").zfill(10),
            )
            existing = by_url.get(url)
            if existing is not None and existing != source:
                conflicts.append(f"Conflicting immutable source metadata for {url}")
                continue
            by_url[url] = source

    if conflicts:
        raise ValueError("; ".join(sorted(set(conflicts))))
    return sorted(by_url.values(), key=lambda item: (item.ticker, item.source_timestamp, item.source_url))


def _source_document(source: RawReplaySource, verified: VerifiedDocumentContent, *, rules_hash: str) -> SourceDocument:
    return SourceDocument(
        document_id=f"raw-replay:{source.source_document_hash}",
        rules_hash=rules_hash,
        ticker=source.ticker,
        cik=source.cik,
        accession=source.source_accession or "unknown",
        form="SEC_ARCHIVE_REPLAY",
        source_url=source.source_url,
        source_timestamp=source.source_timestamp,
        fetched_at=source.source_timestamp,
        stale=False,
        content_hash=verified.content_hash,
        content_type=verified.content_type,
        content=verified.content,
    )


def _canonicalize_ticker(
    sources: list[RawReplaySource],
    verified_documents: Mapping[str, VerifiedDocumentContent],
    *,
    rules_hash: str,
) -> tuple[CanonicalizationResult, int, list[dict[str, Any]]]:
    validator = GuidanceInvariantValidator()
    validated = []
    raw_fact_count = 0
    rejected_candidates: list[dict[str, Any]] = []

    for source in sources:
        verified = verified_documents[source.source_url]
        document = _source_document(source, verified, rules_hash=rules_hash)
        extraction = extract_typed_guidance_facts(document)
        raw_fact_count += len(extraction.facts)
        rejected_candidates.extend(
            {
                "source_url": source.source_url,
                **dict(candidate),
            }
            for candidate in extraction.rejected_candidates
        )
        validated.extend(validator.validate(fact) for fact in extraction.facts)

    canonical = CanonicalGuidanceNormalizer().normalize(validated)
    return canonical, raw_fact_count, rejected_candidates


def raw_sec_replay_differential_report(
    validation: dict[str, Any],
    rules: dict[str, Any],
    verified_documents: Mapping[str, VerifiedDocumentContent],
    *,
    rules_hash: str | None = None,
) -> dict[str, Any]:
    """Replay exact immutable SEC documents through the raw typed architecture.

    `verified_documents` must already have passed byte-hash verification against
    the immutable acceptance manifest. Missing documents are reported and their
    tickers are not partially classified.
    """
    effective_rules_hash = rules_hash or str(validation.get("candidate_rules_hash") or "")
    manifest = build_raw_replay_manifest(validation)
    by_ticker: dict[str, list[RawReplaySource]] = defaultdict(list)
    for source in manifest:
        by_ticker[source.ticker].append(source)

    benchmark = {ticker: payload for ticker, payload in _guidance_payloads(validation)}
    missing_urls = [source.source_url for source in manifest if source.source_url not in verified_documents]
    missing_by_ticker: dict[str, list[str]] = defaultdict(list)
    for source in manifest:
        if source.source_url not in verified_documents:
            missing_by_ticker[source.ticker].append(source.source_url)

    raw_facts = 0
    canonical_facts = 0
    quarantined_facts = 0
    quarantine_codes: Counter[str] = Counter()
    classifications_raw: Counter[str] = Counter()
    divergences: list[dict[str, Any]] = []
    ticker_reports: list[dict[str, Any]] = []
    rejected_count = 0

    for ticker in sorted(benchmark):
        payload = benchmark[ticker]
        old_classification = str(payload.get("classification") or "UNKNOWN")
        ticker_missing = missing_by_ticker.get(ticker, [])
        if ticker_missing:
            ticker_reports.append(
                {
                    "ticker": ticker,
                    "legacy_classification": old_classification,
                    "status": "INCOMPLETE_SOURCE_REPLAY",
                    "missing_source_count": len(ticker_missing),
                    "missing_sources": sorted(ticker_missing),
                }
            )
            continue

        canonical, ticker_raw_count, rejected = _canonicalize_ticker(
            by_ticker.get(ticker, []),
            verified_documents,
            rules_hash=effective_rules_hash,
        )
        raw_facts += ticker_raw_count
        rejected_count += len(rejected)
        canonical_facts += len(canonical.accepted)
        quarantined_facts += len(canonical.quarantined)

        ticker_codes: Counter[str] = Counter()
        for item in canonical.quarantined:
            for violation in item.violations:
                if violation.quarantine:
                    quarantine_codes[violation.code.value] += 1
                    ticker_codes[violation.code.value] += 1

        assessment = assess_canonicalization_result(
            canonical,
            ticker,
            rules,
            rules_hash=effective_rules_hash,
        )
        raw_classification = assessment.classification.value
        classifications_raw[raw_classification] += 1
        if raw_classification != old_classification:
            divergences.append(
                {
                    "ticker": ticker,
                    "legacy_classification": old_classification,
                    "raw_canonical_classification": raw_classification,
                    "legacy_rule_path": payload.get("rule_path"),
                    "raw_rule_path": assessment.rule_path,
                    "raw_reasons": list(assessment.reasons),
                    "source_document_count": len(by_ticker.get(ticker, [])),
                    "raw_fact_count": ticker_raw_count,
                    "canonical_fact_count": len(canonical.accepted),
                    "quarantined_fact_count": len(canonical.quarantined),
                    "quarantine_codes": dict(sorted(ticker_codes.items())),
                }
            )

        ticker_reports.append(
            {
                "ticker": ticker,
                "legacy_classification": old_classification,
                "raw_canonical_classification": raw_classification,
                "status": "COMPLETE",
                "source_document_count": len(by_ticker.get(ticker, [])),
                "raw_fact_count": ticker_raw_count,
                "canonical_fact_count": len(canonical.accepted),
                "quarantined_fact_count": len(canonical.quarantined),
                "quarantine_codes": dict(sorted(ticker_codes.items())),
                "rejected_candidate_count": len(rejected),
            }
        )

    complete_tickers = sum(1 for item in ticker_reports if item.get("status") == "COMPLETE")
    return {
        "rules_hash": effective_rules_hash,
        "tickers_with_guidance_payload": len(benchmark),
        "source_manifest_count": len(manifest),
        "verified_source_count": len(manifest) - len(missing_urls),
        "missing_source_count": len(missing_urls),
        "complete_ticker_count": complete_tickers,
        "incomplete_ticker_count": len(benchmark) - complete_tickers,
        "raw_typed_fact_count": raw_facts,
        "canonical_fact_count": canonical_facts,
        "quarantined_fact_count": quarantined_facts,
        "rejected_candidate_count": rejected_count,
        "quarantine_codes": dict(sorted(quarantine_codes.items())),
        "raw_classification_distribution": dict(sorted(classifications_raw.items())),
        "classification_divergence_count": len(divergences),
        "classification_divergences": sorted(divergences, key=lambda item: item["ticker"]),
        "missing_sources": sorted(missing_urls),
        "ticker_reports": ticker_reports,
    }
