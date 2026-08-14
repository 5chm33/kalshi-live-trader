# V11 Research Integrity Acceptance Matrix

**Status:** Paper-only research system. **Scope:** This document converts the two Elicit reviews dated 2026-08-14 into testable requirements. It does not authorize trading or assert profitability.

## Triage

| ID | Finding | Assessment | Acceptance criterion | Priority |
|---|---|---|---|---|
| R1 | Clean-machine validator can pass while dependencies are absent | Valid | Validator verifies declared modules before tests and CI runs in a fresh environment | P0 |
| R2 | Research package could import legacy execution code | Valid defense-in-depth gap | Static regression forbids `core.kalshi_client`, `place_order`, and HTTP mutations under `research/` | P0 |
| R3 | Flexible research risks accidental train/test overlap | Valid | Immutable strategy manifest binds hypothesis, feature schema, training/holdout dates, code commit, and first prospective timestamp; evaluator fails on overlap | P0 |
| R4 | Existing reports lack decision record | Valid | Every published evaluation includes a signed decision record with hypothesis, available data, exclusions, endpoint, promotion/retirement/data criteria, and falsifier | P0 |
| R5 | Archived MLB timing is too uncertain for event-time evidence | Valid | Record source/receipt/book timestamps and apply explicit post-state and stale-book censoring; report sensitivity windows | P1 |
| R6 | Paper execution assumes a fillable snapshot | Valid | Separate settlement-only, taker, and maker lifecycles; taker model applies configurable latency/price haircut and stale-book rejection | P1 |
| R7 | Null/placebo controls are absent | Valid | Every directional study includes shifted-state/placebo and market-baseline controls before any promotion review | P1 |
| R8 | Promotion gates omit uncertainty and multiple-testing controls | Valid | Pre-registration defines primary metric, CI method, lower-bound threshold, calibration target, drawdown/locked-capital limits, and variant budget | P1 |
| R9 | Reports lack capital efficiency economics | Valid | Candidate report distinguishes entry-to-settlement vs entry-to-exit, fee-adjusted dollars/contract, capital at risk, holding time, locked-capital return, turnover, and concurrent exposure | P1 |
| R10 | Settlement and fee assumptions are not retained at row level | Valid | Manifest plus candidate record retain fee schedule source/version, multiplier, rounding, tick, settlement-rule hash, and source mapping | P1 |
| R11 | Stream/data health lacks measurements | Valid | Collector emits reconnects, gaps, resyncs, stale-book age, offset, coverage, and zero-observation metrics | P1 |
| R12 | Market selection can create hidden overfitting | Valid | Separate market-universe liquidity report is frozen before a hypothesis run | P1 |
| R13 | Research records are not append-only snapshots | Valid | Hash-chained signed local evaluation snapshots include manifest, code revision, dataset fingerprint, and result | P1 |
| R14 | Restore and monitoring have not been tested | Valid | Nightly backup, tested restore/replay script, independent health check, and alert log are deployed | P1 |
| R15 | Tax/account exports are missing | Valid | Read-only account export contains fills, settlements, fees, deposits/withdrawals when available, and raw export hash | P2 |
| R16 | Define project retirement criteria | Valid | Decision policy states measurable conditions for data-only continuation, retirement, or narrowed re-study | P2 |
| R17 | More strategies now | Rejected for now | No new predictive family is added until R1–R14 are complete; active collectors are evidence collection, not strategy promotion | Enforced |

## Decision Record Standard

Every evaluation must create an immutable JSON record before seeing that evaluation’s result. The record must state the hypothesis, strategy version, allowed market universe, data available at decision time, excluded rows and reasons, primary endpoint, fee and execution lifecycle, uncertainty method, promotion threshold, retirement threshold, additional-data criterion, and the observation that would falsify the conclusion. It must also contain a SHA-256 fingerprint of the input dataset and the source-code commit.

## Promotion Boundary

A method remains **data collection only** unless all P0 and relevant P1 acceptance criteria pass. A positive point estimate alone is insufficient. No V11 module may submit, cancel, amend, or exit an exchange order. Any future execution system would require separate review and a separate repository.

## Source

This matrix is derived from user-provided Elicit reviews in `pasted_content_26.txt` and `pasted_content_27.txt` on 2026-08-14.
