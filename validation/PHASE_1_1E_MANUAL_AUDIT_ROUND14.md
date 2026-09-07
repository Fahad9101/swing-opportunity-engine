# Phase 1.1E round 14 — run 80

Decision: **FAIL — early stop for systematic evidence corruption at sample 5 (ITT)**.

Run `34153720181`, artifact `10032639161`, head `1a0143dc257268bfcf60d8d6bafba29875aa9287`.
Snapshot: `58c6c02f3e56f3eb406691a7cc11227aac840343fa467f8883909660e6f0daea`.
Baseline scan: `c0f80364-a7ec-4b40-b76d-996a1df32603`.

All nine automated gates passed. The snapshot contains 5,151 symbols, 2,316 universal survivors,
78 fully scored candidate opportunities, guidance coverage 73/75, distress coverage 113/113,
and materiality/surprise coverage 110/110. The automated decision remains PENDING_MANUAL_AUDIT.

## Audited prefix

1. ETN guidance: the source annual unadjusted EPS ranges fall from 11.57–12.07 to
   10.36–10.56. This supports DETERIORATED under the frozen material-cut rule.
2. ALGM distress: persisted interest coverage 0.9541677419 is below 1.0 with
   debt outstanding 281,109,000. This supports the absolute-coverage distress path.
   This checks the rule against persisted inputs, not a new independent XBRL derivation.
3. RSI guidance: annual revenue increases from 1,050–1,100 million to 1,100–1,120 million;
   adjusted EBITDA increases from 133–147 million to 147–153 million. Source comparison
   supports NOT_DETERIORATED.
4. CSX surprise: the cited primary source is a June 30, 2026 Form 10-Q containing
   completed quarterly income statements. Persisted surprise inputs give 1 + 1 + 1 = 3.
5. ITT: output label NOT_DETERIORATED agrees with the releases, but the underlying
   EPS records are wrong. Stop: label agreement cannot excuse corrupted evidence.

## ITT defect and repair

The May 6 release gives FY2026 GAAP EPS of 4.15–4.45 and adjusted EPS of 7.70–8.00.
The August 6 release gives GAAP EPS of 4.47–4.67 and adjusted EPS of 8.12–8.32.
Both reconciliation tables have explicit Low/High columns and basis labels following
“EPS from Continuing Operations.” Before repair, extraction yielded GAAP and ADJUSTED
point records both equal to the GAAP lower bound (4.15, then 4.47).

The normalization layer now reads this explicit table shape, preserves both endpoints
and the row's basis, and replaces conflicting generic EPS records for the same document
and fiscal period. Reconciliation adjustment rows never become EPS facts. Ambiguous
column order, inverted ranges, and reported-results headers are rejected.

Primary releases were downloaded and replayed using their printed release dates,
May 6 and August 6, 2026. These dates establish release ordering for the diagnostic
comparison; exact SEC filing acceptance-time replay is not claimed. The corrected records
are the four ranges above, and the unchanged ledger returns NOT_DETERIORATED.

Sources:

- https://www.sec.gov/Archives/edgar/data/216228/000021622826000034/earningsrelease2026q1.htm
- https://www.sec.gov/Archives/edgar/data/216228/000021622826000061/earningsrelease2026q2.htm
- ETN and RSI source URLs and CSX source URL are retained in the immutable run artifact.

## Verification and limitations

532 tests passed, 0 failed; two existing dependency deprecation warnings. Six new
regressions cover endpoints, basis, rising guidance, an adjusted cut despite rising
GAAP EPS, invalid column order, reported-results exclusion, and inverted ranges
(some cases are parameterized). No investment-rule file changed.

The remaining 95 sample items are unadjudicated. No full-sample concordance is claimed.
The next acceptance step is a fresh full-market run at the repaired head followed by
a new independent audit. SOE-1.0.0 stays active; PR 16 stays draft/unmerged; activation
and Milestone 3 remain blocked. IEE v1.7.2 is untouched.

Provider debt: four recorded Yahoo 429 crumb-bootstrap failures plus three SEC bulk
read failures (AYA, IBN, OZK); 12 malformed historical SEC-row enrichment errors.
These failures are persisted and did not abort the market scan. No paid provider was added.
