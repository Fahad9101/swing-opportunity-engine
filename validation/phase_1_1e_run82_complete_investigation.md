# Phase 1.1E: run 82 complete investigation and combined repair

Run **34219223992**, artifact **10057882884**, code **5ec53e54b04448381a8b56c448a346398994def4** fails the source audit. Investigation continued through all 100 sampled entries. All 164 distinct cited source files are available; the JSON records source hashes, per-entry findings, and the limits of each check. Thirteen of the 19 guidance entries contain confirmed extraction defects. This is a defect count, not a count of incorrect final classifications.

## Combined findings

| Cause | Sample tickers | Repair |
| --- | --- | --- |
| Product or adjacent metric values substituted | RARE, MSCI, DT | Prefer explicit total revenue; require complete metric labels immediately before values; exclude EBITDA expense; preserve actual FCF and operating margin. |
| Quarter, annual, or historical year confused | RBRK, MSI | Keep annual and quarterly sections separate; historical growth comparisons cannot open a new forecast scope. |
| Prior/current/actual columns and units confused | OPLN, WMS | Require declared column order and units. WMS's unchanged guidance must not become a material cut through missing million-dollar scaling. |
| Primary metrics omitted | TEM, RELY, GRMN, ALSN | Retain forward EBITDA points, explicit range clauses, comma-formatted amounts, operating margins and accompanying annual metrics. Pro forma EPS becomes adjusted EPS only when the issuer expressly defines it as non-GAAP. |
| Accounting bases share the wrong value | HUM | Bind GAAP and adjusted EPS to their separate explicit lower bounds. |
| Historical forecast treated as a new update | ECG | Respect the explicit statement that the forecast is neither reaffirmed nor updated today; persist a rejection reason and do not emit new policy evidence. |

The six other guidance entries are CXT, ACMR, MWH, KGS, PGY and IRTC. Their checked comparisons show no confirmed discrepancy. Discretionary cash flow, revenue plus other income, gross margin and EBITDA margin are not silently reinterpreted as the approved primary metrics.

## What the checks establish

- **19 guidance entries:** source values and layouts reviewed in both cited documents; 13 defective entries repaired as one batch. Replayed all 38 source documents through guarded extraction after repairs. Diagnostic replay dates are placeholders; the replay does not certify chronology or point-in-time classifications.
- **31 distress entries:** independent arithmetic on persisted inputs agrees with the recorded classification. Same-day downloaded SEC companyfacts replay reproduces debt, net cash, leverage and interest coverage with no differences. This uses the production normalizer and is not an independent XBRL derivation. It does not certify all sector assignments, FCF/runway inputs or completeness of hard-flag discovery.
- **50 catalyst entries:** all score arithmetic agrees with recorded earnings inputs. Cited primary documents support completed earnings/results or periodic financial reporting. These checks do not independently certify the future Nasdaq calendar dates or the captured consensus inputs.

No manual acceptance concordance percentage or activation sign-off is manufactured from these differently scoped checks. Run 82 remains FAIL even though its nine automated gates pass.

## Engineering and tests

Two normalization helpers and the existing Phase 1.1E wrapper contain the source-binding repairs. No provider acquisition, schema, screening, scoring, ranking, classification, API, UI, default runtime selection, frozen rule file, or IEE change is included.

- Full suite: **566 passed, 0 failed**, two existing dependency deprecation warnings.
- **18 new regression cases**, including source metric separation, fiscal scope, units, current-column selection, omitted values, source-defined accounting basis, and negative cases.
- All 38 run-82 guidance documents replayed after the repair; all 28 prior run-81 guidance documents also replayed to check previously repaired layouts.
- Both frozen rule hashes match the audit artifact and the existing contract.

Files changed: `backend/app/services/guidance_explicit_scope_normalizer_v1_1.py`, `backend/app/services/guidance_declared_layout_normalizer_v1_1.py`, `backend/app/services/phase_1_1e_guidance_table_normalizer_v1_1.py`, `backend/tests/test_guidance_declared_layout_normalizer_v1_1.py`, and the two run-82 investigation reports in `validation/`.

## Provider status and remaining work

Run 82 captured 5,150 symbols, with 2,316 universal survivors and 78 fully scored candidate names. Guidance coverage was 92/93 (98.92%), distress 113/113, and materiality/surprise 110/110. These are pre-repair run-82 metrics, not measurements of the repaired code.

Providers remain free/public. The run recorded 16 baseline provider errors and 13 enrichment errors. The latter include 12 duplicated malformed historical INOD submission entries (six distinct old rows with no primary document) and one failed PR exhibit request. No provider failure crashed the market scan. Paid data is not required or introduced.

Technical debt remains in layered, explicitly bounded source-layout adapters and in independent verification of calendar/consensus inputs, distress inputs and filing selection. Provider errors need to remain visible in validation evidence. The next step is a fresh **Phase 1.1E full-market shadow run and complete independent acceptance audit** against the repaired commit. Phase 1.1E is not complete until acceptance succeeds. Do not activate SOE-1.1 or start Milestone 3 without separate approval.
