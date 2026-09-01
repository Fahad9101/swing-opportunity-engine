# SOE-1.1.0 Implementation & Validation Plan

This plan sequences implementation so each structural input is independently testable and reversible. Milestone 3 remains blocked until SOE-1.1.0 passes its shadow-validation gate.

## Phase 1.1A — Evidence and guidance ledger

Deliverables:

- primary-document cache/index for gated tickers
- structured guidance metric schema and immutable ledger
- deterministic guidance comparison engine
- `guidance_deterioration` tri-state output
- tests for all cut/raise/reaffirm/withdraw/no-guidance paths

Exit gate:

- no active SOE-1.0.0 code path changed
- >=80% classification coverage among names with comparable primary-source guidance
- 100% provenance on non-null classifications

## Phase 1.1B — Sector-aware distress classification

Deliverables:

- universal hard-distress overrides
- corporate, utility, REIT, bank and insurer adapters
- deterministic derivation of leverage/coverage/liquidity/runway metrics
- `balance_sheet_distressed` tri-state output

Exit gate:

- >=90% classification coverage for non-financial names with sufficient inputs
- no financial company evaluated using corporate leverage thresholds
- no false safe classification from missing maturities/coverage data

## Phase 1.1C — Catalyst materiality

Deliverables:

- event-family normalization
- economic-exposure estimator using verified segment/asset/company-wide facts
- consequence-severity classifier
- deterministic 0-10 materiality score
- scoring-ready gate with explicit missing reasons

Exit gate:

- >=90% materiality coverage for catalyst candidates with sufficient primary evidence
- all scores reproducible from rule config and evidence
- administrative/unverified events cannot score

## Phase 1.1D — Surprise / re-rating potential

Deliverables:

- earnings/guidance consensus dispersion and instability logic
- clinical/regulatory expectation-uncertainty logic
- transaction/legal/financing contingency logic
- valuation-concentration factor
- deterministic 0-5 surprise score

Exit gate:

- >=80% surprise-score coverage for candidates with sufficient evidence
- no directional prediction masquerading as surprise potential
- missing analyst ranges/prior clinical evidence stays null

## Phase 1.1E — Integration and full-market shadow run

Run SOE-1.0.0 and SOE-1.1.0 on the same market snapshot.

Required report:

- exact unchanged universe/gate thresholds
- Growth-Pullback newly resolved counts
- Biotech/Catalyst newly resolved counts
- catalyst score distribution
- fully scored opportunity count
- Top 20 complete-score list
- per-name component delta versus v1.0 partial scores
- provider/data errors
- null-reason distribution
- manual audit sample >=100

Decision outcomes:

- `PASS`: all acceptance gates met; SOE-1.1.0 may become the discovery model and Milestone 3 may start.
- `CONDITIONAL PASS`: engine is technically sound but one structural coverage gate remains below target; do not start Milestone 3 unless the unresolved field is explicitly accepted by governance.
- `FAIL`: rule behavior, data integrity, or audit concordance is inadequate; remain on SOE-1.0.0.

## Change-control rule

Any threshold change to the proposed rules after the first shadow run must be justified by a documented model rationale and creates a new candidate rules hash. Thresholds may not be tuned merely to increase the number of qualifiers or Top Swing signals.
