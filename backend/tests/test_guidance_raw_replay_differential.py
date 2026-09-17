from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import yaml

from app.domain.guidance_canonical_v1 import (
    EvidenceBinding,
    GuidanceFactRole,
    GuidancePeriodKind,
    GuidanceProvenance,
    GuidanceScopeKind,
    GuidanceUnit,
    TypedGuidanceFact,
)
from app.domain.soe_v1_1 import ExtractionMethod, GuidanceAction, GuidanceMetric
from app.services import guidance_raw_replay_differential_service as replay
from app.services.guidance_raw_replay_differential_service import (
    VerifiedDocumentContent,
    build_raw_replay_manifest,
    raw_sec_replay_differential_report,
)


def _rules() -> dict:
    with open("config/soe_v1_1_rules.yaml", "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _record(*, ticker: str, url: str, content: bytes, ts: str, low: float, high: float) -> dict:
    return {
        "ticker": ticker,
        "fiscal_period": "FY2026",
        "metric": "revenue",
        "accounting_basis": "UNSPECIFIED",
        "low": low,
        "high": high,
        "unit": "USD",
        "source": "SEC EDGAR",
        "source_url": url,
        "source_accession": "0000000001-26-000001",
        "source_timestamp": ts,
        "source_document_hash": hashlib.sha256(content).hexdigest(),
        "explicit_action": "INITIATE",
        "verified": True,
        "extraction_method": "deterministic_text",
        "as_of": ts,
        "fetched_at": ts,
        "stale": False,
        "rules_hash": "candidate-hash",
    }


def _validation() -> tuple[dict, dict[str, bytes]]:
    old = b"Full-year 2026 guidance. The company expects total revenue of $100 million."
    new = b"Full-year 2026 guidance. The company expects total revenue of $105 million."
    old_url = "https://www.sec.gov/Archives/edgar/data/1/old.htm"
    new_url = "https://www.sec.gov/Archives/edgar/data/1/new.htm"
    old_record = _record(
        ticker="TEST",
        url=old_url,
        content=old,
        ts="2026-01-01T00:00:00Z",
        low=100_000_000.0,
        high=100_000_000.0,
    )
    new_record = _record(
        ticker="TEST",
        url=new_url,
        content=new,
        ts="2026-04-01T00:00:00Z",
        low=105_000_000.0,
        high=105_000_000.0,
    )
    validation = {
        "candidate_rules_hash": "candidate-hash",
        "per_name_deltas": [
            {
                "ticker": "TEST",
                "structural_inputs": {
                    "guidance": {
                        "classification": "NOT_DETERIORATED",
                        "rule_path": "guidance_v1_1.no_material_cut",
                        "ledger_records": [old_record, new_record, dict(new_record)],
                    }
                },
            }
        ],
    }
    return validation, {old_url: old, new_url: new}


def _typed_fact(
    document,
    *,
    metric: GuidanceMetric,
    period: str,
    kind: GuidancePeriodKind,
    metric_text: str,
    value_text: str,
    period_text: str,
    low: float,
    high: float,
    action: GuidanceAction = GuidanceAction.INITIATE,
) -> TypedGuidanceFact:
    text = document.content
    metric_start = text.index(metric_text)
    value_start = text.index(value_text)
    period_start = text.index(period_text)
    action_text = "expect" if "expect" in text.lower() else None
    action_start = text.lower().index("expect") if action_text else None
    evidence = EvidenceBinding(
        full_text=text,
        metric_text=metric_text,
        value_text=value_text,
        period_text=period_text,
        action_text=action_text,
        metric_start=metric_start,
        metric_end=metric_start + len(metric_text),
        value_start=value_start,
        value_end=value_start + len(value_text),
        period_start=period_start,
        period_end=period_start + len(period_text),
        action_start=action_start,
        action_end=None if action_start is None else action_start + len(action_text),
    )
    provenance = GuidanceProvenance(
        document_id=document.document_id,
        source=document.source,
        source_url=document.source_url,
        source_accession=document.accession,
        source_timestamp=document.source_timestamp,
        source_document_hash=document.content_hash,
        evidence=evidence,
    )
    return TypedGuidanceFact(
        ticker=document.ticker,
        metric=metric,
        raw_metric_label=metric.value,
        fiscal_period=period,
        authoritative_period=period,
        period_kind=kind,
        accounting_basis="UNSPECIFIED",
        scope_kind=GuidanceScopeKind.COMPANY,
        scope_label=None,
        role=GuidanceFactRole.CURRENT,
        low=low,
        high=high,
        unit=GuidanceUnit.USD,
        explicit_action=action,
        extraction_method=ExtractionMethod.DETERMINISTIC_TEXT,
        provenance=[provenance],
    )


def _single_replay_source(ticker: str, content: str):
    payload = content.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    url = f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}-replay.htm"
    source = replay.RawReplaySource(
        ticker=ticker,
        source_url=url,
        source_document_hash=digest,
        source_accession="0000000001-26-999999",
        source_timestamp=datetime(2026, 9, 14, tzinfo=UTC),
        cik="0000000001",
    )
    verified = {
        url: VerifiedDocumentContent(
            content=content,
            content_hash=digest,
            content_type="text/plain",
        )
    }
    return source, verified


def test_manifest_deduplicates_exact_immutable_sec_documents():
    validation, contents = _validation()
    manifest = build_raw_replay_manifest(validation)
    assert len(manifest) == 2
    assert {item.source_url for item in manifest} == set(contents)
    assert all(item.cik == "0000000001" for item in manifest)


def test_raw_replay_matches_validated_classification_without_legacy_rows():
    validation, contents = _validation()
    verified = {
        url: VerifiedDocumentContent(
            content=payload.decode("utf-8"),
            content_hash=hashlib.sha256(payload).hexdigest(),
            content_type="text/plain",
        )
        for url, payload in contents.items()
    }
    report = raw_sec_replay_differential_report(
        validation,
        _rules(),
        verified,
        rules_hash="candidate-hash",
    )
    assert report["evidence_binder_version"] == "strict-v4"
    assert report["source_manifest_count"] == 2
    assert report["verified_source_count"] == 2
    assert report["complete_ticker_count"] == 1
    assert report["incomplete_ticker_count"] == 0
    assert report["classification_divergence_count"] == 0
    assert report["raw_typed_fact_count"] >= 2


def test_missing_source_fails_closed_without_partial_ticker_classification():
    validation, contents = _validation()
    first_url, first_payload = next(iter(contents.items()))
    report = raw_sec_replay_differential_report(
        validation,
        _rules(),
        {
            first_url: VerifiedDocumentContent(
                content=first_payload.decode("utf-8"),
                content_hash=hashlib.sha256(first_payload).hexdigest(),
            )
        },
        rules_hash="candidate-hash",
    )
    assert report["missing_source_count"] == 1
    assert report["complete_ticker_count"] == 0
    assert report["incomplete_ticker_count"] == 1
    assert report["classification_divergence_count"] == 0
    assert report["ticker_reports"][0]["status"] == "INCOMPLETE_SOURCE_REPLAY"


def test_raw_replay_quarantines_strict_v4_run_rate_ebitda(monkeypatch):
    text = (
        "Commonwealth Financial Network: On track to complete the conversion in the fourth quarter of 2026. "
        "Continue to expect asset retention of approximately 90% and run-rate EBITDA of approximately $425 million."
    )
    source, verified = _single_replay_source("LPLA", text)

    def fake_extract(document):
        fact = _typed_fact(
            document,
            metric=GuidanceMetric.EBITDA,
            period="Q4FY2026",
            kind=GuidancePeriodKind.QUARTER,
            metric_text="EBITDA",
            value_text="$425 million",
            period_text="fourth quarter of 2026",
            low=425e6,
            high=425e6,
        )
        return SimpleNamespace(facts=[fact], rejected_candidates=[])

    monkeypatch.setattr(replay, "extract_canonical_typed_guidance_facts", fake_extract)
    canonical, raw_count, rejected, errors = replay._canonicalize_ticker(
        [source], verified, rules_hash="candidate-hash"
    )

    assert raw_count == 1
    assert rejected == []
    assert errors == []
    assert canonical.accepted == []
    assert len(canonical.quarantined) == 1


def test_raw_replay_preserves_valid_strict_v4_quarter_guidance(monkeypatch):
    text = (
        "Financial Outlook: Netskope is providing the following guidance for the third quarter and full year fiscal 2027. "
        "For the third quarter of fiscal 2027, we expect Revenue of $227 million to $229 million."
    )
    source, verified = _single_replay_source("NTSK", text)

    def fake_extract(document):
        fact = _typed_fact(
            document,
            metric=GuidanceMetric.REVENUE,
            period="Q3FY2027",
            kind=GuidancePeriodKind.QUARTER,
            metric_text="Revenue",
            value_text="$227 million to $229 million",
            period_text="third quarter of fiscal 2027",
            low=227e6,
            high=229e6,
        )
        return SimpleNamespace(facts=[fact], rejected_candidates=[])

    monkeypatch.setattr(replay, "extract_canonical_typed_guidance_facts", fake_extract)
    canonical, raw_count, rejected, errors = replay._canonicalize_ticker(
        [source], verified, rules_hash="candidate-hash"
    )

    assert raw_count == 1
    assert rejected == []
    assert errors == []
    assert len(canonical.accepted) == 1
    assert canonical.quarantined == []
