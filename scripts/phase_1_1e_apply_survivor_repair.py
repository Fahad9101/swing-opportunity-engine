"""Verify the materialized survivor repair; never patch production at run time.

The reviewed repair now lives in the production modules and regression suite.
Historical YAML-embedded payloads are no longer an executable source of truth.
"""
from __future__ import annotations

import py_compile
from pathlib import Path


REPAIR_FILES = (
    "backend/app/services/guidance_raw_typed_extractor.py",
    "backend/app/services/guidance_raw_canonical_extractor.py",
    "backend/app/services/guidance_semantic_ownership_service.py",
    "backend/tests/test_guidance_survivor_semantic_regressions.py",
)


def main() -> None:
    for filename in REPAIR_FILES:
        if not Path(filename).is_file():
            raise RuntimeError(f"Materialized survivor repair is missing: {filename}")
        py_compile.compile(filename, doraise=True)
    print("Materialized survivor repair compiles; semantic and full-suite gates follow.")


if __name__ == "__main__":
    main()
