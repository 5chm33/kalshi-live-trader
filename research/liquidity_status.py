"""Report measured paper-research liquidity from recorded WebSocket books; no network or orders."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.liquidity import LiquidityPolicy, liquidity_report
from research.models import BookLevel, CanonicalBook, SourceStamp
from research.store import ResearchStore


def _book(row: object) -> CanonicalBook:
    payload = json.loads(row["payload_json"])
    stamp = SourceStamp(
        "kalshi_ws_orderbook",
        datetime.fromisoformat(row["received_at"]),
        datetime.fromisoformat(row["source_at"]) if row["source_at"] else None,
        row["payload_sha256"],
    )
    return CanonicalBook(
        payload["ticker"],
        tuple(BookLevel(Decimal(price), Decimal(qty)) for price, qty in payload["yes_bids"]),
        tuple(BookLevel(Decimal(price), Decimal(qty)) for price, qty in payload["no_bids"]),
        stamp,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--minimum-observations", type=int, default=50)
    parser.add_argument("--maximum-spread", type=Decimal, default=Decimal("0.03"))
    parser.add_argument("--minimum-top-depth", type=Decimal, default=Decimal("3"))
    parser.add_argument("--required-contracts", type=Decimal, default=Decimal("1"))
    args = parser.parse_args()
    store = ResearchStore(args.database)
    with store.connect() as conn:
        rows = conn.execute("SELECT * FROM observations WHERE entity_type='kalshi_ws_orderbook' ORDER BY received_at").fetchall()
    by_ticker: dict[str, list[CanonicalBook]] = defaultdict(list)
    for row in rows:
        try:
            book = _book(row)
            by_ticker[book.ticker].append(book)
        except (KeyError, ValueError, TypeError):
            continue
    policy = LiquidityPolicy(args.minimum_observations, args.maximum_spread, args.minimum_top_depth, args.required_contracts)
    report = {ticker: {side: liquidity_report(books, side, policy) for side in ("yes", "no")} for ticker, books in sorted(by_ticker.items())}
    print(json.dumps({"mode": "paper_only_no_orders", "tickers": report, "observation_rows": len(rows)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
