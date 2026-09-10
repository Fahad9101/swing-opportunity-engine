# Phase 1.1E — run 84 complete investigation and repair batch

**Decision: FAIL. Repair tests pass; fresh market validation and independent acceptance remain pending.** SOE-1.1 is not activated and Milestone 3 is not approved.

Audited workflow: [34388856577](https://github.com/Fahad9101/swing-opportunity-engine/actions/runs/34388856577), artifact `10124684666`, published code `61becac44f19c258c6ffbe034e733d1f7d650380`. All eight jobs succeeded and all nine automated gates passed. The source audit still found defects.

The entire **100-entry queue** was investigated: **24 guidance, 22 distress and 54 catalyst entries**. Retrieval covered **243 unique source files**, including every historical source in the newly persisted guidance ledger. **16 guidance entries have confirmed extraction defects**, including historical defects where the latest comparison itself agrees. Eight guidance entries have no discrepancy in the checked comparison. The JSON report preserves all entries, captured ledger values, source hashes, diagnostic replay and limitations. No limited-scope check receives acceptance sign-off.

## Repair batch

| Defect | Sampled names | Engineering change |
|---|---|---|
| Product forecasts replacing company totals | PTCT, GH | Reject explicitly excluded product-only totals and screening revenue as consolidated revenue. |
| Fiscal scope, historical results, prior ranges | ANDG, BG, STRL, COCO, CDNA, NVT, PCOR | Preserve explicit annual/quarter scope, reject half-year and completed-period rebinding, separate prior EPS clauses, retain stated GAAP basis and operating-margin scope. |
| Wrong columns, endpoint units or signs | FLEX, LINC, ANDG, OPLN, GH, RBRK, BKSY | Select revised columns, convert mixed declared endpoint units, recognize M units, retain negative FCF/loss bounds and zero breakeven bounds. Contradictory issuer forecast years cause abstention. |
| Omitted explicit metrics | FLEX, TEM, PLTR, OPLN, COCO, CDNA, NVT | Support colon rows, accompanying annual forecasts, point estimates, inline footnotes, separately reported EPS/EBITDA and quarterly estimates. |

ECG, LB, ACMR, DGX, GKOS, RARE, ATMU and EE have no discrepancy in their checked comparisons. This does not certify exhaustive extraction from every possible document or layout.

## Tests and validation scope

- Full local suite: **611 passed, 0 failed**, two dependency deprecation warnings; **21 new regression tests** preserve the prior 590 passing tests.
- Regression tests exercise the guarded extraction/global-dedupe pipeline with source-transcribed positive and negative cases. They do not change frozen classification behavior.
- Every cited guidance document was replayed through production extraction and global dedupe. Matching ledger timestamps are retained; sources without a matching row use a diagnostic fallback and the form is diagnostic 8-K. This checks binding, not independent chronology, classification or source-discovery completeness.
- All **22 distress** arithmetic checks agree with persisted inputs; SEC companyfacts replay agrees for checked debt, net cash, leverage and interest coverage. Production-normalizer replay is not independent XBRL derivation. FCF/runway, sector routing, full hard-flag coverage and point-in-time source selection remain uncertified.
- All **54 catalyst** arithmetic checks agree with persisted inputs and cited documents support earnings/results or periodic financial reporting. Future calendar dates, consensus completeness and point-in-time filing selection remain uncertified.
- No manual concordance percentage is claimed. Negative guidance midpoint handling remains with the frozen classifier and may still produce UNKNOWN.

## Architecture and files

Two normalization services change: `backend/app/services/guidance_explicit_scope_normalizer_v1_1.py` and `backend/app/services/guidance_declared_layout_normalizer_v1_1.py`. The batch adds `backend/tests/test_phase_1_1e_run84_regressions.py` and this Markdown/JSON report pair under `validation/`.

No provider interface, persistence schema, screening, scoring, ranking/classification, API/UI or runtime model selection changes are introduced. IEE v1.7.2 remains untouched. Frozen rule hashes:

- Baseline: `59cc7ffe14472434bfbb92b07b89b0b48293d0c5762d5270769bce3b494550ac`
- Candidate: `bcd0bd71b53a242b4e9d143525d6cd3ea1e0550ae27cca1788540250bf9468ca`

## Providers, debt and exact next step

Run 84 captured **5,153 symbols**, **2,317 universal survivors** and **99 fully scored candidate names**. Guidance coverage was **104/106 (98.11%)**, distress **113/113**, and catalyst materiality/surprise **156/156**. Three baseline provider errors and 12 enrichment errors were isolated without crashing the scan. These measurements precede this repair batch. Data remains free/public, including SEC filings/companyfacts and official Nasdaq directories; no paid provider or Docker installation is required.

Technical debt remains in layered layout adapters, exhaustive presentation extraction, historical identical GAAP/unspecified duplicates, independent chronology/source selection, full distress derivation and calendar/consensus validation. This complete queue investigation must not be represented as complete independent acceptance.

**Exact next step: run full-market Phase 1.1E shadow validation on the published repair commit, investigate its complete required audit sample and resolve remaining findings before acceptance.** Keep PR #16 draft. The next milestone is completion of Phase 1.1E acceptance, not SOE-1.1 activation or Milestone 3; either subsequent advancement requires approval.
