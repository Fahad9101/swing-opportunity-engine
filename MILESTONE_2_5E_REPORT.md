# Milestone 2.5E — targeted real-data scanner validation

Date: 2026-08-31  
Model: `SOE-1.0.0`  
Purpose: verify that the live-validated free estimate/revision enrichment can move real securities from `DATA_INCOMPLETE` into genuine scanner qualification without changing frozen SOE rules.

## Result

The targeted audit used real free/public inputs for DELL, AVGO, FAST, LUV and ARWR:

- Nasdaq Trader / Nasdaq metadata for the universe and company metadata.
- Yahoo Finance completed EOD OHLCV for technicals.
- SEC EDGAR companyfacts for reported fundamentals.
- Yahoo Finance `quoteSummary` / `earningsTrend` for forward EPS growth and EPS revision data.
- No fixture or synthetic financial input.

The audit completed successfully in GitHub Actions.

## Scanner outcome

| Ticker | Re-Rating | Growth Pullback | Biotech/Catalyst | Key reason |
| --- | --- | --- | --- | --- |
| DELL | **QUALIFIED** | DATA_INCOMPLETE | N/A | 4/6 Re-Rating conditions true with intact technical gate |
| FAST | **QUALIFIED** | DATA_INCOMPLETE | N/A | 4/6 Re-Rating conditions true with intact technical gate |
| AVGO | Not qualified | DATA_INCOMPLETE | N/A | 4/6 Re-Rating fundamentals true, but technical gate false |
| LUV | Not qualified | DATA_INCOMPLETE | N/A | Technical Re-Rating gate false at the audit date |
| ARWR | DATA_INCOMPLETE | Not qualified | DATA_INCOMPLETE | Biotech catalyst and cash-runway eligibility remain unavailable |

## DELL audit

- Price: 456.24
- SMA50: 433.17
- SMA200: 244.73
- Pullback from 50-day high: 11.24%
- RSI14: 49.59
- QoQ revenue growth: +62.35% → TRUE
- Operating margin improving: TRUE
- FCF growth: +39.95% → TRUE
- EPS revision breadth: 3 upgrades / 0 downgrades → TRUE
- Forward EPS growth: +7.10% → FALSE versus >10% rule
- Valuation discount: unavailable
- Result: **4/6, Re-Rating QUALIFIED**

Diagnostic partial scores after qualification:

- Fundamental: 12/20 with 15 points currently available
- Technical: 11/15
- Revisions: 5/10 with EPS half available
- Balance sheet: 2/5
- Liquidity: 3/5 with institutional-ownership portion unavailable
- Catalyst: unavailable
- Valuation: unavailable
- Partial Opportunity Score: 33/100

The 33/100 value is not a complete actionable SOE Opportunity Score; it is the sum of presently available components. It must not be treated as a rejection caused by poor catalyst/valuation data, because those components are missing rather than zero.

## FAST audit

- Price: 49.78
- SMA50: 48.40
- SMA200: 45.16
- Pullback from 50-day high: 5.93%
- QoQ revenue growth: +8.41% → TRUE
- Forward EPS growth: +10.70% → TRUE
- Operating margin improving: TRUE
- EPS revision breadth: 10 upgrades / 0 downgrades → TRUE
- FCF growth: -3.68% → FALSE
- Valuation discount: unavailable
- Result: **4/6, Re-Rating QUALIFIED**

Diagnostic partial Opportunity Score: 32/100. Catalyst and valuation remain unavailable, and institutional ownership remains unavailable.

## AVGO audit

AVGO had four favorable Re-Rating conditions including +67.7% forward EPS growth and positive revisions, but the technical gate was false at the audit timestamp:

- Price: 368.79
- SMA50: 386.11
- SMA200: 369.38
- RSI14: 23.46

The engine correctly refused to qualify it despite strong fundamentals because the frozen technical gate was not satisfied.

## LUV audit

LUV had strong estimate momentum:

- Forward EPS growth: +43.70%
- EPS revisions: 16 upgrades / 4 downgrades
- YoY revenue growth: +16.40%

But price was below SMA50 and SMA200 at the audit timestamp, so the Re-Rating technical gate was false. No rule was weakened to force qualification.

## ARWR audit

ARWR remained correctly blocked from the Biotech/Catalyst scanner:

- Price > SMA50 and SMA200
- Pullback: 11.08%
- EPS revisions: 0 upgrades / 6 downgrades
- Cash-runway eligibility: unavailable from current normalized SEC facts
- Verified scored A/B catalyst: unavailable

No trial event was promoted into an FDA/PDUFA catalyst and no catalyst score was fabricated.

## Conclusion

The original zero-candidate result was primarily a data-availability problem rather than a scanner-logic failure. The free estimate/revision enrichment now produces genuine rule-compliant Re-Rating candidates: **DELL and FAST qualified in the targeted live audit without changing any SOE-1.0.0 investment threshold or weight.**

The next data gaps with the highest value are:

1. Valuation / expected swing upside.
2. Scored catalyst materiality and surprise.
3. Institutional ownership and short float.
4. Growth Pullback guidance / balance-sheet distress state.
5. Biotech cash-runway and catalyst completeness.

Milestone 3 remains intentionally deferred until the discovery layer is sufficiently complete to generate auditable candidate rankings rather than partial scores.
