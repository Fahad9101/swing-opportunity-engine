# Milestone 2.5G — free/public valuation and expected-upside validation

Date: 2026-08-31  
Model: `SOE-1.0.0`  
Scope: populate and validate the existing frozen valuation-support and expected-upside inputs using free/public data, without changing any SOE investment rule, threshold, scoring weight, scanner condition, classification, or Investment Execution Engine file.

## Result

Milestone 2.5G is validated on real data. The discovery layer can now populate conventional-company valuation support and analyst-consensus headroom while preserving missing-data semantics and the frozen SOE scoring architecture.

No change was made to `config/soe_v1_0_rules.yaml`. Milestone 3 remains deferred.

## Methodology

### 1. Historical valuation support

For eligible conventional U.S. common shares, SEC EDGAR companyfacts supply compact quarterly revenue, net-income and share history. Yahoo Finance completed EOD prices provide the corresponding split-adjusted market prices.

The historical normalized-value hierarchy is:

1. `HISTORICAL_MEDIAN_PE` when positive TTM net income and adequate history exist.
2. `HISTORICAL_MEDIAN_PS` only as an explicit fallback when earnings are not usable and the sector adapter allows a sales multiple.
3. `null` when the available public data are not sufficiently reliable for either path.

At least four valid historical multiple observations are required. `fundamental_undervaluation` is calculated as normalized value per share divided by current price minus one. `valuation_discount` is true only when that self-relative normalized value is above current price.

This input feeds the existing frozen 8-point valuation-support component and the pre-existing Re-Rating `valuation_discount` condition. No score band was changed.

### 2. Split/restatement normalization

Yahoo historical prices are split-adjusted. SEC instant share facts can contain pre-split and retrospectively restated values in the same companyfacts history. If a large share-count discontinuity is detected, historical multiple observations use the current share basis and explicitly record `CURRENT_SHARES_SPLIT_NORMALIZED`. Otherwise the engine uses `PERIOD_END_SHARES`.

This is a data-normalization safeguard only. It does not alter any investment rule or scoring threshold.

### 3. Expected-upside headroom

Yahoo Finance `financialData.targetMeanPrice` supplies the current analyst-consensus mean target when available and non-stale. The normalized input is:

`expected_swing_upside = consensus_mean_target / current_price - 1`

This is explicitly a **prototype discovery-stage headroom proxy**. It is **not** Milestone-3 T2, not a 1–8 week price forecast, and not a claim that analyst consensus will be achieved during the swing horizon.

The analyst headroom input and historical valuation-support input remain independent, matching the frozen SOE design: 12 possible upside points plus 8 possible valuation-support points.

### 4. Specialized exclusions

Generic historical-multiple valuation is not forced onto:

- biotech, which remains under the separate catalyst/runway framework;
- ADRs, where the free stack cannot yet guarantee correct ADR-to-ordinary-share ratio normalization;
- Real Estate names, where FFO/AFFO-specific valuation is not yet available.

Financial companies may use a valid earnings-based historical path, but generic P/S fallback is disabled. Unsupported cases remain `null` rather than receiving an invented score.

## Deterministic verification

GitHub Actions run `33421381457` completed successfully after the final test correction.

Result: **96 passed, 0 failed**. One non-failing Starlette/httpx deprecation warning was reported.

Coverage includes:

- historical P/E normalization;
- explicit P/S fallback;
- independent upside and valuation-support scoring inputs;
- no manufactured valuation support from analyst targets;
- stale analyst-target rejection;
- split/restatement share normalization;
- missing-data preservation;
- prior ownership/short-float and scanner regression coverage.

The frozen valuation scorer itself was not modified.

## Live targeted real-data audit

GitHub Actions run `33421271134`, job `99583963727`, completed successfully using real free/public inputs. The live audit covered DELL, AVGO, FAST, LUV and ARWR.

| Ticker | Current price | Consensus headroom | Historical method | Historical normalized value | Self-relative support | Valuation score | Scanner outcome |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- |
| DELL | $456.24 | +11.84% | Median P/E 16.73x | $216.83 | -52.47% | 0/20 | **Re-Rating QUALIFIED**, partial Opportunity Score 35 |
| AVGO | $368.79 | +42.62% | Median P/S 21.11x | $334.86 | -9.20% | 12/20 | Not qualified; Re-Rating technical gate false |
| FAST | $49.78 | -2.51% | Median P/E 38.64x | $45.52 | -8.55% | 0/20 | **Re-Rating QUALIFIED**, partial Opportunity Score 34 |
| LUV | $39.64 | +29.44% | Unavailable | — | `null` | 8/20 of 12 available points | Not qualified; Re-Rating technical gate false |
| ARWR | $84.91 | `null` | N/A by design | — | `null` | unavailable | Biotech/Catalyst `DATA_INCOMPLETE` |

### DELL

DELL remains a genuine Re-Rating candidate through four non-valuation conditions: improving FCF/EBITDA trajectory, improving margin, positive revisions and positive QoQ revenue growth, with its technical requirement intact. The new valuation layer does **not** endorse current price as historically cheap: its normalized historical P/E value is approximately $216.83 versus $456.24, and analyst consensus headroom of 11.84% is below the frozen 15% first upside-scoring band. The result is correctly 0/20 for valuation while Re-Rating still qualifies 4/6.

### AVGO

AVGO shows substantial analyst-consensus headroom of about 42.62%, producing the frozen 12-point upside subscore, but its self-relative historical P/S support is negative by about 9.20%. It therefore receives no valuation-support points. More importantly, the Re-Rating technical requirement remains false, so strong fundamentals and analyst headroom do not manufacture scanner qualification.

The historical series records `CURRENT_SHARES_SPLIT_NORMALIZED`, demonstrating the split safeguard on live data.

### FAST

FAST remains a frozen-rule Re-Rating qualifier, but the new valuation data are not supportive at the audit price. Its own historical median P/E implies approximately $45.52 versus $49.78 current price, while consensus mean target is approximately $48.53. The valuation component therefore contributes 0/20, and the partial Opportunity Score remains 34 rather than being artificially lifted by the new data.

FAST also records `CURRENT_SHARES_SPLIT_NORMALIZED`, confirming that mixed pre/post-split SEC share facts are not multiplied blindly by split-adjusted historical prices.

### LUV

LUV has approximately 29.44% analyst-consensus headroom, which produces 8/12 available upside points. A sufficiently dependable generic historical normalized multiple was not available, so valuation support remains `null` rather than zero or fabricated. The security still fails the Re-Rating technical gate.

### ARWR

ARWR remains outside conventional valuation treatment. No generic P/E/P/S valuation or analyst expected-upside score is forced onto the biotech. Its Biotech/Catalyst scanner remains `DATA_INCOMPLETE` because cash-runway eligibility and a verified scored A/B catalyst are still missing.

## What changed in data completeness

Milestone 2.5G closes the principal conventional valuation-data gap for the discovery layer where the public data are adequate. It also makes the original Re-Rating valuation condition auditable rather than silently unavailable for many conventional names.

Importantly, better data did not force favorable results. DELL and FAST remained scanner candidates even though valuation support was negative; AVGO and LUV remained blocked by technical rules; ARWR remained incomplete under biotech-specific rules.

## Remaining material data gaps

The highest-value remaining free/public-data gaps are now:

1. scored catalyst materiality, date confidence and surprise/re-rating inputs;
2. Growth Pullback guidance-deterioration state and explicit balance-sheet-distress state;
3. biotech cash-runway/financing completeness and verified scored catalysts;
4. forward EBITDA plus revenue/EBITDA revision breadth;
5. market breadth for the regime model.

A fresh full-market validation run is still required before Milestone 2.5 is considered fully production-validated.

## Commercial-data caveat

Yahoo's web endpoints remain prototype-only in this project. They have no contractual SLA or explicit commercial redistribution grant here and must be replaced or separately licensed before commercial production. SEC EDGAR remains the primary public source for reported company fundamentals.

## Conclusion

Milestone 2.5G successfully populates and validates the frozen SOE valuation-support and expected-upside inputs using free/public data, while preserving null semantics, sector/asset-type safeguards, provenance and scanner discipline.

- `SOE-1.0.0` investment rules: **unchanged**.
- Scoring bands and weights: **unchanged**.
- Scanner logic and classifications: **unchanged**.
- Investment Execution Engine v1.7.2: **not modified**.
- Milestone 3: **not started**.
