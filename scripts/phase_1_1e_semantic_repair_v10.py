from __future__ import annotations

from pathlib import Path

# Build on the blocked v9 working-tree patch. v10 only resolves the three
# deterministic failures left by v9: quarter-vs-annual ownership and a
# historical point-result tail that leaked into a later guidance section.
import phase_1_1e_semantic_repair_v9  # noqa: F401,E402

ROOT = Path(__file__).resolve().parents[1]


def replace_function(text: str, name: str, new_source: str) -> str:
    marker = f"\ndef {name}("
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"{name}: function start not found")
    start += 1
    next_start = text.find("\ndef ", start + 1)
    if next_start < 0:
        raise RuntimeError(f"{name}: next function boundary not found")
    return text[:start] + new_source.rstrip() + "\n\n" + text[next_start + 1:]


def patch_canonical_extractor() -> None:
    path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
    text = path.read_text()

    text = replace_function(
        text,
        "_strong_forward_year_binding",
        r'''def _strong_forward_year_binding(clause: str, anchor: int, mention) -> _PeriodBinding | None:
    mention_end = anchor + len(mention.text)

    # A locally owned quarter heading must not be duplicated as full-year merely
    # because the same clause/segment also contains a fiscal-year outlook. This
    # deliberately requires guidance/outlook ownership next to the quarter; an
    # unrelated historical quarter (for example, "Q4 2023 performance") does
    # not block a later explicit annual-guidance heading.
    local_quarters: list[_PeriodBinding] = []
    for pattern in _CANONICAL_QUARTER:
        for match in pattern.finditer(clause):
            token = match.group(1)
            q = token if token.isdigit() else _QUARTER_WORD[token.lower()]
            year = _normalize_year(match.group(2))
            local_quarters.append(
                _PeriodBinding(
                    f"Q{q}FY{year}",
                    GuidancePeriodKind.QUARTER,
                    match.group(0),
                    match.start(),
                    match.end(),
                )
            )
    for match in _CANONICAL_YEAR_QUARTER.finditer(clause):
        year = int(match.group(1))
        q = _QUARTER_WORD[match.group(2).lower()]
        local_quarters.append(
            _PeriodBinding(
                f"Q{q}FY{year}",
                GuidancePeriodKind.QUARTER,
                match.group(0),
                match.start(),
                match.end(),
            )
        )

    for quarter in local_quarters:
        distance = min(
            abs(quarter.end - anchor),
            abs(quarter.start - mention_end),
        )
        if distance > 90:
            continue
        prefix = clause[max(0, quarter.start - 100):quarter.start]
        suffix = clause[quarter.end:min(len(clause), quarter.end + 70)]
        prefix_owned = bool(
            re.search(
                r"(?:\b(?:guidance|outlook|forecast)\b|"
                r"\bprovid(?:e|es|ed|ing)\s+guidance\b)"
                r"[^.;\n]{0,65}$",
                prefix,
                re.I,
            )
        )
        suffix_owned = bool(
            re.match(r"^\s*(?:guidance|outlook|forecast)\b", suffix, re.I)
        )
        historical_suffix = bool(
            re.match(
                r"^\s*(?:performance|results?|actuals?|comparison|compared)\b",
                suffix,
                re.I,
            )
        )
        if (prefix_owned or suffix_owned) and not historical_suffix:
            return None

    candidates: list[tuple[int, int, _PeriodBinding]] = []
    for pattern in _STRONG_FORWARD_YEAR_PATTERNS:
        for match in pattern.finditer(clause):
            year_match = match.group("year")
            start, end = match.start("year"), match.end("year")
            prefix = clause[max(0, start - 60):start]
            suffix = clause[end:min(len(clause), end + 80)]
            around = clause[max(0, start - 35):min(len(clause), end + 35)]
            if re.search(r"\bquarter\b", around, re.I):
                continue
            if _COMPARISON_YEAR_PREFIX.search(prefix):
                continue
            forward_after = _FORWARD_SIGNAL.search(suffix)
            if forward_after and re.search(
                r"\b(?:preliminary|unaudited|results?|actual)\b",
                suffix[:forward_after.start()],
                re.I,
            ):
                continue
            binding = _PeriodBinding(
                f"FY{int(year_match)}",
                GuidancePeriodKind.FULL_YEAR,
                year_match,
                start,
                end,
            )
            if end <= anchor:
                candidates.append((0, anchor - end, binding))
            elif start >= mention_end:
                candidates.append((1, start - mention_end, binding))
            else:
                candidates.append((0, 0, binding))
    if not candidates:
        return None
    preceding = [item for item in candidates if item[0] == 0]
    pool = preceding or [item for item in candidates if item[0] == 1 and item[1] <= 160]
    if not pool:
        return None
    pool.sort(key=lambda item: (item[0], item[1], -item[2].start))
    best_direction, best_distance = pool[0][0], pool[0][1]
    tied = [item[2] for item in pool if item[0] == best_direction and item[1] == best_distance]
    periods = {item.period for item in tied}
    return tied[0] if len(periods) == 1 else None''',
    )

    text = replace_function(
        text,
        "_value_is_historical_actual",
        r'''def _value_is_historical_actual(clause: str, anchor: int, value) -> bool:
    if value is None:
        return False
    immediate_before = clause[max(0, value.start - 110):value.start]
    after = clause[value.end:min(len(clause), value.end + 120)]
    metric_to_value = clause[anchor:value.start] if value.start >= anchor else ""
    is_point = (
        value.low is not None
        and value.high is not None
        and abs(value.low - value.high) <= 1e-12
    )

    # A single reported point followed immediately by an up/down YoY result tail
    # is historical even if a later sentence in the same extracted clause raises
    # guidance. Preserve genuine point guidance when its own metric-to-value span
    # contains an explicit forward marker such as "expected".
    if (
        is_point
        and re.search(
            r"^\s*(?:,|;)?\s*(?:up|down)\s+\d+(?:\.\d+)?%\b"
            r"(?:\s+(?:YoY|Y/Y|year[- ]over[- ]year))?",
            after,
            re.I,
        )
        and not _EXPLICIT_FORWARD.search(metric_to_value)
    ):
        return True

    immediate_forward = bool(_EXPLICIT_FORWARD.search(immediate_before))
    if re.search(r"\bpreliminary(?:\s+unaudited)?\b", immediate_before, re.I) and not immediate_forward:
        return True

    start = max(0, min(anchor, value.start) - 180)
    before = clause[start:value.start]
    actuals = list(_ACTUAL_VALUE.finditer(before))
    if not actuals:
        return False
    latest_actual = actuals[-1]
    after_actual = before[latest_actual.end():]
    if _FORWARD_SIGNAL.search(after_actual):
        return False
    return len(before) - latest_actual.end() <= 140''',
    )

    path.write_text(text)


def patch_tests() -> None:
    path = ROOT / "backend/tests/test_guidance_raw_canonical_extractor.py"
    text = path.read_text()
    marker = "def test_semantic_v10_point_guidance_with_yoy_is_retained():"
    if marker not in text:
        text += r'''


def test_semantic_v10_point_guidance_with_yoy_is_retained():
    extraction = extract_canonical_typed_guidance_facts(
        _document(
            "POINTGUIDE",
            "FY 2026 guidance. Adjusted EBITDA is expected to be $102.6 million, up 11.5% year-over-year.",
        )
    )
    ebitda = [fact for fact in extraction.facts if fact.metric.value == "ebitda"]
    assert any(
        fact.fiscal_period == "FY2026"
        and fact.low == 102.6
        and fact.high == 102.6
        for fact in ebitda
    )
'''
    path.write_text(text)


patch_canonical_extractor()
patch_tests()
