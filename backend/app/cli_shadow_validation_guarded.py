from __future__ import annotations

from typing import Any

from app import cli_shadow_validation
from app.domain.soe_v1_1 import GuidanceMetric
from app.services import fact_extraction_service, shadow_enrichment_service
from app.services.guidance_binding_patch_v1_1 import install_binding_patch
from app.services.phase_1_1e_catalyst_evidence_round5_v1_1 import (
    extract_sec_catalyst_candidates_round5,
)
from app.services.phase_1_1e_evidence_hygiene_round3_patch_v1_1 import (
    extract_hard_distress_flags_round3,
)
from app.services.phase_1_1e_guidance_actual_guard_round6_v1_1 import (
    dedupe_guidance_records_round6,
    extract_guidance_facts_round6,
)


_original_numeric_range = fact_extraction_service._numeric_range
_original_index_submissions_payload = shadow_enrichment_service.index_submissions_payload
_original_enrich = shadow_enrichment_service.ShadowStructuralEnricher.enrich
_malformed_sec_rows: dict[str, list[str]] = {}
_guards_installed = False


def _guard_numeric_range(
    text: str,
    metric: GuidanceMetric,
    *,
    anchor: int,
) -> tuple[float, float, str] | None:
    """Reject structurally invalid guidance ranges instead of aborting 1.1E.

    Phase 1.1E is a shadow-validation/orchestration run. If deterministic text
    extraction produces low > high, the source fact is ambiguous and must remain
    unknown. Reordering the values would manufacture a fact, while allowing the
    Pydantic validation error to escape would terminate the full-market run.
    """
    result = _original_numeric_range(text, metric, anchor=anchor)
    if result is None:
        return None
    low, high, unit = result
    if low > high:
        return None
    return low, high, unit


def _safe_index_submissions_payload(
    ticker: str,
    cik: str | int,
    payload: dict,
    *,
    allowed_forms: set[str] | None = None,
    limit: int = 24,
):
    """Skip malformed SEC recent-filing rows only for the 1.1E validation run.

    SEC bulk submissions occasionally contain an allowed filing row whose
    accession/document pair cannot form a valid SEC archive URL. Such a row is
    missing/invalid evidence, not a reason to terminate the full-market shadow
    run. The row is removed without substitution and is recorded as an
    enrichment error so coverage is not silently overstated.
    """
    recent = ((payload.get("filings") or {}).get("recent") or {})
    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    primary_documents = recent.get("primaryDocument") or []
    filing_dates = recent.get("filingDate") or []
    allowed = allowed_forms or {"10-K", "10-Q", "8-K", "6-K"}

    clean_forms: list[Any] = []
    clean_accessions: list[Any] = []
    clean_primary: list[Any] = []
    clean_dates: list[Any] = []

    for idx, form in enumerate(forms):
        if idx >= len(accessions) or idx >= len(primary_documents):
            continue
        accession = accessions[idx]
        primary = primary_documents[idx]
        accession_compact = str(accession or "").replace("-", "")
        primary_text = str(primary or "").strip()
        if form in allowed and (not accession_compact.isdigit() or not primary_text):
            error = f"SEC_SUBMISSION_ROW_INVALID:{form}:{accession}:{primary}"
            _malformed_sec_rows.setdefault(ticker.upper(), []).append(error)
            print(f"[1.1E sec-row-skip] ticker={ticker.upper()} error={error}", flush=True)
            continue
        clean_forms.append(form)
        clean_accessions.append(accession)
        clean_primary.append(primary)
        clean_dates.append(filing_dates[idx] if idx < len(filing_dates) else None)

    sanitized = dict(payload)
    filings = dict(payload.get("filings") or {})
    filings["recent"] = {
        "form": clean_forms,
        "accessionNumber": clean_accessions,
        "primaryDocument": clean_primary,
        "filingDate": clean_dates,
    }
    sanitized["filings"] = filings
    return _original_index_submissions_payload(
        ticker,
        cik,
        sanitized,
        allowed_forms=allowed_forms,
        limit=limit,
    )


def consume_sec_row_errors(ticker: str) -> list[str]:
    """Return and clear malformed-row errors accumulated for one ticker."""
    return _malformed_sec_rows.pop(ticker.upper(), [])


async def _guarded_enrich(
    self,
    instrument,
    fundamental,
    events,
    *,
    need_guidance: bool,
    need_distress: bool,
    need_catalyst: bool,
):
    result = await _original_enrich(
        self,
        instrument,
        fundamental,
        events,
        need_guidance=need_guidance,
        need_distress=need_distress,
        need_catalyst=need_catalyst,
    )
    result.errors.extend(consume_sec_row_errors(instrument.ticker))
    return result


def install_guards() -> None:
    """Install fail-closed data guards for Phase 1.1E orchestration only."""
    global _guards_installed
    if _guards_installed:
        return
    install_binding_patch()
    fact_extraction_service._numeric_range = _guard_numeric_range
    shadow_enrichment_service.index_submissions_payload = _safe_index_submissions_payload
    shadow_enrichment_service.extract_guidance_facts = extract_guidance_facts_round6
    shadow_enrichment_service._dedupe_guidance = dedupe_guidance_records_round6
    shadow_enrichment_service.extract_hard_distress_flags = extract_hard_distress_flags_round3
    shadow_enrichment_service.extract_sec_catalyst_candidates = extract_sec_catalyst_candidates_round5
    shadow_enrichment_service.ShadowStructuralEnricher.enrich = _guarded_enrich
    _guards_installed = True


def main() -> int:
    install_guards()
    return cli_shadow_validation.main()


if __name__ == "__main__":
    raise SystemExit(main())
