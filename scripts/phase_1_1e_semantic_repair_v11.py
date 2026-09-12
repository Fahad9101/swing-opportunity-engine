from __future__ import annotations

from pathlib import Path

# v11 keeps the now-green v10 period ownership logic and only makes the
# historical single-point YoY tail detector robust to value spans that end
# before the printed scale token (e.g. numeric span before "million").
import phase_1_1e_semantic_repair_v10  # noqa: F401,E402

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


path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()
text = replace_function(
    text,
    "_value_is_historical_actual",
    r'''def _value_is_historical_actual(clause: str, anchor: int, value) -> bool:
    if value is None:
        return False
    immediate_before = clause[max(0, value.start - 110):value.start]
    after = clause[value.end:min(len(clause), value.end + 140)]
    metric_to_value = clause[anchor:value.start] if value.start >= anchor else ""
    is_point = (
        value.low is not None
        and value.high is not None
        and abs(value.low - value.high) <= 1e-12
    )

    # SEC/press-release result prose often binds the numeric token separately
    # from its printed scale. Accept either span shape, but only when the value
    # is a single point, the YoY result tail is immediate, and this metric's own
    # path to the value contains no forward marker such as "expected".
    if is_point and not _EXPLICIT_FORWARD.search(metric_to_value):
        result_tail = after[:90]
        if re.match(
            r"^\s*(?:(?:million|billion|thousand|bn|mm|m|b)\b\s*)?"
            r"(?:,|;)?\s*(?:up|down)\s+\d+(?:\.\d+)?%\b"
            r"(?:\s+(?:YoY|Y/Y|year[- ]over[- ]year))?",
            result_tail,
            re.I,
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
