from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from app.domain.schemas import FieldProvenance, FundamentalSnapshot
from app.providers.errors import ProviderError
from app.providers.sec_biotech import (
    FILING_DOCUMENT_URL,
    SecBiotechIntelligenceProvider,
    _plain_text,
    derive_operating_cashflow_quarters,
    normalize_recent_filings,
)


_PERIODIC_FORMS = {"10-Q", "10-Q/A", "10-K", "10-K/A"}
_AMOUNT = r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(million|billion)"
_MARKETABLE_PHRASE = r"(?:available[- ]for[- ]sale\s+securities|marketable\s+securities|short[- ]term\s+investments)"
_CASH_PHRASE = r"cash\s*(?:,\s*|and\s+)cash\s+equivalents(?:\s*,?\s*and\s+restricted\s+cash)?"


def _scaled_amount(value: str, scale: str) -> float:
    amount = float(value.replace(",", ""))
    return amount * (1_000_000_000 if scale.lower() == "billion" else 1_000_000)


def _date_variants(value: date) -> tuple[str, ...]:
    return (
        f"{value.strftime('%B')} {value.day}, {value.year}".lower(),
        f"{value.strftime('%b')} {value.day}, {value.year}".lower(),
        value.strftime("%m/%d/%Y").lower(),
        value.isoformat().lower(),
    )


def _nearest_scaled_amount(text: str, phrase_match: re.Match[str]) -> tuple[float | None, str | None]:
    start = max(0, phrase_match.start() - 140)
    end = min(len(text), phrase_match.end() + 140)
    window = text[start:end]
    candidates: list[tuple[int, float, str]] = []
    for match in re.finditer(_AMOUNT, window, re.I):
        absolute_start = start + match.start()
        absolute_end = start + match.end()
        if absolute_end <= phrase_match.start():
            distance = phrase_match.start() - absolute_end
        elif absolute_start >= phrase_match.end():
            distance = absolute_start - phrase_match.end()
        else:
            distance = 0
        candidates.append((distance, _scaled_amount(match.group(1), match.group(2)), match.group(0)))
    if not candidates:
        return None, None
    distance, amount, raw = min(candidates, key=lambda item: item[0])
    if distance > 100:
        return None, None
    return amount, raw


def extract_periodic_filing_liquidity(document: str, period_end: date) -> dict[str, Any]:
    """Extract only explicit scaled liquidity balances from a periodic SEC filing.

    Unscaled table values are ignored because the table unit may be thousands or
    millions. Milestone receivables, collaboration payments and financing
    capacity are ignored because extraction is anchored to explicit liquidity
    balance phrases only.
    """
    text = _plain_text(document)
    lowered = text.lower()
    date_variants = _date_variants(period_end)

    def best(phrase_pattern: str) -> dict[str, Any] | None:
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        for phrase in re.finditer(phrase_pattern, text, re.I):
            amount, raw_amount = _nearest_scaled_amount(text, phrase)
            if amount is None:
                continue
            context_start = max(0, phrase.start() - 260)
            context_end = min(len(text), phrase.end() + 260)
            context = text[context_start:context_end]
            context_lower = lowered[context_start:context_end]
            date_score = 1 if any(value in context_lower for value in date_variants) else 0
            candidates.append((date_score, -phrase.start(), {
                "amount": amount,
                "phrase": phrase.group(0),
                "raw_amount": raw_amount,
                "context": context[:520],
                "period_date_present": bool(date_score),
            }))
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[0], item[1]))[2]

    marketable = best(_MARKETABLE_PHRASE)
    cash = best(_CASH_PHRASE)
    marketable_phrase_present = re.search(_MARKETABLE_PHRASE, text, re.I) is not None
    cash_phrase_present = re.search(_CASH_PHRASE, text, re.I) is not None

    combined_patterns = (
        rf"{_CASH_PHRASE}\s*,?\s*and\s+{_MARKETABLE_PHRASE}[^$]{{0,100}}{_AMOUNT}",
        rf"{_AMOUNT}[^.]{{0,100}}{_CASH_PHRASE}\s*,?\s*and\s+{_MARKETABLE_PHRASE}",
    )
    combined: dict[str, Any] | None = None
    for pattern in combined_patterns:
        match = re.search(pattern, text, re.I | re.S)
        if not match:
            continue
        amount_match = re.search(_AMOUNT, match.group(0), re.I)
        if amount_match:
            combined = {
                "amount": _scaled_amount(amount_match.group(1), amount_match.group(2)),
                "context": match.group(0)[:520],
            }
            break

    return {
        "period_end": period_end.isoformat(),
        "cash": None if cash is None else cash["amount"],
        "marketable_securities": None if marketable is None else marketable["amount"],
        "combined_liquidity": None if combined is None else combined["amount"],
        "cash_phrase_present": cash_phrase_present,
        "marketable_phrase_present": marketable_phrase_present,
        "cash_evidence": cash,
        "marketable_securities_evidence": marketable,
        "combined_liquidity_evidence": combined,
        "method": "explicit scaled periodic-filing liquidity phrases",
    }


def _runway_from_periodic_liquidity(payload: dict[str, Any], filing_liquidity: dict[str, Any]) -> dict[str, Any] | None:
    try:
        period_end = date.fromisoformat(str(filing_liquidity["period_end"]))
    except (KeyError, ValueError):
        return None

    combined = filing_liquidity.get("combined_liquidity")
    cash = filing_liquidity.get("cash")
    marketable = filing_liquidity.get("marketable_securities")
    if combined is not None:
        liquidity = max(0.0, float(combined))
        method = "filing_combined_liquidity"
    elif marketable is not None:
        liquidity = max(0.0, float(marketable)) + (max(0.0, float(cash)) if cash is not None else 0.0)
        method = "filing_cash_plus_marketable_securities" if cash is not None else "filing_marketable_securities_only_conservative"
    elif cash is not None and not filing_liquidity.get("marketable_phrase_present"):
        liquidity = max(0.0, float(cash))
        method = "filing_cash_only_no_marketable_phrase"
    else:
        return None

    quarters, cfo_concept = derive_operating_cashflow_quarters(payload)
    quarters = [row for row in quarters if str(row.get("end") or "") <= period_end.isoformat()]
    trailing = quarters[-4:]
    if len(trailing) < 2:
        return None
    values = [float(row["val"]) for row in trailing]
    trailing_negative_monthly_burn = sum(max(-value, 0.0) for value in values) / (3 * len(values))
    latest_quarter_monthly_burn = max(-values[-1], 0.0) / 3
    monthly_burn = max(trailing_negative_monthly_burn, latest_quarter_monthly_burn)
    if monthly_burn <= 0:
        return None
    return {
        "cash_runway_months": liquidity / monthly_burn,
        "status": "DERIVED_WITH_PERIODIC_FILING_LIQUIDITY",
        "cash": cash,
        "marketable_securities": marketable,
        "liquidity": liquidity,
        "cfo_concept": cfo_concept,
        "quarters_used": trailing,
        "trailing_negative_monthly_burn": trailing_negative_monthly_burn,
        "latest_quarter_monthly_burn": latest_quarter_monthly_burn,
        "conservative_monthly_burn": monthly_burn,
        "method": f"{method} / max(latest-quarter burn, trailing negative-quarter burn)",
        "liquidity_fallback_method": method,
        "liquidity_fallback": filing_liquidity,
        "as_of": period_end.isoformat(),
    }


def apply_filing_liquidity_fallback(runway: dict[str, Any], filing_liquidity: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible helper used by deterministic unit tests.

    This preserves the initial companyfacts burn rate and only replaces missing
    liquidity. Production enrichment uses the latest-period recomputation above.
    """
    if runway.get("marketable_securities") is not None:
        return runway
    combined = filing_liquidity.get("combined_liquidity")
    filing_cash = filing_liquidity.get("cash")
    marketable = filing_liquidity.get("marketable_securities")
    existing_cash = runway.get("cash")
    if combined is not None:
        liquidity = float(combined)
        method = "filing_combined_liquidity"
    elif marketable is not None:
        cash = filing_cash if filing_cash is not None else existing_cash
        if cash is None:
            return runway
        liquidity = max(0.0, float(cash)) + max(0.0, float(marketable))
        method = "filing_cash_plus_marketable_securities" if filing_cash is not None else "companyfacts_cash_plus_filing_marketable_securities"
    else:
        return runway
    monthly_burn = runway.get("conservative_monthly_burn")
    if monthly_burn in (None, 0) or float(monthly_burn) <= 0:
        return runway
    enriched = dict(runway)
    enriched.update({
        "cash_runway_months": liquidity / float(monthly_burn),
        "status": "DERIVED_WITH_PERIODIC_FILING_LIQUIDITY_FALLBACK",
        "liquidity": liquidity,
        "marketable_securities": marketable,
        "filing_cash": filing_cash,
        "liquidity_fallback": filing_liquidity,
        "liquidity_fallback_method": method,
        "method": f"{runway.get('method')} + {method}",
    })
    return enriched


class SecBiotechLiquidityFallbackProvider(SecBiotechIntelligenceProvider):
    """Recover latest biotech liquidity from periodic filings when XBRL tags are incomplete."""

    async def _latest_periodic_filing_liquidity(self, ticker: str, cik: str) -> tuple[dict[str, Any] | None, datetime]:
        submissions, fetched_at = await self._submissions(ticker, cik)
        periodic: list[tuple[date, str, dict[str, Any]]] = []
        for row in normalize_recent_filings(submissions):
            if str(row.get("form") or "").upper() not in _PERIODIC_FORMS:
                continue
            try:
                report_date = date.fromisoformat(str(row.get("reportDate") or ""))
            except ValueError:
                continue
            periodic.append((report_date, str(row.get("filingDate") or ""), row))
        if not periodic:
            return None, fetched_at
        report_date, _, row = max(periodic, key=lambda item: (item[0], item[1]))
        accession = str(row.get("accessionNumber") or "")
        document = str(row.get("primaryDocument") or "")
        if not accession or not document:
            return None, fetched_at
        url = FILING_DOCUMENT_URL.format(cik=int(cik), accession=accession.replace("-", ""), document=document)
        text, document_at = await self._get_text(
            url,
            f"sec-periodic-liquidity:{accession}:{document}",
            self.rules["data_quality"]["cache_ttl_seconds"]["fundamentals"],
        )
        extracted = extract_periodic_filing_liquidity(text, report_date)
        extracted.update({
            "filing_date": row.get("filingDate"),
            "report_date": row.get("reportDate"),
            "form": row.get("form"),
            "accession_number": accession,
            "source_url": url,
        })
        return extracted, document_at

    async def enrich_fundamental(self, ticker: str, fundamental: FundamentalSnapshot) -> FundamentalSnapshot:
        enriched = await super().enrich_fundamental(ticker, fundamental)
        raw = dict(enriched.raw)
        base_runway = dict(raw.get("biotech_runway") or {})
        cik = (await self.sec.ticker_map()).get(ticker.upper().replace(".", "-"))
        if not cik:
            return enriched
        try:
            companyfacts, companyfacts_at, _ = await self._companyfacts(ticker)
            filing_liquidity, filing_at = await self._latest_periodic_filing_liquidity(ticker, cik)
        except ProviderError:
            return enriched
        if not filing_liquidity:
            return enriched

        raw["biotech_filing_liquidity"] = filing_liquidity
        latest_period = filing_liquidity.get("period_end")
        base_period = base_runway.get("as_of")
        latest_is_newer = bool(latest_period and (not base_period or str(latest_period) > str(base_period)))
        should_recompute = latest_is_newer or base_runway.get("marketable_securities") is None
        if not should_recompute:
            return enriched.model_copy(update={"raw": raw})

        corrected = _runway_from_periodic_liquidity(companyfacts, filing_liquidity)
        if corrected is None:
            if latest_is_newer and filing_liquidity.get("marketable_phrase_present") and filing_liquidity.get("marketable_securities") is None:
                unresolved = dict(base_runway)
                unresolved.update({
                    "cash_runway_months": None,
                    "status": "LATEST_PERIOD_MARKETABLE_SECURITIES_UNRESOLVED",
                    "as_of": latest_period,
                    "liquidity_fallback": filing_liquidity,
                })
                raw["biotech_runway"] = unresolved
                return enriched.model_copy(update={"cash_runway_months": None, "raw": raw})
            return enriched.model_copy(update={"raw": raw})

        raw["biotech_runway"] = corrected
        period_end = date.fromisoformat(str(corrected["as_of"]))
        provenance = dict(enriched.field_provenance)
        provenance["cash_runway_months"] = FieldProvenance(
            source="SEC periodic filing deterministic biotech liquidity",
            as_of=datetime.combine(period_end, datetime.min.time(), tzinfo=UTC),
            fetched_at=filing_at,
            stale=False,
            raw_field="primaryDocument explicit scaled liquidity + SEC companyfacts operating cash flow",
        )
        return enriched.model_copy(update={
            "cash_runway_months": corrected["cash_runway_months"],
            "raw": raw,
            "field_provenance": provenance,
            "fetched_at": max(enriched.fetched_at, companyfacts_at, filing_at),
        })
