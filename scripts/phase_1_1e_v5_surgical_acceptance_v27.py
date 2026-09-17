from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v26.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()

helper_marker = "\ndef _fact_role(clause: str, value) -> GuidanceFactRole:\n"
helper = r'''
_PRIOR_ROLE_MARKER = re.compile(
    r"\b(?:from\s+(?:our\s+)?)?(?:prior|previous)(?:ly)?\b",
    re.I,
)


def _metric_local_fact_role(clause: str, anchor: int, mention, value) -> GuidanceFactRole:
    """Assign CURRENT/QUOTED_PRIOR using the marker owned by this metric.

    Flattened guidance lists often contain several metric rows, each with a
    parenthetical ``previous outlook``. A prior marker belonging to an earlier
    metric must not turn a later metric's current value into QUOTED_PRIOR.
    """
    if value is None:
        return GuidanceFactRole.CURRENT
    left = max(0, value.start - 180)
    markers = list(_PRIOR_ROLE_MARKER.finditer(clause, left, value.start))
    if not markers:
        return GuidanceFactRole.CURRENT
    mentions = _metric_mentions(clause)
    for marker in reversed(markers):
        # Marker after this metric mention directly owns the following value.
        if marker.start() >= anchor:
            return GuidanceFactRole.QUOTED_PRIOR
        # Marker before this metric owns it only if no *other* metric mention
        # intervenes. This preserves "previous FCF outlook of $350m" while
        # blocking an EPS previous-outlook marker from owning the next FCF row.
        intervening = [
            item for item in mentions
            if marker.end() <= item.start < anchor and item.metric is not mention.metric
        ]
        if not intervening:
            return GuidanceFactRole.QUOTED_PRIOR
    return GuidanceFactRole.CURRENT

'''
if "def _metric_local_fact_role(" not in text:
    count = text.count(helper_marker)
    if count != 1:
        raise RuntimeError(f"v27 role helper insertion: expected one marker, found {count}")
    text = text.replace(helper_marker, helper + helper_marker, 1)

old_role = "            role = GuidanceFactRole.CURRENT if previous_now_value is not None else _fact_role(clause, value)\n"
new_role = "            role = GuidanceFactRole.CURRENT if previous_now_value is not None else _metric_local_fact_role(clause, anchor, mention, value)\n"
count = text.count(old_role)
if count != 1:
    raise RuntimeError(f"v27 metric-local role selection: expected one match, found {count}")
path.write_text(text.replace(old_role, new_role, 1))

# Regressions for flattened multi-metric current/prior rows and genuine prior rows.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_prior_marker_for_eps_does_not_turn_following_fcf_current_into_prior_v27():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CLSV27",
        "2025 Annual Outlook Update\n"
        "Adjusted EPS (non-GAAP) of $5.50 (previous outlook $5.00) • "
        "Non-GAAP free cash flow of $400 million (previous outlook $350 million)",
    ))
    fcf400 = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 400_000_000.0]
    assert fcf400, ex.rejected_candidates
    assert all(f.role.value == "CURRENT" for f in fcf400), [(f.role.value, f.low, f.fiscal_period) for f in fcf400]


def test_explicit_previous_fcf_outlook_remains_quoted_prior_v27():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CLSV27PRIOR",
        "2025 Annual Outlook Update. Our previous non-GAAP free cash flow outlook of $350 million remains unchanged.",
    ))
    prior = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 350_000_000.0]
    assert prior, ex.rejected_candidates
    assert all(f.role.value == "QUOTED_PRIOR" for f in prior), [(f.role.value, f.low, f.fiscal_period) for f in prior]
''')
