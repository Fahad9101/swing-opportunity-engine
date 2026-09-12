# Phase 1.1E Manual Audit — Round 3 Final

**Contract:** SOE-1.1E-SHADOW-V1  
**Workflow run:** 33894726477  
**Audited head:** `977247c9eab54263fed4a052116a98244024a1db`  
**Captured snapshot:** `fbc73771af655b98668718c3f4a1cc84f946f5aa99f1d05dfef0cb30e17be1c8`  
**Candidate rules hash:** `bcd0bd71b53a242b4e9d143525d6cd3ea1e0550ae27cca1788540250bf9468ca`  
**Sampling:** Deterministic random shuffle seeded by captured snapshot SHA-256; first N classifications selected without score/outcome filtering.

## Final decision

**FAIL — 81/100 concordant (81.0%)**

The locked minimum is **95/100**, and activation also requires **no systematic audit errors**. Both conditions are violated.

SOE-1.0 remains the active discovery model. SOE-1.1 is not promoted. PR #16 must remain unmerged. Milestone 3 remains blocked.

## Domain results

| Domain | Concordant | Sample | Concordance |
|---|---:|---:|---:|
| Guidance | 29 | 46 | 63.04% |
| Balance-sheet distress | 19 | 20 | 95.00% |
| Catalyst materiality | 14 | 15 | 93.33% |
| Catalyst surprise/re-rating | 19 | 19 | 100.00% |
| **Total** | **81** | **100** | **81.00%** |

## Discordant cases

| Ticker | Domain | Engine | Independent adjudication | Root cause |
|---|---|---|---|---|
| VOYG | guidance | True | UNKNOWN / insufficient evidence | `guidance_historical_actual_contamination` |
| CDNS | guidance | True | False | `guidance_directional_current_prior_binding` |
| TTMI | guidance | False | UNKNOWN / insufficient evidence | `guidance_cross_quarter_comparison` |
| KMT | guidance | False | UNKNOWN / insufficient evidence | `guidance_cross_fiscal_year_comparison` |
| DUOL | guidance | True | False | `guidance_directional_current_prior_binding` |
| KTB | guidance | False | UNKNOWN / insufficient evidence | `guidance_scope_horizon_mismatch` |
| MYRG | guidance | False | UNKNOWN / insufficient evidence | `guidance_historical_actual_contamination` |
| TVTX | guidance | True | UNKNOWN / insufficient evidence | `guidance_historical_actual_contamination` |
| DASH | guidance | False | UNKNOWN / insufficient evidence | `guidance_cross_quarter_comparison` |
| DY | balance_sheet_distress | True | False | `distress_covenant_context_binding` |
| MIR | guidance | True | False | `guidance_directional_current_prior_binding` |
| MWH | guidance | True | False | `guidance_directional_current_prior_binding` |
| CVNA | guidance | False | UNKNOWN / insufficient evidence | `guidance_invented_comparable_prior` |
| ROKU | guidance | False | UNKNOWN / insufficient evidence | `guidance_cross_fiscal_year_comparison` |
| ZG | guidance | True | UNKNOWN / insufficient evidence | `guidance_cross_quarter_comparison` |
| AUPH | guidance | False | UNKNOWN / insufficient evidence | `guidance_cross_fiscal_year_comparison` |
| BRZE | catalyst_materiality | 8 | UNKNOWN / insufficient evidence | `catalyst_scheduling_notice_as_results` |
| DELL | guidance | True | False | `guidance_directional_current_prior_binding` |
| ALAB | guidance | True | UNKNOWN / insufficient evidence | `guidance_cross_quarter_comparison` |

## Systematic defect families

1. **Guidance directional/current-vs-prior binding (5):** CDNS, DUOL, MIR, MWH, DELL. Same-period guidance was raised or remained within frozen tolerances, but the evidence layer reversed or misbound current/prior numeric values.
2. **Cross-quarter guidance comparison (4):** TTMI, DASH, ZG, ALAB. Different fiscal quarters were treated as comparable.
3. **Cross-fiscal-year guidance comparison (3):** KMT, ROKU, AUPH. Different fiscal years were treated as comparable.
4. **Historical actuals admitted as guidance (3):** VOYG, MYRG, TVTX.
5. **Guidance scope/horizon mismatch (1):** KTB. Consolidated annual guidance was compared with segment/long-term target evidence.
6. **Invented quantitative prior (1):** CVNA. Current quantitative FY2026 EBITDA guidance was paired against prior qualitative/actual evidence despite no verified same-period quantitative prior.
7. **Distress covenant-context binding (1):** DY. Customer-contract default language was misclassified as a registrant covenant/default event.
8. **Catalyst evidence type (1):** BRZE. A future earnings-release scheduling notice was accepted as completed primary earnings evidence.

## Representative evidence findings

- **DY:** the captured evidence says customer contracts can be cancelled regardless of whether the company is in default; it does not establish a registrant covenant breach. The same filing states covenant compliance. This is a context-binding error.
- **BRZE:** the selected SEC exhibit announces that results will be released later. It is not completed quarterly-earnings evidence.
- **DUOL:** FY2026 revenue and adjusted EBITDA increased, yet the engine classified both as material cuts.
- **MWH:** full-year revenue guidance increased from $3.72–3.82B to $3.87–3.97B, yet the engine classified a revenue cut.
- **DELL:** FY2027 revenue and GAAP/non-GAAP EPS guidance increased materially, yet the engine classified an EPS cut.
- **CVNA:** Q4 2025 and Q1 2026 evidence contain qualitative FY2026 growth outlook; Q2 first supplies quantitative FY2026 adjusted EBITDA of $2.7–3.0B. Missing same-period quantitative prior should remain UNKNOWN.

## Governance outcome

This audit is a hard activation blocker. No scoring threshold, scanner gate, weight, penalty, market-regime rule, SOE-1.0 rule, or IEE rule may be changed to improve this result.

The next repair must be limited to evidence extraction/binding/validation:
- issuer-specific covenant/default subject binding;
- completed-results versus scheduling-notice validation;
- strict same-fiscal-period guidance comparability;
- consolidated/segment/horizon scope binding;
- historical-actual exclusion;
- current/prior directional numeric binding;
- explicit missing-prior preservation as UNKNOWN.

Each of the 19 failures requires a deterministic regression. All prior regression tests remain mandatory, followed by a new full same-snapshot Phase 1.1E run and a fresh independent >=100-name audit.
