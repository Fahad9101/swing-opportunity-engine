from __future__ import annotations

from textwrap import dedent, indent

import phase_1_1e_semantic_repair as repair


def replace_once(text: str, old: str, new: str, label: str) -> str:
    old0 = dedent(old).lstrip("\n")
    new0 = dedent(new).lstrip("\n")
    candidates: list[tuple[str, str]] = [(old0, new0)]
    for spaces in (4, 8, 12, 16, 20):
        prefix = " " * spaces
        candidates.append((indent(old0, prefix), indent(new0, prefix)))
    matches = [(candidate_old, candidate_new) for candidate_old, candidate_new in candidates if text.count(candidate_old) == 1]
    if len(matches) != 1:
        counts = [text.count(candidate_old) for candidate_old, _ in candidates]
        raise RuntimeError(f"{label}: expected one indentation-aware match, counts={counts}")
    candidate_old, candidate_new = matches[0]
    return text.replace(candidate_old, candidate_new, 1)


repair.replace_once = replace_once
repair.patch_canonical_extractor()
repair.patch_typed_extractor()
repair.patch_replay_report()
repair.patch_tests()
