"""Bounded, read-only MLB signal observation against live public data.

This intentionally has no order-submission path. The previous live entry point was
unsafe; its original implementation remains available in git history for review.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

from core.espn_feed import ESPNFeed
from core.market_matcher import MarketMatcher
from core.public_market import MarketDataError, PublicMarketClient, quote_from_orderbook
from strategies.latency_sniper import LatencySniper


def estimated_taker_fee(price: Decimal, count: int = 1) -> Decimal:
    """Standard-fee estimate only; actual Kalshi series fees may vary."""
    if count < 1 or not Decimal("0") < price < Decimal("1"):
        raise ValueError("invalid fee inputs")
    return (Decimal("0.07") * count * price * (1 - price)).quantize(
        Decimal("0.01"), rounding=ROUND_CEILING
    )


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def observe_cycle(feed: ESPNFeed, matcher: MarketMatcher, client: PublicMarketClient,
                  strategy: LatencySniper, output) -> dict:
    games, changes = feed.poll()
    for change in changes:
        strategy.on_score_change(change)
    matched = matcher.match_games(games)
    counters = {"games_in_progress": len(games), "score_changes": len(changes),
                "strict_matches": len(matched), "usable_books": 0,
                "universe_books": 0, "heuristic_candidates": 0,
                "quote_errors": 0, "real_orders": 0}

    # Prove public market discovery and orderbook connectivity even if none
    # of today's games has an open, correctly dated matching market.
    if not matched:
        for sample in matcher._get_markets("KXMLBGAME")[:5]:
            ticker = sample.get("ticker")
            if not ticker:
                continue
            try:
                quote = quote_from_orderbook(client.get_orderbook(ticker))
                if quote is None:
                    continue
                counters["universe_books"] = 1
                output.write(json.dumps({"type": "unmatched_market_quote", "observed_at": timestamp(),
                    "ticker": ticker, "yes_bid": str(quote.yes_bid),
                    "yes_ask": str(quote.yes_ask), "no_bid": str(quote.no_bid),
                    "no_ask": str(quote.no_ask), "yes_ask_size": str(quote.yes_ask_size),
                    "note": "Public quote only; not matched to live game; not an order."}) + "\n")
                break
            except Exception:
                counters["quote_errors"] += 1

    for game in matched:
        fresh = {}
        for team, market in (("a", game.market_a), ("b", game.market_b)):
            if not market:
                continue
            try:
                book = client.get_orderbook(market.ticker)
                quote = quote_from_orderbook(book)
                if quote is None:
                    raise MarketDataError("One-sided or empty executable book")
                fresh[team] = (replace(market, yes_bid=float(quote.yes_bid),
                                       yes_ask=float(quote.yes_ask)), quote)
                counters["usable_books"] += 1
                output.write(json.dumps({"type": "quote", "observed_at": timestamp(),
                    "ticker": market.ticker, "event_time": game.event_time,
                    "game_id": game.game_id, "team_a": game.team_a,
                    "team_b": game.team_b, "score_a": game.score_a,
                    "score_b": game.score_b, "inning": game.period,
                    "yes_bid": str(quote.yes_bid), "yes_ask": str(quote.yes_ask),
                    "no_bid": str(quote.no_bid), "no_ask": str(quote.no_ask),
                    "yes_ask_size": str(quote.yes_ask_size),
                    "no_ask_size": str(quote.no_ask_size)}) + "\n")
            except Exception as exc:
                counters["quote_errors"] += 1
                output.write(json.dumps({"type": "quote_error", "observed_at": timestamp(),
                    "ticker": market.ticker, "error": str(exc)[:200]}) + "\n")

        # Missing either side means the signal has not been fully checked.
        if set(fresh) != {"a", "b"}:
            continue
        updated = replace(game, market_a=fresh["a"][0], market_b=fresh["b"][0])
        signal = strategy.evaluate(updated)
        if not signal:
            continue
        market_key = "a" if signal.ticker == updated.market_a.ticker else "b"
        quote = fresh[market_key][1]
        if quote.yes_ask_size < 1 or quote.no_ask_size < 1:
            continue
        entry = quote.yes_ask
        exit_bid = quote.yes_bid
        entry_fee = estimated_taker_fee(entry)
        exit_fee = estimated_taker_fee(exit_bid)
        counters["heuristic_candidates"] += 1
        output.write(json.dumps({"type": "candidate", "observed_at": timestamp(),
            "ticker": signal.ticker, "game_id": game.game_id,
            "side": "BUY_YES_SHADOW_ONLY", "best_ask": str(entry),
            "best_bid": str(exit_bid), "ask_size": str(quote.yes_ask_size),
            "heuristic_probability_uncalibrated": signal.fair_value,
            "gross_heuristic_edge": signal.edge,
            "estimated_entry_fee_per_contract": str(entry_fee),
            "estimated_exit_fee_per_contract": str(exit_fee),
            "estimated_immediate_roundtrip_pnl_per_contract": str(
                exit_bid - entry - entry_fee - exit_fee),
            "note": "No order sent; fill and future win/loss are unobserved."}) + "\n")
        strategy.mark_observed(game.game_id)
    strategy.cleanup()
    result = {"type": "cycle", "observed_at": timestamp(), **counters}
    output.write(json.dumps(result) + "\n")
    output.flush()
    return counters


def run(cycles: int, interval: float, output_path: Path) -> int:
    client = PublicMarketClient()
    feed = ESPNFeed(sports=["mlb"])
    matcher = MarketMatcher(client)
    strategy = LatencySniper()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    totals = {"games_in_progress": 0, "score_changes": 0, "strict_matches": 0,
              "usable_books": 0, "universe_books": 0,
              "heuristic_candidates": 0, "quote_errors": 0,
              "real_orders": 0}
    with output_path.open("a", encoding="utf-8") as output:
        for i in range(cycles):
            started = time.monotonic()
            try:
                current = observe_cycle(feed, matcher, client, strategy, output)
            except Exception as exc:
                # A failed market-data request never turns into a false empty portfolio.
                output.write(json.dumps({"type": "cycle_error", "observed_at": timestamp(),
                    "error": str(exc)[:200]}) + "\n")
                output.flush()
                print(f"Cycle {i + 1}/{cycles} DATA ERROR: {exc}", file=sys.stderr)
                return 2
            for key, value in current.items():
                totals[key] += value
            print(f"Cycle {i + 1}/{cycles}: {current}", flush=True)
            if i + 1 < cycles:
                time.sleep(max(0, interval - (time.monotonic() - started)))
    print("TOTALS", json.dumps(totals, sort_keys=True), "journal", output_path)
    print("No real orders placed. Win rate and net P&L: NOT MEASURED.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=3, help="Bounded number of scans, 1-180")
    parser.add_argument("--interval", type=float, default=10, help="Seconds between scans, >= 10")
    parser.add_argument("--output", type=Path, default=Path("logs/shadow_observations.jsonl"))
    parser.add_argument("--live", action="store_true", help="Explicitly disabled pending validation")
    args = parser.parse_args()
    if args.live:
        parser.error("LIVE ORDERS DISABLED: strategy, reconciliation, exits, and fee-adjusted evidence are unvalidated")
    if not 1 <= args.cycles <= 180 or args.interval < 10:
        parser.error("Use 1-180 cycles with an interval of at least 10 seconds")
    return run(args.cycles, args.interval, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
