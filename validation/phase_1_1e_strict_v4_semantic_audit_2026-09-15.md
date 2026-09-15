# Phase 1.1E strict-v4 semantic audit — 2026-09-15

Status: **BLOCKED — NOT READY FOR ACCEPTANCE**

This evidence record documents the canonical strict-v4 same-snapshot preflight and semantic blockers found before any full-market acceptance rerun. No frozen SOE-1.0.0 investment rule, filter, threshold, weight, scanner, ranking, or classification rule is changed by this commit.

## Canonical same-snapshot preflight inspected

- Branch baseline audited: `phase-1.1e-canonical-guidance`
- Canonical baseline SHA: `70b9f9230ff943a90f2045608b9a580963dff100`
- Latest successful strict-v4 exhaustive preflight run inspected: GitHub Actions run `34893719210`
- Consolidated artifact: `phase-1.1e-guidance-binder-preflight`, artifact id `10371156232`
- Target population: exactly **432**
- Snapshot fingerprint: `bb7e318b467d1142ec6ea25d1b6d9dd55ecdcf3e13c44434238f07ef454976a9`
- Baseline rules hash: `59cc7ffe14472434bfbb92b07b89b0b48293d0c5762d5270769bce3b494550ac`
- Candidate rules hash: `bcd0bd71b53a242b4e9d143525d6cd3ea1e0550ae27cca1788540250bf9468ca`
- Workflow SHA == checked-out SHA == `70b9f9230ff943a90f2045608b9a580963dff100`
- One snapshot fingerprint across all shards
- One rules-hash pair across all shards
- No duplicate/missing ticker assertion failure
- Binder version: `strict-v4` for all 432 rows
- Classification distribution: 48 `NOT_DETERIORATED`, 384 `UNKNOWN`, 0 `DETERIORATED`
- Classified survivor population: 48 names (47 with `sufficient_comparable_guidance`; BX classified through the explicit standing-no-guidance policy path)

Classified survivors in the consolidated artifact:

`ACMR, ALB, ANDG, APPF, ATMU, AUPH, BG, BKSY, BWMN, BX, CDNA, CECO, CRCL, DAVE, DXCM, ESI, FLY, FROG, FSS, GEV, GKOS, HTFL, IRTC, ISRG, ITT, JBL, KGS, KMT, KTOS, LB, LOAR, MDB, MNTN, MRVL, NBIX, NET, NMAX, NTSK, NVCR, OKTA, OMDA, OPLN, ORCL, PTGX, PTRN, RCUS, WAB, YOU`

## Replay parity

`backend/app/services/guidance_raw_replay_differential_service.py` at the audited baseline does not bypass the binder. Its committed-source replay order is:

`raw extraction -> strict-v4 evidence binder -> invariant validation -> canonical normalization -> ledger -> classifier`

The existing replay regression suite includes a run-rate EBITDA example that is quarantined before invariant validation rather than admitted directly.

## Semantic blockers found in the surviving classified population

The strict-v4 survivor ledger is **not semantically clean**. The following are generic defect classes, not ticker-specific exceptions. The examples below are representative evidence discovered in the exhaustive survivor review and are sufficient to block Phase 1.1E acceptance until the full class is repaired and the same 432-target snapshot is rerun.

1. **Segment / named-business ownership leakage**
   - Example: ALB admits Ketjen/Specialties revenue and adjusted EBITDA guidance as company-scope guidance.
   - Required architecture: bind company vs segment/business ownership before canonical admission; ambiguous ownership must quarantine.

2. **Long-term strategic target serialized as fiscal-period guidance**
   - Example: ACMR admits a `$4B` long-term revenue target as FY2025 revenue guidance.
   - Required architecture: strategic/long-term target language cannot acquire a fiscal period from neighboring text.

3. **Historical actual/result contamination**
   - Example: NMAX admits realized Broadcast Revenues/result text as FY guidance.
   - Required architecture: result/actual rows and columns must be excluded from forward-guidance ownership unless a local forward owner unambiguously binds the selected value.

4. **Quarter/full-year neighboring-period leakage**
   - Examples observed in the survivor ledger include ANDG, MRVL and PTRN, where values associated with one explicit period are also serialized under another period.
   - Required architecture: the selected metric/value must inherit its period from the same owned row/clause/table column; nearby headers cannot leak across guidance records.

5. **Revenue subcomponent / recognition leakage**
   - Example: OKTA admits remaining-performance-obligation revenue-recognition amounts as issuer total revenue guidance.
   - Required architecture: RPO/deferred/collaboration/milestone recognition amounts are not consolidated issuer revenue guidance merely because the word `revenue` is present.

6. **Loss-sign semantics lost during extraction**
   - Example: OMDA evidence stating adjusted EBITDA `loss` can be represented with positive numeric endpoints.
   - Required architecture: where negative semantics are explicit, normalize the sign deterministically; where sign is ambiguous, fail closed. Do not classify a positive interval from explicit loss evidence.

7. **Current-vs-prior role leakage across metrics**
   - Example: PTRN current FY2026 adjusted EBITDA can be marked `QUOTED_PRIOR` because prior-guidance language from another nearby metric leaks into role assignment.
   - Required architecture: current/prior role must be owned by the same metric/value cell or clause.

8. **Portfolio-pruning / business-exit amount treated as consolidated revenue**
   - Example: WAB admits `$40M`/`$50M` business-exit / portfolio-pruning amounts as issuer revenue guidance alongside the true consolidated multi-billion-dollar revenue range.
   - Required architecture: divestiture/business-exit/pruning effects are adjustments or components, not total issuer revenue guidance.

9. **Transaction non-guidance treated as operating guidance**
   - Example: FSS admits transaction synergy / EPS-accretion / headwind amounts as guidance.
   - Required architecture: transaction economics must not be promoted to issuer operating guidance without explicit period-level issuer guidance ownership.

10. **Correct final label can be reached from an invalid ledger**
    - Several examples remain `NOT_DETERIORATED` because a valid comparable pair coexists with semantically invalid records.
    - Acceptance therefore cannot be based on label accuracy or a percentage alone; the admitted canonical ledger itself must be semantically clean.

## Failed repair experiment and rollback

A defensive strict-v4 hardening experiment was attempted after these findings. It correctly exposed additional interactions but failed the deterministic suite (3 failures, 889 passes) before promotion. The experimental commits were **force-removed from the branch**, restoring the audited baseline `70b9f9230ff943a90f2045608b9a580963dff100` before this evidence-only commit.

The failed experiment was not retained because Phase 1.1E must not be left in a partially repaired or falsely green state. In particular, signed-loss handling needs an extractor/normalizer repair rather than a broad downstream quarantine rule, and semantic exclusions must preserve exact replay/classification parity.

## Acceptance consequence

Per the Phase 1.1E acceptance rule, **any systematic semantic error blocks acceptance**. Therefore:

- A fresh official full-market acceptance run was intentionally **not** triggered from the contaminated strict-v4 implementation.
- The four automated full-market gates were **not re-certified** after this audit.
- The deterministic 100-case manual audit queue was **not accepted** because the prerequisite canonical guidance semantic validation is not clean.
- PR #17 remains unmerged.
- SOE-1.1 / Milestone 3 were not activated or started.

## Required next repair boundary

Repair the generic ownership/sign/role classes in the extractor + strict evidence binder + canonical normalization path, add generic regression fixtures, rerun the exact same 432-target snapshot, then re-audit every surviving classified case. Only after zero systematic semantic defect remains should the fresh official full-market Phase 1.1E acceptance workflow and deterministic 100-case manual audit be run.
