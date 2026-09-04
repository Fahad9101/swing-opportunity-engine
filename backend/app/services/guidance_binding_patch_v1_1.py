from __future__ import annotations

import re

from app.domain.soe_v1_1 import GuidanceMetric
from app.services import guidance_extraction_hardening_v1_1 as hardened


_original_infer_fiscal_period = hardened.infer_fiscal_period
_original_range_after_metric = hardened._range_after_metric
_installed = False

_SCALE = {
    "k": 1_000.0,
    "thousand": 1_000.0,
    "m": 1_000_000.0,
    "mm": 1_000_000.0,
    "million": 1_000_000.0,
    "b": 1_000_000_000.0,
    "bn": 1_000_000_000.0,
    "billion": 1_000_000_000.0,
}


def _amount(token: str, scale: str | None) -> float:
    value = float(token.replace(",", ""))
    if scale:
        value *= _SCALE.get(scale.lower().rstrip("."), 1.0)
    return value


def infer_fiscal_period(text: str, *, anchor: int) -> str | None:
    """Add common SEC shorthand such as 'fiscal 2027' without changing rules."""
    original = _original_infer_fiscal_period(text, anchor=anchor)
    shorthand = [
        (f"FY{int(match.group(1))}", match.start(), match.end())
        for match in re.finditer(r"\bfiscal\s+(20\d{2})\b", text, re.I)
    ]
    if not shorthand:
        return original

    def distance(item: tuple[str, int, int]) -> tuple[int, int, int]:
        _, start, end = item
        d = 0 if start <= anchor <= end else min(abs(start - anchor), abs(end - anchor))
        return d, 0 if start >= anchor else 1, start

    short = min(shorthand, key=distance)
    short_distance = distance(short)[0]
    if short_distance > 260:
        return original
    if original is None:
        return short[0]

    # Compare with the explicit-period result. Shorthand wins only when it is
    # materially closer to the metric, preventing a distant FY heading from
    # overriding a local 'fiscal 2027' statement.
    explicit_matches = []
    for pattern in (
        r"\b(?:FY|fiscal\s+year|full[-\s]?year)\s*(20\d{2})\b",
        r"\b(20\d{2})\s*(?:fiscal\s+year|full[-\s]?year)\b",
    ):
        for match in re.finditer(pattern, text, re.I):
            explicit_matches.append((f"FY{int(match.group(1))}", match.start(), match.end()))
    if not explicit_matches:
        return short[0]
    explicit = min(explicit_matches, key=distance)
    return short[0] if short_distance < distance(explicit)[0] else original


def _metric_start(text: str, metric: GuidanceMetric, metric_end: int) -> int | None:
    aliases = hardened._METRIC_ALIASES[metric]
    matches = []
    for alias in aliases:
        for match in re.finditer(rf"\b{re.escape(alias)}\b", text, re.I):
            if match.end() == metric_end:
                return match.start()
            matches.append(match)
    if not matches:
        return None
    nearest = min(matches, key=lambda match: abs(match.end() - metric_end))
    return nearest.start() if abs(nearest.end() - metric_end) <= 6 else None


def _preceding_range(text: str, metric: GuidanceMetric, *, metric_end: int):
    start = _metric_start(text, metric, metric_end)
    if start is None:
        return None
    prefix = text[max(0, start - 150) : start]

    # Require a tight grammatical link into the metric. This supports SEC prose
    # such as '$400M to $430M in adjusted free cash flow' but refuses a prior
    # result number separated by a sentence or unrelated noun phrase.
    if metric is GuidanceMetric.EPS:
        pattern = re.compile(
            r"\$\s*(?P<low>-?\d+(?:\.\d+)?)\s*(?:to|through|and|-|–|—)\s*\$?\s*(?P<high>-?\d+(?:\.\d+)?)"
            r"\s+(?:in|for|of)\s+(?:adjusted\s+|diluted\s+|non[-\s]?GAAP\s+|GAAP\s+)*$",
            re.I,
        )
        match = pattern.search(prefix)
        if not match:
            return None
        low, high = float(match.group("low")), float(match.group("high"))
        return (low, high, "USD/share") if low <= high else None

    if metric in {GuidanceMetric.GROSS_MARGIN, GuidanceMetric.OPERATING_MARGIN}:
        pattern = re.compile(
            r"(?P<low>\d{1,3}(?:\.\d+)?)\s*%\s*(?:to|through|and|-|–|—)\s*(?P<high>\d{1,3}(?:\.\d+)?)\s*%"
            r"\s+(?:in|for|of)\s+(?:adjusted\s+)?$",
            re.I,
        )
        match = pattern.search(prefix)
        if not match:
            return None
        low, high = float(match.group("low")) / 100, float(match.group("high")) / 100
        return (low, high, "fraction") if low <= high else None

    pattern = re.compile(
        r"(?P<d1>\$)?\s*(?P<low>\d[\d,]*(?:\.\d+)?)\s*(?P<s1>billion|million|thousand|bn|mm|[bmk])?\s*"
        r"(?:to|through|and|-|–|—)\s*(?P<d2>\$)?\s*(?P<high>\d[\d,]*(?:\.\d+)?)\s*(?P<s2>billion|million|thousand|bn|mm|[bmk])?"
        r"\s+(?:in|for|of)\s+(?:adjusted\s+|non[-\s]?GAAP\s+|GAAP\s+)*$",
        re.I,
    )
    match = pattern.search(prefix)
    if not match or not (match.group("d1") or match.group("d2") or match.group("s1") or match.group("s2")):
        return None
    shared = match.group("s2") or match.group("s1")
    low = _amount(match.group("low"), match.group("s1") or shared)
    high = _amount(match.group("high"), match.group("s2") or shared)
    return (low, high, "USD") if low <= high else None


def range_after_or_tightly_before_metric(text: str, metric: GuidanceMetric, *, metric_end: int):
    forward = _original_range_after_metric(text, metric, metric_end=metric_end)
    if forward is not None:
        return forward
    return _preceding_range(text, metric, metric_end=metric_end)


def install_binding_patch() -> None:
    global _installed
    if _installed:
        return
    hardened.infer_fiscal_period = infer_fiscal_period
    hardened._range_after_metric = range_after_or_tightly_before_metric
    _installed = True


def extract_guidance_facts_hardened(*args, **kwargs):
    install_binding_patch()
    return hardened.extract_guidance_facts_hardened(*args, **kwargs)


def dedupe_guidance_records(*args, **kwargs):
    install_binding_patch()
    return hardened.dedupe_guidance_records(*args, **kwargs)
