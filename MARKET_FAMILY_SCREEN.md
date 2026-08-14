# Broad Market-Family Screen — V11

**Purpose:** Rank non-political Kalshi market families for falsifiable, paper-only research. This is a discovery screen, not evidence of profitability.

The full parallel-screen raw results, including per-family source URLs and failure modes, are preserved at `/home/ubuntu/screen_kalshi_market_families.csv` and `/home/ubuntu/screen_kalshi_market_families.json`.

## Screening Outcomes

| Family | Initial research status | Primary external truth source | Research value | Core limitation |
|---|---|---|---|---|
| Cross-outcome / same-event parity | Highest priority | Kalshi order book and series rules | Does not require forecasting; testable with live book snapshots and fees | Atomic multi-leg execution, stale book levels, and fill risk can eliminate theoretical arbitrage |
| Weather | Eligible but only with contract/station mapping | Kalshi weather rules; NWS/NOAA CLI and ASOS observations | Deterministic outcomes and rich historical data | Exact settlement-station basis, wide spreads, and model calibration |
| Scheduled macro releases | Eligible | BLS, BEA, Federal Reserve official releases | Fixed event clock and deterministic published values | Consensus-data quality, revisions, and book evaporation at release |
| Crypto | Eligible but lower priority | Kalshi contract rules; CF Benchmarks settlement indices | Continuous public markets and exact time windows | Reference-index basis, severe adverse selection, and fast competition |
| Sports in-play | Needs a fully specified model before study | League-controlled live score/play-by-play feeds | Rich state data, but the generic MLB late-lead hypothesis already failed | Feed timing, low fill probability, and model misspecification |
| Corporate earnings/events | Eligible only with rule-to-filing mapping | SEC EDGAR, issuer releases, Kalshi contract rules | Deterministic publication events | Low liquidity, filing/release timing, and pre-release information already priced |

## Authoritative Sources

- Kalshi API and WebSocket documentation: https://docs.kalshi.com/welcome
- Kalshi weather-market specification: https://help.kalshi.com/en/articles/13823837-weather-markets
- National Weather Service: https://www.weather.gov
- NOAA NCEI station archives: https://www.ncei.noaa.gov
- U.S. Bureau of Labor Statistics: https://www.bls.gov
- U.S. Bureau of Economic Analysis: https://www.bea.gov
- U.S. Federal Reserve: https://www.federalreserve.gov
- CF Benchmarks: https://www.cfbenchmarks.com
- SEC EDGAR: https://www.sec.gov/edgar
- Kalshi rulebook: https://kalshi.com/regulatory/rulebook

## Pre-registered Next Screen

The next implementation target is **same-event parity/arbitrage detection**. It must calculate the combined cost of executable YES/NO or mutually exclusive outcome legs using both sides of the book, documented fees, available depth, and atomic-fill risk. It remains paper-only until prospective book observations show a positive result net of those costs.
