from app.services.guidance_raw_canonical_extractor import (
    _metric_mentions,
    _metric_clause,
    _segments,
    _suffix_owned_money_range,
    _canonical_period_binding,
)

text = "Raised full-year 2025 guidance to: $452 - $458 million revenue; $138.5 - $141.5 million Adjusted EBITDA."
for segment in _segments(text):
    print("SEGMENT", repr(segment))
    mentions = _metric_mentions(segment)
    for i, mention in enumerate(mentions):
        clause, anchor = _metric_clause(segment, mentions, i)
        value = _suffix_owned_money_range(clause, anchor, mention)
        period = _canonical_period_binding(clause, anchor, mention)
        print({
            "metric": mention.metric.value,
            "mention": mention.text,
            "clause": clause,
            "anchor": anchor,
            "suffix_value": None if value is None else (value.low, value.high, value.unit.value, value.text),
            "period": None if period is None else period.period,
        })
