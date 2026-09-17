# Phase 1.1E survivor audit: a8a77d8

**Semantic acceptance failed; structural gates passed.**

Reviewed all 246 ledger records across 24 classified survivors, plus BX policy evidence. This is an exhaustive ledger-span review, not a completed independent full-document acceptance audit. There were 32 rows with fetch errors and zero extraction exceptions.

| Survivor | Ledger records | Finding |
|---|---:|---|
| ACMR | 10 | FAIL: 1–2 preliminary FY2025 results published January 2026; 8 subsidiary RMB range downgraded to qualitative company guidance. Original SEC sources corroborate both. |
| ANDG | 5 | No numeric, period, role or scope defect identified in the five evidence spans. |
| APPF | 7 | Prior rounded midpoint removed. No new value defect; increasing-range action remains implicit rather than RAISE. |
| ATMU | 8 | Numeric/period ownership consistent. Explicit heading actions are incompletely propagated; no clean action-concordance claim. |
| AUPH | 8 | Numeric, period and scope evidence consistent; duplicate qualitative and numeric reaffirmations retained. |
| BX | 0 | Policy evidence now present: issuer explicitly does not provide quarterly/annual guidance. Artifact supplies URL, date and evidence span; independent full-document withdrawal search not completed. |
| CDNA | 18 | Previous current/prior defects resolved. Historical withdrawals now quoted prior. Repeated expectation statements incorrectly assert INITIATE; batch normalizes unproven initiation. |
| CECO | 20 | FAIL: 11 results-quarter headline becomes guidance; 15 prior EBITDA range loses prior ownership at page break. Original SEC source confirms 115–135 is previous, not current, guidance. |
| DXCM | 21 | Percentage interval and directional action repairs visible. No new numeric or period defect in 21 spans. |
| ESI | 16 | FAIL: 5 prior quarter EBITDA interval inherits following annual period. Expectation statements also overstate initiation. |
| ETON | 10 | Historical results and annual run-rate removed. Threshold-style guidance remains represented as a point under existing extractor convention; no exact-endpoint acceptance claim. |
| FLY | 5 | Numeric/period evidence consistent; expectation alone incorrectly asserts INITIATE. |
| FROG | 14 | All 14 revenue records have consistent numeric and quarter/year evidence. |
| GKOS | 25 | Current FY2026 role repaired; 25 records reviewed without another numeric/period defect. |
| HTFL | 4 | Truncated $21 removed and current gross-margin role repaired; four remaining spans consistent. |
| IRTC | 11 | Revenue basis repair visible. Record 0 is the high endpoint of a quoted prior range represented as a point; unresolved endpoint semantics. |
| ISRG | 6 | Six percentage ranges now complete and fiscal periods consistent; expectation alone incorrectly asserts INITIATE. |
| LB | 12 | FAIL: 9 duplicates annual EBITDA as Q1; bare year/metric/footnote owner is explicit. Reaffirmation repair visible. |
| LOAR | 5 | Five spans reviewed; no new numeric/role defect. Forward-year scope of narrative-only heading still requires full-source corroboration. |
| NVCR | 4 | Current negative EBITDA role/sign correct; four spans consistent. |
| OMDA | 7 | Annual versus quarter/comparator duplicates removed; expectation statements overstate initiation. |
| ORCL | 5 | EPS 8.05 and reaffirmed prior-current role repaired. One-sided revenue floor remains represented as a point under existing convention. |
| PTRN | 14 | Prior revenue comparison no longer relabels current EBITDA; all 14 spans numerically and temporally consistent. |
| TIC | 11 | FAIL: 1 risk-list maintain profitability leaks to FCF; 9 compound run-and-maintain in historical revenue mix becomes reaffirmation. |

Provenance, exact record indices and replay identity are in `survivor-audit-a8a77d8.json`.

The next generic batch addresses source-page prior ownership, relative-quarter and explicit year/metric period conflicts, unowned qualitative actions, unsupported currencies, preliminary completed-year results, and unsupported initiation actions. Ten new regressions accompany the batch. One-sided threshold conventions and source corroboration remain acceptance work; a new 432 replay must be audited on its exact SHA.

PR #17 remains draft/unmerged. Frozen SOE rules and IEE are unchanged. No full-market gate or 100-case audit is accepted.
