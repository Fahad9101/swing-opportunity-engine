from __future__ import annotations

import asyncio
import json

from app.providers.provider_registry import get_provider


DEFAULT_TICKERS = ("AVGO", "ORCL", "ADBE", "COST", "NKE", "LUV", "ARWR", "BEAM")


async def smoke(tickers: tuple[str, ...] = DEFAULT_TICKERS) -> list[dict]:
    provider = get_provider("free_public")
    instruments = await provider.list_instruments()
    available = {item.ticker for item in instruments}
    await provider.prefetch_calendar()

    results: list[dict] = []
    for ticker in tickers:
        if ticker not in available:
            results.append({"ticker": ticker, "status": "NOT_IN_UNIVERSE"})
            continue
        evidence = await provider.get_catalyst_evidence(ticker)
        scored = await provider.get_catalysts(ticker)
        event_rows = []
        for item in evidence:
            event_rows.append(
                {
                    "type": item.type,
                    "title": item.title,
                    "event_date_anchor": item.event_date.isoformat(),
                    "window_start": item.window_start.isoformat() if item.window_start else None,
                    "window_end": item.window_end.isoformat() if item.window_end else None,
                    "date_precision": item.date_precision,
                    "date_confidence": item.date_confidence.value if item.date_confidence else None,
                    "timing": item.timing,
                    "verified": item.verified,
                    "catalyst_candidate": item.catalyst_candidate,
                    "scoring_ready": item.scoring_ready,
                    "materiality": item.materiality,
                    "surprise_potential": item.surprise_potential,
                    "missing_score_fields": item.missing_score_fields,
                    "evidence_status": item.evidence_status,
                    "source": item.source,
                    "source_url": item.source_url,
                }
            )
        results.append(
            {
                "ticker": ticker,
                "status": "OK",
                "is_biotech": provider._instruments[ticker].is_biotech,
                "evidence_count": len(event_rows),
                "scored_catalyst_count": len(scored or []),
                "events": event_rows,
            }
        )
    return results


def main() -> None:
    results = asyncio.run(smoke())
    print(json.dumps(results, indent=2, sort_keys=True))
    usable = [row for row in results if row.get("status") == "OK"]
    evidence = [event for row in usable for event in row.get("events", [])]
    if not evidence:
        raise SystemExit("Live catalyst smoke failed: no public event evidence was returned for the targeted sample.")
    if not any(event.get("date_confidence") in {"A", "B"} for event in evidence):
        raise SystemExit("Live catalyst smoke failed: no A/B date-confidence evidence was produced.")
    for event in evidence:
        if event.get("scoring_ready") and (event.get("materiality") is None or event.get("surprise_potential") is None):
            raise SystemExit("Live catalyst smoke failed: event marked scoring-ready with a missing frozen score input.")
    for row in usable:
        if row.get("scored_catalyst_count", 0) and not any(event.get("scoring_ready") for event in row.get("events", [])):
            raise SystemExit("Live catalyst smoke failed: scored catalyst appeared without scoring-ready evidence.")


if __name__ == "__main__":
    main()
