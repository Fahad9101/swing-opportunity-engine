from __future__ import annotations

from pathlib import Path

# v13 keeps v12's sentence-boundary ownership rule, but restores the prior
# metric-specific action discipline and records historical candidates before
# the no-forward-context early exit.
import phase_1_1e_semantic_repair_v12  # noqa: F401,E402

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
    "_metric_action",
    r'''def _metric_action(segment: str, clause: str, anchor: int, mention) -> GuidanceAction:
    local = clause[max(0, anchor - 140): min(len(clause), anchor + len(mention.text) + 180)]
    has_forward_context = _metric_forward_context(clause, anchor, mention)

    # Directional actions are owned only through the existing metric-aware
    # binder. Do not fall back to _action(local) for RAISE/LOWER/etc., because
    # that would let one metric's action bleed into a later metric in the same
    # compact sentence/table.
    directional = _owned_directional_action(clause, anchor, mention.text, mention.metric)
    if directional is not GuidanceAction.NONE:
        return directional if has_forward_context else GuidanceAction.NONE

    local_action = _action(local)
    if local_action is GuidanceAction.INITIATE and has_forward_context:
        return local_action

    segment_action = _action(segment)
    if segment_action is GuidanceAction.INITIATE and has_forward_context:
        return segment_action
    return GuidanceAction.NONE''',
)

old = '''            explicit_forward = _metric_forward_context(clause, anchor, mention)\n            local_action = _metric_action(segment, clause, anchor, mention)\n            if not explicit_forward and local_action is GuidanceAction.NONE:\n                continue\n'''
new = '''            explicit_forward = _metric_forward_context(clause, anchor, mention)\n            local_action = _metric_action(segment, clause, anchor, mention)\n            if not explicit_forward and local_action is GuidanceAction.NONE:\n                # Preserve the semantic audit trail for historical actuals even\n                # when the later guidance sentence no longer (correctly) gives\n                # this metric forward ownership.\n                preliminary_value = _bind_metric_value(clause, mention, anchor)\n                if preliminary_value is not None and _value_is_historical_actual(clause, anchor, preliminary_value):\n                    rejected.append({\n                        "reason": "historical_actual",\n                        "metric": mention.metric.value,\n                        "value_text": preliminary_value.text,\n                        "evidence": clause[:500],\n                    })\n                continue\n'''
if text.count(old) != 1:
    raise RuntimeError(f"historical early-exit audit patch: expected one match, found {text.count(old)}")
text = text.replace(old, new, 1)
path.write_text(text)
