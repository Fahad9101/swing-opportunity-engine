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
_COMPACT_FORWARD_MONEY_RANGE = re.compile(
    r"^\s*(?:\(\s*\d+[A-Za-z]?\s*\)\s*)?(?:(?:of|at)\s+)?"
    r"(?P<d1>\$)?\s*(?P<lo>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s1>billion|million|thousand|bn|mm|m|b)?\s*"
    r"(?:-|–|—|to|through|and)\s*"
    r"(?P<d2>\$)?\s*(?P<hi>-?\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<s2>billion|million|thousand|bn|mm|m|b)?"
    r"(?P<after>\s+(?:Full[- ]Year|FY|Fiscal(?:\s+Year)?)\s*'?20\d{2}\b.{0,28}\b(?:Adjusted\s+)?Guidance\b)",
    re.I,
)


def _compact_metric_forward_guidance_value(clause: str, anchor: int, mention) -> _ValueBinding | None:
    """Bind only deterministic metric-before-value compact guidance rows.

    Example: ``EBITDA (1) of $381 million to $403 million Full Year 2025 Adjusted Guidance``.
    The range must immediately follow the metric (apart from a footnote and
    ``of``/``at``), and an explicit full-year guidance label must immediately
    follow the range. This intentionally does not cover free prose.
    """
    mention_end = anchor + len(mention.text)
    tail = clause[mention_end:min(len(clause), mention_end + 180)]
    match = _COMPACT_FORWARD_MONEY_RANGE.match(tail)
    if not match:
        return None

    s1 = (match.group("s1") or "").lower()
    s2 = (match.group("s2") or "").lower()
    if s1 and s2 and s1 != s2:
        aliases = {"m": "million", "mm": "million", "b": "billion", "bn": "billion"}
        if aliases.get(s1, s1) != aliases.get(s2, s2):
            return None
    scale = match.group("s2") or match.group("s1")
    if not scale:
        return None

    unit = _unit_from_scale(
        scale,
        mention.metric,
        dollar=bool(match.group("d1") or match.group("d2")),
    )
    if unit is GuidanceUnit.UNKNOWN:
        return None

    low = float(match.group("lo").replace(",", ""))
    high = float(match.group("hi").replace(",", ""))
    if low > high:
        return None

    value_start = mention_end + match.start("lo")
    # Include a leading dollar sign in the raw evidence span when present.
    if match.group("d1"):
        value_start = mention_end + match.start("d1")
    value_end = mention_end + match.end("s2") if match.group("s2") else mention_end + match.end("s1")
    return _ValueBinding(
        low,
        high,
        unit,
        GuidanceValueKind.ABSOLUTE_LEVEL,
        clause[value_start:value_end].strip(),
        value_start,
        value_end,
    )

'''
if "def _compact_metric_forward_guidance_value(" not in text:
    text = replace_once(text, helper_marker, helper + helper_marker, "insert v15 compact forward value helper")

old_values = '''            suffix_value = _suffix_owned_money_range(clause, anchor, mention)\n            breakeven_value = _breakeven_value(clause, anchor, mention)\n            owned_value = previous_now_value or directional_value or suffix_value or breakeven_value\n            value = owned_value or _bind_value(clause, mention, anchor)\n'''
new_values = '''            suffix_value = _suffix_owned_money_range(clause, anchor, mention)\n            breakeven_value = _breakeven_value(clause, anchor, mention)\n            compact_forward_value = _compact_metric_forward_guidance_value(clause, anchor, mention)\n            owned_value = previous_now_value or directional_value or suffix_value or breakeven_value or compact_forward_value\n            value = owned_value or _bind_value(clause, mention, anchor)\n'''
text = replace_once(text, old_values, new_values, "v15 compact forward owned-value selection")
path.write_text(text)

# Regression cases from the v13 population audit.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_compact_ebitda_value_before_full_year_guidance_heading_is_retained_v15():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "STRLV15",
        "Net Income of $222 million to $239 million • Diluted EPS of $7.15 to $7.65 • EBITDA (1) of $381 million to $403 million Full Year 2025 Adjusted Guidance",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda" and f.low == 381.0 and f.high == 403.0]
    assert ebitda
    assert all(f.fiscal_period == "FY2025" for f in ebitda), [(f.fiscal_period, f.low, f.high) for f in ebitda]


def test_compact_forward_binding_does_not_steal_prior_investment_value_v15():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "WABV15",
        "Committed $3.5 billion to investments expected to create immediate value, with higher adjusted EBITDA margins and increased adjusted EPS in the first year.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps"]
    assert not any(f.low == 3.5 for f in eps), [(f.fiscal_period, f.low, f.high) for f in eps]


def test_compact_forward_binding_rejects_mismatched_scales_v15():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "BADSCV15",
        "EBITDA of $381 million to $403 billion Full Year 2025 Adjusted Guidance",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda"]
    assert not any(f.low == 381.0 and f.high == 403.0 for f in ebitda)
''')
