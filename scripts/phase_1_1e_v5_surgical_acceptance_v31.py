from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v30.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()

# v30 proved that generic quarter recovery was too permissive around result
# headings. A quarter may override only when it directly owns the metric/value:
# either the quarter token is between the metric and value, or a strict
# "Fiscal YYYY Nth Quarter Outlook/Guidance" heading immediately precedes the
# metric without a sentence/list boundary.
start = text.index("def _local_explicit_quarter_before_value_v29(")
end = text.index("\ndef _semantic_alias_reason_v29(", start)
new_quarter_helper = r'''def _local_explicit_quarter_before_value_v29(clause: str, anchor: int, mention, value) -> _PeriodBinding | None:
    """Recover a quarter only when the quarter directly owns this metric/value."""
    if value is None:
        return None
    candidates: list[_PeriodBinding] = []

    def directly_owned(match: re.Match[str]) -> bool:
        if match.end() > value.start:
            return False
        # Explicit quarter embedded in this metric's guidance phrase, e.g.
        # "revenue guidance for 2Q26 is $86-$88m".
        if match.start() >= anchor:
            if value.start - match.end() > 90:
                return False
            bridge = clause[max(0, anchor - 32):value.start]
            if not re.search(r"\b(?:guidance|outlook|forecast|estimat(?:e|es|ed)|expects?)\b", bridge, re.I):
                return False
            # A later explicit annual token before the value owns the value instead.
            tail = clause[match.end():value.start]
            if re.search(r"\b(?:FY\s*'?\d{2,4}|full[- ]year\s+20\d{2}|Fiscal(?:\s+Year)?\s+20\d{2})\b", tail, re.I):
                return False
            return True

        # Heading-owned form, e.g. "Fiscal 2026 First Quarter Outlook HPE estimates revenue ...".
        if anchor - match.end() > 70:
            return False
        bridge = clause[match.end():anchor]
        if re.search(r"[.;•]", bridge):
            return False
        return bool(re.match(r"\s*(?:outlook|guidance)\b", bridge, re.I))

    for match in _LOCAL_FISCAL_YEAR_QUARTER_V29.finditer(clause):
        if not directly_owned(match):
            continue
        q = _QUARTER_WORD[match.group("word").lower()]
        year = _normalize_year(match.group("year"))
        candidates.append(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()))

    for pattern in (_LOCAL_QFY_V29, _LOCAL_NQ_V29):
        for match in pattern.finditer(clause):
            if not directly_owned(match):
                continue
            q = match.group("q")
            year = _normalize_year(match.group("year"))
            candidates.append(_PeriodBinding(f"Q{q}FY{year}", GuidancePeriodKind.QUARTER, match.group(0), match.start(), match.end()))

    if not candidates:
        return None
    return max(candidates, key=lambda item: item.end)

'''
text = text[:start] + new_quarter_helper + text[end:]

old_call = "            local_quarter_period_v29 = _local_explicit_quarter_before_value_v29(clause, value)\n"
new_call = "            local_quarter_period_v29 = _local_explicit_quarter_before_value_v29(clause, anchor, mention, value)\n"
if text.count(old_call) != 1:
    raise RuntimeError(f"v31 quarter call: expected one match, found {text.count(old_call)}")
text = text.replace(old_call, new_call, 1)

# v30's generic "following section" rejection removed genuine PLTR/RELY/APPS
# guidance. Keep only the proven alias shape: a FULL-YEAR period recovered from
# after the value when the value already sits under an explicit quarter
# guidance/outlook heading before it.
old_following = '''        if re.search(r"[.!?•]\\s*$", bridge):
            return "following_section_period_alias"
'''
new_following = r'''        if fact.fiscal_period.startswith("FY"):
            before_value = clause[max(0, vs - 260 if vs is not None else 0):ve]
            quarter_before = bool(
                re.search(
                    r"\b(?:Q[1-4]\s*(?:FY)?\s*'?20\d{2}|[1-4]Q\s*'?20\d{2}|"
                    r"(?:first|second|third|fourth)\s+quarter(?:\s+(?:of\s+)?20\d{2})?)"
                    r"[^.;•]{0,55}\b(?:guidance|outlook)\b",
                    before_value,
                    re.I,
                )
                or re.search(
                    r"\b(?:guidance|outlook)\b[^.;•]{0,55}"
                    r"(?:Q[1-4]\s*(?:FY)?\s*'?20\d{2}|[1-4]Q\s*'?20\d{2}|"
                    r"(?:first|second|third|fourth)\s+quarter(?:\s+(?:of\s+)?20\d{2})?)",
                    before_value,
                    re.I,
                )
            )
            if quarter_before:
                return "following_full_year_overrides_local_quarter"
'''
if text.count(old_following) != 1:
    raise RuntimeError(f"v31 following-section narrowing: expected one match, found {text.count(old_following)}")
text = text.replace(old_following, new_following, 1)
path.write_text(text)


test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_annual_guidance_survives_unrelated_earlier_quarter_results_v31():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "GEO31",
        "2Q26 Adjusted EBITDA increased 20% to $142.0 million. "
        "Guidance for FY26 Revenues of $2.95 billion to $3.05 billion.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 2.95]
    assert revenue and all(f.fiscal_period == "FY2026" for f in revenue), [(f.fiscal_period, f.low) for f in revenue]


def test_annual_eps_guidance_survives_prior_quarter_backlog_reference_v31():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "TPC31",
        "Backlog of $21.1 billion at the end of Q2 2025, up 102% Y/Y. "
        "Company increases 2025 EPS guidance: 2025 GAAP EPS guidance now $1.70 to $2.00.",
    ))
    eps = [f for f in ex.facts if f.metric.value == "eps" and f.low == 1.70]
    assert eps and all(f.fiscal_period == "FY2025" for f in eps), [(f.fiscal_period, f.low) for f in eps]


def test_prior_q3_reference_does_not_steal_fourth_quarter_guidance_v31():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "SHAK31",
        "Targets provided in its Q3 2025 shareholder letter. "
        "For the Fourth Quarter, ending December 31, 2025, the Company continues to expect total revenue of $406 million to $412 million.",
    ))
    revenue = [f for f in ex.facts if f.metric.value == "revenue" and f.low == 406.0]
    assert revenue and all(f.fiscal_period == "Q4FY2025" for f in revenue), [(f.fiscal_period, f.low) for f in revenue]


def test_plain_annual_guidance_is_not_rejected_by_later_section_period_v31():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "PLTR31",
        "We are raising our adjusted free cash flow guidance to between $1.6 billion and $1.8 billion. Full Year 2025",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 1.6]
    assert fcf, ex.rejected_candidates
''')
