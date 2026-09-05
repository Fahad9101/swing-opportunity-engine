from __future__ import annotations

import json
import os
import time
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.config import get_settings
from app.domain.catalyst_surprise_v1_1 import CatalystSurpriseInput
from app.domain.catalyst_v1_1 import CatalystEventFamily
from app.domain.distress_v1_1 import DistressAssessment, DistressSectorAdapter
from app.domain.schemas import CorporateEvent, FundamentalSnapshot, Instrument
from app.domain.soe_v1_1 import GuidanceAssessment, GuidanceMetricRecord, GuidancePolicyEvidence
from app.providers.sec_distress import normalize_distress_companyfacts
from app.providers.sec_edgar import COMPANYFACTS_URL, TICKER_MAP_URL
from app.providers.yahoo_analyst import YahooAnalystEstimateProvider
from app.providers.yahoo_surprise_consensus import YahooSurpriseConsensusProvider
from app.services.cache_service import JsonFileCache
from app.services.catalyst_materiality_service import assess_materiality
from app.services.catalyst_primary_evidence_service import extract_sec_catalyst_candidates
from app.services.catalyst_surprise_service import assess_surprise_potential
from app.services.distress_classifier import classify_distress
from app.services.distress_fact_extraction_service import extract_hard_distress_flags, finalize_hard_distress_screen
from app.services.distress_metric_service import derive_distress_inputs
from app.services.distress_sector_service import route_distress_sector
from app.services.fact_extraction_service import extract_guidance_facts
from app.services.guidance_ledger_service import GuidanceLedger
from app.services.shadow_validation_service import CatalystStructuralOverride, catalyst_event_key
from app.services.source_document_service import SourceDocumentService, index_submissions_payload


SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_GUIDANCE_FORMS = {"10-K", "10-Q", "8-K", "6-K"}
_DISTRESS_FORMS = {"10-K", "10-Q", "8-K", "6-K"}
_CATALYST_FORMS = {"10-K", "10-Q", "8-K", "6-K"}


@dataclass
class StructuralEnrichmentResult:
    ticker: str
    guidance_deterioration: bool | None = None
    balance_sheet_distressed: bool | None = None
    catalyst_overrides: dict[str, CatalystStructuralOverride] = field(default_factory=dict)
    guidance: dict[str, Any] = field(default_factory=dict)
    distress: dict[str, Any] = field(default_factory=dict)
    catalysts: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _guidance_record_key(record: GuidanceMetricRecord) -> tuple[Any, ...]:
    return (
        record.comparison_key,
        record.source_timestamp,
        record.low,
        record.high,
        record.midpoint,
        record.unit,
        record.explicit_action.value,
    )


def _dedupe_guidance(records: list[GuidanceMetricRecord]) -> list[GuidanceMetricRecord]:
    chosen: dict[tuple[Any, ...], GuidanceMetricRecord] = {}
    for record in records:
        key = _guidance_record_key(record)
        existing = chosen.get(key)
        if existing is None or record.source_url < existing.source_url:
            chosen[key] = record
    return sorted(chosen.values(), key=lambda item: (item.source_timestamp, item.metric.value, item.fiscal_period))


def guidance_comparable_pair_count(ledger: GuidanceLedger, ticker: str) -> int:
    current, prior = ledger.current_and_prior(ticker)
    prior_keys = {item.comparison_key for item in prior if item.midpoint is not None}
    return sum(1 for item in current if item.midpoint is not None and item.comparison_key in prior_keys)


def nonfinancial_distress_decision_evidence(inputs, rules: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return whether available nonfinancial inputs independently reach a frozen decision path.

    This defines the Phase 1.1E coverage denominator. It does not classify the
    company; the pure distress classifier remains the authority. Gray-zone inputs
    are not counted as coverage failures merely because the frozen rules are
    intentionally indeterminate there.
    """
    config = rules["balance_sheet_distress_v1_1"]
    hard = config["universal_hard_overrides"]
    if any(hard.get(flag.value) is True for flag in inputs.hard_distress_flags):
        return True, ["verified_hard_distress_flag"]

    reasons: list[str] = []
    adapter = inputs.sector_adapter
    if adapter is DistressSectorAdapter.CORPORATE:
        bad, safe = config["corporate"]["distressed"], config["corporate"]["safe"]
        if inputs.net_cash is True:
            reasons.append("net_cash_safe_path")
        if inputs.net_debt_to_ebitda is not None and inputs.interest_coverage is not None:
            if inputs.net_debt_to_ebitda > bad["net_debt_to_ebitda_gt"] and inputs.interest_coverage < bad["paired_interest_coverage_lt"]:
                reasons.append("high_leverage_low_coverage_distress_path")
            if inputs.net_debt_to_ebitda <= safe["net_debt_to_ebitda_lte"] and inputs.interest_coverage >= safe["paired_interest_coverage_gte"]:
                reasons.append("leverage_coverage_safe_path")
        if (
            inputs.debt_outstanding is not None
            and inputs.debt_outstanding > 0
            and inputs.interest_coverage is not None
            and inputs.interest_coverage < bad["interest_coverage_absolute_lt"]
        ):
            reasons.append("absolute_interest_coverage_distress_path")
        if inputs.liquidity_coverage is not None:
            if inputs.liquidity_coverage < bad["liquidity_coverage_lt"] and inputs.financing_secured is not True:
                reasons.append("liquidity_shortfall_distress_path")
            if inputs.liquidity_coverage >= safe["liquidity_coverage_gte"] and inputs.trailing_fcf is not None and inputs.trailing_fcf > 0:
                reasons.append("liquidity_fcf_safe_path")
        if inputs.trailing_fcf is not None and inputs.trailing_fcf < 0 and inputs.cash_runway_months is not None:
            if inputs.cash_runway_months < bad["negative_fcf_runway_months_lt"] and inputs.financing_secured is not True:
                reasons.append("negative_fcf_short_runway_distress_path")
            if inputs.cash_runway_months >= safe["negative_fcf_runway_months_gte"]:
                reasons.append("negative_fcf_runway_safe_path")
    elif adapter is DistressSectorAdapter.UTILITY:
        bad, safe = config["utilities"]["distressed"], config["utilities"]["safe"]
        if inputs.net_debt_to_ebitda is not None and inputs.interest_coverage is not None:
            if inputs.net_debt_to_ebitda > bad["net_debt_to_ebitda_gt"] and inputs.interest_coverage < bad["paired_interest_coverage_lt"]:
                reasons.append("utility_distress_path")
            if inputs.net_debt_to_ebitda <= safe["net_debt_to_ebitda_lte"] and inputs.interest_coverage >= safe["paired_interest_coverage_gte"]:
                reasons.append("utility_safe_path")
        if inputs.liquidity_coverage is not None and inputs.liquidity_coverage < bad["liquidity_coverage_lt"] and inputs.financing_secured is not True:
            reasons.append("utility_liquidity_distress_path")
    elif adapter is DistressSectorAdapter.REIT:
        bad, safe = config["reits"]["distressed"], config["reits"]["safe"]
        if inputs.debt_to_ebitdare is not None and inputs.fixed_charge_coverage is not None:
            if inputs.debt_to_ebitdare > bad["debt_to_ebitdare_gt"] and inputs.fixed_charge_coverage < bad["paired_fixed_charge_coverage_lt"]:
                reasons.append("reit_distress_path")
            if inputs.debt_to_ebitdare <= safe["debt_to_ebitdare_lte"] and inputs.fixed_charge_coverage >= safe["paired_fixed_charge_coverage_gte"]:
                reasons.append("reit_safe_path")
        if inputs.liquidity_coverage is not None and inputs.liquidity_coverage < bad["liquidity_coverage_lt"] and inputs.financing_secured is not True:
            reasons.append("reit_liquidity_distress_path")
    return bool(reasons), reasons


class ShadowStructuralEnricher:
    """Targeted primary-source enrichment for Phase 1.1E shadow validation only.

    Expensive document retrieval is limited to names that survive the frozen
    market/universal gates and need a structural field. The class never changes
    market, technical, valuation, estimate, scanner, or score-weight inputs.
    """

    def __init__(self, *, rules: dict[str, Any], rules_hash: str, cache_dir: Path | None = None):
        self.rules = rules
        self.rules_hash = rules_hash
        self.settings = get_settings()
        self.cache_dir = Path(cache_dir or self.settings.cache_dir / "phase_1_1e")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        user_agent = os.environ.get("SEC_USER_AGENT", self.settings.sec_user_agent).strip()
        if "@" not in user_agent:
            raise RuntimeError("SEC_USER_AGENT must contain a contact email for Phase 1.1E SEC access")
        self.client = httpx.Client(
            timeout=30.0,
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            follow_redirects=True,
        )
        self.request_state = {"last": 0.0}
        self.document_service = SourceDocumentService(
            cache_dir=self.cache_dir / "documents",
            user_agent=user_agent,
            client=self.client,
            min_request_interval_seconds=0.15,
        )
        self.companyfacts_archive = self._open_archive(self.settings.sec_companyfacts_zip_path)
        self.submissions_archive = self._open_archive(self.settings.sec_submissions_zip_path)
        analyst = YahooAnalystEstimateProvider(cache=JsonFileCache(self.cache_dir / "analyst"), rules=rules)
        self.consensus = YahooSurpriseConsensusProvider(analyst)
        self._ticker_map: dict[str, str] | None = None
        self._submissions_cache: dict[str, dict[str, Any]] = {}
        self._document_cache: dict[tuple[str, int, int, tuple[str, ...]], list[Any]] = {}

    @staticmethod
    def _open_archive(path: Path) -> zipfile.ZipFile | None:
        try:
            return zipfile.ZipFile(path) if path.exists() else None
        except zipfile.BadZipFile:
            return None

    def close(self) -> None:
        self.document_service.close()
        self.client.close()
        if self.companyfacts_archive is not None:
            self.companyfacts_archive.close()
        if self.submissions_archive is not None:
            self.submissions_archive.close()

    def _get(self, url: str) -> httpx.Response:
        elapsed = time.monotonic() - self.request_state["last"]
        if elapsed < 0.15:
            time.sleep(0.15 - elapsed)
        response = self.client.get(url)
        self.request_state["last"] = time.monotonic()
        response.raise_for_status()
        return response

    def _mapping(self) -> dict[str, str]:
        if self._ticker_map is not None:
            return self._ticker_map
        path = self.cache_dir / "ticker_map.json"
        if path.exists() and datetime.now(UTC) - datetime.fromtimestamp(path.stat().st_mtime, UTC) < timedelta(hours=24):
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = self._get(TICKER_MAP_URL).json()
            path.write_text(json.dumps(payload), encoding="utf-8")
        fields = payload.get("fields") or []
        mapping: dict[str, str] = {}
        for values in payload.get("data") or []:
            row = dict(zip(fields, values, strict=False))
            ticker = str(row.get("ticker") or "").upper().replace(".", "-")
            if ticker and row.get("cik") is not None:
                mapping[ticker] = f"{int(row['cik']):010d}"
        self._ticker_map = mapping
        return mapping

    def _cik(self, ticker: str) -> str | None:
        return self._mapping().get(ticker.upper().replace(".", "-"))

    def _archive_json(self, archive: zipfile.ZipFile | None, member: str) -> dict[str, Any] | None:
        if archive is None:
            return None
        try:
            return json.loads(archive.read(member))
        except (KeyError, json.JSONDecodeError):
            return None

    def _submissions(self, ticker: str) -> tuple[str | None, dict[str, Any] | None]:
        ticker = ticker.upper().replace(".", "-")
        if ticker in self._submissions_cache:
            return self._cik(ticker), self._submissions_cache[ticker]
        cik = self._cik(ticker)
        if cik is None:
            return None, None
        payload = self._archive_json(self.submissions_archive, f"CIK{cik}.json")
        if payload is None:
            path = self.cache_dir / f"submissions-CIK{cik}.json"
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
            else:
                payload = self._get(SUBMISSIONS_URL.format(cik=cik)).json()
                path.write_text(json.dumps(payload), encoding="utf-8")
        self._submissions_cache[ticker] = payload
        return cik, payload

    def _companyfacts(self, ticker: str) -> tuple[str | None, dict[str, Any] | None]:
        cik = self._cik(ticker)
        if cik is None:
            return None, None
        payload = self._archive_json(self.companyfacts_archive, f"CIK{cik}.json")
        if payload is not None:
            return cik, payload
        path = self.cache_dir / f"companyfacts-CIK{cik}.json"
        if path.exists():
            return cik, json.loads(path.read_text(encoding="utf-8"))
        payload = self._get(COMPANYFACTS_URL.format(cik=cik)).json()
        path.write_text(json.dumps(payload), encoding="utf-8")
        return cik, payload

    def _filings(self, ticker: str, *, forms: set[str], lookback_days: int, limit: int):
        cik, submissions = self._submissions(ticker)
        if cik is None or submissions is None:
            return []
        refs = index_submissions_payload(ticker, cik, submissions, allowed_forms=forms, limit=max(limit * 4, 80))
        cutoff = date.today() - timedelta(days=lookback_days)
        refs = [ref for ref in refs if ref.filing_date is None or ref.filing_date >= cutoff]
        refs.sort(key=lambda ref: (ref.filing_date or date.min, ref.accession), reverse=True)
        return refs[:limit]

    def _documents(self, ticker: str, *, forms: set[str], lookback_days: int, limit: int, max_exhibits: int) -> tuple[list[Any], list[str]]:
        cache_key = (ticker.upper(), lookback_days, limit, tuple(sorted(forms)))
        if cache_key in self._document_cache:
            return list(self._document_cache[cache_key]), []
        documents: list[Any] = []
        errors: list[str] = []
        for filing in reversed(self._filings(ticker, forms=forms, lookback_days=lookback_days, limit=limit)):
            try:
                refs = self.document_service.filing_documents(filing, max_exhibits=max_exhibits)
            except (httpx.HTTPError, ValueError, json.JSONDecodeError):
                refs = [filing]
            for ref in refs:
                try:
                    documents.append(self.document_service.fetch(ref, rules_hash=self.rules_hash))
                except (httpx.HTTPError, OSError, ValueError) as exc:
                    errors.append(f"DOC:{ref.accession}:{ref.primary_document}:{type(exc).__name__}")
        self._document_cache[cache_key] = list(documents)
        return documents, errors

    def assess_guidance(self, ticker: str) -> tuple[GuidanceAssessment | None, dict[str, Any], list[str]]:
        documents, errors = self._documents(
            ticker,
            forms=_GUIDANCE_FORMS,
            lookback_days=650,
            limit=32,
            max_exhibits=4,
        )
        records: list[GuidanceMetricRecord] = []
        policies: list[GuidancePolicyEvidence] = []
        for document in documents:
            extraction = extract_guidance_facts(document, rules_hash=self.rules_hash)
            records.extend(extraction.records)
            if extraction.policy_evidence is not None:
                policies.append(extraction.policy_evidence)
        records = _dedupe_guidance(records)
        ledger = GuidanceLedger(records)
        comparable_pairs = guidance_comparable_pair_count(ledger, ticker) if records else 0
        policy = max(policies, key=lambda item: item.source_timestamp) if policies else None
        assessment = ledger.assess(ticker, self.rules, rules_hash=self.rules_hash, policy=policy) if records or policy else None
        meta = {
            "records": len(records),
            "documents": len(documents),
            "comparable_pairs": comparable_pairs,
            "sufficient_comparable_guidance": comparable_pairs > 0,
            "classification": assessment.classification.value if assessment else "UNKNOWN",
            "guidance_deterioration": assessment.guidance_deterioration if assessment else None,
            "rule_path": assessment.rule_path if assessment else "guidance_v1_1.no_extracted_primary_guidance",
            "sources": assessment.sources if assessment else [],
            "reasons": assessment.reasons if assessment else ["No supported primary-source guidance fact extracted."],
        }
        return assessment, meta, errors

    def _distress_screen_refs(self, ticker: str, *, lookback_days: int = 500, max_event_filings: int = 16):
        refs = self._filings(ticker, forms=_DISTRESS_FORMS, lookback_days=lookback_days, limit=120)
        periodic = [ref for ref in refs if ref.form in {"10-K", "10-Q"} and ref.filing_date is not None]
        if not periodic:
            return []
        latest = max(periodic, key=lambda ref: (ref.filing_date or date.min, ref.accession))
        events = [
            ref for ref in refs
            if ref.form in {"8-K", "6-K"} and (ref.filing_date or date.min) > (latest.filing_date or date.min)
        ]
        events.sort(key=lambda ref: (ref.filing_date or date.min, ref.accession))
        return [latest, *events[:max_event_filings]]

    def assess_distress(
        self,
        instrument: Instrument,
        fundamental: FundamentalSnapshot | None,
    ) -> tuple[DistressAssessment | None, dict[str, Any], list[str]]:
        adapter = route_distress_sector(instrument)
        if adapter is None:
            return None, {
                "adapter": None,
                "sufficient_decision_evidence": False,
                "classification": "UNKNOWN",
                "balance_sheet_distressed": None,
                "rule_path": "balance_sheet_distress_v1_1.no_sector_adapter",
            }, []
        cik, companyfacts = self._companyfacts(instrument.ticker)
        if cik is None or companyfacts is None:
            return None, {
                "adapter": adapter.value,
                "sufficient_decision_evidence": False,
                "classification": "UNKNOWN",
                "balance_sheet_distressed": None,
                "rule_path": "balance_sheet_distress_v1_1.missing_companyfacts",
            }, ["COMPANYFACTS_UNAVAILABLE"]

        now = datetime.now(UTC)
        raw = normalize_distress_companyfacts(
            instrument.ticker,
            companyfacts,
            sector_adapter=adapter,
            fetched_at=now,
        )
        # Reuse captured SEC-derived FCF/runway only when the baseline fundamental
        # itself came from SEC. This is evidence reuse from the same shadow snapshot,
        # not a new estimate or favorable fill.
        if fundamental is not None and "SEC" in fundamental.source.upper():
            raw = raw.model_copy(
                update={
                    "trailing_fcf": fundamental.fcf,
                    "cash_runway_months": fundamental.cash_runway_months,
                    "financing_secured": fundamental.financing_secured,
                }
            )

        selected = self._distress_screen_refs(instrument.ticker)
        screened = []
        evidence: list[dict[str, Any]] = []
        failed: list[str] = []
        errors: list[str] = []
        for ref in selected:
            try:
                document = self.document_service.fetch(ref, rules_hash=self.rules_hash)
                screened.append(document)
                evidence.extend(extract_hard_distress_flags(document))
            except (httpx.HTTPError, OSError, ValueError) as exc:
                failed.append(ref.source_url)
                errors.append(f"HARD_SCREEN:{ref.accession}:{type(exc).__name__}")
        raw = finalize_hard_distress_screen(
            raw,
            screened_documents=screened,
            evidence=evidence,
            failed_document_urls=failed,
            required_document_count=len(selected),
        )
        inputs = derive_distress_inputs(raw)
        assessment = classify_distress(inputs, self.rules, rules_hash=self.rules_hash)
        sufficient, sufficient_reasons = nonfinancial_distress_decision_evidence(inputs, self.rules)
        meta = {
            "adapter": adapter.value,
            "hard_flag_screen_complete": inputs.hard_flag_screen_complete,
            "hard_distress_flags": [flag.value for flag in inputs.hard_distress_flags],
            "sufficient_decision_evidence": sufficient if adapter in {DistressSectorAdapter.CORPORATE, DistressSectorAdapter.UTILITY, DistressSectorAdapter.REIT} else False,
            "sufficient_evidence_reasons": sufficient_reasons,
            "classification": assessment.classification.value,
            "balance_sheet_distressed": assessment.balance_sheet_distressed,
            "rule_path": assessment.rule_path,
            "sources": assessment.sources,
            "reasons": assessment.reasons,
            "inputs": inputs.model_dump(mode="json"),
        }
        return assessment, meta, errors

    async def assess_earnings_catalysts(self, ticker: str, events: list[CorporateEvent]) -> tuple[dict[str, CatalystStructuralOverride], list[dict[str, Any]], list[str]]:
        target_events = [event for event in events if event.catalyst_candidate and event.type.upper() == "EARNINGS"]
        if not target_events:
            return {}, [], []
        documents, errors = self._documents(
            ticker,
            forms=_CATALYST_FORMS,
            lookback_days=500,
            limit=20,
            max_exhibits=4,
        )
        primary = None
        for document in reversed(documents):
            candidates = extract_sec_catalyst_candidates(document)
            earnings = [candidate for candidate in candidates if candidate.input.event_type == "quarterly_earnings"]
            if earnings:
                primary = earnings[-1]
                break
        if primary is None:
            return {}, [
                {
                    "event_key": catalyst_event_key(event),
                    "event_type": event.type,
                    "sufficient_primary_evidence": False,
                    "materiality": None,
                    "surprise_potential": None,
                    "missing_reason": "no_recent_primary_sec_earnings_evidence",
                }
                for event in target_events
            ], errors

        overrides: dict[str, CatalystStructuralOverride] = {}
        rows: list[dict[str, Any]] = []
        for event in target_events:
            key = catalyst_event_key(event)
            future_input = primary.input.model_copy(
                update={
                    "event_id": f"shadow:{key}",
                    "event_date": event.event_date,
                    # Do not assume an as-yet unknown future formal guidance action.
                    "formal_guidance_action": False,
                }
            )
            materiality = assess_materiality(future_input, self.rules, rules_hash=self.rules_hash)
            eps = revenue = None
            consensus_error = None
            try:
                eps, revenue = await self.consensus.get_consensus(ticker, event_type="quarterly_earnings")
            except Exception as exc:  # preserve provider failure as validation evidence
                consensus_error = f"CONSENSUS:{type(exc).__name__}:{exc}"
                errors.append(consensus_error)
            surprise = None
            if materiality.materiality is not None:
                surprise_input = CatalystSurpriseInput(
                    ticker=ticker,
                    event_id=f"shadow:{key}",
                    event_family=CatalystEventFamily.EARNINGS_GUIDANCE,
                    event_type="quarterly_earnings",
                    economic_exposure_score=materiality.economic_exposure_score,
                    catalyst_candidate=materiality.catalyst_candidate,
                    verified=True,
                    eps_consensus=eps,
                    revenue_consensus=revenue,
                    source=materiality.source,
                    source_url=materiality.source_url,
                    source_timestamp=materiality.source_timestamp,
                    extraction_method=materiality.extraction_method,
                    evidence_spans=materiality.evidence_spans,
                    structured_provenance={
                        **materiality.structured_provenance,
                        "future_event_source": event.source,
                        "future_event_source_url": event.source_url,
                        "future_event_date": event.event_date.isoformat(),
                    },
                )
                surprise = assess_surprise_potential(surprise_input, self.rules, rules_hash=self.rules_hash)
            materiality_value = materiality.materiality
            surprise_value = surprise.surprise_potential if surprise else None
            if materiality_value is not None or surprise_value is not None:
                overrides[key] = CatalystStructuralOverride(
                    materiality=materiality_value,
                    surprise_potential=surprise_value,
                    evidence_id=materiality.event_id,
                    reasons=tuple(materiality.reasons + (surprise.reasons if surprise else [])),
                )
            rows.append(
                {
                    "event_key": key,
                    "event_type": event.type,
                    "event_date": event.event_date.isoformat(),
                    "future_event_source": event.source,
                    "primary_evidence_source": materiality.source,
                    "primary_evidence_url": materiality.source_url,
                    "sufficient_primary_evidence": materiality.materiality_ready,
                    "materiality": materiality_value,
                    "economic_exposure_score": materiality.economic_exposure_score,
                    "surprise_potential": surprise_value,
                    "expectation_uncertainty": surprise.expectation_uncertainty if surprise else None,
                    "surprise_ready": surprise.surprise_ready if surprise else False,
                    "consensus_error": consensus_error,
                    "materiality_rule_path": materiality.rule_path,
                    "surprise_rule_path": surprise.rule_path if surprise else None,
                }
            )
        return overrides, rows, errors

    async def enrich(
        self,
        instrument: Instrument,
        fundamental: FundamentalSnapshot | None,
        events: list[CorporateEvent],
        *,
        need_guidance: bool,
        need_distress: bool,
        need_catalyst: bool,
    ) -> StructuralEnrichmentResult:
        result = StructuralEnrichmentResult(ticker=instrument.ticker)
        if need_guidance:
            assessment, meta, errors = self.assess_guidance(instrument.ticker)
            result.guidance = meta
            result.guidance_deterioration = assessment.guidance_deterioration if assessment else None
            result.errors.extend(errors)
        if need_distress:
            assessment, meta, errors = self.assess_distress(instrument, fundamental)
            result.distress = meta
            result.balance_sheet_distressed = assessment.balance_sheet_distressed if assessment else None
            result.errors.extend(errors)
        if need_catalyst:
            overrides, rows, errors = await self.assess_earnings_catalysts(instrument.ticker, events)
            result.catalyst_overrides = overrides
            result.catalysts = rows
            result.errors.extend(errors)
        return result
