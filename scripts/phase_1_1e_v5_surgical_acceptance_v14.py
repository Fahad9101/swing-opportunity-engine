from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v13.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


helper_marker = "\ndef _value_has_local_metric_owner(clause: str, anchor: int, mention, value) -> bool:\n"
helper = r'''

def _compact_metric_value_full_year_guidance_row(clause: str, anchor: int, mention, value) -> bool:
    """Allow deterministic compact rows where metric -> value -> FY guidance heading.

    Example: ``EBITDA of $381M-$403M Full Year 2025 Adjusted Guidance``.
    This is intentionally narrow: the value must follow the metric closely, no
    intervening metric owner may appear, and a full-year guidance label must
    immediately follow the value. It must not rescue values that precede a
    later unrelated metric mention.
    """
    if value is None or value.start < anchor:
        return False
    mention_end = anchor + len(mention.text)
    between = clause[mention_end:value.start]
    if len(between) > 48:
        return False
    if not re.fullmatch(r"[\s()0-9.,'’\-–—:]*?(?:of\s*)?", between, re.I):
        return False
    # If another metric owner appears between this metric and its value, the
    # ownership is not deterministic.
    for owner, pattern in _VALUE_OWNER_PATTERNS:
        for match in pattern.finditer(clause[mention_end:value.start]):
            if owner is not mention.metric:
                return False
    after = clause[value.end:min(len(clause), value.end + 96)]
    return bool(
        re.match(
            r"\s*(?:[•|;,]\s*)?(?:Full[- ]Year|FY|Fiscal(?:\s+Year)?)\s*'?20\d{2}\b.{0,28}\b(?:Adjusted\s+)?Guidance\b",
            after,
            re.I,
        )
    )

'''
if "def _compact_metric_value_full_year_guidance_row(" not in text:
    text = replace_once(text, helper_marker, helper + helper_marker, "insert v14 compact guidance row helper")

old_locality = '''            if value is not None and owned_value is None and not _value_has_local_metric_owner(clause, anchor, mention, value):\n                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
new_locality = '''            if value is not None and owned_value is None and not _value_has_local_metric_owner(clause, anchor, mention, value) and not _compact_metric_value_full_year_guidance_row(clause, anchor, mention, value):\n                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
text = replace_once(text, old_locality, new_locality, "v14 compact guidance locality exception")
path.write_text(text)

# Regression cases from the v13 population audit.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_compact_ebitda_value_before_full_year_guidance_heading_is_retained_v14():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "STRLV14",
        "Net Income of $222 million to $239 million • Diluted EPS of $7.15 to $7.65 • EBITDA (1) of $381 million to $403 million Full Year 2025 Adjusted Guidance",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda" and f.low == 381.0 and f.high == 403.0]
    assert ebitda
    assert all(f.fiscal_period == "FY2025" for f in ebitda), [(f.fiscal_period, f.low, f.high) for f in ebitda]


def test_prior_investment_value_cannot_be_stolen_by_later_eps_mention_v14():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "WABV14",
        "Committed $3.5 billion to investments expected to create immediate value, with higher adjusted EBITDA margins and increased adjusted EPS in the first year.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps"]
    assert not any(f.low == 3.5 for f in eps), [(f.fiscal_period, f.low, f.high) for f in eps]
''')
