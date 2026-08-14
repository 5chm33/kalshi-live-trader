"""Read-only account reconciliation for the V11 research system."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from research.kalshi_readonly import ReadOnlyKalshiClient
from research.models import SourceStamp, payload_hash
from research.store import ResearchStore


@dataclass(frozen=True)
class ReconciliationSummary:
    cash_dollars: str | None
    portfolio_value_raw: Any
    position_count: int
    fill_count: int
    resting_order_count: int
    observations_written: int


class AccountReconciler:
    """Captures production-account state using authenticated GET requests only."""

    def __init__(self, client: ReadOnlyKalshiClient, store: ResearchStore):
        self.client = client
        self.store = store

    @staticmethod
    def _stamp(source: str, payload: Mapping[str, Any]) -> SourceStamp:
        return SourceStamp(
            source=source,
            source_at=None,
            received_at=datetime.now(timezone.utc),
            payload_sha256=payload_hash(payload),
        )

    def _capture_page(self, source: str, entity_type: str, entity_id: str,
                      payload: Mapping[str, Any]) -> int:
        return int(self.store.record_observation(self._stamp(source, payload), entity_type, entity_id, payload))

    @staticmethod
    def _all_pages(fetch: Callable[[str | None], Mapping[str, Any]], collection_key: str) -> list[Mapping[str, Any]]:
        cursor: str | None = None
        items: list[Mapping[str, Any]] = []
        seen_cursors: set[str] = set()
        while True:
            page = fetch(cursor)
            page_items = page.get(collection_key, [])
            if not isinstance(page_items, list):
                raise ValueError(f"{collection_key} response is not a list")
            items.extend(item for item in page_items if isinstance(item, Mapping))
            next_cursor = page.get("cursor") or ""
            if not next_cursor:
                break
            if next_cursor in seen_cursors:
                raise RuntimeError(f"pagination cursor repeated for {collection_key}")
            seen_cursors.add(next_cursor)
            cursor = str(next_cursor)
        return items

    def reconcile(self) -> ReconciliationSummary:
        balance = self.client.balance()
        positions_page = self.client.positions()
        fills_page = self.client.fills()
        orders_page = self.client.resting_orders()

        written = 0
        written += self._capture_page("kalshi_rest", "account_balance", "primary", balance)
        written += self._capture_page("kalshi_rest", "positions_page", "initial", positions_page)
        written += self._capture_page("kalshi_rest", "fills_page", "initial", fills_page)
        written += self._capture_page("kalshi_rest", "resting_orders_page", "initial", orders_page)

        # Write every object separately as well, using a deterministic entity ID.
        positions = self._all_pages(self.client.positions, "market_positions")
        fills = self._all_pages(self.client.fills, "fills")
        orders = self._all_pages(self.client.resting_orders, "orders")
        for position in positions:
            written += self._capture_page("kalshi_rest", "position", str(position.get("ticker", "unknown")), position)
        for fill in fills:
            written += self._capture_page("kalshi_rest", "fill", str(fill.get("fill_id", "unknown")), fill)
        for order in orders:
            written += self._capture_page("kalshi_rest", "resting_order", str(order.get("order_id", "unknown")), order)

        return ReconciliationSummary(
            cash_dollars=balance.get("balance_dollars"),
            portfolio_value_raw=balance.get("portfolio_value"),
            position_count=len(positions),
            fill_count=len(fills),
            resting_order_count=len(orders),
            observations_written=written,
        )
