# Phase 1.1E — run 83 complete investigation and repair batch

**Decision: FAIL. Engineering repaired; fresh market validation and independent acceptance are pending.** No activation or Milestone 3 approval is implied.

Audited workflow: [34308598710](https://github.com/Fahad9101/swing-opportunity-engine/actions/runs/34308598710), artifact `10090589843`, published code `e50ab936f6935d3aa39f68c2a9243c092541b2e7`. All eight workflow jobs succeeded and all nine automated gates passed. These outcomes do not override the source audit.

All **100** sampled entries were investigated, using **146** downloaded unique source files. The accompanying JSON records every entry, source URL/hash, finding and limitation. There are **22 guidance entries (43 cited documents), 23 distress entries, and 55 catalyst entries**. Guidance has **17 confirmed defective entries** and five entries with no discrepancy in the checked evidence. No entry receives acceptance sign-off from limited checks alone.

## Repairs

| Finding | Affected sampled names | Repair |
|---|---|---|
| Global dedupe undoes structured extraction | WMS, DDOG and explicit-scope records generally | Recognize explicit normalized evidence as authoritative so generic prose rebinding cannot discard metrics, rescale dollar values or replace fiscal scope. |
| Wrong column, product value or change amount | LINC, SUPN, DGX, VCEL | Select declared current columns and complete company totals. Separate GAAP/adjusted endpoints. Bind “raised by 10m to 326–336m” to the new range. |
| Quarter/year scope, loss signs or accounting basis | BFLY, ALKT, HPE, RSI, PL | Preserve explicit fiscal/ordinal quarter headers, adjusted aliases, signed loss bounds and annual FCF floors. Overlapping annual tokens inside quarter headings cannot open annual scopes. |
| Omitted primary metrics | SPGI, PLTR, HNGE, VRT, CWST | Retain stated FCF, operating margins, accompanying EPS and plural revenue labels. Compact tables handle M units and inline footnotes. Preserve separately stated reported EPS beside adjusted-only tables. |
| Costs or quarter EBITDA substituted for annual revenue/EBITDA | ZG | Reject the qualitative revenue/fixed-cost conflation; require corroborated quarter scope and stop the table before annual guidance. |

EE, BX, RARE, IRTC and BG have no discrepancy in the checked comparison or policy. BX explicitly states a standing policy of not providing expected quarterly/annual operating-result guidance. Its zero numeric records are consistent with the captured policy rule, not an extraction failure.

The evidence layer now serializes the exact post-dedupe ledger inputs and selected policy evidence into guidance metadata. Future reports can reproduce source timestamps, values, accounting bases and policy selection without reconstructing them from a list of URLs. This is an additive audit payload; no schema migration or business-rule change is introduced.

## Validation performed

- Full test suite: **590 passed, 0 failed**, two dependency deprecation warnings. This includes **24 new pipeline regression cases** and preserves the previous 566 tests.
- Tests exercise extraction through global dedupe and the frozen ledger, repeated-dedupe stability, source-defined accounting basis, negative cases, and serialization of numeric/policy evidence including provider failure metadata.
- All 43 run-83 guidance documents replayed through guarded extraction and global dedupe. Diagnostic timestamps are placeholders; this verifies source binding, not chronology or point-in-time acceptance.
- Prior run-82 (38 documents) and run-81 (28 documents) extraction replays also completed as regression diagnostics. These use the same implementation and do not supply independent acceptance evidence.
- All 23 distress checks match persisted rule arithmetic and a fresh SEC companyfacts replay for debt, net cash, leverage and interest coverage. The replay uses the production normalizer; it does not independently derive all XBRL values, FCF/runway, sector assignments or complete hard-flag coverage.
- All 55 catalyst score arithmetic checks agree with persisted inputs. Cited primary documents support earnings/results or periodic financial reporting. Future calendar dates and consensus inputs remain outside this independent check.

No manual concordance percentage is claimed. Negative or zero guidance midpoint handling remains the frozen classifier's responsibility; correct extraction can still yield UNKNOWN. No threshold is relaxed to turn coverage or classification green.

## Architecture and files

The batch changes four service files: `guidance_explicit_scope_normalizer_v1_1.py`, `guidance_declared_layout_normalizer_v1_1.py`, `phase_1_1e_guidance_table_dedupe_v1_1.py`, and `shadow_enrichment_service.py`. It adds `backend/tests/test_phase_1_1e_run83_pipeline_regressions.py` and this Markdown/JSON report pair under `validation/`.

Provider acquisition, persistence schema, screening, scoring, ranking/classification, API/UI and default model selection are unchanged. IEE v1.7.2 is untouched. Frozen hashes remain:

- Baseline: `59cc7ffe14472434bfbb92b07b89b0b48293d0c5762d5270769bce3b494550ac`
- Candidate: `bcd0bd71b53a242b4e9d143525d6cd3ea1e0550ae27cca1788540250bf9468ca`

## Providers, debt and exact next step

Run 83 captured 5,153 symbols and 2,317 universal survivors. There were 76 fully scored candidate names; guidance coverage was 99/100, distress 114/114, and materiality/surprise 113/113. The run recorded eight baseline provider errors and 12 enrichment errors without crashing the market scan. These are pre-repair measurements. Sources remain free/public; no paid provider or Docker installation is required.

Technical debt remains in layered source-layout adapters and in independent validation of chronology, filing-selection completeness, distress derivations and calendar/consensus inputs. The new ledger evidence makes future audits more reproducible but does not retroactively prove those inputs.

**Next step: run Phase 1.1E full-market shadow validation on the published repair commit, then investigate its complete required audit sample and resolve all findings before acceptance.** Keep PR #16 draft. Phase 1.1E remains open until validation succeeds; SOE-1.1 activation and Milestone 3 require separate approval.
