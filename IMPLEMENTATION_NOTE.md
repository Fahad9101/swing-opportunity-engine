# SOE-1.0.0 implementation notes

These notes preserve the frozen investment specification and record ambiguities without silently redesigning it.

## Penalty sign convention

- Existing specification: individual penalties are shown as negative values (for example, `-3`), while one displayed formula subtracts `penalty_points`.
- Problem: subtracting an already-negative number would increase the score.
- Implemented interpretation: penalty values and the aggregate `penalty_points` are negative; the deterministic calculation is `base + penalty_points + bonus`.
- Why: this reproduces the specification's worked example: `77 - 3 + 2 = 76`.

## Upside rejection before target construction

- Existing specification: `UPSIDE_BELOW_15` exists as an automatic-rejection code, but target construction is deferred to Milestone 3.
- Problem: Milestones 1–2 cannot independently calculate credible swing upside without the deferred target engine.
- Implemented interpretation: the code exists but is not automatically applied. Valuation/upside scoring accepts only explicit provider-supplied, provenance-bearing inputs and otherwise reports the component as unavailable.
- Suggested Milestone 3 decision: apply the rejection only after target construction produces a valid, auditable upside estimate.

## Sector-specific balance sheets

- Existing specification: do not apply generic debt/EBITDA blindly to banks, insurers, REITs, or utilities.
- Implemented interpretation: these sectors return an unavailable balance-sheet component until their dedicated adapters exist. No neutral or zero score is fabricated.

## Historical immutability

- Existing specification: completed scan records must be immutable.
- Implemented interpretation: the repository refuses updates after a scan reaches `COMPLETED`; production deployment should additionally revoke SQL `UPDATE`/`DELETE` permissions for the application role on historical tables or add database triggers.

