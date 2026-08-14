"""Bounded signed-GET-only mutually-exclusive NO-basket snapshot collector."""
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

from research.guards import is_political_market
from research.kalshi_readonly import ReadOnlyKalshiClient
from research.mec_no_basket import assess_mec_no_basket
from research.models import SourceStamp, decimal, payload_hash
from research.orderbook import parse_orderbook
from research.run_mlb_paper import load_config
from research.store import ResearchStore


def run_cycle(client: ReadOnlyKalshiClient, store: ResearchStore, max_events: int = 25, screen_legs: int = 12, requested_contracts: str = "1") -> dict[str, Any]:
    if max_events <= 0 or screen_legs < 2:
        raise ValueError("invalid bounded MEC collector parameters")
    page = client.get("/events", {"status": "open", "limit": 200})
    events = [event for event in page.get("events", []) if isinstance(event, dict)]
    scanned = blocked = eligible_events = eligible_legs = candidates = stored = errors = 0
    for event in events:
        if scanned >= max_events:
            break
        if is_political_market(event):
            blocked += 1
            continue
        if not bool(event.get("mutually_exclusive")):
            continue
        event_ticker = str(event.get("event_ticker", ""))
        if not event_ticker:
            continue
        scanned += 1
        try:
            detail = client.get(f"/events/{event_ticker}")
            raw_markets = [market for market in detail.get("markets", []) if isinstance(market, dict)]
            # Use the event response's current no_ask only to select a bounded
            # set for full orderbook inspection; all final costs use depth.
            markets = [
                market for market in raw_markets
                if str(market.get("market_type", "")) == "binary"
                and str(market.get("status", "")).lower() in {"open", "active"}
                and market.get("no_ask_dollars") is not None
                and decimal(market.get("no_ask_dollars")) > 0
            ]
            markets.sort(key=lambda market: decimal(market["no_ask_dollars"]))
            markets = markets[:screen_legs]
            if len(markets) < 2:
                continue
            eligible_events += 1
            books = {}
            raw_books = {}
            for market in markets:
                ticker = str(market["ticker"])
                response = client.orderbook(ticker)
                raw_books[ticker] = response
                now = datetime.now(timezone.utc)
                books[ticker] = parse_orderbook(ticker, response, SourceStamp("kalshi_rest_mec_no_basket", now, None, payload_hash(response)))
            assessments = assess_mec_no_basket(event_ticker, books, requested_contracts=requested_contracts)
            eligible_legs += len(books)
            candidates += sum(int(assessment.is_candidate) for assessment in assessments)
            record = {
                "event": event, "detail": detail, "orderbooks": raw_books,
                "assessments": [{
                    "tickers": assessment.tickers, "matched_contracts": str(assessment.matched_contracts),
                    "leg_prices": [str(value) for value in assessment.leg_prices], "estimated_fees": [str(value) for value in assessment.estimated_fees],
                    "total_debit": str(assessment.total_debit), "guaranteed_payout_floor": str(assessment.guaranteed_payout_floor),
                    "net_locked_value": str(assessment.net_locked_value), "status": assessment.status, "rationale": assessment.rationale,
                    "atomic_fill_assumption": "not available; multi-leg atomicity reserve included",
                } for assessment in assessments],
            }
            now = datetime.now(timezone.utc)
            stored += int(store.record_observation(SourceStamp("kalshi_rest_mec_no_basket", now, None, payload_hash(record)), "mec_no_basket", event_ticker, record))
        except Exception:
            errors += 1
    return {
        "mode": "paper_only_no_orders", "events_returned": len(events), "events_scanned": scanned,
        "political_blocked": blocked, "eligible_events": eligible_events, "eligible_legs": eligible_legs,
        "candidates": candidates, "observations_stored": stored, "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 paper-only MEC NO-basket collector")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--max-events", type=int, default=25)
    parser.add_argument("--screen-legs", type=int, default=12)
    parser.add_argument("--requested-contracts", default="1")
    args = parser.parse_args()
    api_config, config = load_config(args.config)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    print(json.dumps(run_cycle(client, ResearchStore(args.database), args.max_events, args.screen_legs, args.requested_contracts), sort_keys=True))


if __name__ == "__main__":
    main()
