# Milestone 2.5F — institutional ownership and short-float validation

Date: 2026-08-31  
Model: `SOE-1.0.0`  
Scope: enrich the free/public validation stack with institutional ownership and short float without changing any frozen investment rule, threshold, score weight, scanner condition, or classification.

## Implementation

The free-public provider now includes an isolated Yahoo Finance `quoteSummary` ownership/statistics adapter for prototype validation:

- `majorHoldersBreakdown.institutionsPercentHeld` → `institutional_ownership`
- `defaultKeyStatistics.shortPercentOfFloat` → `short_float`

Both fields are normalized as fractions. Missing values stay `null`; values outside broad plausible ranges are rejected rather than clipped or silently re-scaled. Field-level provenance, fetch time and staleness are retained.

Ownership enrichment is optional. If Yahoo ownership data fails for one ticker, the error is recorded and valid SEC EDGAR fundamentals are retained rather than discarded.

## Frozen-rule integration

No new scoring rule was introduced.

The existing SOE liquidity component already awards institutional-ownership points. Once ownership is present, that existing component can use all 5 available liquidity points rather than only the 3 dollar-volume points.

The frozen rules file already contains:

```yaml
short_float_over_25: [-2, -2]
```

Milestone 2.5F only supplies the missing normalized input and activates that existing penalty when `short_float > 0.25`. Exactly 25% does not trigger it. Missing short float never becomes zero and never creates a penalty.

Deterministic tests verify:

- 31% short float produces the existing fixed −2 penalty.
- exactly 25% produces no penalty.
- implausible ownership/short-float ranges are rejected.
- Yahoo cookie/crumb bootstrap and caching work without credentials.

## Live ownership smoke

GitHub Actions live run `33418040571` completed successfully against five real securities:

| Ticker | Institutional ownership | Short float | Status |
| --- | ---: | ---: | --- |
| DELL | 75.596% | 4.64% | Valid |
| AVGO | 80.147% | 1.20% | Valid |
| FAST | 87.604% | 3.10% | Valid |
| LUV | 93.751% | 6.78% | Valid |
| ARWR | 85.597% | 9.07% | Valid |

All five records passed range validation and were non-stale at the smoke timestamp. None of these five exceeded the frozen 25% short-float threshold, so the live sample generated no short-float penalty; the threshold behavior is covered deterministically by tests.

## End-to-end targeted scanner audit

GitHub Actions run `33418182954` completed successfully after wiring ownership into SEC fundamentals and the existing scoring/penalty path.

The scanner decisions remained stable relative to Milestone 2.5E:

| Ticker | Scanner result | Ownership effect |
| --- | --- | --- |
| DELL | **Re-Rating QUALIFIED** | Liquidity increased from 3/5 to 5/5; partial Opportunity Score 33 → 35 |
| FAST | **Re-Rating QUALIFIED** | Liquidity increased from 3/5 to 5/5; partial Opportunity Score 32 → 34 |
| AVGO | Not qualified | Ownership available; technical Re-Rating requirement still false |
| LUV | Not qualified | Ownership available; technical Re-Rating requirement still false |
| ARWR | Biotech/Catalyst DATA_INCOMPLETE | Ownership available; catalyst/runway inputs remain the blocker |

This is the intended behavior: better data completeness changes only the score components that were already designed to consume those fields. It does not weaken scanner gates or manufacture qualification.

## SEC Form 13F status

SEC Form 13F remains the preferred public-source direction for a commercial-quality institutional-ownership implementation where practical. It is **not** claimed as implemented in this milestone.

A reliable full-universe aggregation requires issuer/security identity resolution, particularly robust CUSIP-to-listed-ticker mapping, amendment handling, reporting-period aggregation and avoidance of double counting. The current project does not yet have a sufficiently dependable free production mapping layer for that task. Therefore Yahoo ownership data remains explicitly isolated as prototype-only validation data rather than being mislabeled as SEC-derived institutional ownership.

## Commercial-data caveat

Yahoo's web endpoints are undocumented for this project and provide no contractual SLA or explicit commercial redistribution grant. They are suitable for validating the SOE discovery model and data plumbing, but must be replaced or separately licensed before commercial production.

## Remaining material data gaps

After Milestone 2.5F, the principal free-data gaps affecting full score/scanner completeness remain:

1. Valuation support / expected swing upside.
2. Scored catalyst materiality and surprise inputs.
3. Growth Pullback guidance-deterioration state and explicit balance-sheet distress state.
4. Biotech cash-runway/financing completeness and verified scored catalysts.
5. Forward EBITDA and revenue/EBITDA revision breadth.
6. Market breadth for the regime model.

## Conclusion

Milestone 2.5F validates institutional ownership and short-float enrichment end to end. The new fields are live, normalized, provenance-aware and integrated into the pre-existing liquidity and penalty paths. DELL and FAST remain genuine frozen-rule Re-Rating candidates while their partial scores become more complete.

No `SOE-1.0.0` investment rule was changed. Investment Execution Engine v1.7.2 was not modified. Milestone 3 remains deferred.
