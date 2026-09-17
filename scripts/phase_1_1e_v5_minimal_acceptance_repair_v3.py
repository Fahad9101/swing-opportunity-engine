from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_minimal_acceptance_repair_v2.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()


def replace_function(source: str, name: str, new_source: str) -> str:
    marker = f"\ndef {name}("
    start = source.find(marker)
    if start < 0:
        raise RuntimeError(f"{name}: function start not found")
    start += 1
    next_start = source.find("\ndef ", start + 1)
    if next_start < 0:
        return source[:start] + new_source.rstrip() + "\n"
    return source[:start] + new_source.rstrip() + "\n\n" + source[next_start + 1:]


text = replace_function(
    text,
    "_suffix_owned_money_range",
    r'''def _suffix_owned_money_range(clause: str, anchor: int, mention) -> _ValueBinding | None:
    candidates: list[_ValueBinding] = []
    for match in _SUFFIX_MONEY_RANGE.finditer(clause):
        if match.end() > anchor:
            continue
        bridge = clause[match.end():anchor]
        # A suffix-owned compact table cell may contain whitespace, commas,
        # colons or parentheses between value and metric. It must never cross
        # a semicolon/bullet/sentence boundary into a different metric cell.
        if len(bridge) > 24 or not re.fullmatch(r"[\s,:()]*", bridge):
            continue
        scale = match.group("s2") or match.group("s1")
        dollar = bool(match.group("d1") or match.group("d2"))
        unit = _unit_from_scale(scale, mention.metric, dollar=dollar)
        if unit is GuidanceUnit.UNKNOWN:
            continue
        low = float(match.group("lo").replace(",", ""))
        high = float(match.group("hi").replace(",", ""))
        if low > high:
            continue
        candidates.append(
            _ValueBinding(
                low,
                high,
                unit,
                GuidanceValueKind.ABSOLUTE_LEVEL,
                match.group(0),
                match.start(),
                match.end(),
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: anchor - item.end)
    return candidates[0]''',
)

text = replace_function(
    text,
    "_local_guidance_year_before_value",
    r'''def _local_guidance_year_before_value(clause: str, value) -> _PeriodBinding | None:
    if value is None:
        return None
    left = max(0, value.start - 210)
    prefix = clause[left:value.start]
    years = list(re.finditer(r"\b20\d{2}\b", prefix))
    candidates: list[_PeriodBinding] = []
    for idx, year_match in enumerate(years):
        next_year_start = years[idx + 1].start() if idx + 1 < len(years) else len(prefix)
        after_year = prefix[year_match.end():next_year_start]
        before_year = prefix[max(0, year_match.start() - 80):year_match.start()]

        # Forward ownership must belong to this year token itself. Do not let an
        # older comparison year greedily span across a newer fiscal year into
        # that newer year's Guidance/Outlook heading.
        forward_after = re.search(r"\b(?:guidance|outlook)\b", after_year, re.I)
        forward_before = re.search(r"\b(?:guidance|outlook)\b[^.;•]{0,60}$", before_year, re.I)
        if not forward_after and not forward_before:
            continue
        if forward_after and forward_after.start() > 70:
            continue
        if re.search(r"\b(?:prior|previous|comparison|compared)\b", before_year[-45:], re.I):
            continue

        absolute_start = left + year_match.start()
        absolute_end = left + year_match.end()
        candidates.append(
            _PeriodBinding(
                f"FY{int(year_match.group(0))}",
                GuidancePeriodKind.FULL_YEAR,
                year_match.group(0),
                absolute_start,
                absolute_end,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: value.start - item.end)
    return candidates[0]''',
)

# Add a narrowly scoped supplement for explicit company forward statements that
# the shared raw segment gate misses because it recognizes "expects" but not
# the passive "is/are expected to be" construction.
insert_before = "\ndef _canonical_period_binding("
helper = r'''
def _canonical_segments(text: str):
    seen: set[str] = set()
    for segment in _segments(text):
        if segment not in seen:
            seen.add(segment)
            yield segment

    normalized = re.sub(r"[ \t]+", " ", text.replace("\xa0", " "))
    for part in re.split(r"[\r\n]+|(?<=[.;])\s+(?=[A-Z0-9])", normalized):
        part = part.strip()
        if not (20 <= len(part) <= 1800) or part in seen:
            continue
        if not re.search(r"\b(?:is|are)\s+expected\s+to\s+be\b", part, re.I):
            continue
        if not _metric_mentions(part):
            continue
        has_period = any(pattern.search(part) for pattern in (*_CANONICAL_FULL_YEAR, *_CANONICAL_QUARTER))
        has_period = has_period or bool(_CANONICAL_YEAR_QUARTER.search(part))
        if not has_period:
            continue
        seen.add(part)
        yield part

'''
pos = text.find(insert_before)
if pos < 0:
    raise RuntimeError("canonical segment insertion point not found")
if "def _canonical_segments(" not in text:
    text = text[:pos] + helper + text[pos:]

old_loop = "    for segment in _segments(text):\n"
if text.count(old_loop) != 1:
    raise RuntimeError(f"expected one canonical segment loop, found {text.count(old_loop)}")
text = text.replace(old_loop, "    for segment in _canonical_segments(text):\n", 1)

old_values = '''            breakeven_value = _breakeven_value(clause, anchor, mention)\n            suffix_value = _suffix_owned_money_range(clause, anchor, mention)\n            value = previous_now_value or directional_value or breakeven_value or suffix_value or _bind_value(clause, mention, anchor)\n            explicit_prior = previous_now_prior or directional_prior\n'''
new_values = '''            breakeven_value = _breakeven_value(clause, anchor, mention)\n            suffix_value = _suffix_owned_money_range(clause, anchor, mention)\n            owned_value = previous_now_value or directional_value or breakeven_value or suffix_value\n            value = owned_value or _bind_value(clause, mention, anchor)\n            explicit_prior = previous_now_prior or directional_prior\n'''
if text.count(old_values) != 1:
    raise RuntimeError("owned-value selection block not found exactly once")
text = text.replace(old_values, new_values, 1)

old_locality = '''            if value is not None and not _value_has_local_metric_owner(clause, anchor, mention, value):\n                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
new_locality = '''            if value is not None and owned_value is None and not _value_has_local_metric_owner(clause, anchor, mention, value):\n                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n'''
if text.count(old_locality) != 1:
    raise RuntimeError("locality block not found exactly once")
text = text.replace(old_locality, new_locality, 1)

path.write_text(text)
