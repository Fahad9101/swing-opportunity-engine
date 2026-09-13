from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v15.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


helper_marker = "\ndef _following_period_is_new_outlook_heading(clause: str, anchor: int, mention, value, period: _PeriodBinding | None) -> bool:\n"
helper = r'''

def _compact_forward_period_is_owned(clause: str, value, period: _PeriodBinding | None) -> bool:
    """Treat a trailing FY period as part of the same deterministic compact row.

    This is deliberately narrower than general following-period recovery. The
    value must already be the strict compact-forward owned value, the selected
    period must be FULL_YEAR, start immediately after that value, and the
    period must itself be followed by an explicit Guidance label.
    """
    if value is None or period is None or period.kind is not GuidancePeriodKind.FULL_YEAR:
        return False
    if period.start < value.end or period.start - value.end > 4:
        return False
    if clause[value.end:period.start].strip():
        return False
    suffix = clause[period.end:min(len(clause), period.end + 36)]
    return bool(re.match(r"\s*(?:Adjusted\s+)?Guidance\b", suffix, re.I))

'''
if "def _compact_forward_period_is_owned(" not in text:
    text = replace_once(text, helper_marker, helper + helper_marker, "insert v16 compact period ownership helper")

old_period_guard = '''            if period is not None and period is not direct_period and (\n                _selected_following_period_crosses_sentence(clause, anchor, mention, value, period)\n                or _following_period_is_new_outlook_heading(clause, anchor, mention, value, period)\n            ):\n                period = None\n'''
new_period_guard = '''            compact_forward_period_owned = _compact_forward_period_is_owned(clause, compact_forward_value, period)\n            if period is not None and period is not direct_period and not compact_forward_period_owned and (\n                _selected_following_period_crosses_sentence(clause, anchor, mention, value, period)\n                or _following_period_is_new_outlook_heading(clause, anchor, mention, value, period)\n            ):\n                period = None\n'''
text = replace_once(text, old_period_guard, new_period_guard, "v16 compact trailing period ownership")
path.write_text(text)

# Additional boundary regression: sentence-separated headings must not be
# rescued as belonging to the preceding metric/value row.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_sentence_separated_full_year_heading_is_not_compact_owned_v16():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "STRLNEG16",
        "EBITDA of $381 million to $403 million. Full Year 2025 Adjusted Guidance: Revenue $1.0 billion to $1.1 billion.",
    ))
    ebitda = [f for f in ex.facts if f.metric.value == "ebitda" and f.low == 381.0 and f.high == 403.0]
    assert not any(f.fiscal_period == "FY2025" for f in ebitda), [(f.fiscal_period, f.low, f.high) for f in ebitda]
''')
