from __future__ import annotations

import html
import json
import re
import statistics
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx

from app.domain.schemas import FieldProvenance, FundamentalSnapshot
from app.providers.errors import ProviderError
from app.providers.sec_edgar import COMPANYFACTS_URL, SecEdgarProvider
from app.services.cache_service import JsonFileCache


SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FILING_DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"

_CASH_CONCEPTS = (
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
)
_MARKETABLE_SECURITIES_CONCEPTS = (
    "ShortTermInvestments",
    "MarketableSecuritiesCurrent",
    "DebtSecuritiesAvailableForSaleCurrent",
    "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    "AvailableForSaleSecuritiesCurrent",
)
_CFO_CONCEPTS = ("NetCashProvidedByUsedInOperatingActivities",)
_FORMS_FINANCING_DOCUMENT = {"8-K", "8-K/A", "6-K", "6-K/A"}
_FORMS_CAPACITY_ONLY = {"S-3", "S-3/A", "S-3ASR", "F-3", "F-3/A", "F-3ASR", "424B3", "424B5"}
_FINANCE_ITEM_CODES = {"1.01", "2.03", "3.02", "8.01"}

_SECURED_PATTERNS = (
    re.compile(r"\b(?:completed|closed|consummated)\b.{0,240}\b(?:public offering|private placement|registered direct offering|offering|financing)\b", re.I | re.S),
    re.compile(r"\b(?:public offering|private placement|registered direct offering|offering|financing)\b.{0,240}\b(?:completed|closed|consummated)\b", re.I | re.S),
    re.compile(r"\breceived\b.{0,100}\b(?:net|gross)\s+proceeds\b", re.I | re.S),
    re.compile(r"\bnet proceeds\b.{0,120}\bwere approximately\b", re.I | re.S),
    re.compile(r"\bissued and sold\b.{0,220}\b(?:shares|securities)\b.{0,220}\b(?:gross|net) proceeds\b", re.I | re.S),
)
_CAPACITY_PATTERNS = (
    re.compile(r"\bat[- ]the[- ]market\b", re.I),
    re.compile(r"\bshelf registration\b", re.I),
    re.compile(r"\bprospectus supplement\b", re.I),
    re.compile(r"\bexpects? to close\b", re.I),
    re.compile(r"\bpricing of (?:its|the|an?) .{0,80}offering\b", re.I | re.S),
    re.compile(r"\bmay offer\b", re.I),
)
_PROCEEDS_PATTERN = re.compile(
    r"\b(?:aggregate\s+)?(?:net|gross)\s+proceeds\b[^$]{0,100}\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(million|billion)?",
    re.I | re.S,
)


def _duration_days(row: dict[str, Any]) -> int | None:
    if not row.get("start") or not row.get("end"):
        return None
    try:
        return (date.fromisoformat(str(row["end"])) - date.fromisoformat(str(row["start"]))).days
    except ValueError:
        return None


def _concept_rows(payload: dict[str, Any], concepts: tuple[str, ...], units: tuple[str, ...] = ("USD",)) -> tuple[list[dict[str, Any]], str | None]:
    facts = (payload.get("facts") or {}).get("us-gaap") or {}
    for concept in concepts:
        unit_map = (facts.get(concept) or {}).get("units") or {}
        for unit in units:
            rows = unit_map.get(unit)
            if rows:
                return list(rows), f"us-gaap:{concept}:{unit}"
    return [], None


def _latest_instant(payload: dict[str, Any], concepts: tuple[str, ...]) -> tuple[dict[str, Any] | None, str | None]:
    rows, concept = _concept_rows(payload, concepts)
    rows = [
        row for row in rows
        if row.get("end") and row.get("form") in {"10-Q", "10-Q/A", "10-K", "10-K/A"}
    ]
    if not rows:
        return None, concept
    return max(rows, key=lambda row: (str(row.get("end") or ""), str(row.get("filed") or ""))), concept


def _matching_instant(payload: dict[str, Any], concepts: tuple[str, ...], target_end: str) -> tuple[dict[str, Any] | None, str | None]:
    rows, concept = _concept_rows(payload, concepts)
    usable = [
        row for row in rows
        if row.get("end") and row.get("form") in {"10-Q", "10-Q/A", "10-K", "10-K/A"}
    ]
    exact = [row for row in usable if row.get("end") == target_end]
    if exact:
        return max(exact, key=lambda row: str(row.get("filed") or "")), concept
    try:
        target = date.fromisoformat(target_end)
    except ValueError:
        return None, concept
    nearby = []
    for row in usable:
        try:
            distance = abs((date.fromisoformat(str(row["end"])) - target).days)
        except ValueError:
            continue
        if distance <= 45:
            nearby.append((distance, row))
    if not nearby:
        return None, concept
    return min(nearby, key=lambda item: (item[0], -int(str(item[1].get("filed") or "0").replace("-", "") or 0)))[1], concept


def _pick(rows: list[dict[str, Any]], fp: str, minimum_days: int, maximum_days: int) -> dict[str, Any] | None:
    candidates = [
        row for row in rows
        if str(row.get("fp") or "").upper() == fp
        and (days := _duration_days(row)) is not None
        and minimum_days <= days <= maximum_days
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda row: (str(row.get("end") or ""), str(row.get("filed") or "")))


def _derived_quarter(source: dict[str, Any], value: float, label: str) -> dict[str, Any]:
    return {
        "start": source.get("start"),
        "end": source.get("end"),
        "filed": source.get("filed"),
        "form": source.get("form"),
        "fy": source.get("fy"),
        "fp": label,
        "val": value,
        "derived": True,
    }


def derive_operating_cashflow_quarters(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """Build discrete CFO quarters from SEC duration facts without mixing YTD and quarter values."""
    rows, concept = _concept_rows(payload, _CFO_CONCEPTS)
    rows = [
        row for row in rows
        if row.get("form") in {"10-Q", "10-Q/A", "10-K", "10-K/A"}
        and row.get("end")
        and (days := _duration_days(row)) is not None
        and 60 <= days <= 400
    ]
    by_fy: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        fy = str(row.get("fy") or str(row.get("end"))[:4])
        by_fy.setdefault(fy, []).append(row)

    quarters: list[dict[str, Any]] = []
    for fy_rows in by_fy.values():
        q1 = _pick(fy_rows, "Q1", 60, 120)
        q2_direct = _pick(fy_rows, "Q2", 60, 120)
        q2_ytd = _pick(fy_rows, "Q2", 140, 220)
        q3_direct = _pick(fy_rows, "Q3", 60, 120)
        q3_ytd = _pick(fy_rows, "Q3", 220, 310)
        annual = _pick(fy_rows, "FY", 300, 400)

        q2 = q2_direct
        if q2 is None and q2_ytd is not None and q1 is not None:
            q2 = _derived_quarter(q2_ytd, float(q2_ytd["val"]) - float(q1["val"]), "Q2")

        q3 = q3_direct
        if q3 is None and q3_ytd is not None:
            if q2_ytd is not None:
                q3 = _derived_quarter(q3_ytd, float(q3_ytd["val"]) - float(q2_ytd["val"]), "Q3")
            elif q1 is not None and q2 is not None:
                q3 = _derived_quarter(q3_ytd, float(q3_ytd["val"]) - float(q1["val"]) - float(q2["val"]), "Q3")

        q4 = None
        if annual is not None and q1 is not None and q2 is not None and q3 is not None:
            q4 = _derived_quarter(
                annual,
                float(annual["val"]) - float(q1["val"]) - float(q2["val"]) - float(q3["val"]),
                "Q4",
            )

        for row in (q1, q2, q3, q4):
            if row is not None:
                quarters.append(row)

    deduped: dict[str, dict[str, Any]] = {}
    for row in quarters:
        end = str(row.get("end") or "")
        if not end:
            continue
        existing = deduped.get(end)
        if existing is None or str(row.get("filed") or "") > str(existing.get("filed") or ""):
            deduped[end] = row
    return sorted(deduped.values(), key=lambda row: str(row["end"])), concept


def derive_biotech_runway(payload: dict[str, Any], fallback_cash: float | None = None) -> dict[str, Any]:
    """Derive conservative cash runway from reported liquidity and operating cash burn.

    The method uses cash plus one non-overlapping current marketable-securities
    concept and discrete SEC operating-cash-flow quarters. Positive operating
    inflows do not offset negative-quarter burn. The larger of the latest-quarter
    monthly burn and trailing negative-quarter burn rate is used so an accelerating
    burn cannot be diluted by older periods.
    """
    cash_row, cash_concept = _latest_instant(payload, _CASH_CONCEPTS)
    if cash_row is None:
        cash = fallback_cash
        target_end = None
    else:
        cash = float(cash_row["val"])
        target_end = str(cash_row["end"])

    investments_row, investments_concept = (None, None)
    if target_end:
        investments_row, investments_concept = _matching_instant(payload, _MARKETABLE_SECURITIES_CONCEPTS, target_end)
    investments = float(investments_row["val"]) if investments_row is not None else 0.0
    liquidity = None if cash is None else max(0.0, cash) + max(0.0, investments)

    quarters, cfo_concept = derive_operating_cashflow_quarters(payload)
    if target_end:
        quarters = [row for row in quarters if str(row.get("end") or "") <= target_end]
    trailing = quarters[-4:]
    if liquidity is None or len(trailing) < 2:
        return {
            "cash_runway_months": None,
            "status": "INSUFFICIENT_REPORTED_BURN_HISTORY" if liquidity is not None else "LIQUIDITY_UNAVAILABLE",
            "cash": cash,
            "marketable_securities": investments if investments_row is not None else None,
            "liquidity": liquidity,
            "cash_concept": cash_concept,
            "marketable_securities_concept": investments_concept,
            "cfo_concept": cfo_concept,
            "quarters_used": trailing,
        }

    values = [float(row["val"]) for row in trailing]
    months = 3 * len(values)
    trailing_negative_burn = sum(max(-value, 0.0) for value in values) / months
    latest_monthly_burn = max(-values[-1], 0.0) / 3
    conservative_monthly_burn = max(trailing_negative_burn, latest_monthly_burn)
    if conservative_monthly_burn <= 0:
        runway = None
        status = "NO_REPORTED_OPERATING_CASH_BURN"
    else:
        runway = liquidity / conservative_monthly_burn
        status = "DERIVED"

    return {
        "cash_runway_months": runway,
        "status": status,
        "cash": cash,
        "marketable_securities": investments if investments_row is not None else None,
        "liquidity": liquidity,
        "cash_concept": cash_concept,
        "marketable_securities_concept": investments_concept,
        "cfo_concept": cfo_concept,
        "quarters_used": trailing,
        "trailing_negative_monthly_burn": trailing_negative_burn,
        "latest_quarter_monthly_burn": latest_monthly_burn,
        "conservative_monthly_burn": conservative_monthly_burn,
        "method": "liquidity / max(latest-quarter burn, trailing negative-quarter burn)",
        "as_of": target_end,
    }


def normalize_recent_filings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    recent = ((payload.get("filings") or {}).get("recent")) or {}
    fields = (
        "accessionNumber",
        "filingDate",
        "reportDate",
        "acceptanceDateTime",
        "form",
        "primaryDocument",
        "primaryDocDescription",
        "items",
    )
    lengths = [len(recent.get(field) or []) for field in fields]
    total = max(lengths, default=0)
    rows: list[dict[str, Any]] = []
    for index in range(total):
        row: dict[str, Any] = {}
        for field in fields:
            values = recent.get(field) or []
            row[field] = values[index] if index < len(values) else None
        if row.get("accessionNumber") and row.get("filingDate") and row.get("form"):
            rows.append(row)
    return rows


def _plain_text(document: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", document)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_proceeds(text: str) -> float | None:
    match = _PROCEEDS_PATTERN.search(text)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    scale = (match.group(2) or "").lower()
    if scale == "million":
        value *= 1_000_000
    elif scale == "billion":
        value *= 1_000_000_000
    return value


def classify_financing_document(document: str) -> dict[str, Any]:
    text = _plain_text(document)
    secured_match = next((pattern.search(text) for pattern in _SECURED_PATTERNS if pattern.search(text)), None)
    if secured_match:
        return {
            "status": "COMPLETED_OR_CLOSED_FINANCING",
            "secured": True,
            "matched_text": secured_match.group(0)[:300],
            "proceeds": _extract_proceeds(text),
        }
    capacity_match = next((pattern.search(text) for pattern in _CAPACITY_PATTERNS if pattern.search(text)), None)
    if capacity_match:
        return {
            "status": "CAPACITY_OR_ANNOUNCED_FINANCING_NOT_CLOSED",
            "secured": False,
            "matched_text": capacity_match.group(0)[:300],
            "proceeds": _extract_proceeds(text),
        }
    return {"status": "NO_COMPLETED_FINANCING_LANGUAGE", "secured": False, "matched_text": None, "proceeds": None}


class SecBiotechIntelligenceProvider:
    """Free/public SEC specialization for biotech runway and post-period financing evidence."""

    name = "sec_biotech_intelligence"

    def __init__(
        self,
        *,
        sec: SecEdgarProvider,
        cache: JsonFileCache,
        submissions_zip_path: Path,
        user_agent: str,
        rules: dict[str, Any],
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.sec = sec
        self.cache = cache
        self.submissions_zip_path = submissions_zip_path
        self.user_agent = user_agent
        self.rules = rules
        self.transport = transport
        self._submissions_archive: zipfile.ZipFile | None = None

    async def _get_json(self, url: str, cache_key: str, ttl_seconds: int) -> tuple[dict[str, Any], datetime]:
        cached = self.cache.get_entry(cache_key)
        if cached:
            return cached.data, cached.created_at
        try:
            async with httpx.AsyncClient(
                timeout=self.rules["data_quality"]["provider"]["timeout_seconds"],
                transport=self.transport,
                headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            ) as client:
                response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
            fetched_at = datetime.now(UTC)
            self.cache.set(cache_key, payload, ttl_seconds, created_at=fetched_at)
            return payload, fetched_at
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(self.name, "SEC_BIOTECH_DATA_UNAVAILABLE", "SEC biotech intelligence request failed.", retryable=True, endpoint=url) from exc

    async def _get_text(self, url: str, cache_key: str, ttl_seconds: int) -> tuple[str, datetime]:
        cached = self.cache.get_entry(cache_key)
        if cached and isinstance(cached.data, str):
            return cached.data, cached.created_at
        try:
            async with httpx.AsyncClient(
                timeout=self.rules["data_quality"]["provider"]["timeout_seconds"],
                transport=self.transport,
                headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            ) as client:
                response = await client.get(url)
            response.raise_for_status()
            fetched_at = datetime.now(UTC)
            self.cache.set(cache_key, response.text, ttl_seconds, created_at=fetched_at)
            return response.text, fetched_at
        except httpx.HTTPError as exc:
            raise ProviderError(self.name, "SEC_FILING_DOCUMENT_UNAVAILABLE", "SEC filing document request failed.", retryable=True, endpoint=url) from exc

    async def _companyfacts(self, ticker: str) -> tuple[dict[str, Any], datetime, str]:
        cik = (await self.sec.ticker_map()).get(ticker.upper().replace(".", "-"))
        if not cik:
            raise ProviderError(self.name, "SEC_CIK_NOT_FOUND", "SEC CIK mapping unavailable for ticker.", retryable=False, ticker=ticker)
        if self.sec.zip_path.exists():
            try:
                with zipfile.ZipFile(self.sec.zip_path) as archive:
                    payload = json.loads(archive.read(f"CIK{cik}.json"))
                return payload, datetime.fromtimestamp(self.sec.zip_path.stat().st_mtime, UTC), cik
            except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
                raise ProviderError(self.name, "SEC_BULK_READ_ERROR", "SEC companyfacts bulk archive could not be read for biotech ticker.", retryable=False, ticker=ticker, endpoint=str(self.sec.zip_path)) from exc
        payload, fetched_at = await self._get_json(
            COMPANYFACTS_URL.format(cik=cik),
            f"sec-biotech-companyfacts:{cik}",
            self.rules["data_quality"]["cache_ttl_seconds"]["fundamentals"],
        )
        return payload, fetched_at, cik

    async def _submissions(self, ticker: str, cik: str) -> tuple[dict[str, Any], datetime]:
        if self.submissions_zip_path.exists():
            try:
                if self._submissions_archive is None:
                    self._submissions_archive = zipfile.ZipFile(self.submissions_zip_path)
                payload = json.loads(self._submissions_archive.read(f"CIK{cik}.json"))
                return payload, datetime.fromtimestamp(self.submissions_zip_path.stat().st_mtime, UTC)
            except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
                raise ProviderError(self.name, "SEC_SUBMISSIONS_BULK_READ_ERROR", "SEC submissions bulk archive could not be read for ticker.", retryable=False, ticker=ticker, endpoint=str(self.submissions_zip_path)) from exc
        return await self._get_json(
            SUBMISSIONS_URL.format(cik=cik),
            f"sec-submissions:{cik}",
            self.rules["data_quality"]["cache_ttl_seconds"]["calendar"],
        )

    async def assess_post_period_financing(self, ticker: str, cik: str, balance_sheet_date: date) -> tuple[bool | None, dict[str, Any], datetime]:
        payload, fetched_at = await self._submissions(ticker, cik)
        filings = []
        capacity_filings = []
        for row in normalize_recent_filings(payload):
            try:
                filing_date = date.fromisoformat(str(row["filingDate"]))
            except ValueError:
                continue
            if filing_date <= balance_sheet_date:
                continue
            form = str(row.get("form") or "").upper()
            if form in _FORMS_CAPACITY_ONLY:
                capacity_filings.append(row)
            if form in _FORMS_FINANCING_DOCUMENT:
                filings.append(row)

        filings.sort(key=lambda row: str(row.get("filingDate") or ""), reverse=True)
        inspected: list[dict[str, Any]] = []
        incomplete = False
        for row in filings[:12]:
            form = str(row.get("form") or "").upper()
            items = {part.strip() for part in str(row.get("items") or "").split(",") if part.strip()}
            description = str(row.get("primaryDocDescription") or "")
            likely_financing = form.startswith("6-K") or bool(items & _FINANCE_ITEM_CODES) or bool(re.search(r"offering|financ|securit|underwrit|placement|credit|loan", description, re.I))
            if not likely_financing:
                continue
            accession = str(row.get("accessionNumber") or "")
            document = str(row.get("primaryDocument") or "")
            if not accession or not document:
                incomplete = True
                inspected.append({"filing": row, "status": "PRIMARY_DOCUMENT_MISSING"})
                continue
            url = FILING_DOCUMENT_URL.format(cik=int(cik), accession=accession.replace("-", ""), document=document)
            try:
                text, document_at = await self._get_text(
                    url,
                    f"sec-filing-document:{accession}:{document}",
                    self.rules["data_quality"]["cache_ttl_seconds"]["calendar"],
                )
            except ProviderError:
                incomplete = True
                inspected.append({"filing": row, "status": "DOCUMENT_FETCH_FAILED", "url": url})
                continue
            classification = classify_financing_document(text)
            inspected.append({"filing": row, "url": url, "document_fetched_at": document_at.isoformat(), **classification})
            if classification["secured"] is True:
                return True, {
                    "status": "COMPLETED_FINANCING_AFTER_BALANCE_SHEET",
                    "balance_sheet_date": balance_sheet_date.isoformat(),
                    "matched_filing": inspected[-1],
                    "capacity_filings": capacity_filings,
                    "search_complete": not incomplete,
                }, fetched_at

        secured: bool | None = None if incomplete else False
        status = "FINANCING_SEARCH_INCOMPLETE" if incomplete else "NO_COMPLETED_FINANCING_AFTER_BALANCE_SHEET"
        return secured, {
            "status": status,
            "balance_sheet_date": balance_sheet_date.isoformat(),
            "inspected_filings": inspected,
            "capacity_filings": capacity_filings,
            "search_complete": not incomplete,
        }, fetched_at

    async def enrich_fundamental(self, ticker: str, fundamental: FundamentalSnapshot) -> FundamentalSnapshot:
        payload, companyfacts_at, cik = await self._companyfacts(ticker)
        runway = derive_biotech_runway(payload, fallback_cash=fundamental.cash)
        raw = dict(fundamental.raw)
        raw["biotech_runway"] = runway
        updates: dict[str, Any] = {"raw": raw}
        provenance = dict(fundamental.field_provenance)

        runway_value = runway.get("cash_runway_months")
        runway_as_of = fundamental.as_of
        if runway.get("as_of"):
            try:
                runway_as_of = datetime.combine(date.fromisoformat(str(runway["as_of"])), datetime.min.time(), tzinfo=UTC)
            except ValueError:
                pass
        if runway_value is not None:
            updates["cash_runway_months"] = float(runway_value)
            provenance["cash_runway_months"] = FieldProvenance(
                source="SEC EDGAR companyfacts biotech runway",
                as_of=runway_as_of,
                fetched_at=companyfacts_at,
                stale=fundamental.stale,
                raw_field=f"{runway.get('cash_concept')} + {runway.get('marketable_securities_concept')} / {runway.get('cfo_concept')}",
            )

        try:
            financing, financing_raw, financing_at = await self.assess_post_period_financing(ticker, cik, runway_as_of.date())
        except ProviderError as exc:
            financing, financing_at = None, datetime.now(UTC)
            financing_raw = {"status": "SEC_FINANCING_DATA_UNAVAILABLE", "error": exc.as_dict(), "balance_sheet_date": runway_as_of.date().isoformat()}
        raw["biotech_financing"] = financing_raw
        updates["raw"] = raw
        updates["financing_secured"] = financing
        provenance["financing_secured"] = FieldProvenance(
            source="SEC EDGAR submissions + filing documents",
            as_of=datetime.now(UTC),
            fetched_at=financing_at,
            stale=False,
            raw_field="filings.recent + primaryDocument",
        )
        updates["field_provenance"] = provenance
        updates["fetched_at"] = max(fundamental.fetched_at, companyfacts_at, financing_at)
        return fundamental.model_copy(update=updates)
