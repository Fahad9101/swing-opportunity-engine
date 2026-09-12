from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.domain.soe_v1_1 import SourceDocument
import app.services.guidance_raw_canonical_extractor as g

text = (
    "Adjusted EBITDA of $102.6 million, up 11.5% YoY. "
    "Raising 2025 Guidance (all comparisons against the full year 2024, unless otherwise noted). "
    "Revenue range of $2.20 billion to $2.26 billion."
)
digest = hashlib.sha256(text.encode()).hexdigest()
doc = SourceDocument(
    document_id="coord-debug",
    rules_hash="coord-debug",
    ticker="DEBUG",
    cik="0000000001",
    accession="0000000001-26-000001",
    form="8-K",
    source_url="https://www.sec.gov/debug",
    source_timestamp=datetime(2026, 8, 15, tzinfo=UTC),
    fetched_at=datetime(2026, 8, 15, tzinfo=UTC),
    content_hash=digest,
    content_type="text/plain",
    content=text,
)

print("=== coordinate diagnostic ===")
for segment in g._segments(text):
    mentions = g._metric_mentions(segment)
    for index, mention in enumerate(mentions):
        if mention.metric.value != "ebitda":
            continue
        clause, anchor = g._metric_clause(segment, mentions, index)
        action = g._metric_action(segment, clause, anchor, mention)
        current, _ = g._previous_now_value_pair(clause, mention)
        directional, _ = g._directional_value_pair(clause, anchor, mention, action)
        bound = g._bind_metric_value(clause, mention, anchor)
        value = current or directional or bound
        print("SEGMENT", repr(segment))
        print("CLAUSE", repr(clause))
        print("ANCHOR", anchor, "MENTION", repr(mention.text), "ACTION", action.value)
        print("VALUE", value)
        if value is not None:
            print("VALUE_START_END", value.start, value.end, "CLAUSE_LEN", len(clause))
            print("AT_VALUE", repr(clause[max(0, value.start - 20):min(len(clause), value.end + 100)]))
            print("METRIC_TO_VALUE", repr(clause[anchor:value.start] if value.start >= anchor else "<value-before-metric>"))
            print("AFTER", repr(clause[value.end:min(len(clause), value.end + 140)]))
            print("HISTORICAL", g._value_is_historical_actual(clause, anchor, value))
print("FINAL FACTS", g.extract_canonical_typed_guidance_facts(doc).facts)
print("FINAL REJECTED", g.extract_canonical_typed_guidance_facts(doc).rejected_candidates)
