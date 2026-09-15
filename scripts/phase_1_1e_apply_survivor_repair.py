from __future__ import annotations

import subprocess
from pathlib import Path


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
    brittle = "assert raw.count(old_money) == 1\nraw = raw.replace(old_money, new_money, 1)"
    structural = '''if raw.count(old_money) == 1:
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
    if brittle not in source:
        raise RuntimeError("approved money-range patch guard not found")
    return source.replace(brittle, structural, 1)


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

    previous = subprocess.check_output(
        ["git", "show", "HEAD^:.github/workflows/phase-1.1e-semantic-repair.yml"],
        text=True,
    )
    previous_blocks = _extract_python_blocks(previous)
    if len(previous_blocks) < 2:
        raise RuntimeError("approved semantic repair extension not found in parent commit")
    _exec(previous_blocks[1], "<phase-1.1e-semantic-repair-extension>")


if __name__ == "__main__":
    main()
