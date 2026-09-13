from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).with_name("phase_1_1e_v5_surgical_acceptance_v24.py")
exec(compile(BASE.read_text(), str(BASE), "exec"), {"__name__": "__main__", "__file__": str(BASE)})

path = ROOT / "backend/app/services/guidance_raw_canonical_extractor.py"
text = path.read_text()

marker = '''            directional_section = {GuidanceAction.RAISE, GuidanceAction.LOWER, GuidanceAction.REAFFIRM}\n'''
insert = '''            # Narrow document-context recovery for flattened annual outlook rows.\n            # A current value explicitly paired with a previous outlook/guidance\n            # may inherit only a strict YYYY Annual/Financial Guidance/Outlook\n            # heading from the preceding full-document context. Generic FY\n            # headings remain excluded from this special fallback.\n            if period is None and value is not None and re.search(\n                r"\\bprevious(?:\\s+(?:non[- ]GAAP\\s+)?)?(?:outlook|guidance)\\b",\n                clause,\n                re.I,\n            ):\n                prior_pair_period = _document_heading_period(text, segment, clause, anchor, mention)\n                if (\n                    prior_pair_period is not None\n                    and prior_pair_period.kind is GuidancePeriodKind.FULL_YEAR\n                    and re.search(\n                        r"\\b20\\d{2}\\s+(?:annual|financial)\\s+(?:guidance|outlook)(?:\\s+update)?\\b",\n                        prior_pair_period.text,\n                        re.I,\n                    )\n                ):\n                    period = prior_pair_period\n'''
count = text.count(marker)
if count != 1:
    raise RuntimeError(f"v26 annual prior-pair insertion: expected one marker, found {count}")
path.write_text(text.replace(marker, insert + marker, 1))

# Realistic flattened-list regression: the annual heading falls outside the
# local segment because the FCF row is more than eight source lines later.
test_path = ROOT / "backend/tests/test_guidance_v5_surgical_acceptance.py"
with test_path.open("a") as fh:
    fh.write(r'''


def test_document_annual_heading_recovers_late_current_prior_fcf_pair_v26():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CLSV26",
        "2025 Annual Outlook Update\n"
        "Revenue outlook of $11.55 billion (previous outlook $10.85 billion)\n"
        "Adjusted operating margin outlook of 7.4% (previous outlook 7.2%)\n"
        "Adjusted EPS outlook of $5.50 (previous outlook $5.00)\n"
        "Tariff assumptions remain unchanged\n"
        "Demand assumptions remain unchanged\n"
        "Supply assumptions remain unchanged\n"
        "Tax assumptions remain unchanged\n"
        "Macro assumptions remain unchanged\n"
        "Non-GAAP free cash flow outlook of $400 million (previous outlook $350 million)\n",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 400.0]
    assert fcf, ex.rejected_candidates
    assert all(f.fiscal_period == "FY2025" for f in fcf), [(f.fiscal_period, f.low, f.high) for f in fcf]


def test_intervening_quarter_heading_blocks_annual_prior_pair_recovery_v26():
    ex = extract_canonical_typed_guidance_facts(_doc(
        "CLSV26NEG",
        "2025 Annual Outlook Update\n"
        "Revenue outlook of $11.55 billion (previous outlook $10.85 billion)\n"
        "Q3 2025 Guidance\n"
        "Non-GAAP free cash flow outlook of $400 million (previous outlook $350 million)\n",
    ))
    fcf = [f for f in ex.facts if f.metric.value == "fcf" and f.low == 400.0]
    assert not any(f.fiscal_period == "FY2025" for f in fcf), [(f.fiscal_period, f.low, f.high) for f in fcf]
''')
