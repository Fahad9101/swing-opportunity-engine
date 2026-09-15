from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance.py")
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
    prefix_start = max(0, anchor - 90)
    prefix = clause[prefix_start:anchor]
    boundary = max(prefix.rfind(";"), prefix.rfind("•"), prefix.rfind("."))
    local = prefix[boundary + 1:]

    # Compact tables often put the accounting-basis adjective between the
    # value cell and the metric label, e.g. "$138.5-$141.5 million Adjusted EBITDA".
    # Treat only these basis qualifiers as transparent ownership bridges.
    basis_tail = re.search(r"\s+(?:adjusted|non[- ]GAAP|GAAP)\s*$", local, re.I)
    value_local = local[:basis_tail.start()] if basis_tail else local
    match = _SUFFIX_MONEY_RANGE.search(value_local)
    if not match:
        return None

    absolute_start = prefix_start + boundary + 1 + match.start()
    absolute_end = prefix_start + boundary + 1 + match.end()
    bridge = clause[absolute_end:anchor]
    if len(bridge) > 32 or not re.fullmatch(
        r"[\s,:()]*(?:(?:adjusted|non[- ]GAAP|GAAP)\s*)?",
        bridge,
        re.I,
    ):
        return None

    unit = _unit_from_scale(
        match.group("scale"),
        mention.metric,
        dollar=bool(match.group("d1") or match.group("d2")),
    )
    if unit is GuidanceUnit.UNKNOWN:
        return None
    low = float(match.group("lo").replace(",", ""))
    high = float(match.group("hi").replace(",", ""))
    if low > high:
        return None
    return _ValueBinding(
        low, high, unit, GuidanceValueKind.ABSOLUTE_LEVEL,
        match.group(0).strip(), absolute_start, absolute_end,
    )''',
)

path.write_text(text)
