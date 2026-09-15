# Phase 1.1E strict-v4 semantic audit — 2026-09-15

Status: **BLOCKED — NOT READY FOR ACCEPTANCE**

This evidence record documents the canonical strict-v4 same-snapshot preflight and systematic semantic blockers found before a fresh full-market acceptance rerun. It changes no frozen SOE-1.0.0 investment rule, filter, threshold, weight, scanner, ranking, or classification rule.

## Canonical same-snapshot preflight

- Audited code SHA: `70b9f9230ff943a90f2045608b9a580963dff100`
- Latest successful strict-v4 exhaustive preflight: Actions run `34893719210`
- Consolidated artifact: `phase-1.1e-guidance-binder-preflight`, artifact id `10371156232`
- Exact target population: **432**
- Snapshot fingerprint: `bb7e318b467d1142ec6ea25d1b6d9dd55ecdcf3e13c44434238f07ef454976a9`
- Baseline rules hash: `59cc7ffe14472434bfbb92b07b89b0b48293d0c5762d5270769bce3b494550ac`
- Candidate rules hash: `bcd0bd71b53a242b4e9d143525d6cd3ea1e0550ae27cca1788540250bf9468ca`
- Workflow SHA == checked-out SHA == `70b9f9230ff943a90f2045608b9a580963dff100`
- One snapshot fingerprint and one rules-hash pair across shards
- No duplicate/missing ticker assertion failure
- Binder version `strict-v4` on all 432 rows
- Classification: 48 `NOT_DETERIORATED`, 384 `UNKNOWN`, 0 `DETERIORATED`
- Classified population: 48 names; 47 report sufficient comparable guidance, while BX uses the explicit standing-no-guidance policy path

Classified population:

`ACMR, ALB, ANDG, APPF, ATMU, AUPH, BG, BKSY, BWMN, BX, CDNA, CECO, CRCL, DAVE, DXCM, ESI, FLY, FROG, FSS, GEV, GKOS, HTFL, IRTC, ISRG, ITT, JBL, KGS, KMT, KTOS, LB, LOAR, MDB, MNTN, MRVL, NBIX, NET, NMAX, NTSK, NVCR, OKTA, OMDA, OPLN, ORCL, PTGX, PTRN, RCUS, WAB, YOU`

The complete survivor population was enumerated from the consolidated artifact. Semantic review was started across that population, but **per-case semantic sign-off of all 48 was not completed** because multiple generic systematic defects were already confirmed. Those defects themselves are sufficient to block Phase 1.1E under the governing acceptance rule; this document therefore must not be read as a clean exhaustive 48/48 semantic sign-off.

## Replay parity

At the audited baseline, `backend/app/services/guidance_raw_replay_differential_service.py` follows:

`raw extraction -> strict-v4 evidence binder -> invariant validation -> canonical normalization -> ledger -> classifier`

The existing replay regression includes run-rate EBITDA evidence that is quarantined by the binder rather than bypassing it.

## Confirmed systematic semantic defect classes

1. **Segment / named-business ownership leakage** — ALB admits Ketjen/Specialties revenue and adjusted EBITDA as company-scope guidance.
2. **Long-term target serialized as fiscal-period guidance** — ACMR admits a `$4B` long-term revenue target as FY2025 guidance.
3. **Historical actual/result contamination** — NMAX admits realized Broadcast Revenues/result evidence as forward guidance.
4. **Quarter/full-year neighboring-period leakage** — observed in ANDG, MRVL and PTRN; values can be serialized under a neighboring period rather than the value-owning period.
5. **Revenue subcomponent / recognition leakage** — OKTA admits RPO revenue-recognition amounts as consolidated revenue guidance.
6. **Loss-sign semantics lost during extraction** — OMDA explicit adjusted-EBITDA-loss evidence can become positive numeric endpoints.
7. **Current-vs-prior role leakage across metrics** — PTRN current FY2026 adjusted EBITDA can inherit `QUOTED_PRIOR` from nearby prior-guidance language belonging to another metric.
8. **Portfolio-pruning / business-exit amount treated as consolidated revenue** — WAB admits `$40M`/`$50M` exit/pruning amounts alongside the true consolidated revenue range.
9. **Transaction non-guidance treated as operating guidance** — FSS admits transaction synergy / EPS-accretion / headwind amounts.
10. **Correct final label from an invalid ledger** — some names remain `NOT_DETERIORATED` because valid comparable pairs coexist with invalid admitted records; label-level accuracy therefore cannot establish semantic correctness.

These are generic ownership, period, row/column, role, provenance, and sign-normalization defects. They must be repaired architecturally rather than by ticker-specific exceptions.

## Repair experiment and rollback

A defensive strict-v4 hardening experiment was attempted. It exposed useful interactions but failed the deterministic suite at **3 failures / 889 passes** and was not retained. The experimental commits were force-removed, returning production code to `70b9f9230ff943a90f2045608b9a580963dff100` before this evidence-only commit.

The failure showed, among other things, that explicit loss semantics should be repaired at extraction/normalization when deterministic, not handled only by broad downstream quarantine, and that semantic exclusions must preserve committed replay/classification parity.

## Acceptance consequence

Because systematic semantic defects remain:

- Phase 1.1E is **not ready for approval**.
- A fresh official full-market acceptance run was **not triggered**, because doing so on known-contaminated canonical guidance would not constitute valid acceptance evidence.
- The four automated full-market gates were therefore **not re-certified** after this audit.
- The deterministic 100-case manual audit queue was **not accepted** because canonical guidance validation is not clean.
- PR #17 remains unmerged.
- SOE-1.1 / Milestone 3 were not activated or started.

## Required repair boundary

Repair the generic ownership/sign/role classes in the extractor, strict evidence binder, and canonical normalization/replay path; add regression fixtures for each generic defect; rerun the exact 432-target snapshot; then semantically sign off every surviving classified case. Only after zero systematic semantic defect remains should the fresh official full-market acceptance workflow and deterministic 100-case manual audit be run.
