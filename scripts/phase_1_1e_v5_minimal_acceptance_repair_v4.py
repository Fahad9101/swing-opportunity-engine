from __future__ import annotations

from pathlib import Path

SOURCE = Path(__file__).with_name("phase_1_1e_v5_minimal_acceptance_repair_v3.py")
text = SOURCE.read_text()
old = '''old_loop = "    for segment in _segments(text):\\n"\nif text.count(old_loop) != 1:\n    raise RuntimeError(f"expected one canonical segment loop, found {text.count(old_loop)}")\ntext = text.replace(old_loop, "    for segment in _canonical_segments(text):\\n", 1)\n'''
new = '''old_loop = "    for segment in _segments(text):\\n"\nextractor_start = text.find("\\ndef extract_canonical_typed_guidance_facts(")\nif extractor_start < 0:\n    raise RuntimeError("canonical extractor function not found for segment-loop patch")\nloop_at = text.find(old_loop, extractor_start)\nif loop_at < 0:\n    raise RuntimeError("canonical extractor segment loop not found")\ntext = text[:loop_at] + "    for segment in _canonical_segments(text):\\n" + text[loop_at + len(old_loop):]\n'''
if text.count(old) != 1:
    raise RuntimeError("expected one v3 segment-loop patch block")
text = text.replace(old, new, 1)
exec(compile(text, str(SOURCE), "exec"), {"__name__": "__main__", "__file__": str(SOURCE)})
