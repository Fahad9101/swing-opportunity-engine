# Phase 1.1E round 15 — run 81

**FAIL — early stop at sample 1, ROCK guidance.**

- Run: 34168937582; artifact: 10037117050.
- Audited commit: 35f8877c448c357661f13bb4362bc1a29cbc4897.
- Snapshot: e69c0cd1cf6b9e1471b578be8318a7b5e09f59533f37c8a121f2aff220c3f996.
- All nine automated gates passed; automatic decision was PENDING_MANUAL_AUDIT.
- One sample adjudicated, discordant; remaining 99 unadjudicated. No full-sample concordance is claimed.

## Independent source comparison

The cited second- and third-quarter 2025 releases explicitly state the following
continuing-operations outlook ranges. Both source documents were downloaded and read.

| FY2025 metric | Prior range | Current range | Midpoint change |
|---|---|---|---|
| Revenue | $1.15–1.20 billion | $1.15–1.175 billion | -1.06383% |
| GAAP EPS | $3.67–3.91 | $3.67–3.77 | -1.84697% |
| Adjusted EPS | $4.20–4.45 | $4.20–4.30 | -1.73410% |

Revenue and EPS are two distinct supported metrics with cuts of at least 1%.
The frozen rule therefore requires DETERIORATED via
`guidance_v1_1.multi_metric_small_cut`. This conclusion does not depend on counting
GAAP and adjusted EPS as separate metrics or on interpreting the word “narrowing.”

The persisted audit entry instead reports NOT_DETERIORATED through
`guidance_v1_1.comparable_set_within_tolerance`, with one comparable pair.
Replaying the current extractor on the two cited sources retains only the two
revenue ranges and no EPS ranges. Missing accompanying EPS guidance prevents
the multi-metric cut from being recognized.

An independent set of manually transcribed ranges supplied directly to the unchanged
classifier produced DETERIORATED and the expected multi-metric rule path. This
is a source-adjudication check, not an exact SEC acceptance-timestamp replay or
a claim to have reconstructed all 40 documents processed by production.

Primary sources:

- https://www.sec.gov/Archives/edgar/data/912562/000091256225000033/exhibit991q22025earningsre.htm
- https://www.sec.gov/Archives/edgar/data/912562/000091256225000052/exhibit991q32025earningsre.htm

## Required engineering follow-up

Repair extraction of the accompanying forward EPS ranges under the shared annual
guidance scope. Protect explicit GAAP and adjusted basis, exclude 2024 reported
comparators, and test the multi-metric cut end to end. Do not change thresholds,
the classifier, or the interpretation of narrowing. After repair, run regressions
and fresh full-market validation, then restart the independent audit.

This commit records audit findings only; it does not repair the newly discovered
extraction gap. No investment methodology, runtime code, provider or IEE v1.7.2
code is changed. PR 16 remains draft/unmerged; SOE-1.0.0 stays active and
Milestone 3 remains blocked. Automated success alone is insufficient for activation.
