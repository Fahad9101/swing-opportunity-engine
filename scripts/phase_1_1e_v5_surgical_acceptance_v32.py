from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v31.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()

# v31 deliberately narrowed quarter ownership to avoid stale-result aliases.
# Preserve that rule, but allow one strict segment-heading form to carry across
# adjacent sentences in the same extracted segment:
#   "Fiscal 2026 First Quarter Outlook ... revenue ... . ... EPS ..."
# This is not a generic quarter fallback: the segment must begin with the exact
# fiscal-year + ordinal-quarter + Outlook/Guidance heading and no competing
# explicit period may appear between that heading and the metric.
helper_marker = "\ndef _semantic_alias_reason_v29(fact: TypedGuidanceFact) -> str | None:\n"
helper = r'''
def _strict_segment_quarter_heading_v32(segment: str, clause: str, anchor: int, mention) -> _PeriodBinding | None:
    heading = re.match(
        r"\s*Fiscal(?:\s+Year)?\s+(?P<year>20\d{2})\s+"
        r"(?P<word>First|Second|Third|Fourth)\s+Quarter\s+"
        r"(?:Outlook|Guidance)\b",
        segment,
        re.I,
    )
    if heading is None:
        return None
    # Do not carry the heading through a later explicit quarter/year heading.
    metric_pos = segment.find(mention.text)
    if metric_pos < 0:
        return None
    between = segment[heading.end():metric_pos]
    if re.search(
        r"\b(?:Q[1-4]\s*(?:FY)?\s*'?20\d{2}|[1-4]Q\s*'?20\d{2}|"
        r"Fiscal(?:\s+Year)?\s+20\d{2}\s+(?:First|Second|Third|Fourth)\s+Quarter|"
        r"FY\s*'?20\d{2}|Full[- ]Year\s+20\d{2})\b",
        between,
        re.I,
    ):
        return None
    q = _QUARTER_WORD[heading.group("word").lower()]
    year = _normalize_year(heading.group("year"))
    return _PeriodBinding(
        f"Q{q}FY{year}",
        GuidancePeriodKind.QUARTER,
        heading.group(0),
        heading.start(),
        heading.end(),
    )


def _trailing_full_year_heading_v32(clause: str, anchor: int, mention, value) -> _PeriodBinding | None:
    """Recover only a terminal `. Full Year YYYY` layout heading.

    The value must belong to explicit directional guidance/outlook in the same
    sentence. This targets flattened SEC/table layout such as PLTR without
    reintroducing the rejected generic following-section fallback.
    """
    if value is None:
        return None
    tail = clause[value.end():]
    match = re.match(
        r"\s*[.!?]\s*Full[- ]Year\s+(?P<year>20\d{2})\s*$",
        tail,
        re.I,
    )
    if match is None:
        return None
    local = clause[max(0, anchor - 120):value.start]
    if not re.search(r"\b(?:guidance|outlook|forecast)\b", local, re.I):
        return None
    if not re.search(r"\b(?:rais(?:e|es|ed|ing)|lower(?:s|ed|ing)?|revis(?:e|es|ed|ing)|updat(?:e|es|ed|ing)|reaffirm(?:s|ed|ing)?)\b", local, re.I):
        return None
    start = value.end() + match.start("year")
    end = value.end() + match.end("year")
    year = _normalize_year(match.group("year"))
    return _PeriodBinding(f"FY{year}", GuidancePeriodKind.FULL_YEAR, match.group(0).strip(), start, end)

'''
if "def _strict_segment_quarter_heading_v32(" not in text:
    if text.count(helper_marker) != 1:
        raise RuntimeError(f"v32 helper insertion: expected one marker, found {text.count(helper_marker)}")
    text = text.replace(helper_marker, "\n" + helper + helper_marker.lstrip("\n"), 1)

period_marker = "            if _period_is_presentation_footer(clause, period):\n"
period_insert = '''            strict_segment_quarter_v32 = _strict_segment_quarter_heading_v32(segment, clause, anchor, mention)\n            if strict_segment_quarter_v32 is not None and (period is None or period.kind is GuidancePeriodKind.FULL_YEAR):\n                period = strict_segment_quarter_v32\n            if period is None:\n                trailing_full_year_v32 = _trailing_full_year_heading_v32(clause, anchor, mention, value)\n                if trailing_full_year_v32 is not None:\n                    period = trailing_full_year_v32\n'''
if "strict_segment_quarter_v32 =" not in text:
    if text.count(period_marker) != 1:
        raise RuntimeError(f"v32 period insertion: expected one marker, found {text.count(period_marker)}")
    text = text.replace(period_marker, period_insert + period_marker, 1)

path.write_text(text)

# Focused guards: carry strict quarter heading across a second sentence, but do
# not carry it past a competing annual heading; accept only terminal annual
# layout headings attached to directional guidance.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_strict_quarter_outlook_heading_carries_to_second_metric_v32():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEQ132",
        "Fiscal 2026 First Quarter Outlook HPE estimates revenue to be in the range of $9.0 billion to $9.4 billion. "
        "HPE estimates GAAP diluted net EPS to be in the range of $0.09 to $0.13.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 0.09]
    assert eps and all(f.fiscal_period == "Q1FY2026" for f in eps), [(f.fiscal_period, f.low) for f in eps]


def test_competing_annual_heading_blocks_quarter_heading_carry_v32():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "HPEQ132NEG",
        "Fiscal 2026 First Quarter Outlook HPE estimates revenue to be $9.0 billion to $9.4 billion. "
        "Full Year 2026 Outlook. HPE estimates GAAP diluted net EPS to be $1.90 to $2.10.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 1.90]
    assert not any(f.fiscal_period == "Q1FY2026" for f in eps), [(f.fiscal_period, f.low) for f in eps]


def test_terminal_full_year_heading_recovers_directional_guidance_v32():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "PLTR32",
        "We are raising our adjusted free cash flow guidance to between $1.6 billion and $1.8 billion. Full Year 2025",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 1.6]
    assert fcf and all(f.fiscal_period == "FY2025" for f in fcf), [(f.fiscal_period, f.low) for f in fcf]


def test_terminal_full_year_heading_does_not_recover_non_directional_actual_v32():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "PLTR32NEG",
        "Adjusted free cash flow was $1.6 billion. Full Year 2025",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 1.6]
    assert not fcf, [(f.fiscal_period, f.low) for f in fcf]
''')
