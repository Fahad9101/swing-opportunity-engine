# Phase 1.1E survivor review: 24d77f2

**Not accepted. Systematic semantic defects remain.**

The exact 432-target replay passed structural parity checks. All 338 ledger records across 29 classified survivors were reviewed against their evidence spans. This is not a completed independent full-source audit. Original source corroboration and BX policy provenance remain open. Full-market gates and the deterministic 100-case audit are blocked.

- Exact target set matches the immutable capture; 432 unique targets, no missing or duplicate targets.
- One baseline/candidate hash pair; strict-v4 on all 432 rows; workflow and checkout SHA match.
- 17 rows have fetch errors; no extraction exceptions.
- Semantic runner 35110132061 and normal PR CI 35110139114 succeeded. Frozen v1.0 rules unchanged.

| Survivor | Records reviewed | Finding |
|---|---:|---|
| ACMR | 11 | Review required: record 9 subsidiary RMB outlook becomes qualitative company guidance; post-period preliminary result context also requires verification. |
| ANDG | 5 | No defect identified in 5 ledger evidence spans; full original-document corroboration remains pending. |
| APPF | 8 | Review required: record 4 rounded guidance midpoint represented as a point; action ownership on records 6–7. |
| ATMU | 8 | No defect identified in 8 ledger evidence spans; full original-document corroboration remains pending. |
| AUPH | 8 | No defect identified in 8 ledger evidence spans; full original-document corroboration remains pending. |
| BX | 0 | Policy classification has no ledger records or source manifest in consolidated artifact; source corroboration required. |
| CDNA | 22 | Defects: 0–2 and 16 preliminary prior-year results; 6/10/14 historical withdrawal CURRENT; 19 current EBITDA marked prior from preceding revenue comparison. |
| CECO | 21 | Defects: 11 result-quarter headline owns annual guidance; 15 prior EBITDA range represented as current reaffirmation. |
| CSTL | 29 | Defects: 3 and 17–18 historical revenue admitted; 23 medical treatment guidance/action cross-ownership. |
| DXCM | 22 | Defects: 13 gross-margin range collapsed to endpoint; 4/9 action ownership crosses metrics. |
| ESI | 19 | Defect: 6 prior quarterly range inherits following annual period. |
| ETON | 13 | Defects: 0/3 historical EBITDA; 1 annual revenue run-rate attached to quarter. |
| FLY | 5 | No defect identified in 5 ledger evidence spans; full original-document corroboration remains pending. |
| FROG | 14 | No defect identified in 14 ledger evidence spans; full original-document corroboration remains pending. |
| GEV | 15 | Defects: 2 current FCF marked prior; 4 result headline admitted; 8 revenue basis inherited from adjusted EBITDA; 10/14 historical revenue growth bullets admitted. |
| GKOS | 25 | Defect: 13 FY2026 revenue marked prior from preceding-year comparison. |
| HTFL | 6 | Defects: 1 truncated $21 fragment (source range $218–222 million); 3 current gross margin marked prior. Original SEC release independently checked. |
| IRTC | 11 | Defects: 2/6 revenue basis inherited from adjusted EBITDA. |
| ISRG | 9 | Defects: 0/6 preliminary historical quarter; 1 comparator fiscal year; multiple percentage ranges collapsed to points. |
| KMT | 10 | Defects: 0/2/3/9 comparator quarters used as guidance periods; 4/5 annual EPS attached to quarter; 8 comparator year used for annual guidance. November 2025 original source confirms FY2026 Q2 versus annual separation. |
| LB | 11 | Defects: 0 recently increased overrides reaffirmation; 8 annual range duplicated under quarter. |
| LOAR | 5 | No defect identified in 5 ledger evidence spans; full original-document corroboration remains pending. |
| NBIX | 2 | Defects: 0–1 product valbenazine net sales classified as company revenue. |
| NET | 14 | No defect identified in 14 ledger evidence spans; full original-document corroboration remains pending. |
| NTSK | 12 | No defect identified in 12 ledger evidence spans; full original-document corroboration remains pending. |
| NVCR | 4 | Defect: 1 current negative EBITDA marked prior from revenue comparison. |
| OMDA | 9 | Defects: 1 annual loss duplicated as quarter; 4 FY2026 EBITDA duplicated under FY2025 comparator. |
| ORCL | 6 | Defects: 2 EPS 8.05 truncated to 8.0; 3 reaffirmed prior revenue guidance marked quoted prior. |
| PTRN | 14 | Defect: 6 current EBITDA marked prior from revenue-growth comparison. |

Machine-readable evidence, record indices, hashes and source URLs: `survivor-audit-24d77f2.json`.

Original sources checked for ambiguous defects: [KMT](https://www.sec.gov/Archives/edgar/data/55242/000162828025049219/kmt9302025exhibit991.htm), [HTFL](https://www.sec.gov/Archives/edgar/data/1464521/000146452126000040/htfl-20260318xex99_1.htm).

A generic extraction/ownership repair is in progress. A fresh exact 432-target replay on the next tested source SHA is required. PR #17 remains draft and unmerged; Phase 1.1E is not ready for approval.
