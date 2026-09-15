from __future__ import annotations

import subprocess
from pathlib import Path


_EXTENSION_SOURCE_COMMIT = "b96fbe2f1e7a231ef9cb68c06e87c637963f2015"


def _extract_python_blocks(workflow: str) -> list[str]:
    marker = "          python - <<'PY'\n"
    end_marker = "\n          PY"
    blocks: list[str] = []
    cursor = 0
    while True:
        try:
            start = workflow.index(marker, cursor) + len(marker)
        except ValueError:
            break
        end = workflow.index(end_marker, start)
        lines = workflow[start:end].splitlines()
        blocks.append("\n".join(line[10:] if line.startswith("          ") else line for line in lines))
        cursor = end + len(end_marker)
    return blocks


def _normalize_embedded_role_helper(source: str) -> str:
    """Repair YAML-dedent damage inside the approved role-helper string only."""
    helper_start_marker = "role_helper = '''def _quoted_prior_locally_owns_value"
    helper_end_marker = "'''\nassert canonical.count(role_anchor) == 1"
    start = source.index(helper_start_marker)
    end = source.index(helper_end_marker, start)
    block = source[start:end]
    malformed = (
        "    if preceding:\n"
        "        owner = max(preceding, key=lambda item: item.end)\n"
        "        if owner.metric is not mention.metric:\n"
        "  return False\n"
        "    return anchor - absolute_marker_end <= 90\n"
    )
    corrected = (
        "    if preceding:\n"
        "        owner = max(preceding, key=lambda item: item.end)\n"
        "        if owner.metric is not mention.metric:\n"
        "            return False\n"
        "    return anchor - absolute_marker_end <= 90\n"
    )
    if malformed not in block:
        raise RuntimeError("approved role-helper dedent defect not found")
    block = block.replace(malformed, corrected, 1)
    return source[:start] + block + source[end:]


def _compat_survivor_payload(source: str) -> str:
    """Keep approved semantics while tolerating harmless live-source formatting drift."""
    source = _normalize_embedded_role_helper(source)

    brittle_money = "assert raw.count(old_money) == 1\nraw = raw.replace(old_money, new_money, 1)"
    structural_money = '''money_lines = new_money.rstrip("\\n").splitlines()
assert money_lines and money_lines[0].lstrip().startswith("for match in _MONEY_RANGE.finditer(clause):")
body_indents = [len(line) - len(line.lstrip()) for line in money_lines[1:] if line.strip()]
assert body_indents
body_shift = 12 - min(body_indents)
assert body_shift >= 0
normalized_money_lines = ["        " + money_lines[0].lstrip()]
for line in money_lines[1:]:
    if not line.strip():
        normalized_money_lines.append("")
        continue
    indent = len(line) - len(line.lstrip())
    normalized_money_lines.append(" " * (indent + body_shift) + line.lstrip())
normalized_money = "\\n".join(normalized_money_lines) + "\\n"
if raw.count(old_money) == 1:
    raw = raw.replace(old_money, normalized_money, 1)
else:
    money_marker = "        for match in _MONEY_RANGE.finditer(clause):\\n"
    single_marker = "        for match in _MONEY_SINGLE.finditer(clause):\\n"
    bind_start = raw.index("def _bind_value(clause: str, mention: _MetricMention, anchor: int)")
    start = raw.find(money_marker, bind_start)
    end = raw.find(single_marker, start)
    assert start >= 0 and end > start
    assert raw.find(money_marker, start + len(money_marker)) < 0
    raw = raw[:start] + normalized_money + raw[end:]
'''.rstrip()
    if brittle_money not in source:
        raise RuntimeError("approved money-range patch guard not found")
    source = source.replace(brittle_money, structural_money, 1)

    brittle_compact = "assert canonical.count(compact_old) == 1\ncanonical = canonical.replace(compact_old, compact_new, 1)"
    structural_compact = '''if canonical.count(compact_old) == 1:
    canonical = canonical.replace(compact_old, compact_new, 1)
else:
    fn_start = canonical.index("def _compact_metric_forward_guidance_value(clause: str, anchor: int, mention)")
    start_marker = '    s1 = (match.group("s1") or "").lower()\\n'
    end_marker = '    value_start = mention_end + match.start("lo")\\n'
    start = canonical.find(start_marker, fn_start)
    end = canonical.find(end_marker, start)
    assert start >= 0 and end > start
    assert canonical.find(start_marker, start + len(start_marker)) < 0
    canonical = canonical[:start] + compact_new + canonical[end:]
'''.rstrip()
    if brittle_compact not in source:
        raise RuntimeError("approved compact-range patch guard not found")
    source = source.replace(brittle_compact, structural_compact, 1)

    brittle_role = "assert canonical.count(role_old) == 1\ncanonical = canonical.replace(role_old, role_new, 1)"
    structural_role = '''if canonical.count(role_old) == 1:
    canonical = canonical.replace(role_old, role_new, 1)
else:
    extract_start = canonical.index("def extract_canonical_typed_guidance_facts(document: SourceDocument)")
    start_marker = "            role = GuidanceFactRole.CURRENT if pending_review or previous_now_value is not None else _fact_role(clause, value)\\n"
    end_marker = "            canonical_period = _canonical_period_binding(clause, anchor, mention)\\n"
    start = canonical.find(start_marker, extract_start)
    end = canonical.find(end_marker, start)
    assert start >= 0 and end > start
    assert canonical.find(start_marker, start + len(start_marker)) < 0
    canonical = canonical[:start] + role_new + canonical[end:]
'''.rstrip()
    if brittle_role not in source:
        raise RuntimeError("approved role-locality patch guard not found")
    source = source.replace(brittle_role, structural_role, 1)

    brittle_section = "assert canonical.count(section_use_anchor) == 1\ncanonical = canonical.replace(section_use_anchor, section_use_new, 1)"
    structural_section = '''if canonical.count(section_use_anchor) == 1:
    canonical = canonical.replace(section_use_anchor, section_use_new, 1)
else:
    extract_start = canonical.index("def extract_canonical_typed_guidance_facts(document: SourceDocument)")
    start_marker = "            section_period = _nearest_section_heading_period(segment, clause, anchor, mention)\\n"
    end_marker = "            compact_forward_period_owned = _compact_forward_period_is_owned(clause, compact_forward_value, period)\\n"
    start = canonical.find(start_marker, extract_start)
    end = canonical.find(end_marker, start)
    assert start >= 0 and end >= start
    assert canonical.find(start_marker, start + len(start_marker)) < 0
    end += len(end_marker)
    canonical = canonical[:start] + section_use_new + canonical[end:]
'''.rstrip()
    if brittle_section not in source:
        raise RuntimeError("approved annual-section patch guard not found")
    source = source.replace(brittle_section, structural_section, 1)

    brittle_local = "assert canonical.count(local_quarter_anchor) == 1\ncanonical = canonical.replace(local_quarter_anchor, local_quarter_new, 1)"
    structural_local = '''if canonical.count(local_quarter_anchor) == 1:
    canonical = canonical.replace(local_quarter_anchor, local_quarter_new, 1)
else:
    extract_start = canonical.index("def extract_canonical_typed_guidance_facts(document: SourceDocument)")
    start_marker = "            local_quarter_period_v29 = _local_explicit_quarter_before_value_v29(clause, anchor, mention, value)\\n"
    end_marker = "            strict_segment_quarter_v32 = _strict_segment_quarter_heading_v32(segment, clause, anchor, mention)\\n"
    start = canonical.find(start_marker, extract_start)
    end = canonical.find(end_marker, start)
    assert start >= 0 and end > start
    assert canonical.find(start_marker, start + len(start_marker)) < 0
    insertion = "            local_full_year_period = _local_full_year_phrase_before_value(clause, anchor, mention, value)\\n            if local_full_year_period is not None:\\n                period = local_full_year_period\\n"
    canonical = canonical[:end] + insertion + canonical[end:]
'''.rstrip()
    if brittle_local not in source:
        raise RuntimeError("approved local-full-year patch guard not found")
    return source.replace(brittle_local, structural_local, 1)


def _exec(source: str, label: str) -> None:
    try:
        exec(compile(source, label, "exec"), {})
    except AssertionError:
        import sys

        _, _, tb = sys.exc_info()
        while tb is not None and tb.tb_next is not None:
            tb = tb.tb_next
        lineno = tb.tb_lineno if tb is not None else 0
        lines = source.splitlines()
        lo = max(1, lineno - 5)
        hi = min(len(lines), lineno + 5)
        print(f"ASSERTION_CONTEXT {label} line={lineno}")
        for number in range(lo, hi + 1):
            marker = ">>" if number == lineno else "  "
            print(f"{marker} {number:04d}: {lines[number - 1]}")
        raise


def main() -> None:
    survivor = Path(".github/workflows/phase-1.1e-survivor-semantic-repair.yml").read_text()
    survivor_blocks = _extract_python_blocks(survivor)
    if not survivor_blocks:
        raise RuntimeError("approved survivor repair payload not found")
    source = _compat_survivor_payload(survivor_blocks[0])
    _exec(source, "<phase-1.1e-survivor-semantic-repair>")

    historical = subprocess.check_output(
        ["git", "show", f"{_EXTENSION_SOURCE_COMMIT}:.github/workflows/phase-1.1e-semantic-repair.yml"],
        text=True,
    )
    historical_blocks = _extract_python_blocks(historical)
    if len(historical_blocks) < 2:
        raise RuntimeError("approved semantic repair extension not found in historical source commit")
    _exec(historical_blocks[1], "<phase-1.1e-semantic-repair-extension>")


if __name__ == "__main__":
    main()
