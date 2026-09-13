from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def _regex_once(text: str, pattern: str, replacement: str, *, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex anchor, found {count}")
    return updated


def patch_source_document_service() -> None:
    path = "backend/app/services/source_document_service.py"
    text = _read(path)
    if "def complete_submission_text_reference(" in text:
        return
    anchor = '''def filing_index_json_url(cik: str | int, accession: str) -> str:\n    return sec_archive_url(cik, accession, "index.json")\n'''
    addition = anchor + '''\n\ndef complete_submission_text_reference(filing: SecDocumentReference) -> SecDocumentReference:\n    """Return the official complete-submission text as an index-failure fallback.\n\n    This is used only when SEC filing-directory discovery fails. It preserves the\n    issuer filing date/accession and exposes all embedded exhibits without guessing\n    an issuer-specific filename.\n    """\n    name = f"{filing.accession}.txt"\n    return SecDocumentReference(\n        ticker=filing.ticker,\n        cik=filing.cik,\n        accession=filing.accession,\n        form=filing.form,\n        filing_date=filing.filing_date,\n        primary_document=name,\n        source_url=sec_archive_url(filing.cik, filing.accession, name),\n    )\n'''
    text = _replace_once(text, anchor, addition, label="source-document fallback")
    _write(path, text)


def patch_shadow_enrichment() -> None:
    path = "backend/app/services/shadow_enrichment_service.py"
    text = _read(path)

    text = _replace_once(
        text,
        "from app.domain.soe_v1_1 import GuidanceAssessment, GuidanceMetricRecord, GuidancePolicyEvidence\n",
        "from app.domain.soe_v1_1 import GuidanceAssessment\n",
        label="shadow domain imports",
    )
    text = _replace_once(
        text,
        "from app.services.fact_extraction_service import extract_guidance_facts\nfrom app.services.guidance_ledger_service import GuidanceLedger\n",
        "from app.services.canonical_shadow_guidance_service import (\n"
        "    assess_canonical_guidance_documents,\n"
        "    guidance_comparable_pair_count,\n"
        ")\n",
        label="shadow canonical imports",
    )
    text = _replace_once(
        text,
        "from app.services.source_document_service import SourceDocumentService, index_submissions_payload\n",
        "from app.services.source_document_service import (\n"
        "    SourceDocumentService,\n"
        "    complete_submission_text_reference,\n"
        "    index_submissions_payload,\n"
        ")\n",
        label="shadow source imports",
    )

    text = _regex_once(
        text,
        r"def _guidance_record_key\(.*?\n\ndef nonfinancial_distress_decision_evidence",
        "def nonfinancial_distress_decision_evidence",
        label="remove legacy numeric guidance helpers",
    )

    text = _replace_once(
        text,
        "        self._document_cache: dict[tuple[str, int, int, tuple[str, ...]], list[Any]] = {}\n",
        "        self._document_cache: dict[tuple[str, int, int, tuple[str, ...]], list[Any]] = {}\n"
        "        self._document_error_cache: dict[tuple[str, int, int, tuple[str, ...]], list[str]] = {}\n",
        label="document error cache",
    )

    documents_block = '''    def _documents(self, ticker: str, *, forms: set[str], lookback_days: int, limit: int, max_exhibits: int) -> tuple[list[Any], list[str]]:\n        cache_key = (ticker.upper(), lookback_days, limit, tuple(sorted(forms)))\n        if cache_key in self._document_cache:\n            return list(self._document_cache[cache_key]), list(self._document_error_cache.get(cache_key, []))\n        documents: list[Any] = []\n        errors: list[str] = []\n        for filing in reversed(self._filings(ticker, forms=forms, lookback_days=lookback_days, limit=limit)):\n            try:\n                refs = self.document_service.filing_documents(filing, max_exhibits=max_exhibits)\n            except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:\n                errors.append(f"INDEX:{filing.accession}:{type(exc).__name__}")\n                refs = [filing]\n                if filing.form in {"8-K", "6-K"}:\n                    refs.append(complete_submission_text_reference(filing))\n            seen_urls: set[str] = set()\n            for ref in refs:\n                if ref.source_url in seen_urls:\n                    continue\n                seen_urls.add(ref.source_url)\n                try:\n                    documents.append(self.document_service.fetch(ref, rules_hash=self.rules_hash))\n                except (httpx.HTTPError, OSError, ValueError) as exc:\n                    errors.append(f"DOC:{ref.accession}:{ref.primary_document}:{type(exc).__name__}")\n        self._document_cache[cache_key] = list(documents)\n        self._document_error_cache[cache_key] = list(errors)\n        return documents, errors\n\n'''
    text = _regex_once(
        text,
        r"    def _documents\(.*?\n\n    def assess_guidance",
        documents_block + "    def assess_guidance",
        label="observable SEC document fallback",
    )

    guidance_block = '''    def assess_guidance(self, ticker: str) -> tuple[GuidanceAssessment | None, dict[str, Any], list[str]]:\n        documents, errors = self._documents(\n            ticker,\n            forms=_GUIDANCE_FORMS,\n            lookback_days=650,\n            limit=32,\n            max_exhibits=4,\n        )\n        assessment, meta, extraction_errors = assess_canonical_guidance_documents(\n            ticker,\n            documents,\n            self.rules,\n            rules_hash=self.rules_hash,\n        )\n        errors.extend(extraction_errors)\n        return assessment, meta, errors\n\n'''
    text = _regex_once(
        text,
        r"    def assess_guidance\(.*?\n\n    def _distress_screen_refs",
        guidance_block + "    def _distress_screen_refs",
        label="canonical full-market guidance path",
    )

    _write(path, text)


def patch_raw_replay_manifest() -> None:
    path = "backend/app/services/guidance_raw_replay_differential_service.py"
    text = _read(path)
    replacement = '''def build_raw_replay_manifest(validation: dict[str, Any]) -> list[RawReplaySource]:\n    """Build the immutable SEC replay manifest from canonical evidence sources.\n\n    New Phase-1.1E artifacts carry `source_documents`, which is authoritative\n    because it includes every document that produced a raw typed guidance fact,\n    including facts later quarantined. Older artifacts fall back to legacy ledger\n    rows so historical acceptance bundles remain replayable.\n    """\n    by_url: dict[str, RawReplaySource] = {}\n    conflicts: list[str] = []\n\n    for ticker, payload in _guidance_payloads(validation):\n        source_rows = list(payload.get("source_documents") or [])\n        rows = source_rows if source_rows else list(payload.get("ledger_records") or [])\n        for record in rows:\n            url = str(record.get("source_url") or "").strip()\n            expected_hash = str(record.get("source_document_hash") or "").strip().lower()\n            timestamp_raw = record.get("source_timestamp")\n            if not url or not expected_hash or not timestamp_raw:\n                continue\n            match = _SEC_URL.match(url)\n            if match is None:\n                conflicts.append(f"Non-SEC archive source in guidance evidence: {url}")\n                continue\n            timestamp = datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00"))\n            source = RawReplaySource(\n                ticker=ticker,\n                source_url=url,\n                source_document_hash=expected_hash,\n                source_accession=record.get("source_accession"),\n                source_timestamp=timestamp,\n                cik=match.group("cik").zfill(10),\n            )\n            existing = by_url.get(url)\n            if existing is not None and existing != source:\n                conflicts.append(f"Conflicting immutable source metadata for {url}")\n                continue\n            by_url[url] = source\n\n    if conflicts:\n        raise ValueError("; ".join(sorted(set(conflicts))))\n    return sorted(by_url.values(), key=lambda item: (item.ticker, item.source_timestamp, item.source_url))\n'''
    text = _regex_once(
        text,
        r"def build_raw_replay_manifest\(validation: dict\[str, Any\]\) -> list\[RawReplaySource\]:.*?return sorted\(by_url.values\(\), key=lambda item: \(item.ticker, item.source_timestamp, item.source_url\)\)\n",
        replacement,
        label="canonical replay manifest",
    )
    _write(path, text)


def patch_pending_guidance_review() -> None:
    path = "backend/app/services/guidance_raw_canonical_extractor.py"
    text = _read(path)
    if "def _pending_guidance_review(" not in text:
        helper = '''\n_PENDING_GUIDANCE_REVIEW = re.compile(\n    r"(?:\\b(?:reviewing|reassessing|evaluating)\\b.{0,260}\\b(?:guidance|outlook)\\b.{0,260}\\b(?:will|expects?\\s+to)\\s+(?:provide|issue|announce|give)\\b.{0,100}\\bupdate\\b"\n    r"|\\b(?:guidance|outlook)\\b.{0,180}\\bunder\\s+review\\b.{0,220}\\bupdate\\b)",\n    re.I | re.S,\n)\n\n\ndef _pending_guidance_review(clause: str) -> bool:\n    """Identify an explicit pending-review state without treating prior bounds as current.\n\n    The issuer has not withdrawn guidance, but the prior quantitative range is no\n    longer a clean current reaffirmation. Emit a qualitative current observation\n    at the new source timestamp so canonical assessment cannot fall back through\n    the unresolved update to an older numeric snapshot.\n    """\n    return bool(_PENDING_GUIDANCE_REVIEW.search(clause))\n\n'''
        text = _replace_once(text, "\ndef _build_fact(", helper + "def _build_fact(", label="pending-review helper")

    text = _replace_once(
        text,
        "            previous_now_value, previous_now_prior = _previous_now_value_pair(clause, mention)\n",
        "            pending_review = _pending_guidance_review(clause)\n"
        "            previous_now_value, previous_now_prior = _previous_now_value_pair(clause, mention)\n",
        label="pending-review detection",
    )
    text = _replace_once(
        text,
        "            value = _normalize_margin_level(clause, anchor, mention, value)\n            explicit_prior = previous_now_prior or directional_prior\n",
        "            value = _normalize_margin_level(clause, anchor, mention, value)\n"
        "            explicit_prior = previous_now_prior or directional_prior\n"
        "            if pending_review:\n"
        "                value = None\n"
        "                explicit_prior = None\n",
        label="pending-review qualitative value",
    )
    text = _replace_once(
        text,
        "            role = GuidanceFactRole.CURRENT if previous_now_value is not None else _fact_role(clause, value)\n",
        "            role = GuidanceFactRole.CURRENT if pending_review or previous_now_value is not None else _fact_role(clause, value)\n",
        label="pending-review current role",
    )
    text = _replace_once(
        text,
        "            if value is None and local_action not in {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM, GuidanceAction.WITHDRAW}:\n",
        "            if value is None and not pending_review and local_action not in {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM, GuidanceAction.WITHDRAW}:\n",
        label="pending-review qualitative allowance",
    )
    _write(path, text)


def main() -> None:
    patch_source_document_service()
    patch_shadow_enrichment()
    patch_raw_replay_manifest()
    patch_pending_guidance_review()
    print("Applied Phase 1.1E canonical shadow integration patch.")


if __name__ == "__main__":
    main()
