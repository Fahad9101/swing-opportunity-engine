# Phase 1.1E Manual Audit — Final

- Contract: SOE-1.1E-SHADOW-V1
- Snapshot fingerprint: afcf5471f78d2a8946f5851108b8049b4ea282b3e2ba522f990f6f10362cd771
- Audit sample: 100
- Concordant: 90
- Discordant: 10
- Rule concordance: 90.0%
- Required concordance: 95.0%
- Systematic error detected: YES
- Final decision: **FAIL**

## Domain results

| Domain | Sample | Concordant | Discordant | Concordance |
|---|---:|---:|---:|---:|
| balance_sheet_distress | 39 | 39 | 0 | 100.0% |
| catalyst_materiality | 11 | 11 | 0 | 100.0% |
| catalyst_surprise | 19 | 19 | 0 | 100.0% |
| guidance | 31 | 21 | 10 | 67.7% |

## Discordant guidance cases

| Ticker | Engine path | Audit finding |
|---|---|---|
| COCO | `guidance_v1_1.explicit_lower_or_withdrawal` | Engine marked explicit LOWER, but the latest primary-source FY2026 outlook explicitly says the company is increasing full-year guidance. |
| WEAV | `guidance_v1_1.explicit_standing_no_guidance_policy` | Engine marked a standing no-guidance policy, but the cited release provides quantitative Q3 and full-year 2026 guidance. |
| CRS | `guidance_v1_1.material_numeric_cut` | Engine marked an FCF material cut by comparing incompatible fiscal periods; FY2026 FCF outlook was raised to ~$350m, while the later release initiates FY2027 FCF outlook of $400-$430m. |
| HNI | `guidance_v1_1.explicit_lower_or_withdrawal` | Engine marked explicit LOWER from prose about 'lower volume growth expectations'; the cited release does not state an explicit management action lowering guidance. |
| MUX | `guidance_v1_1.explicit_lower_or_withdrawal` | Engine marked explicit LOWER from operational/historical 'lower' language; the cited release provides 2026 production/cost outlook without an explicit current guidance-lowering action. |
| WDFC | `guidance_v1_1.explicit_lower_or_withdrawal` | Engine marked WITHDRAW, but the cited release explicitly updates/narrows FY2026 guidance; 'suspended' refers to a share-repurchase program, not guidance. |
| GH | `guidance_v1_1.material_numeric_cut` | Engine marked a material revenue cut, but primary-source revenue guidance increased from $1.30-$1.32b to $1.34-$1.36b. |
| BB | `guidance_v1_1.material_numeric_cut` | Engine marked a material adjusted-EBITDA cut, but FY2027 adjusted EBITDA guidance increased from $110-$130m to $119-$139m. |
| DXPE | `guidance_v1_1.comparable_set_within_tolerance` | Engine marked a comparable guidance set within tolerance, but the cited Q1/Q2 earnings releases contain no quantitative company guidance/outlook from which a comparable pair can be formed. |
| AMCR | `guidance_v1_1.comparable_set_within_tolerance` | Engine marked non-deteriorated, but FY2026 free-cash-flow guidance fell from $1.8-$1.9b to $1.5-$1.6b, far beyond the frozen 5% material-cut threshold. |

## Systematic defect

The failures are concentrated in the guidance extraction/assessment path. The pattern is not random:

1. Ordinary words such as **lower** or **suspended** near guidance-related prose can be interpreted as explicit guidance actions even when they refer to costs, volume expectations, or a share-repurchase program.
2. Fiscal-period binding can create invalid prior/current comparisons across different fiscal years.
3. Numeric guidance can be missed or bound to the wrong metric/period, producing both false material cuts and false non-deterioration decisions.
4. The deterministic distress, catalyst-materiality, and catalyst-surprise audit samples were fully concordant.

Under the preregistered contract, manual concordance below 95% fails the audit gate, and a systematic manual-audit error independently blocks activation.

## Governance disposition

- SOE-1.1.0 must **not** be promoted to the discovery/default model.
- SOE-1.0.0 remains the active frozen baseline.
- Milestone 3 remains blocked.
- No thresholds, weights, scanner gates, penalties, or market-regime rules should be tuned in response.
- The next corrective action is extraction-layer hardening for guidance context and fiscal-period binding, with targeted regression tests for the discordant cases, followed by a complete fresh Phase 1.1E rerun.
