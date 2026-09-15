from __future__ import annotations

from textwrap import dedent, indent

import phase_1_1e_semantic_repair as repair


def replace_once(text: str, old: str, new: str, label: str) -> str:
    old0 = dedent(old).lstrip("\n")
    new0 = dedent(new).lstrip("\n")
    matches: list[tuple[int, str, str]] = []
    for spaces in (0, 4, 8, 12, 16, 20):
        if spaces:
            candidate_old = indent(old0, " " * spaces)
            candidate_new = indent(new0, " " * spaces)
        else:
            candidate_old, candidate_new = old0, new0
        if text.count(candidate_old) == 1:
            matches.append((spaces, candidate_old, candidate_new))
    if not matches:
        raise RuntimeError(f"{label}: no indentation-aware match")
    _, candidate_old, candidate_new = max(matches, key=lambda item: item[0])
    return text.replace(candidate_old, candidate_new, 1)


repair.replace_once = replace_once
repair.patch_canonical_extractor()
repair.patch_typed_extractor()
repair.patch_replay_report()
repair.patch_tests()
