from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.domain.soe_v1_1 import SecDocumentReference, SourceDocument


SEC_ARCHIVE_ROOT = "https://www.sec.gov/Archives/edgar/data"
_EXHIBIT_HINT = re.compile(r"(?:^|[-_])(ex(?:hibit)?[-_]?99|ex99|99[._-]?1|earn|release|press)", re.I)
_XBRL_NOISE = re.compile(
    r"^(?:r\d+\.htm|filingsummary|metalink|financial_report|calculation|definition|label|presentation|schema|instance)",
    re.I,
)


def normalize_cik(cik: str | int) -> str:
    digits = re.sub(r"\D", "", str(cik))
    if not digits:
        raise ValueError("CIK must contain digits")
    return digits.zfill(10)


def sec_archive_url(cik: str | int, accession: str, document: str) -> str:
    cik_digits = str(int(normalize_cik(cik)))
    accession_compact = accession.replace("-", "")
    safe_document = document.strip().lstrip("/")
    if not accession_compact.isdigit() or not safe_document:
        raise ValueError("Invalid SEC accession or document")
    return f"{SEC_ARCHIVE_ROOT}/{cik_digits}/{accession_compact}/{safe_document}"


def filing_index_json_url(cik: str | int, accession: str) -> str:
    return sec_archive_url(cik, accession, "index.json")


def index_submissions_payload(
    ticker: str,
    cik: str | int,
    payload: dict,
    *,
    allowed_forms: set[str] | None = None,
    limit: int = 24,
) -> list[SecDocumentReference]:
    allowed_forms = allowed_forms or {"10-K", "10-Q", "8-K", "6-K"}
    recent = ((payload.get("filings") or {}).get("recent") or {})
    forms = recent.get("form") or []
    accessions = recent.get("accessionNumber") or []
    primary_documents = recent.get("primaryDocument") or []
    filing_dates = recent.get("filingDate") or []
    refs: list[SecDocumentReference] = []
    for idx, form in enumerate(forms):
        if form not in allowed_forms or idx >= len(accessions) or idx >= len(primary_documents):
            continue
        filing_date = None
        if idx < len(filing_dates) and filing_dates[idx]:
            try:
                filing_date = datetime.fromisoformat(filing_dates[idx]).date()
            except ValueError:
                filing_date = None
        accession = accessions[idx]
        primary = primary_documents[idx]
        refs.append(
            SecDocumentReference(
                ticker=ticker.upper(),
                cik=normalize_cik(cik),
                accession=accession,
                form=form,
                filing_date=filing_date,
                primary_document=primary,
                source_url=sec_archive_url(cik, accession, primary),
            )
        )
        if len(refs) >= limit:
            break
    return refs


class SourceDocumentService:
    """Targeted primary-document fetch/cache service for gated SOE-1.1 names."""

    def __init__(
        self,
        *,
        cache_dir: str | Path,
        user_agent: str,
        timeout_seconds: float = 20.0,
        min_request_interval_seconds: float = 0.15,
        client: httpx.Client | None = None,
    ):
        if "@" not in user_agent and "mailto:" not in user_agent.lower():
            raise ValueError("SEC automated access requires a declared contact in the User-Agent")
        if min_request_interval_seconds < 0.10:
            raise ValueError("SEC request interval must remain at or above 0.10 seconds")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent
        self.min_request_interval_seconds = min_request_interval_seconds
        self._last_request_at = 0.0
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout_seconds,
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            follow_redirects=True,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _request(self, url: str) -> httpx.Response:
        elapsed = time.monotonic() - self._last_request_at
        wait = self.min_request_interval_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        response = self.client.get(url)
        self._last_request_at = time.monotonic()
        return response

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {"www.sec.gov", "sec.gov"}:
            raise ValueError("SourceDocumentService only fetches official SEC archive URLs")
        if not parsed.path.startswith("/Archives/edgar/data/"):
            raise ValueError("Only SEC EDGAR archive document paths are allowed")

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.txt", self.cache_dir / f"{key}.json"

    def _cached_json(self, url: str, *, force: bool = False) -> dict:
        self._validate_url(url)
        key = hashlib.sha256(("json|" + url).encode("utf-8")).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if not force and path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        response = self._request(url)
        response.raise_for_status()
        payload = response.json()
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return payload

    @staticmethod
    def _candidate_priority(item: dict, *, form: str, primary_name: str) -> tuple[int, int, str] | None:
        name = str(item.get("name") or "").strip()
        lower = name.lower()
        if not lower.endswith((".htm", ".html")) or lower == primary_name:
            return None
        if _XBRL_NOISE.search(lower):
            return None
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        if _EXHIBIT_HINT.search(lower):
            return (0, -size, lower)
        # 8-K/6-K exhibits are often named with issuer-specific abbreviations
        # rather than ex99/earnings keywords. Strict guidance extraction makes
        # a bounded generic HTML fallback safe; do not apply it to 10-K/10-Q.
        if form in {"8-K", "6-K"} and 1_000 <= size <= 2_500_000:
            return (1, -size, lower)
        return None

    def filing_documents(
        self,
        filing: SecDocumentReference,
        *,
        max_exhibits: int = 4,
        force: bool = False,
    ) -> list[SecDocumentReference]:
        """Return primary filing plus bounded likely earnings/guidance exhibits.

        Strong filename hints rank first. For 8-K/6-K only, a small generic HTML
        fallback catches issuer-specific exhibit filenames that omit ex99/earnings
        tokens. XBRL rendering files are excluded. Returned files remain evidence
        candidates only; they are not classified as guidance by discovery alone.
        """
        payload = self._cached_json(filing_index_json_url(filing.cik, filing.accession), force=force)
        items = ((payload.get("directory") or {}).get("item") or [])
        primary_name = filing.primary_document.lower()
        ranked: list[tuple[tuple[int, int, str], str]] = []
        for item in items:
            priority = self._candidate_priority(item, form=filing.form, primary_name=primary_name)
            if priority is None:
                continue
            ranked.append((priority, str(item.get("name") or "").strip()))
        ranked.sort(key=lambda value: value[0])
        candidates: list[str] = []
        seen: set[str] = set()
        for _, name in ranked:
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            candidates.append(name)
            if len(candidates) >= max_exhibits:
                break

        refs = [filing]
        for name in candidates:
            refs.append(
                SecDocumentReference(
                    ticker=filing.ticker,
                    cik=filing.cik,
                    accession=filing.accession,
                    form=filing.form,
                    filing_date=filing.filing_date,
                    primary_document=name,
                    source_url=sec_archive_url(filing.cik, filing.accession, name),
                )
            )
        return refs

    def fetch(self, ref: SecDocumentReference, *, rules_hash: str, force: bool = False) -> SourceDocument:
        self._validate_url(ref.source_url)
        content_path, meta_path = self._paths(ref.source_url)
        fetched_at = datetime.now(UTC)
        if not force and content_path.exists() and meta_path.exists():
            content = content_path.read_text(encoding="utf-8", errors="replace")
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            return SourceDocument(
                document_id=meta["document_id"],
                rules_hash=rules_hash,
                ticker=ref.ticker,
                cik=ref.cik,
                accession=ref.accession,
                form=ref.form,
                filing_date=ref.filing_date,
                source_url=ref.source_url,
                source_timestamp=datetime.fromisoformat(meta["source_timestamp"]),
                fetched_at=datetime.fromisoformat(meta["fetched_at"]),
                content_hash=meta["content_hash"],
                cache_path=str(content_path),
                content_type=meta.get("content_type"),
                content=content,
            )

        response = self._request(ref.source_url)
        response.raise_for_status()
        content = response.text
        content_hash = hashlib.sha256(response.content).hexdigest()
        source_timestamp = (
            datetime.combine(ref.filing_date, datetime.min.time(), tzinfo=UTC)
            if ref.filing_date
            else fetched_at
        )
        document_id = hashlib.sha256(
            f"{ref.cik}|{ref.accession}|{ref.primary_document}|{content_hash}".encode("utf-8")
        ).hexdigest()
        content_path.write_text(content, encoding="utf-8")
        meta = {
            "document_id": document_id,
            "content_hash": content_hash,
            "source_timestamp": source_timestamp.isoformat(),
            "fetched_at": fetched_at.isoformat(),
            "content_type": response.headers.get("content-type"),
            "source_url": ref.source_url,
        }
        meta_path.write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
        return SourceDocument(
            document_id=document_id,
            rules_hash=rules_hash,
            ticker=ref.ticker,
            cik=ref.cik,
            accession=ref.accession,
            form=ref.form,
            filing_date=ref.filing_date,
            source_url=ref.source_url,
            source_timestamp=source_timestamp,
            fetched_at=fetched_at,
            content_hash=content_hash,
            cache_path=str(content_path),
            content_type=response.headers.get("content-type"),
            content=content,
        )