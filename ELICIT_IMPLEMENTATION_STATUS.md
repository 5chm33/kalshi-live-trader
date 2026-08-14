# Elicit Review Implementation Status

**Branch:** `research-v11`  
**Mode:** Paper-only; no Kalshi exchange mutation capability exists in the V11 research package.  
**Status date:** 2026-08-14 UTC

This document records what the two Elicit reviews identified, what was implemented, and what remains deliberately unavailable. It is an engineering status record, not evidence of profitability.

| Elicit requirement | Disposition | Evidence in V11 |
|---|---|---|
| Fresh-environment reproducibility | Implemented | `scripts/validate_clean_env.sh`, `.github/workflows/validate.yml`, declared dependencies, and CI run the tests from a clean virtual environment. |
| Isolation from legacy live execution | Implemented | `tests/test_research_isolation.py` rejects legacy execution imports and HTTP mutation behavior; `main.py` remains hard-disabled. |
| Secrets and configuration safety | Implemented | Local configuration and audit key are permission-restricted and ignored; public validation runs a credential-pattern scan. |
| Immutable manifests and pre-analysis decisions | Implemented with one legacy exception documented | `research/audit.py`, `strategy_manifests`, `decision_records`, signed local audit key, and `weather_settlement_mapped_v1_0_1`. The earlier v1.0.0 manifest remains auditable but is explicitly ineligible because it lacked a pinned commit. |
| Append-only evaluation snapshots | Implemented | `evaluation_snapshots` has immutable digest identity and optional local HMAC signatures through `research/snapshot_evaluation.py`. |
| Lifecycle-consistent economics | Implemented | `research/economics.py` separates entry-to-settlement from entry-to-exit and reports locked capital and observed losing streaks. |
| Event-time and stream-health measurement | Implemented with source limitation labeled | WebSocket observations now retain sequence, source/receipt timing, poll-to-book delay, reconnects, errors, and sequence gaps. The public MLB feed does **not** provide an independently verified score-change timestamp, so the data label never treats poll time as true event time. |
| Stale-book and latency realism | Implemented for taker paper stress only | `TakerExecutionPolicy` rejects stale books and applies configurable adverse-price haircuts. Maker queue position and partial-fill waiting are intentionally **not modeled**, not assumed favorable. |
| Multiple testing, confidence, calibration, and placebo controls | Implemented | `research/statistical_gates.py`, `research/placebo.py`, and fixed variant budgets in manifests block promotion on sparse or unregistered results. |
| Liquidity/market selection | Implemented | `research/liquidity.py` and `research/liquidity_status.py` report observed width, displayed depth, and coverage; lack of data is ineligible rather than favorable. |
| Backup, restore test, retention export | Implemented and tested on cloud | Daily `kalshi-research-v11-backup.timer` uses SQLite backup, integrity/restore verification, checksums, and compressed exports. The first production run completed successfully. |
| Independent health monitoring | Implemented with alerting limitation | Five-minute `kalshi-research-v11-health.timer` validates four collectors, SQLite integrity, and observation freshness. It exposes nonzero systemd/journal status. An external alert target has not been configured because none was provided. |

## Remaining Non-Promotable Gaps

The following are constraints, not unresolved code defects. They prevent any claim of an executable or profitable strategy.

| Constraint | Consequence |
|---|---|
| No verified positive, net, out-of-sample strategy | Live activation remains prohibited. |
| Weather v1.0.1 prospective window has just started | It has no settled calibration sample yet. |
| No independent provider score-change timestamp | MLB studies may measure poll-to-book time but cannot claim true score-event latency. |
| No maker/queue-position model | V11 does not claim maker rebate, queue, or passive-fill edge. |
| No external health-alert destination | Failed health checks appear in systemd/journal only. |
| Liquidity report currently has no live-book rows outside game windows | It cannot select eligible contracts until the WebSocket collector captures live games. |

> **Promotion rule:** A paper study can only request a separate review after its immutable manifest, prospectively timestamped data, station/contract settlement mapping where applicable, fee/depth/latency sensitivity, calibration gate, and out-of-sample lower confidence bound all satisfy the pre-registered rule. That rule has not been met by any V11 study.
