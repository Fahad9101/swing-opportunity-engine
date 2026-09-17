from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_minimal_acceptance_repair_v4.py")
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
    "_canonical_segments",
    r'''def _canonical_segments(text: str):
    seen: set[str] = set()
    for segment in _segments(text):
        if segment not in seen:
            seen.add(segment)
            yield segment

    # The shared raw segment gate misses passive "is expected" prose. Do not
    # generalize that vocabulary here: the audited need is the explicit
    # breakeven-to-upper-bound guidance form only. This keeps population recall
    # anchored to published v5 while admitting that deterministic value form.
    normalized = re.sub(r"[ \t]+", " ", text.replace("\xa0", " "))
    for part in re.split(r"[\r\n]+|(?<=[.;])\s+(?=[A-Z0-9])", normalized):
        part = part.strip()
        if not (20 <= len(part) <= 1800) or part in seen:
            continue
        if not re.search(r"\bbreakeven\b", part, re.I):
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
        yield part''',
)

path.write_text(text)
