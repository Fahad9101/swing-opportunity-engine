from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.soe_v1_1 import SourceDocument
from app.services.guidance_raw_canonical_extractor import extract_canonical_typed_guidance_facts

TS = datetime(2026, 8, 15, tzinfo=UTC)


def doc(ticker: str, text: str) -> SourceDocument:
    digest = hashlib.sha256(text.encode()).hexdigest()
    return SourceDocument(
        document_id=f"diag-{ticker}-{digest[:10]}", rules_hash="diag", ticker=ticker,
        cik="0000000001", accession="0000000001-26-000001", form="8-K",
        source_url=f"https://www.sec.gov/Archives/edgar/data/1/{ticker.lower()}.htm",
        source_timestamp=TS, fetched_at=TS, stale=False, content_hash=digest,
        content_type="text/plain", content=text,
    )

CASES = {
    "historical-quarter-vs-annual": "Fourth quarter of 2023 performance is shown for comparison while Fiscal 2025 Guidance Revenue is expected to be $500 million to $520 million.",
    "endpoint-fragment": "Fiscal 2026 guidance: Revenue is expected to be $500 million to $520 million; Revenue is expected to be $520 million.",
    "directional-owner": "2026 Guidance. The Company lowers revenue to $4.0 billion to $4.2 billion; adjusted EPS is expected to be $5.00 to $5.20.",
    "breakeven": "Full year 2025 Adjusted EBITDA is expected to be between breakeven and $10 million.",
    "compact-suffix": "Raised full-year 2025 guidance to: $452 - $458 million revenue; $138.5 - $141.5 million Adjusted EBITDA.",
}

for name, text in CASES.items():
    ex = extract_canonical_typed_guidance_facts(doc(name.upper(), text))
    print(f"\n=== {name} ===")
    for f in ex.facts:
        print({
            "metric": f.metric.value, "period": f.fiscal_period, "low": f.low, "high": f.high,
            "unit": f.unit.value, "role": f.role.value, "action": f.explicit_action.value,
            "scope": f.scope_kind.value, "basis": f.accounting_basis,
            "value_text": f.provenance[0].evidence.value_text,
            "period_text": f.provenance[0].evidence.period_text,
            "evidence": f.provenance[0].evidence.full_text[:350],
        })
    print("rejected:")
    for r in ex.rejected_candidates:
        print(r)
