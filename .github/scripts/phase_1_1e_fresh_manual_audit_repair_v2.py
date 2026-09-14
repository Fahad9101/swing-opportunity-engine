from __future__ import annotations

import importlib.util
from pathlib import Path

PATCHER = Path(__file__).with_name("phase_1_1e_fresh_manual_audit_repair.py")
spec = importlib.util.spec_from_file_location("phase_1_1e_fresh_manual_audit_repair", PATCHER)
if spec is None or spec.loader is None:
    raise SystemExit("unable to load v34 repair patcher")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# The original temporary patcher was generated through nested raw strings and
# retained four backslashes for regex escapes. Normalize those generated source
# fragments to the single backslashes required by Python raw regex literals.
normalized = module.V34_CODE
normalized = normalized.replace(chr(92) * 2, chr(92))
normalized = normalized.replace(chr(92) * 2, chr(92))
module.V34_CODE = normalized
module.main()
