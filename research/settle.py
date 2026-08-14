"""Reconcile settled Kalshi market outcomes into the V11 paper ledger.

This module is read-only: it calls only the GET-only research client and writes
local SQLite records used for evaluation.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from research.kalshi_readonly import ReadOnlyKalshiClient
from research.models import SourceStamp, payload_hash
from research.store import ResearchStore


class SettlementReconciler:
    def __init__(self, client: ReadOnlyKalshiClient, store: ResearchStore):
        self.client = client
        self.store = store

    @staticmethod
    def _market(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        inner = payload.get("market")
        return inner if isinstance(inner, Mapping) else payload

    def run(self, limit: int = 250) -> dict[str, int]:
        pending = self.store.unsettled_tickers()[:limit]
        summary = {"checked": 0, "settled": 0, "still_open": 0, "unrecognized": 0}
        for ticker in pending:
            payload = self.client.market(ticker)
            market = self._market(payload)
            summary["checked"] += 1
            result = str(market.get("result", "")).lower()
            status = str(market.get("status", "")).lower()
            if result in {"yes", "no"}:
                stamp = SourceStamp(
                    source="kalshi_rest_market",
                    source_at=datetime.now(timezone.utc),
                    received_at=datetime.now(timezone.utc),
                    payload_sha256=payload_hash(payload),
                )
                self.store.record_settlement(ticker, result, stamp, payload)
                summary["settled"] += 1
            elif status in {"open", "active", "initialized"}:
                summary["still_open"] += 1
            else:
                summary["unrecognized"] += 1
        return summary
