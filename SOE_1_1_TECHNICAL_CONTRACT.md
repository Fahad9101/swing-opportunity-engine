# SOE-1.1.0 Technical Implementation Contract

Status: DESIGN ONLY. No runtime path may load the proposed SOE-1.1.0 rules until an implementation PR is separately approved and the validation gates in `SOE_1_1_SPEC.md` pass.

## 1. Implementation objective

Implement deterministic, auditable population of:

- `Catalyst.materiality`
- `Catalyst.surprise_potential`
- `FundamentalSnapshot.guidance_deterioration`
- `FundamentalSnapshot.balance_sheet_distressed`

without changing any unaffected SOE-1.0.0 threshold, scanner rule, score weight, classification rule, or Investment Execution Engine v1.7.2 behavior.

## 2. Versioning

Create a new active config only during implementation:

- `config/soe_v1_1_rules.yaml`
- `model_version = SOE-1.1.0`
- new SHA-256 rules hash persisted on every scan, opportunity, evidence object and outcome.

Keep `config/soe_v1_0_rules.yaml` byte-identical forever.

The file `design/soe_v1_1_rules_proposed.yaml` is non-runtime design input and must not be selectable by provider/runtime code.

## 3. New domain models

### 3.1 CatalystEvidence

Required fields:

- ticker
- event_id
- event_family
- event_type
- source
- source_url/accession
- source_timestamp
- event_date/window
- date_confidence
- event_class_base
- economic_exposure_score
- economic_exposure_basis
- economic_exposure_value
- consequence_severity
- outcome_binaryity
- expectation_uncertainty
- expectation_uncertainty_basis
- valuation_concentration
- materiality
- surprise_potential
- scoring_ready
- missing_fields[]
- extraction_method (`structured`, `deterministic_text`, `llm_extract_then_validate`)
- evidence_spans[] or structured field provenance

### 3.2 GuidanceMetricRecord

Required fields:

- ticker
- fiscal_period
- metric
- accounting_basis
- low
- high
- midpoint
- unit
- source
- source_timestamp
- explicit_action (`RAISE`, `REAFFIRM`, `LOWER`, `WITHDRAW`, `INITIATE`, `NONE`)
- verified
- supersedes_record_id

### 3.3 GuidanceAssessment

Required fields:

- ticker
- as_of
- current_guidance_record_ids[]
- prior_guidance_record_ids[]
- comparable_metrics[]
- metric_deltas[]
- explicit_cut_or_withdrawal
- classification (`DETERIORATED`, `NOT_DETERIORATED`, `UNKNOWN`)
- `guidance_deterioration: bool | null`
- rule_path
- reasons[]
- sources[]

### 3.4 DistressAssessment

Required fields:

- ticker
- sector_adapter
- as_of
- hard_distress_flags[]
- net_debt_to_ebitda
- interest_coverage
- liquidity_coverage
- cash_runway_months
- financing_secured
- debt_maturities_12m
- committed_liquidity
- sector_specific_metrics{}
- classification (`DISTRESSED`, `NOT_DISTRESSED`, `UNKNOWN`)
- `balance_sheet_distressed: bool | null`
- rule_path
- reasons[]
- sources[]

## 4. New services/modules

Implement in this order:

1. `app/services/source_document_service.py`
   - fetch/cache primary SEC/company/regulatory text and metadata
   - content hashing and deduplication
   - no scoring

2. `app/services/fact_extraction_service.py`
   - structured parsing first
   - optional LLM extraction only for text-to-fact conversion
   - emits typed candidate facts plus exact source provenance
   - never emits authoritative scores/classes

3. `app/services/guidance_ledger_service.py`
   - normalize comparable guidance metrics by fiscal period/basis
   - identify prior/current records
   - reject incompatible comparisons

4. `app/services/guidance_classifier.py`
   - pure deterministic function
   - input: validated guidance records
   - output: `GuidanceAssessment`

5. `app/services/distress_metric_service.py`
   - derive leverage, coverage, liquidity and runway inputs
   - sector-specific adapter routing

6. `app/services/distress_classifier.py`
   - pure deterministic function
   - output: `DistressAssessment`

7. `app/services/catalyst_evidence_service.py`
   - combine event metadata, exposure evidence and expectation context
   - calculate materiality/surprise only from v1.1 config
   - emit scoring-ready `Catalyst` only when all required factors are available

8. existing `app/scoring/catalyst_score.py`
   - keep 25-point arithmetic unchanged
   - only consume newly scoring-ready Catalyst objects

## 5. Provider/data requirements

### SEC

Use the existing bulk `companyfacts.zip` and `submissions.zip` cache as the primary market-wide backbone.

Add document retrieval only for shortlisted/gated names, not all 5,000+ symbols. Target filings/exhibits:

- 10-K
- 10-Q
- 8-K
- 6-K
- EX-99.1 / earnings releases where available

Respect SEC fair-access rules, cache documents, and persist accession/source metadata.

### Clinical/regulatory

- ClinicalTrials.gov: phase, endpoints, enrollment, study status, primary completion windows.
- FDA/regulator primary pages: decision dates/status when available.
- Company IR: only when primary regulatory/SEC evidence does not yet contain the required fact.

### Consensus context

The existing prototype consensus adapter may provide estimate average/high/low, 30d/90d changes and analyst counts. If a required high/low range is unavailable, use the defined fallback to consensus instability. Do not fabricate ranges.

## 6. Pipeline placement

New expensive text/document work must occur only after universal gating and preferably after technical readiness.

Recommended pipeline:

`Universe -> universal gate -> market/technical -> SEC bulk fundamentals -> estimates -> candidate event discovery -> targeted primary-document enrichment -> guidance/distress classification -> scanner evaluation -> catalyst scoring -> opportunity scoring -> ranking`

For Growth Pullback, guidance/distress enrichment is mandatory only for names that could otherwise satisfy the quantitative growth conditions. Do not fetch full documents for obvious quantitative failures.

For Re-Rating, catalyst enrichment is required for a complete 100-point score but not for scanner qualification.

For Biotech/Catalyst, primary event verification and runway remain mandatory before qualification under the existing rules.

## 7. Persistence

Add immutable tables or equivalent append-only records:

- `source_documents`
- `catalyst_evidence_snapshots`
- `guidance_metric_records`
- `guidance_assessments`
- `distress_assessments`

Every record must contain:

- model_version
- rules_hash
- scan_run_id where applicable
- ticker
- source/provenance
- as_of/fetched_at
- stale
- normalized payload
- audit/reason payload

Historical evidence must not be overwritten in place.

## 8. Deterministic APIs/functions

Required pure functions:

```python
score_materiality(event_class_base: int, exposure: int, consequence: int) -> int
score_surprise(binaryity: int, expectation_uncertainty: int, valuation_concentration: int) -> int
classify_guidance(current: list[GuidanceMetricRecord], prior: list[GuidanceMetricRecord], rules: Rules) -> GuidanceAssessment
classify_distress(metrics: DistressInputs, sector_adapter: str, rules: Rules) -> DistressAssessment
```

Pure functions may not perform network access or call an LLM.

## 9. Guidance comparison rules

Normalize percentage deltas as:

`delta = current_midpoint / prior_midpoint - 1`

Margins use basis-point delta:

`delta_bps = (current_margin - prior_margin) * 10_000`

If prior midpoint is zero, sign-changing, or not economically comparable, percentage comparison is invalid and that metric is excluded from numeric comparison; explicit management action may still classify the record.

Accounting-basis changes require an explicit reconciliation or same-basis restatement before comparison.

## 10. Distress derivations

### Non-financial

`net_debt_to_ebitda = max(debt - cash_and_marketable_securities, 0) / EBITDA`

Do not calculate when EBITDA <=0; route negative-EBITDA/negative-FCF firms to runway/liquidity logic instead.

`interest_coverage = EBIT / cash_interest_expense`

Do not use EBITDA/interest as a silent substitute unless a separately named metric/rule is configured.

`liquidity_coverage = (cash + marketable_securities + committed_undrawn_revolver + max(trailing_FCF, 0)) / debt_maturities_12m`

If debt maturities cannot be verified, liquidity coverage is null.

### Sector adapters

Adapters must be explicit classes, e.g.:

- `CorporateDistressAdapter`
- `UtilityDistressAdapter`
- `ReitDistressAdapter`
- `BankDistressAdapter`
- `InsurerDistressAdapter`

Never choose thresholds based on company-specific discretion.

## 11. AI extraction controls

When LLM extraction is used:

- prompt must request facts only, never ratings/scores;
- output must conform to a strict JSON schema;
- each extracted fact must carry a quoted/located source span or structured source field;
- deterministic validation checks units, dates, fiscal periods and numeric consistency;
- unsupported facts are discarded;
- conflicting facts cause null/UNKNOWN unless source precedence resolves them;
- model/provider/version of extractor is stored for audit, but changing extractor must not change deterministic scoring rules.

## 12. Testing contract

Minimum new deterministic tests before activation:

- materiality: all base/exposure/consequence boundaries, null paths, cap at 10
- surprise: all family paths and thresholds
- guidance: >=30 cases including exact 2% revenue, 5% EPS/EBITDA/FCF and 100 bps margin boundaries
- guidance: changed fiscal periods/bases must return UNKNOWN
- no-guidance policy: explicit policy vs simple missing guidance
- distress: >=40 cases across sector adapters and exact leverage/coverage/runway boundaries
- provenance: every non-null classification/score has source and rule path
- persistence: nested dates/datetimes remain JSON-safe
- regression: every existing SOE-1.0.0 test still passes where version-independent

## 13. Shadow validation contract

Run SOE-1.0.0 and SOE-1.1.0 from the same market-data snapshot.

Required comparison report:

- universe and universal-gate equality
- technical snapshot equality
- Re-Rating scanner equality except data-completeness effects that do not alter its existing conditions
- Growth-Pullback newly resolved true/false/null counts by field
- Biotech catalyst qualification changes with evidence paths
- number of catalyst candidates, scoring-ready catalysts and score distribution
- number of fully scored opportunities
- Top 20 under v1.1 with full component availability
- per-name delta from v1.0 partial score to v1.1 complete score
- false-positive audit sample and null-reason distribution

A v1.1 activation recommendation requires the acceptance gates in the specification, not merely a non-zero count of fully scored names.

## 14. Explicit non-goals

SOE-1.1.0 does not add:

- options/implied volatility scoring
- social sentiment
- machine-learning ranking
- broker integration
- position sizing
- short strategies
- non-US markets
- changes to Entry Score or Milestone 3 trade construction

Those remain separate milestones.
