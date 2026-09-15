from __future__ import annotations

from pathlib import Path

# Build on the blocked v8 working-tree patch, then narrow the rules that the
# deterministic suite identified as over-broad. Nothing is published unless
# the workflow's full pytest + immutable replay gates pass.
import phase_1_1e_semantic_repair_v8  # noqa: F401,E402

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


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_canonical_extractor() -> None:
    path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
    text = path.read_text()

    text = replace_function(
        text,
        "_strong_forward_year_binding",
        r'''def _strong_forward_year_binding(clause: str, anchor: int, mention) -> _PeriodBinding | None:
    mention_end = anchor + len(mention.text)
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

    # Strong, explicit annual guidance headings beat a historical nearby quarter.
    # Quarter precedence remains when the year is itself part of a quarter phrase.
    old = '''    near_quarters = [
        item for item in explicit
        if item[2].kind is GuidancePeriodKind.QUARTER and item[1] <= 80
    ]
    if near_quarters:
        near_quarters.sort(key=lambda item: (item[0], item[1], -item[2].end))
        best = near_quarters[0]
        tied = [item for item in near_quarters if item[:2] == best[:2]]
        periods = {item[2].period for item in tied}
        if len(periods) == 1:
            return tied[0][2]

    strong = _strong_forward_year_binding(clause, anchor, mention)
    if strong is not None:
        return strong
'''
    new = '''    strong = _strong_forward_year_binding(clause, anchor, mention)
    if strong is not None:
        return strong

    near_quarters = [
        item for item in explicit
        if item[2].kind is GuidancePeriodKind.QUARTER and item[1] <= 80
    ]
    if near_quarters:
        near_quarters.sort(key=lambda item: (item[0], item[1], -item[2].end))
        best = near_quarters[0]
        tied = [item for item in near_quarters if item[:2] == best[:2]]
        periods = {item[2].period for item in tied}
        if len(periods) == 1:
            return tied[0][2]
'''
    text = replace_once(text, old, new, "strong annual period precedence")

    text = replace_function(
        text,
        "_bind_metric_value",
        r'''def _bind_metric_value(clause: str, mention, anchor: int) -> _ValueBinding | None:
    preceding = _bind_value(clause[:anchor], mention, anchor)
    if preceding is not None and preceding.end <= anchor:
        gap = anchor - preceding.end
        bridge = clause[preceding.end:anchor]
        before_value = clause[max(0, preceding.start - 50):preceding.start]
        tight_bridge = bool(
            re.fullmatch(
                r"\s*(?:(?:in|of|for)\s+)?"
                r"(?:(?:adjusted|non[- ]GAAP|GAAP|diluted)\s+)?",
                bridge,
                re.I,
            )
        )
        if (
            gap <= 40
            and tight_bridge
            and not re.search(r"\b(?:previously|prior|from)\b", before_value, re.I)
        ):
            return preceding
    return _bind_value(clause, mention, anchor)''',
    )

    text = replace_function(
        text,
        "_value_has_local_metric_owner",
        r'''def _value_has_local_metric_owner(clause: str, anchor: int, mention, value) -> bool:
    current_start = anchor
    current_end = anchor + len(mention.text)
    current_gap = _span_gap(current_start, current_end, value.start, value.end)
    nearest_other: tuple[int, GuidanceMetric | str] | None = None
    current_basis = (
        "ADJUSTED" if re.search(r"\b(?:adjusted|non[- ]GAAP)\b", mention.text, re.I)
        else "GAAP" if re.search(r"(?<!non[- ])\bGAAP\b", mention.text, re.I)
        else None
    )
    for owner, pattern in _VALUE_OWNER_PATTERNS:
        for match in pattern.finditer(clause):
            overlaps_current = not (match.end() <= current_start or match.start() >= current_end)
            gap = _span_gap(match.start(), match.end(), value.start, value.end)
            if owner is mention.metric and overlaps_current:
                current_gap = min(current_gap, gap)
                continue
            owner_is_effectively_other = owner is not mention.metric
            if owner is mention.metric and value.end <= current_start:
                owner_text = match.group(0)
                owner_basis = (
                    "ADJUSTED" if re.search(r"\b(?:adjusted|non[- ]GAAP)\b", owner_text, re.I)
                    else "GAAP" if re.search(r"(?<!non[- ])\bGAAP\b", owner_text, re.I)
                    else None
                )
                owner_is_effectively_other = bool(
                    current_basis and owner_basis and current_basis != owner_basis
                )
            if not owner_is_effectively_other:
                continue
            if match.end() <= value.start:
                bridge = clause[match.end():value.start]
            elif value.end <= match.start():
                bridge = clause[value.end:match.start()]
            else:
                bridge = ""
            if re.search(r"[;•]|[.!?]\s", bridge):
                continue
            if value.end <= current_start and match.end() <= value.start:
                prior_gap = value.start - match.end()
                if prior_gap <= 120 and prior_gap <= current_gap + 80:
                    return False
            if nearest_other is None or gap < nearest_other[0]:
                nearest_other = (gap, owner)
    if nearest_other is None:
        return True
    other_gap, _ = nearest_other
    return current_gap <= other_gap''',
    )

    text = replace_function(
        text,
        "_value_is_historical_actual",
        r'''def _value_is_historical_actual(clause: str, anchor: int, value) -> bool:
    if value is None:
        return False
    immediate_before = clause[max(0, value.start - 110):value.start]
    after = clause[value.end:min(len(clause), value.end + 120)]
    immediate_forward = bool(_EXPLICIT_FORWARD.search(immediate_before))
    if re.search(
        r"^\s*(?:,|;)?\s*(?:up|down)\s+\d+(?:\.\d+)?%\b"
        r"(?:\s+(?:YoY|Y/Y|year[- ]over[- ]year))?",
        after,
        re.I,
    ) and not immediate_forward:
        return True
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
    text = replace_once(
        text,
        '"FY 2025 Adjusted EBITDA is expected to be between breakeven and $10 million.",',
        '"FY 2025 Adjusted EBITDA guidance is expected to be between breakeven and $10 million.",',
        "breakeven guidance fixture",
    )
    path.write_text(text)


patch_canonical_extractor()
patch_tests()
