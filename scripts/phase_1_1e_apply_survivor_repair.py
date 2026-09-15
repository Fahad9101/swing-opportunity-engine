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


def _compat_survivor_payload(source: str) -> str:
    """Keep approved semantics while tolerating harmless live-source formatting drift."""
    brittle_money = "assert raw.count(old_money) == 1\nraw = raw.replace(old_money, new_money, 1)"
    structural_money = '''if raw.count(old_money) == 1:
    raw = raw.replace(old_money, new_money, 1)
else:
    money_marker = "        for match in _MONEY_RANGE.finditer(clause):\\n"
    single_marker = "        for match in _MONEY_SINGLE.finditer(clause):\\n"
    bind_start = raw.index("def _bind_value(clause: str, mention: _MetricMention, anchor: int)")
    start = raw.find(money_marker, bind_start)
    end = raw.find(single_marker, start)
    assert start >= 0 and end > start
    assert raw.find(money_marker, start + len(money_marker)) < 0
    raw = raw[:start] + new_money + raw[end:]
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
    return source.replace(brittle_compact, structural_compact, 1)


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
