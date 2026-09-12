# Phase 1.1E Manual Audit — Round 4

Run: `33906976599`
Head: `6f325745c9689c31d31f0d8729a4875a728081e5`
Contract: `SOE-1.1E-SHADOW-V1`

## Result

**98/100 = 98.0% numeric concordance.**

The locked numeric threshold of >=95% is met, but **Phase 1.1E remains FAIL / activation blocked** because the contract separately requires no systematic audit errors. Two remaining guidance evidence-binding defects were confirmed.

## Domain results

| Domain | Concordant | Sample | Rate |
|---|---:|---:|---:|
| Balance-sheet distress | 30 | 30 | 100.0% |
| Catalyst materiality | 30 | 30 | 100.0% |
| Catalyst surprise/re-rating | 16 | 16 | 100.0% |
| Guidance | 22 | 24 | 91.7% |
| **Total** | **98** | **100** | **98.0%** |

## Confirmed discrepancies

### 1. ATRO — guidance fiscal-period binding

Engine classification: `NOT_DETERIORATED`, with one supposedly comparable pair.

Independent evidence:
- The prior source is 2025 guidance: Astronics raised the lower end of **2025** revenue guidance to $840–860 million from $820–860 million.
- The later source maintains an initial **2026** revenue guide of $950–990 million.

These are different fiscal years and must not form a comparable guidance pair. Correct manual result: **insufficient same-period comparable guidance / null**, not `NOT_DETERIORATED` from a FY2025-vs-FY2026 comparison.

Root-cause family: fiscal-period binding/comparability.

### 2. VG — guidance current/prior directional binding

Engine classification: `DETERIORATED`, citing a material cut.

Independent evidence:
- Q1 FY2026 source: consolidated adjusted EBITDA guidance $8.2–8.5 billion.
- Q2 FY2026 source: guidance explicitly **increased** to $8.7–9.1 billion from $8.2–8.5 billion.

Correct manual result: **NOT_DETERIORATED**. The engine reversed/misbound the economic direction/current side of the same-period guidance transition.

Root-cause family: current-vs-prior/directional guidance binding.

## Clean domains

### Balance-sheet distress — 30/30
All sampled classifications recomputed concordantly from the frozen corporate distress rules. Absolute-interest-coverage, net-cash safety, leverage/coverage safety, and negative-FCF-runway paths matched the evidence supplied by the SEC-derived distress inputs. No DY-style hypothetical/third-party covenant false positive recurred.

### Catalyst materiality — 30/30
All sampled events recomputed to the frozen ordinary earnings materiality score and had admissible SEC primary evidence representing completed financial results/earnings evidence. No BRZE-style future earnings scheduling notice or ILMN-style legal exhibit was admitted as completed quarterly earnings evidence.

### Catalyst surprise/re-rating — 16/16
All sampled scores recomputed from the frozen formula: quarterly-earnings outcome binaryity + expectation uncertainty + valuation concentration. No scoring-rule deviation was observed.

## Governance decision

**FAIL / BLOCKED despite 98% numeric concordance.**

Reason: `SOE-1.1E-SHADOW-V1` requires both >=95% manual rule concordance **and no systematic audit errors**. The two discrepancies are evidence-binding defects in the guidance pipeline, the same broad defect class that previously caused manual-audit failures. They therefore block activation.

Consequences:
- SOE-1.0.0 remains the active model.
- SOE-1.1.0 remains a shadow candidate.
- PR #16 remains draft/unmerged.
- Milestone 3 remains blocked.
- No threshold, weight, score, scanner, market-regime, SOE-1.0, or IEE logic is to be changed to address this result.

## Required repair

Evidence-layer repair only:
1. Fail closed unless current and prior guidance records share the exact normalized fiscal period before entering the comparable set.
2. For explicit raise/lower transitions, bind the current value to the semantic current side and enforce action-consistent monotonicity within the same fiscal period.
3. Add generic regressions reproducing ATRO-style cross-fiscal-year pairing and VG-style explicit-raise reversal.
4. Run deterministic CI, then a fresh same-snapshot full-market shadow validation and a new independent >=100-name audit.
