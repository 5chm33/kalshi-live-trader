"""Bounded signed-GET-only same-event directional-cover snapshot collector."""
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

from research.directional_parity import assess_directional_cover, is_directional_upper_tail
from research.guards import is_political_market
from research.kalshi_readonly import ReadOnlyKalshiClient
from research.models import SourceStamp, decimal, payload_hash
from research.orderbook import parse_orderbook
from research.run_mlb_paper import load_config
from research.store import ResearchStore


def run_cycle(client: ReadOnlyKalshiClient, store: ResearchStore, max_events: int = 50, requested_contracts: str = "1") -> dict[str, Any]:
    if max_events <= 0:
        raise ValueError("max_events must be positive")
    page = client.get("/events", {"status": "open", "limit": 200})
    events = [event for event in page.get("events", []) if isinstance(event, dict)]
    scanned = blocked = structural_events = pairs = candidates = stored = errors = 0
    for event in events:
        if scanned >= max_events:
            break
        if is_political_market(event):
            blocked += 1
            continue
        # Multi-outcome groups are handled by their own study; this contract
        # requires ordered, co-resolving threshold markets.
        if bool(event.get("mutually_exclusive")):
            continue
        event_ticker = str(event.get("event_ticker", ""))
        if not event_ticker:
            continue
        scanned += 1
        try:
            detail = client.get(f"/events/{event_ticker}")
            markets = [market for market in detail.get("markets", []) if isinstance(market, dict) and is_directional_upper_tail(market)]
            markets.sort(key=lambda market: decimal(market["floor_strike"]))
            if len(markets) < 2:
                continue
            structural_events += 1
            books = {}
            for market in markets:
                ticker = str(market["ticker"])
                response = client.orderbook(ticker)
                now = datetime.now(timezone.utc)
                books[ticker] = (response, parse_orderbook(ticker, response, SourceStamp("kalshi_rest_directional_cover", now, None, payload_hash(response))))
            assessments = []
            for index, lower in enumerate(markets[:-1]):
                for upper in markets[index + 1:]:
                    lower_ticker, upper_ticker = str(lower["ticker"]), str(upper["ticker"])
                    assessment = assess_directional_cover(
                        books[lower_ticker][1], books[upper_ticker][1], lower["floor_strike"], upper["floor_strike"], requested_contracts=requested_contracts,
                    )
                    pairs += 1
                    candidates += int(assessment.is_candidate)
                    assessments.append({
                        "lower_ticker": assessment.lower_ticker, "upper_ticker": assessment.upper_ticker,
                        "lower_floor": str(assessment.lower_floor), "upper_floor": str(assessment.upper_floor),
                        "matched_contracts": str(assessment.matched_contracts), "total_debit": str(assessment.total_debit),
                        "net_locked_value": str(assessment.net_locked_value), "status": assessment.status, "rationale": assessment.rationale,
                    })
            raw = {"event": event, "detail": detail, "assessments": assessments, "orderbooks": {ticker: response for ticker, (response, _) in books.items()}}
            now = datetime.now(timezone.utc)
            stamp = SourceStamp("kalshi_rest_directional_cover", now, None, payload_hash(raw))
            stored += int(store.record_observation(stamp, "directional_threshold_cover", event_ticker, raw))
        except Exception:
            errors += 1
    return {
        "mode": "paper_only_no_orders", "events_returned": len(events), "events_scanned": scanned,
        "political_blocked": blocked, "structural_events": structural_events, "pairs_assessed": pairs,
        "candidates": candidates, "observations_stored": stored, "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 paper-only directional-cover collector")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    parser.add_argument("--max-events", type=int, default=50)
    parser.add_argument("--requested-contracts", default="1")
    args = parser.parse_args()
    api_config, config = load_config(args.config)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    print(json.dumps(run_cycle(client, ResearchStore(args.database), args.max_events, args.requested_contracts), sort_keys=True))


if __name__ == "__main__":
    main()
