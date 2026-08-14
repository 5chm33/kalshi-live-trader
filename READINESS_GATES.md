# Research and Production Readiness Gates

A positive research result **does not enable trading**. V11 has no live-order pathway, and no research function is permitted to create one.

> **Rule:** Passing research readiness creates a **review candidate** only. Production readiness and explicit human approval are separate, later gates.

| Gate | Purpose | Minimum conditions | Output | Does it enable orders? |
|---|---|---|---|---|
| Research readiness | Establish whether a narrowly registered hypothesis has credible empirical support | Immutable manifest and stopping rule; prospective candidate-to-settlement chain; declared exclusions; out-of-sample lower confidence bound; calibration and placebo checks; fee/depth/latency sensitivity | `review_candidate` or `retired` | **No** |
| Independent model review | Challenge leakage, selection effects, repeated testing, and fill assumptions | Fresh checkout plus read-only ledger reproduction; documented reviewer conclusion | `independent_review_complete` | **No** |
| Production readiness | Establish operational safety, not expected value | Credential isolation; reconciliation; tested kill switch; exchange-status handling; order idempotency; sell/cancel behavior; durable audit trail; monitoring with an alert destination; incident runbook | `production_review_candidate` | **No** |
| Human activation | A user makes an explicit, transaction-specific decision after reviewing both gates | Explicit approval in the active conversation stating the intended scope, risk limits, and consequence | Separate confirmation record | Only then, and only if a future independently reviewed order system exists |

## Permanent Constraints

The following conditions are always disqualifying for research promotion or production review. A new study must be separately versioned rather than silently patched around them.

| Condition | Result |
|---|---|
| Manifest lacks a pinned code revision, defined eligible population, or fixed stopping rule | Study is ineligible. |
| Candidate, quote, fill, or settlement data are missing for the declared lifecycle | Study is ineligible. |
| Positive result fails its registered placebo, calibration, uncertainty, liquidity, or latency sensitivity check | Study is retired or re-specified as a new version. |
| Research result has not been independently reproduced | Cannot progress beyond review candidate. |
| Any production control is absent or untested | Cannot progress to production review. |
| Political market | Permanently blocked. |

## Current Status

V11 is **not research-ready for promotion** and **not production-ready**. The published MLB generic late-lead rule is retired. The weather pilot is collecting its first settlement-mapped prospective window. No study has a positive, independently reproducible, fee-adjusted, fill-aware out-of-sample result.
