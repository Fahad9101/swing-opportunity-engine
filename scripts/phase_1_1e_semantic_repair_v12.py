from __future__ import annotations

from pathlib import Path

# v12 builds on the green v10 period/locality repairs and the v11 value-tail
# hardening, but fixes the final defect at its actual boundary: a later
# guidance sentence must not bind backward to a metric/value in a completed
# historical-results sentence.
import phase_1_1e_semantic_repair_v11  # noqa: F401,E402

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

helper_marker = "\ndef _metric_action("
if "def _metric_forward_context(" not in text:
    idx = text.find(helper_marker)
    if idx < 0:
        raise RuntimeError("metric forward-context insertion point not found")
    helper = r'''
def _metric_forward_context(clause: str, anchor: int, mention) -> bool:
    current_start = anchor
    current_end = anchor + len(mention.text)
    left = max(0, current_start - 160)
    right = min(len(clause), current_end + 220)
    local = clause[left:right]

    for match in _EXPLICIT_FORWARD.finditer(local):
        start = left + match.start()
        end = left + match.end()

        # Forward language after the current metric can own it only within the
        # same sentence. A completed sentence followed by a new guidance
        # heading/action belongs to what follows, not to the historical metric
        # behind it. Semicolons remain admissible because compact guidance
        # tables commonly use them inside one sentence.
        if start >= current_end:
            bridge = clause[current_end:start]
            if re.search(r"[.!?](?:\s|$)", bridge):
                continue

        # A forward heading before the metric may legitimately govern the next
        # sentence/row (e.g. "2026 Guidance. Revenue ..."), so do not impose
        # the same punctuation restriction in the forward direction.
        if end <= current_start:
            return True

        return True
    return False
'''
    text = text[:idx] + helper + text[idx:]

text = replace_function(
    text,
    "_metric_action",
    r'''def _metric_action(segment: str, clause: str, anchor: int, mention) -> GuidanceAction:
    local = clause[max(0, anchor - 140): min(len(clause), anchor + len(mention.text) + 180)]
    has_forward_context = _metric_forward_context(clause, anchor, mention)
    directional = _owned_directional_action(clause, anchor, mention.text, mention.metric)
    if directional is not GuidanceAction.NONE:
        return directional if has_forward_context else GuidanceAction.NONE
    local_action = _action(local)
    if local_action is GuidanceAction.INITIATE and has_forward_context:
        return local_action
    # Directional actions found only in a later completed sentence must not be
    # inherited backward. Conversely, a preceding guidance heading can govern
    # the current metric and remains admissible through owned forward context.
    if local_action in {
        GuidanceAction.RAISE,
        GuidanceAction.LOWER,
        GuidanceAction.REAFFIRM,
        GuidanceAction.WITHDRAW,
    }:
        return local_action if has_forward_context else GuidanceAction.NONE
    segment_action = _action(segment)
    if segment_action is GuidanceAction.INITIATE and has_forward_context:
        return segment_action
    return GuidanceAction.NONE''',
)

old = "            explicit_forward = _explicit_forward_context(local)\n"
new = "            explicit_forward = _metric_forward_context(clause, anchor, mention)\n"
if text.count(old) != 1:
    raise RuntimeError(f"owned forward-context extraction site: expected one match, found {text.count(old)}")
text = text.replace(old, new, 1)

path.write_text(text)
