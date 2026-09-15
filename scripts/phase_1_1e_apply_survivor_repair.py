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
    # The first approved repair batch is retained verbatim in the temporary
    # survivor workflow. Treat it only as a payload file; it is intentionally
    # not executed by GitHub Actions as YAML.
    survivor = Path(".github/workflows/phase-1.1e-survivor-semantic-repair.yml").read_text()
    survivor_blocks = _extract_python_blocks(survivor)
    if not survivor_blocks:
        raise RuntimeError("approved survivor repair payload not found")
    _exec(survivor_blocks[0], "<phase-1.1e-survivor-semantic-repair>")

    # The immediately preceding commit contains the approved extension for
    # post-period actuals and parenthesized loss signs. Extract the second
    # embedded Python payload before the registered workflow is simplified.
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
