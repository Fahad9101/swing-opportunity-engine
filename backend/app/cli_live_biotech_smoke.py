from __future__ import annotations

import asyncio
import json

from app.core.config import get_settings, load_rules
from app.providers.clinical_trials import ClinicalTrialsProvider
from app.providers.nasdaq_calendar import NasdaqEarningsCalendar
from app.providers.sec_biotech import SecBiotechIntelligenceProvider
from app.providers.sec_edgar import SecEdgarProvider
from app.services.biotech_validation_service import build_biotech_validation
from app.services.cache_service import JsonFileCache


SAMPLES = (
    ("ARWR", "Arrowhead Pharmaceuticals, Inc."),
    ("BEAM", "Beam Therapeutics Inc."),
    ("MRNA", "ModernaTX, Inc."),
    ("EDIT", "Editas Medicine, Inc."),
    ("RXRX", "Recursion Pharmaceuticals, Inc."),
)


async def smoke() -> list[dict]:
    settings = get_settings()
    rules = load_rules()
    cache = JsonFileCache(settings.cache_dir)
    sec = SecEdgarProvider(
        cache=cache,
        zip_path=settings.sec_companyfacts_zip_path,
        user_agent=settings.sec_user_agent,
        rules=rules,
    )
    biotech = SecBiotechIntelligenceProvider(
        sec=sec,
        cache=cache,
        submissions_zip_path=settings.sec_submissions_zip_path,
        user_agent=settings.sec_user_agent,
        rules=rules,
    )
    clinical = ClinicalTrialsProvider(timeout_seconds=rules["data_quality"]["provider"]["timeout_seconds"])
    calendar = NasdaqEarningsCalendar(cache=cache, rules=rules)
    await calendar.prefetch()

    rows: list[dict] = []
    for ticker, sponsor in SAMPLES:
        fundamental = await sec.get_fundamentals(ticker)
        if fundamental is None:
            rows.append({"ticker": ticker, "status": "NO_SEC_FUNDAMENTALS"})
            continue
        enriched = await biotech.enrich_fundamental(ticker, fundamental)
        events = list(await calendar.get_events(ticker))
        events.extend(await clinical.get_events(ticker, sponsor, rules["catalyst"]["max_horizon_days"]))
        validation = build_biotech_validation(enriched, events, rules)
        financing = enriched.raw.get("biotech_financing") or {}
        runway = enriched.raw.get("biotech_runway") or {}
        rows.append(
            {
                "ticker": ticker,
                "status": "OK",
                "cash_runway_months": enriched.cash_runway_months,
                "runway_status": validation["runway_status"],
                "runway_method_status": runway.get("status"),
                "reported_cash": runway.get("cash"),
                "marketable_securities": runway.get("marketable_securities"),
                "runway_liquidity": runway.get("liquidity"),
                "financing_secured": enriched.financing_secured,
                "financing_status": financing.get("status"),
                "financing_matched_filing": financing.get("matched_filing"),
                "catalyst_status": validation["catalyst"]["status"],
                "scanner_catalyst_eligible": validation["catalyst"]["scanner_catalyst_eligible"],
                "date_evidence_a_b_incomplete_count": validation["catalyst"]["date_evidence_a_b_incomplete_count"],
                "trial_milestone_only_count": validation["catalyst"]["trial_milestone_only_count"],
                "event_count": validation["catalyst"]["in_horizon_event_count"],
            }
        )
    return rows


def main() -> None:
    rows = asyncio.run(smoke())
    print(json.dumps(rows, indent=2, sort_keys=True, default=str))
    usable = [row for row in rows if row.get("status") == "OK"]
    if len(usable) < 3:
        raise SystemExit("Live biotech smoke failed: fewer than three sample tickers returned SEC fundamentals.")
    runway_usable = [row for row in usable if row.get("cash_runway_months") is not None]
    if len(runway_usable) < 3:
        raise SystemExit("Live biotech smoke failed: fewer than three sample tickers produced deterministic SEC cash runway.")
    if any(float(row["cash_runway_months"]) < 0 for row in runway_usable):
        raise SystemExit("Live biotech smoke failed: negative cash runway detected.")
    for row in usable:
        if row.get("financing_secured") is True and not row.get("financing_matched_filing"):
            raise SystemExit(f"Live biotech smoke failed: {row['ticker']} financing was marked secured without matched SEC filing evidence.")
        if row.get("scanner_catalyst_eligible") is True:
            raise SystemExit(f"Live biotech smoke failed: {row['ticker']} public evidence unexpectedly created a scored catalyst.")


if __name__ == "__main__":
    main()
