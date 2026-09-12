from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.soe_v1_1 import SourceDocument
from app.services.guidance_raw_canonical_extractor import extract_canonical_typed_guidance_facts

TS = datetime(2026, 8, 15, tzinfo=UTC)


def document(ticker: str, text: str) -> SourceDocument:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return SourceDocument(
        document_id=f"debug-{ticker}-{digest[:12]}",
        rules_hash="semantic-debug",
        ticker=ticker,
        cik="0000000001",
        accession="0000000001-26-000001",
        form="8-K",
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}.htm",
        source_timestamp=TS,
        fetched_at=TS,
        content_hash=digest,
        content_type="text/plain",
        content=text,
    )


CASES = {
    "PERIOD": "Fourth quarter of 2023 performance is shown for comparison while Fiscal 2025 Guidance Revenue is expected to be $500 million to $520 million.",
    "MULTI": "Full-year 2026 guidance lowers total revenue to $8.0 billion to $8.4 billion and adjusted EBITDA is expected at $1.0 billion to $1.1 billion.",
    "OWNER2": "Fiscal year 2027 guidance: Revenue of between $630 million and $650 million; Non-GAAP adjusted EBITDA of between $135 million and $145 million. Full year 2026 guidance: net cash provided by operating activities to range between $2.90 billion and $3.40 billion and free cash flow to range between $2.00 billion and $2.50 billion.",
    "TABLE2": "Raised full-year 2025 guidance to: $452 - $458 million revenue; $138.5 - $141.5 million Adjusted EBITDA.",
    "RESULTS2": "Adjusted EBITDA of $102.6 million, up 11.5% YoY. Raising 2025 Guidance (all comparisons against the full year 2024, unless otherwise noted). Revenue range of $2.20 billion to $2.26 billion.",
    "BREAKEVEN": "FY 2025 Adjusted EBITDA is expected to be between breakeven and $10 million.",
}

for ticker, text in CASES.items():
    extraction = extract_canonical_typed_guidance_facts(document(ticker, text))
    print(f"\n=== {ticker} ===")
    for fact in extraction.facts:
        print(
            "FACT",
            fact.metric.value,
            fact.fiscal_period,
            fact.accounting_basis,
            fact.scope_kind.value,
            fact.role.value,
            fact.low,
            fact.high,
            fact.unit.value,
            fact.explicit_action.value,
            fact.provenance[0].evidence.value_text,
            fact.provenance[0].evidence.full_text,
        )
    for item in extraction.rejected_candidates:
        print("REJECT", item)
