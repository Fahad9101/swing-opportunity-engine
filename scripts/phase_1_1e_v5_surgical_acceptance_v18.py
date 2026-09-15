from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v17.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


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


helper_marker = "\ndef _value_starts_inside_period_token_v17(clause: str, value) -> bool:\n"
helper = r'''
def _owned_value_conflicts_with_adjacent_metric_v18(clause: str, anchor: int, mention, value) -> bool:
    """Reject an owned shortcut only when another metric clearly owns its value.

    This is intentionally narrower than the general locality heuristic because
    compact suffix tables legitimately place several metrics close together.
    Hard punctuation boundaries isolate compact cells. A different metric owns
    the candidate when it is directly attached (for example ``Revenue of $X``)
    or materially closer to the value than the current metric.
    """
    if value is None:
        return False
    current_start = anchor
    current_end = anchor + len(mention.text)
    current_gap = _span_gap(current_start, current_end, value.start, value.end)
    for owner, pattern in _VALUE_OWNER_PATTERNS:
        if owner is mention.metric:
            continue
        for match in pattern.finditer(clause):
            if not (match.end() <= value.start or match.start() >= value.end):
                return True
            if match.end() <= value.start:
                between = clause[match.end():value.start]
            else:
                between = clause[value.end:match.start()]
            if re.search(r"[.;•!?]", between):
                continue
            gap = _span_gap(match.start(), match.end(), value.start, value.end)
            if gap <= 18 and re.fullmatch(r"\s*(?:(?:of|at)\s*)?[:,-]?\s*", between, re.I):
                return True
            if gap <= 36 and gap + 8 < current_gap:
                return True
    return False

'''
if "def _owned_value_conflicts_with_adjacent_metric_v18(" not in text:
    text = replace_once(text, helper_marker, "\n" + helper + helper_marker.lstrip("\n"), "insert v18 owned-value guard")

# Only explicit flattened table headers such as "Current Guidance Q1 ... Fiscal
# Year ... <metric> <one value>" are fail-closed. Ordinary prose may mention a
# historical quarter and later annual guidance in the same sentence.
text = replace_function(
    text,
    "_ambiguous_compact_multi_period_table_v17",
    r'''def _ambiguous_compact_multi_period_table_v17(clause: str, anchor: int, mention, value) -> bool:
    if value is None:
        return False
    left = max(0, anchor - 220)
    right = min(len(clause), value.end + 40)
    local = clause[left:right]
    if not re.search(r"\bcurrent\s+guidance\b", local, re.I):
        return False

    quarters: list[tuple[int, int]] = []
    full_years: list[tuple[int, int]] = []
    for pattern in _CANONICAL_QUARTER:
        for match in pattern.finditer(local):
            if left + match.end() <= value.start:
                quarters.append((left + match.start(), left + match.end()))
    for pattern in _CANONICAL_FULL_YEAR:
        for match in pattern.finditer(local):
            if left + match.end() > value.start:
                continue
            span = (left + match.start(), left + match.end())
            if any(qs <= span[0] and span[1] <= qe for qs, qe in quarters):
                continue
            full_years.append(span)
    if not quarters or not full_years:
        return False
    nearest_q = min(value.start - end for _, end in quarters)
    nearest_fy = min(value.start - end for _, end in full_years)
    return nearest_q <= 140 and nearest_fy <= 140''',
)

# An immediate "Record revenue" label is realized-result language even when an
# unrelated outlook phrase appears earlier in the same headline. Preserve true
# "expects record revenue" guidance by checking the short lead-in to Record.
old_result_branch = '''    # Immediate realized-result verbs/labels. ``expects to deliver`` remains\n    # forward because the local forward cue prevents this branch.\n    if not local_forward and re.search(\n        r"\\b(?:record(?:ed)?|reports?|reported|deliver(?:s|ed|ing)?|generated|"\n        r"achieved|realized)\\b[^.;•!?]{0,90}$",\n        local_before,\n        re.I,\n    ):\n        return True\n'''
new_result_branch = '''    record_matches = list(re.finditer(r"\\brecord(?:ed)?\\b[^.;•!?]{0,90}$", local_before, re.I))\n    if record_matches:\n        record = record_matches[-1]\n        lead = local_before[max(0, record.start() - 32):record.start()]\n        if not _FORWARD_SIGNAL.search(lead):\n            return True\n\n    # Other realized-result verbs remain protected by a local forward cue so\n    # phrases such as "expects to deliver" stay forward-looking.\n    if not local_forward and re.search(\n        r"\\b(?:reports?|reported|deliver(?:s|ed|ing)?|generated|achieved|realized)\\b[^.;•!?]{0,90}$",\n        local_before,\n        re.I,\n    ):\n        return True\n'''
text = replace_once(text, old_result_branch, new_result_branch, "v18 record-result ownership")

# Replace v17's global owned-value locality enforcement with a two-tier check:
# generic values keep the mature locality rule, while owned compact values use
# the narrow adjacent-other-metric conflict rule and may rebound once.
old_locality = '''            if value is not None and not _value_has_local_metric_owner(clause, anchor, mention, value):\n                rebound = _bind_value(clause, mention, anchor)\n                rebound = _prefer_same_sentence_value(clause, anchor, mention, rebound)\n                rebound = _normalize_margin_level(clause, anchor, mention, rebound)\n                if rebound is not None and rebound != value and _value_has_local_metric_owner(clause, anchor, mention, rebound):\n                    value = rebound\n                    owned_value = None\n                else:\n                    rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if value is not None and _value_starts_inside_period_token_v17(clause, value):\n'''
new_locality = '''            if value is not None and owned_value is not None and _owned_value_conflicts_with_adjacent_metric_v18(clause, anchor, mention, value):\n                rebound = _bind_value(clause, mention, anchor)\n                rebound = _prefer_same_sentence_value(clause, anchor, mention, rebound)\n                rebound = _normalize_margin_level(clause, anchor, mention, rebound)\n                if rebound is not None and rebound != value and _value_has_local_metric_owner(clause, anchor, mention, rebound):\n                    value = rebound\n                    owned_value = None\n                else:\n                    rejected.append({"reason": "owned_metric_value_cross_owner", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if value is not None and owned_value is None and not _value_has_local_metric_owner(clause, anchor, mention, value):\n                rejected.append({"reason": "metric_value_locality", "metric": mention.metric.value, "value_text": value.text, "evidence": clause[:500]}); continue\n            if value is not None and _value_starts_inside_period_token_v17(clause, value):\n'''
text = replace_once(text, old_locality, new_locality, "v18 narrow owned-value locality")

path.write_text(text)
