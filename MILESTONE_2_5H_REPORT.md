# Milestone 2.5H — Free/Public Catalyst Intelligence Validation

Date: 2026-08-31  
Model: `SOE-1.0.0`  
Scope: validate a free/public catalyst-evidence layer and the pre-existing A/B/C date-confidence framework without changing any SOE investment rule, threshold, scoring weight, scanner condition, classification, or Investment Execution Engine file.

## Result

Milestone 2.5H validates the **evidence and date-confidence layer** of catalyst intelligence on real free/public data while deliberately refusing to fabricate the two catalyst-score inputs that the current public sources do not supply: **materiality (0–10)** and **surprise/re-rating potential (0–5)**.

This distinction is essential. A verified public event can now be retained with source, date/window, timing, date precision, A/B/C date confidence, stale state and scoring-readiness diagnostics. It becomes a scored `Catalyst` only when all frozen score inputs are explicitly available. Therefore a public earnings date or trial milestone cannot silently create catalyst points or qualify the Biotech/Catalyst scanner.

No change was made to `config/soe_v1_0_rules.yaml`. The branch and `main` use the same rules blob SHA: `3cd94be285e0f3b00b8952e33973762ec67b5f4d`. Milestone 3 remains deferred.

## Frozen catalyst architecture preserved

The existing SOE catalyst score remains exactly:

- Materiality: 0–10
- Timing: 0–5
- Date confidence: A = 5, B = 3, C = 0
- Surprise/re-rating potential: 0–5
- Maximum: 25

The existing timing bands, 56-day horizon, Biotech/Catalyst scanner logic, Grade-A exception path and Grade-C limitations were not changed.

Milestone 2.5H only operationalizes the already-defined date-confidence vocabulary for normalized public evidence:

- **A**: verified exact-day / narrow-date evidence from the structured public source.
- **B**: verified guided or estimated day/month window.
- **C**: unverified, speculative or too-coarse evidence.

No new point schedule is introduced.

## Evidence model

`CorporateEvent` now retains optional catalyst-intelligence metadata inside the existing normalized JSON record:

- `date_confidence`
- `date_precision`
- `window_start`
- `window_end`
- `catalyst_candidate`
- `materiality`
- `surprise_potential`
- `scoring_ready`
- `missing_score_fields`
- `evidence_status`
- `source_url`

Missing numerical score inputs remain `null`. The database's existing `corporate_events.normalized_data` JSON preserves these fields, so no schema migration or frozen investment-rule change was required.

## 1. Nasdaq earnings evidence

The existing Nasdaq public earnings-calendar adapter now annotates structured earnings dates as catalyst evidence.

For an exact public date the record retains:

- exact event date;
- pre-market / after-hours timing when supplied;
- `date_precision = DAY`;
- verified source provenance;
- A date-confidence evidence state;
- `catalyst_candidate = true`.

However, Nasdaq's calendar does not provide the SOE materiality or surprise/re-rating score inputs. Therefore:

- `materiality = null`;
- `surprise_potential = null`;
- `scoring_ready = false`;
- `missing_score_fields = [materiality, surprise_potential]`;
- no scored `Catalyst` is produced.

This means a known earnings date is discoverable and auditable but does not receive arbitrary catalyst points.

## 2. ClinicalTrials.gov evidence

ClinicalTrials.gov API v2 is used only for deterministic structured trial metadata. Milestone 2.5H strengthens this adapter in several ways:

1. Lead-sponsor matching is checked after normalization to reduce false ticker-to-study associations.
2. Exact day, month and year precision are retained explicitly rather than converting every coarse date into a fake exact date.
3. A month such as `2026-09` becomes a true September window, not an invented September 1 catalyst date.
4. Primary-completion and study-completion dates remain **trial milestones**, not clinical-data readout dates.
5. They are never converted into FDA/PDUFA dates.
6. They are not promoted into scored catalysts without explicit materiality and surprise inputs.

ClinicalTrials.gov completion dates are therefore useful intelligence about the clinical-development calendar but are not treated as evidence that results will be released on that date.

## 3. Strict promotion gate

A new deterministic promotion function converts a `CorporateEvent` to the existing scored `Catalyst` model only if all required public evidence is present and non-stale:

- verified catalyst-candidate event;
- valid A/B/C date confidence;
- explicit materiality;
- explicit surprise/re-rating potential;
- valid date/window provenance.

If either materiality or surprise is missing, promotion returns `None`. Missing values are never converted to zero, and an incomplete event cannot affect the 25-point catalyst score or the Grade-A Biotech/Catalyst technical-exception path.

## Deterministic verification

GitHub Actions run `33423352652`, job `99590867447`, completed successfully.

Result: **102 passed, 0 failed**. One non-failing Starlette/httpx deprecation warning was reported.

New deterministic coverage includes:

- exact verified day -> A date-confidence evidence;
- estimated day/month -> B evidence;
- coarse year/unverified input -> C evidence;
- month-window preservation;
- no manufactured materiality or surprise for earnings;
- no promotion of incomplete events;
- promotion only when all explicit score inputs exist;
- ClinicalTrials.gov month-window handling;
- trial milestones are not mislabeled as readouts;
- unrelated lead sponsors are rejected.

All prior scanner, scoring, ownership, estimates, valuation and missing-data regression tests continue to pass.

## Live free/public catalyst audit

The same GitHub Actions run executed `app.cli_live_catalyst_smoke` against the production `free_public` provider. The live sample included AVGO, ORCL, ADBE, COST, NKE, LUV, ARWR and BEAM.

| Ticker | Public evidence found | Date / window | Confidence | Scoring ready | Scored catalysts |
| --- | --- | --- | --- | --- | ---: |
| AVGO | Earnings | 2026-09-02 | A | No | 0 |
| ORCL | Earnings | 2026-09-08 | A | No | 0 |
| ADBE | Earnings | 2026-09-10 | A | No | 0 |
| COST | Earnings | 2026-09-24 | A | No | 0 |
| NKE | Earnings | 2026-10-01 | A | No | 0 |
| LUV | None in current 56-day sample | — | — | No | 0 |
| ARWR | None in current 56-day sample | — | — | No | 0 |
| BEAM | None in current 56-day sample | — | — | No | 0 |

The returned earnings records explicitly showed `materiality = null`, `surprise_potential = null`, `scoring_ready = false` and the two missing score fields. That is the intended result under frozen SOE-1.0.0 rules.

### AVGO

Nasdaq returned an after-hours earnings event for 2026-09-02. The engine preserves it as verified exact-day catalyst evidence. It does **not** award any catalyst points because materiality and surprise are unavailable from the source.

### ORCL

Nasdaq returned 2026-09-08 with the calendar timing reported as `time-not-supplied`. The engine retains that source limitation rather than inventing pre-market or after-hours timing. The event remains evidence-only and unscored.

### ADBE / COST / NKE

Each returned an exact public earnings-calendar date, with after-hours timing in the live feed. All were retained as A date-confidence evidence but remained unscored for the same reason: the frozen materiality and surprise inputs are unavailable.

### LUV

No event appeared in the current 56-day targeted public sample. The engine does not infer an earnings event from historical cadence.

### ARWR / BEAM

Both were recognized as biotech names, but the current ClinicalTrials.gov sponsor-filtered 56-day query did not yield an eligible future primary/completion milestone in the targeted run. No clinical catalyst was fabricated. This is a desirable negative-control result: absence of structured evidence remains absence of evidence.

## What Milestone 2.5H closes

Milestone 2.5H closes several catalyst-data integrity gaps:

- verified public events can be retained separately from scored catalysts;
- exact versus guided/coarse date precision is explicit;
- A/B/C date-confidence evidence is auditable;
- coarse trial dates are preserved as windows;
- ClinicalTrials.gov milestones cannot masquerade as readouts or FDA dates;
- sponsor matching reduces false biotech associations;
- missing materiality/surprise remains transparent;
- only score-complete evidence can reach the frozen catalyst scorer.

This is materially better than either ignoring public catalyst evidence or assigning arbitrary catalyst points.

## What remains incomplete

Milestone 2.5H does **not** fully populate the 25-point catalyst score. The main unresolved inputs are:

1. **Materiality (0–10)** — requires event-specific interpretation of how consequential the event is for the equity thesis.
2. **Surprise/re-rating potential (0–5)** — requires expectation context, event asymmetry and likely market sensitivity.
3. **Verified biotech readout/regulatory dates** — ClinicalTrials.gov completion dates are not equivalent to result-release, FDA action or PDUFA dates.
4. **Corporate non-earnings catalysts** — investor days, product launches, major contract milestones, strategic reviews, regulatory decisions and similar events need additional authoritative feeds or filing/news extraction.

Those fields should not be solved by hard-coding new point mappings under `SOE-1.0.0`; that would be a rule change. A later intelligence adapter may extract and audit these already-defined inputs from authoritative text, but any new deterministic scoring rubric would require explicit versioned approval.

## Remaining Milestone 2.5 gaps after H

The highest-value remaining validation gaps are now:

1. biotech cash-runway / financing completeness;
2. Growth Pullback guidance-deterioration and explicit balance-sheet-distress state;
3. forward EBITDA plus revenue/EBITDA revision breadth;
4. market breadth for the regime model;
5. broader authoritative event coverage and score-complete catalyst interpretation;
6. a fresh full-market validation run with the current post-2.5H stack.

## Commercial-data caveat

Nasdaq web endpoints are still prototype-only in this project and have no contractual SLA or explicit commercial redistribution grant here. ClinicalTrials.gov is a public authoritative trial registry, but a registered study milestone is not a company commitment to release data on that date. Any commercial product should preserve that distinction and use appropriately licensed market/news/calendar feeds where required.

## Conclusion

Milestone 2.5H successfully validates a free/public catalyst-intelligence evidence layer without corrupting the frozen SOE catalyst score.

- `SOE-1.0.0` investment rules: **unchanged**.
- Catalyst score weights/bands: **unchanged**.
- Scanner logic and classifications: **unchanged**.
- Rules blob SHA vs `main`: **identical** (`3cd94be285e0f3b00b8952e33973762ec67b5f4d`).
- Investment Execution Engine v1.7.2: **not modified**.
- Milestone 3: **not started**.
