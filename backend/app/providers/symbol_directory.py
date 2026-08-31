from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO

import httpx

from app.domain.enums import AssetType
from app.providers.errors import ProviderError
from app.services.cache_service import JsonFileCache


NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


@dataclass(frozen=True)
class ListedSecurity:
    ticker: str
    provider_symbol: str
    company_name: str
    exchange: str
    asset_type: AssetType
    active: bool
    source: str
    as_of: datetime
    fetched_at: datetime


def _asset_type(name: str, is_etf: bool) -> AssetType:
    upper = name.upper()
    if is_etf:
        return AssetType.ETF
    if any(token in upper for token in (" WARRANT", " WT EXP", "- WARRANT")):
        return AssetType.WARRANT
    if any(token in upper for token in (" RIGHT", " RIGHTS")):
        return AssetType.RIGHT
    preferred_terms = ("PREFERRED STOCK", "PREFERRED SHARE", "PREFERRED SECURIT", "PREFERENCE SHARE", "PREFERENCE UNIT", "TRUST PREFERENCE", " PFD ", " PFD SH", " PFD SER")
    generic_preferred = ("PREFERRED" in upper or "PREFERENCE" in upper) and "PREFERRED BANK COMMON STOCK" not in upper
    unlabeled_series = "%" in upper and re.search(r"\bSERIES\s+[A-Z0-9]\b", upper)
    if generic_preferred or unlabeled_series or any(token in upper for token in preferred_terms) or ("LIQUIDATION PREFERENCE" in upper and "CUMULATIVE" in upper):
        return AssetType.PREFERRED
    if any(token in upper for token in ("DEPOSITARY SHARES", "DEPOSITARY SH ", "DEPOSITARY SHARE ", " DEP SHS ")) and "AMERICAN DEPOSITARY" not in upper:
        return AssetType.PREFERRED
    if any(token in upper for token in ("SENIOR NOTES", "SUBORDINATED NOTES", "SUBORDINATED DEBENTURES", "MORTGAGE BONDS", " NOTES DUE", " BONDS DUE")) or (" NOTES" in upper and " DUE" in upper):
        return AssetType.DEBT_SECURITY
    if upper.startswith("SCE TRUST "):
        return AssetType.PREFERRED
    if any(token in upper for token in (" EXCHANGE TRADED NOTE", " ETN DUE")):
        return AssetType.ETN
    if any(token in upper for token in ("CLOSED-END", "CLOSED END FUND", " FUND INC.", " FUND, INC.", " FUND COMMON SHARES", " FUND COMMON STOCK")):
        return AssetType.CEF
    if "LIMITED PARTNER" in upper or "LIMITED PARTNERSHIP" in upper:
        return AssetType.UNIT
    if "AMERICAN DEPOSITARY" in upper or " DEPOSITARY RECEIPT" in upper or " ADS " in upper:
        return AssetType.ADR
    if any(token in upper for token in ("COMMON UNITS", "LIMITED PARTNERSHIP UNITS", "CORPORATE UNITS", "TANGIBLE EQUITY UNIT")):
        return AssetType.UNIT
    if re.search(r"\bUNITS?\b", upper):
        return AssetType.UNIT
    if "SHELL COMPANY" in upper:
        return AssetType.SHELL
    if "ACQUISITION CORP" in upper or "BLANK CHECK" in upper:
        return AssetType.SPAC
    return AssetType.COMMON_STOCK


def _rows(text: str) -> list[dict[str, str]]:
    lines = [line for line in StringIO(text).read().splitlines() if line and not line.startswith("File Creation Time")]
    if len(lines) < 2:
        raise ValueError("Symbol directory was empty")
    headers = lines[0].split("|")
    return [dict(zip(headers, line.split("|"), strict=False)) for line in lines[1:] if "|" in line]


def normalize_symbol_directories(nasdaq_text: str, other_text: str, *, fetched_at: datetime) -> list[ListedSecurity]:
    securities: dict[str, ListedSecurity] = {}
    for row in _rows(nasdaq_text):
        ticker = row.get("Symbol", "").strip().upper()
        if not ticker or row.get("Test Issue") == "Y":
            continue
        name = row.get("Security Name", "").strip()
        securities[ticker] = ListedSecurity(
            ticker=ticker.replace(".", "-"), provider_symbol=ticker, company_name=name,
            exchange="NASDAQ", asset_type=_asset_type(name, row.get("ETF") == "Y"),
            active=row.get("Financial Status", "N") in {"N", ""}, source="Nasdaq Trader Symbol Directory",
            as_of=fetched_at, fetched_at=fetched_at,
        )
    exchange_map = {"N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}
    for row in _rows(other_text):
        raw_symbol = (row.get("NASDAQ Symbol") or row.get("ACT Symbol") or "").strip().upper()
        if not raw_symbol or row.get("Test Issue") == "Y":
            continue
        exchange = exchange_map.get(row.get("Exchange", ""), row.get("Exchange", ""))
        name = row.get("Security Name", "").strip()
        ticker = raw_symbol.replace(".", "-")
        securities[ticker] = ListedSecurity(
            ticker=ticker, provider_symbol=raw_symbol, company_name=name, exchange=exchange,
            asset_type=_asset_type(name, row.get("ETF") == "Y"), active=True,
            source="Nasdaq Trader Symbol Directory", as_of=fetched_at, fetched_at=fetched_at,
        )
    return sorted(securities.values(), key=lambda item: item.ticker)


class NasdaqSymbolDirectory:
    name = "nasdaq_symbol_directory"

    def __init__(self, *, cache: JsonFileCache, timeout_seconds: float = 20, max_retries: int = 3, transport: httpx.AsyncBaseTransport | None = None):
        self.cache = cache
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.transport = transport

    async def _download(self, url: str, cache_key: str, ttl_seconds: int) -> tuple[str, datetime]:
        cached = self.cache.get_entry(cache_key)
        if cached:
            return str(cached.data), cached.created_at
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds, transport=self.transport) as client:
                    response = await client.get(url)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2**attempt))
                        continue
                response.raise_for_status()
                fetched_at = datetime.now(UTC)
                self.cache.set(cache_key, response.text, ttl_seconds)
                return response.text, fetched_at
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                raise ProviderError(self.name, "SYMBOL_DIRECTORY_UNAVAILABLE", "Unable to fetch the official U.S. symbol directory.", retryable=True, endpoint=url) from exc
        raise ProviderError(self.name, "SYMBOL_DIRECTORY_UNAVAILABLE", "Unable to fetch the official U.S. symbol directory.", retryable=True, endpoint=url)

    async def list_securities(self, ttl_seconds: int = 86400) -> list[ListedSecurity]:
        (nasdaq_text, nasdaq_at), (other_text, other_at) = await asyncio.gather(
            self._download(NASDAQ_URL, "nasdaq-symbol-directory", ttl_seconds),
            self._download(OTHER_URL, "other-symbol-directory", ttl_seconds),
        )
        return normalize_symbol_directories(nasdaq_text, other_text, fetched_at=min(nasdaq_at, other_at))
