# Phase 1.1D Surprise / Re-Rating Validation

- Exit gate: **PASS**
- Targets attempted: 30
- Inherited 1.1C verified candidates: 30
- Targets with live consensus context: 30
- Targets with usable expectation evidence: 30
- Surprise scores among sufficient evidence: 30
- Surprise-score coverage: 100.0%
- Inherited SEC provenance complete: 100.0%
- Non-directional reason present: 100.0%
- Provider errors: 0
- Score distribution: 2 = 15, 3 = 10, 4 = 5
- Expectation basis: EPS consensus dispersion = 29, revenue consensus dispersion = 1

The validation passed the locked SOE-1.1D minimum surprise-score coverage gate of 80%. Missing analyst evidence remained null by construction; this run had no null/error cases. One candidate correctly used revenue dispersion because the EPS expectation range was unsuitable for the EPS-dispersion path.

This is a live structural/provider validation using current-period analyst consensus and inherited Phase 1.1C primary-event/exposure provenance. It is **not** a historical pre-event backtest and does **not** infer the direction of any surprise.

Remote validation evidence:
- GitHub Actions run: `33751982761`
- Job: `live-surprise-validation`
- Artifact: `phase-1.1d-surprise-validation`
- Artifact ID: `9891900958`
- Artifact ZIP SHA-256: `a107289867f9de6f8a09bdf132117aa3e82c9953e28e2f08803a760f536ed8ab`

Deterministic regression CI on the same implementation head also passed: **417 tests passed** with 2 dependency deprecation warnings and no test failures.
