"""Run one paper-only MLB research collection cycle.

This executable imports only ReadOnlyKalshiClient; no exchange mutation methods
are available in its dependency graph.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.config import DEFAULT_CONFIG, ResearchConfig
from research.kalshi_readonly import ReadOnlyKalshiClient
from research.mlb_feed import MLBFeed
from research.mlb_matcher import match_game_markets
from research.mlb_strategy import MLBLateLeadDetector, NoProbabilityModel
from research.models import SourceStamp, payload_hash
from research.orderbook import parse_orderbook
from research.paper_broker import PaperBroker
from research.store import ResearchStore

LOG = logging.getLogger("kalshi_research_v11")


def load_config(path: Path) -> tuple[dict[str, Any], ResearchConfig]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    research = dict(DEFAULT_CONFIG)
    research.update(raw.get("research", {}))
    return raw, ResearchConfig.from_mapping(research)


def run_once(config_file: Path) -> dict[str, int]:
    api_config, config = load_config(config_file)
    client = ReadOnlyKalshiClient(api_config, environment=config.environment)
    store = ResearchStore(config.database_path)
    feed = MLBFeed()
    detector = MLBLateLeadDetector()
    broker = PaperBroker()
    disabled_model = NoProbabilityModel()

    games = feed.live_games()
    market_page = client.markets("KXMLBGAME")
    markets = [item for item in market_page.get("markets", []) if isinstance(item, Mapping)]
    counters = {"live_games": len(games), "mappings": 0, "candidates": 0, "signals": 0, "paper_fills": 0}

    for game in games:
        store.record_observation(game.stamp, "mlb_game", game.source_game_id, dict(game.raw))
        mappings = match_game_markets(game, markets)
        counters["mappings"] += len(mappings)
        for mapping in mappings:
            payload = client.orderbook(mapping.ticker)
            book_stamp = SourceStamp(
                source="kalshi_rest_orderbook",
                source_at=None,
                received_at=datetime.now(timezone.utc),
                payload_sha256=payload_hash(payload),
            )
            store.record_observation(book_stamp, "kalshi_orderbook", mapping.ticker, payload)
            try:
                book = parse_orderbook(mapping.ticker, payload, book_stamp)
            except ValueError as error:
                LOG.warning("Skip malformed book %s: %s", mapping.ticker, error)
                continue
            candidate = detector.detect(game, mapping, book)
            if candidate is None:
                continue
            counters["candidates"] += 1
            candidate_features = candidate.to_features()
            candidate_stamp = SourceStamp(
                source="derived_mlb_candidate",
                source_at=game.stamp.source_at,
                received_at=datetime.now(timezone.utc),
                payload_sha256=payload_hash(candidate_features),
            )
            store.record_observation(
                candidate_stamp, "mlb_late_lead_candidate", candidate.candidate_id, candidate_features
            )

            # This returns None until a separately fitted/calibrated model is
            # explicitly provided. It prevents a heuristic from becoming a fill.
            signal = detector.to_signal(candidate, disabled_model, config.max_paper_contracts)
            if signal is None:
                continue
            counters["signals"] += 1
            store.record_signal(signal)
            order = broker.propose(signal)
            fill = broker.execute(order, book)
            if fill is None:
                store.record_order(order, signal.signal_id, "rejected", "insufficient executable depth at limit")
            else:
                status = "filled" if fill.filled_contracts == order.requested_contracts else "partially_filled"
                store.record_order(order, signal.signal_id, status)
                store.record_fill(fill)
                counters["paper_fills"] += 1

    counters.update({f"db_{key}": value for key, value in store.summary().items()})
    return counters


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 paper-only MLB collection cycle")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    args = parser.parse_args()
    summary = run_once(args.config)
    LOG.info("PAPER-ONLY cycle summary: %s", summary)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
