from __future__ import annotations

from pathlib import Path

SOURCE = Path(__file__).with_name("phase_1_1e_v5_minimal_acceptance_repair.py")
text = SOURCE.read_text()
old = '''    next_start = text.find("\\ndef ", start + 1)\n    if next_start < 0:\n        raise RuntimeError(f"{name}: next function boundary not found")\n    return text[:start] + new_source.rstrip() + "\\n\\n" + text[next_start + 1:]\n'''
new = '''    next_start = text.find("\\ndef ", start + 1)\n    if next_start < 0:\n        return text[:start] + new_source.rstrip() + "\\n"\n    return text[:start] + new_source.rstrip() + "\\n\\n" + text[next_start + 1:]\n'''
if text.count(old) != 1:
    raise RuntimeError("expected one replace_function boundary block")
text = text.replace(old, new, 1)
exec(compile(text, str(SOURCE), "exec"), {"__name__": "__main__", "__file__": str(SOURCE)})
