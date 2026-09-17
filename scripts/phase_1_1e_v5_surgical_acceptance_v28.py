from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v26.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()

helper_marker = "\ndef _fact_role(clause: str, value) -> GuidanceFactRole:\n"
helper = r'''
_PRIOR_ROLE_OWNERSHIP_MARKER = re.compile(
    r"(?:\b(?:from\s+(?:our\s+)?)?prior(?:\s+[A-Za-z0-9*.-]+){0,5}\s+(?:guidance|outlook|forecast)\b"
    r"|\bprevious(?:\s+[A-Za-z0-9*.-]+){0,5}\s+(?:guidance|outlook|forecast)\b"
    r"|\bpreviously\s+(?:expected|forecast|guided|provided|stated)\b)",
    re.I,
)


def _quoted_prior_marker_owned_by_other_metric(clause: str, anchor: int, mention, value) -> bool:
    """Detect only cross-metric contamination of an already-QUOTED_PRIOR role.

    The original role parser remains authoritative. This helper is used only
    after it returned QUOTED_PRIOR. In flattened multi-metric outlook lists,
    an earlier row's ``previous outlook`` marker can otherwise leak into the
    next row's current value. We flip the role only when the latest qualifying
    prior marker is demonstrably owned by a different metric.
    """
    if value is None:
        return False
    left = max(0, value.start - 220)
    markers = list(_PRIOR_ROLE_OWNERSHIP_MARKER.finditer(clause, left, value.start))
    if not markers:
        return False
    mentions = _metric_mentions(clause)
    for marker in reversed(markers):
        # A marker at/after this metric mention belongs to the current row.
        if marker.start() >= anchor:
            return False
        # A marker phrase that itself names the current metric is also owned.
        if any(
            item.metric is mention.metric
            and not (item.end <= marker.start() or item.start >= marker.end())
            for item in mentions
        ):
            return False
        # Otherwise use the nearest metric immediately preceding the marker as
        # its owner. Only explicit ownership by a *different* metric is enough
        # to override the original QUOTED_PRIOR classification.
        preceding = [item for item in mentions if item.end <= marker.start()]
        if preceding:
            owner = max(preceding, key=lambda item: item.end)
            return owner.metric is not mention.metric
    return False

'''
if "def _quoted_prior_marker_owned_by_other_metric(" not in text:
    count = text.count(helper_marker)
    if count != 1:
        raise RuntimeError(f"v28 role helper insertion: expected one marker, found {count}")
    text = text.replace(helper_marker, helper + helper_marker, 1)

old_role = "            role = GuidanceFactRole.CURRENT if previous_now_value is not None else _fact_role(clause, value)\n"
new_role = '''            role = GuidanceFactRole.CURRENT if previous_now_value is not None else _fact_role(clause, value)\n            if (\n                role is GuidanceFactRole.QUOTED_PRIOR\n                and _quoted_prior_marker_owned_by_other_metric(clause, anchor, mention, value)\n            ):\n                role = GuidanceFactRole.CURRENT\n'''
count = text.count(old_role)
if count != 1:
    raise RuntimeError(f"v28 narrow role correction: expected one match, found {count}")
path.write_text(text.replace(old_role, new_role, 1))

# Realistic CLS regression: retain the recovered current $400m FCF fact, but
# do not let an earlier metric row's previous-outlook marker demote it to prior.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_flattened_prior_marker_from_earlier_metric_does_not_demote_fcf_current_v28():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CLSV28",
        "2025 Annual Outlook Update\n"
        "Revenue outlook of $11.55 billion (previous outlook $10.85 billion)\n"
        "Adjusted operating margin outlook of 7.4% (previous outlook 7.2%)\n"
        "Adjusted EPS outlook of $5.50 (previous outlook $5.00)\n"
        "Tariff assumptions remain unchanged\n"
        "Demand assumptions remain unchanged\n"
        "Supply assumptions remain unchanged\n"
        "Tax assumptions remain unchanged\n"
        "Macro assumptions remain unchanged\n"
        "Non-GAAP free cash flow outlook of $400 million (previous outlook $350 million)\n",
    ))
    fcf400 = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 400.0]
    assert fcf400, ex.rejected_candidates
    assert any(f.role.value == "CURRENT" and f.fiscal_period == "FY2025" for f in fcf400), [
        (f.role.value, f.fiscal_period, f.low, f.high) for f in fcf400
    ]
    assert not any(f.role.value == "QUOTED_PRIOR" for f in fcf400), [
        (f.role.value, f.fiscal_period, f.low, f.high) for f in fcf400
    ]
''')
