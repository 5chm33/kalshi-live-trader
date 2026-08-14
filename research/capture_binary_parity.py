"""Bounded, signed-GET-only binary complement parity snapshot collector."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.binary_parity import assess_complement_parity
from research.guards import is_political_market
from research.kalshi_readonly import ReadOnlyKalshiClient
from research.models import SourceStamp, payload_hash
from research.orderbook import parse_orderbook
from research.run_mlb_paper import load_config
from research.store import ResearchStore


def run_cycle(
    client: ReadOnlyKalshiClient,
    store: ResearchStore,
    max_markets: int = 100,
    requested_contracts: str = "1",
) -> dict[str, Any]:
    if max_markets <= 0:
        raise ValueError("max_markets must be positive")
    payload = client.open_markets(limit=max_markets)
    markets = payload.get("markets", [])
    scanned = blocked = errors = candidates = stored = 0
    for market in markets:
        if not isinstance(market, dict):
            continue
        if is_political_market(market):
            blocked += 1
            continue
        ticker = str(market.get("ticker", ""))
        if not ticker:
            continue
        scanned += 1
        try:
            response = client.orderbook(ticker)
            now = datetime.now(timezone.utc)
            raw = {"market": market, "orderbook": response}
            stamp = SourceStamp(
                source="kalshi_rest_binary_parity", received_at=now, source_at=None,
                payload_sha256=payload_hash(raw),
            )
            book = parse_orderbook(ticker, response, stamp)
            assessment = assess_complement_parity(book, requested_contracts=requested_contracts)
            record = {
                "market": market,
                "assessment": {
                    "ticker": assessment.ticker,
                    "requested_contracts": str(assessment.requested_contracts),
                    "matched_contracts": str(assessment.matched_contracts),
                    "yes_average_price": str(assessment.yes_average_price),
                    "no_average_price": str(assessment.no_average_price),
                    "yes_fee": str(assessment.yes_fee),
                    "no_fee": str(assessment.no_fee),
                    "total_debit": str(assessment.total_debit),
                    "locked_payout": str(assessment.locked_payout),
                    "net_locked_value": str(assessment.net_locked_value),
                    "status": assessment.status,
                    "rationale": assessment.rationale,
                    "atomic_fill_assumption": "not available; atomicity reserve included",
                },
                "orderbook": response,
            }
            stored += int(store.record_observation(stamp, "binary_complement_parity", ticker, record))
            candidates += int(assessment.is_candidate)
        except Exception:
            errors += 1
    return {
        "mode": "paper_only_no_orders", "open_markets_returned": len(markets),
        "markets_scanned": scanned, "political_blocked": blocked, "errors": errors,
        "observations_stored": stored, "parity_candidates": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 paper-only binary complement parity collector")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--max-markets", type=int, default=100)
    parser.add_argument("--requested-contracts", default="1")
    args = parser.parse_args()
    api_config, config = load_config(args.config)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    print(json.dumps(run_cycle(client, ResearchStore(args.database), args.max_markets, args.requested_contracts), sort_keys=True))


if __name__ == "__main__":
    main()
