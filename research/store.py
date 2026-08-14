"""SQLite event ledger for the V11 research system.

Writes are append-oriented and idempotent. Database files are runtime artifacts
and excluded from version control.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterator, Mapping

from research.models import PaperFill, PaperOrder, SourceStamp, StrategySignal


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_at TEXT,
    received_at TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(source, payload_sha256, entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    strategy TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    ticker TEXT NOT NULL,
    outcome_side TEXT NOT NULL CHECK(outcome_side IN ('yes', 'no')),
    model_probability TEXT NOT NULL,
    conservative_probability TEXT NOT NULL,
    observed_price TEXT NOT NULL,
    requested_contracts TEXT NOT NULL,
    source TEXT NOT NULL,
    source_at TEXT,
    received_at TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    rationale TEXT NOT NULL,
    features_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_orders (
    paper_order_id TEXT PRIMARY KEY,
    signal_id TEXT,
    strategy_version TEXT NOT NULL,
    ticker TEXT NOT NULL,
    outcome_side TEXT NOT NULL CHECK(outcome_side IN ('yes', 'no')),
    requested_contracts TEXT NOT NULL,
    limit_price TEXT NOT NULL,
    signal_probability TEXT NOT NULL,
    expected_edge_before_cost TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('proposed', 'partially_filled', 'filled', 'rejected')),
    rejection_reason TEXT,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY(signal_id) REFERENCES signals(signal_id)
);

CREATE TABLE IF NOT EXISTS paper_fills (
    fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_order_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    outcome_side TEXT NOT NULL CHECK(outcome_side IN ('yes', 'no')),
    filled_contracts TEXT NOT NULL,
    average_price TEXT NOT NULL,
    position_cost TEXT NOT NULL,
    estimated_fee TEXT NOT NULL,
    estimated_rounding_reserve TEXT NOT NULL,
    total_debit TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY(paper_order_id) REFERENCES paper_orders(paper_order_id)
);

CREATE TABLE IF NOT EXISTS paper_marks (
    mark_id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    outcome_side TEXT NOT NULL CHECK(outcome_side IN ('yes', 'no')),
    mark_price TEXT NOT NULL,
    source TEXT NOT NULL,
    received_at TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settlements (
    ticker TEXT PRIMARY KEY,
    result TEXT NOT NULL CHECK(result IN ('yes', 'no')),
    settled_at TEXT,
    source TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mlb_historical_states (
    game_pk TEXT NOT NULL,
    at_bat_index INTEGER NOT NULL,
    game_date TEXT NOT NULL,
    inning INTEGER NOT NULL,
    inning_half TEXT NOT NULL,
    outs INTEGER,
    leader_is_home INTEGER NOT NULL CHECK(leader_is_home IN (0, 1)),
    lead_runs INTEGER NOT NULL,
    away_runs INTEGER NOT NULL,
    home_runs INTEGER NOT NULL,
    away_team TEXT,
    home_team TEXT,
    leader_won INTEGER NOT NULL CHECK(leader_won IN (0, 1)),
    source TEXT NOT NULL,
    source_at TEXT,
    received_at TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY(game_pk, at_bat_index)
);

CREATE INDEX IF NOT EXISTS idx_mlb_historical_bucket
ON mlb_historical_states(inning, inning_half, leader_is_home, lead_runs);

CREATE TABLE IF NOT EXISTS kalshi_historical_markets (
    ticker TEXT PRIMARY KEY,
    event_ticker TEXT NOT NULL,
    series_ticker TEXT,
    yes_sub_title TEXT,
    no_sub_title TEXT,
    open_time TEXT,
    close_time TEXT,
    settlement_ts TEXT,
    result TEXT,
    rules_primary TEXT,
    raw_json TEXT NOT NULL,
    retrieved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kalshi_historical_candles (
    ticker TEXT NOT NULL,
    end_period_ts INTEGER NOT NULL,
    yes_bid_close TEXT,
    yes_ask_close TEXT,
    price_close TEXT,
    volume_fp TEXT,
    open_interest_fp TEXT,
    raw_json TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY(ticker, end_period_ts)
);

CREATE INDEX IF NOT EXISTS idx_kalshi_historical_candles_ticker_time
ON kalshi_historical_candles(ticker, end_period_ts);

CREATE INDEX IF NOT EXISTS idx_observations_entity ON observations(entity_type, entity_id, received_at);
CREATE INDEX IF NOT EXISTS idx_signals_strategy_time ON signals(strategy_version, created_at);
CREATE INDEX IF NOT EXISTS idx_paper_orders_ticker ON paper_orders(ticker, created_at);
CREATE INDEX IF NOT EXISTS idx_paper_fills_order ON paper_fills(paper_order_id);
"""


class ResearchStore:
    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            # Forward-compatible local migration for ledgers created before
            # exact MLB team names were needed for Kalshi ticker matching.
            existing = {row[1] for row in conn.execute("PRAGMA table_info(mlb_historical_states)")}
            for column in ("away_team", "home_team"):
                if column not in existing:
                    conn.execute(f"ALTER TABLE mlb_historical_states ADD COLUMN {column} TEXT")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # WAL permits readers alongside a writer; a busy timeout prevents a
        # short overlapping REST/stream write from becoming lost telemetry.
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    def record_observation(
        self,
        stamp: SourceStamp,
        entity_type: str,
        entity_id: str,
        payload: Mapping[str, Any],
    ) -> bool:
        """Insert a source payload once; return true only for a new record."""
        with self.connect() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO observations
                   (source, source_at, received_at, payload_sha256, entity_type, entity_id, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    stamp.source,
                    self._iso(stamp.source_at),
                    self._iso(stamp.received_at),
                    stamp.payload_sha256,
                    entity_type,
                    entity_id,
                    self._json(payload),
                ),
            )
            return cursor.rowcount == 1

    def record_signal(self, signal: StrategySignal) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal.signal_id,
                    signal.strategy,
                    signal.strategy_version,
                    signal.ticker,
                    signal.outcome_side,
                    str(signal.model_probability),
                    str(signal.conservative_probability),
                    str(signal.observed_price),
                    str(signal.requested_contracts),
                    signal.source_stamp.source,
                    self._iso(signal.source_stamp.source_at),
                    self._iso(signal.source_stamp.received_at),
                    signal.source_stamp.payload_sha256,
                    signal.rationale,
                    self._json(signal.features),
                    self._iso(signal.source_stamp.received_at),
                ),
            )

    def record_order(self, order: PaperOrder, signal_id: str | None, status: str,
                     rejection_reason: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO paper_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    order.paper_order_id,
                    signal_id,
                    order.strategy_version,
                    order.ticker,
                    order.outcome_side,
                    str(order.requested_contracts),
                    str(order.limit_price),
                    str(order.signal_probability),
                    str(order.expected_edge_before_cost),
                    self._iso(order.created_at),
                    status,
                    rejection_reason,
                    self._json(order.metadata),
                ),
            )

    def record_fill(self, fill: PaperFill) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO paper_fills
                   (paper_order_id, ticker, outcome_side, filled_contracts, average_price,
                    position_cost, estimated_fee, estimated_rounding_reserve, total_debit,
                    model, created_at, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fill.paper_order_id,
                    fill.ticker,
                    fill.outcome_side,
                    str(fill.filled_contracts),
                    str(fill.average_price),
                    str(fill.position_cost),
                    str(fill.estimated_fee),
                    str(fill.estimated_rounding_reserve),
                    str(fill.total_debit),
                    fill.model,
                    self._iso(fill.created_at),
                    self._json(fill.metadata),
                ),
            )

    def record_mark(self, ticker: str, outcome_side: str, mark_price: Decimal,
                    stamp: SourceStamp, reason: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO paper_marks
                   (ticker, outcome_side, mark_price, source, received_at, payload_sha256, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker,
                    outcome_side,
                    str(mark_price),
                    stamp.source,
                    self._iso(stamp.received_at),
                    stamp.payload_sha256,
                    reason,
                ),
            )

    def record_historical_market(self, market: Mapping[str, Any], retrieved_at: datetime) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO kalshi_historical_markets(
                    ticker, event_ticker, series_ticker, yes_sub_title, no_sub_title,
                    open_time, close_time, settlement_ts, result, rules_primary, raw_json, retrieved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(market["ticker"]), str(market.get("event_ticker", "")), market.get("series_ticker"),
                    market.get("yes_sub_title"), market.get("no_sub_title"), market.get("open_time"),
                    market.get("close_time"), market.get("settlement_ts"), market.get("result"),
                    market.get("rules_primary"), json.dumps(dict(market), sort_keys=True, default=str),
                    retrieved_at.isoformat(),
                ),
            )

    def record_historical_candle(self, ticker: str, candle: Mapping[str, Any], retrieved_at: datetime) -> None:
        def nested_close(key: str) -> Any:
            value = candle.get(key)
            if not isinstance(value, Mapping):
                return None
            return value.get("close_dollars", value.get("close"))
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO kalshi_historical_candles(
                    ticker, end_period_ts, yes_bid_close, yes_ask_close, price_close,
                    volume_fp, open_interest_fp, raw_json, retrieved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker, int(candle["end_period_ts"]), nested_close("yes_bid"), nested_close("yes_ask"),
                    nested_close("price"), candle.get("volume_fp", candle.get("volume")),
                    candle.get("open_interest_fp", candle.get("open_interest")),
                    json.dumps(dict(candle), sort_keys=True, default=str), retrieved_at.isoformat(),
                ),
            )

    def record_mlb_historical_state(self, row: Mapping[str, Any], stamp: SourceStamp) -> None:
        """Persist one immutable completed-game state used for calibration."""
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO mlb_historical_states(
                    game_pk, at_bat_index, game_date, inning, inning_half, outs,
                    leader_is_home, lead_runs, away_runs, home_runs, away_team, home_team, leader_won,
                    source, source_at, received_at, payload_sha256, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_pk, at_bat_index) DO UPDATE SET
                  away_team=excluded.away_team, home_team=excluded.home_team,
                  source_at=excluded.source_at, received_at=excluded.received_at,
                  payload_sha256=excluded.payload_sha256, raw_json=excluded.raw_json""",
                (
                    str(row["game_pk"]), int(row["at_bat_index"]), str(row["game_date"]),
                    int(row["inning"]), str(row["inning_half"]),
                    int(row["outs"]) if row.get("outs") is not None else None,
                    int(bool(row["leader_is_home"])), int(row["lead_runs"]),
                    int(row["away_runs"]), int(row["home_runs"]), row.get("away_team"), row.get("home_team"),
                    int(bool(row["leader_won"])), stamp.source, stamp.source_at.isoformat() if stamp.source_at else None,
                    stamp.received_at.isoformat(), stamp.payload_sha256,
                    json.dumps(dict(row), sort_keys=True, default=str),
                ),
            )

    def historical_mlb_state_count(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM mlb_historical_states").fetchone()[0])

    def unsettled_tickers(self) -> list[str]:
        """Return unique candidate/fill contracts with no recorded settlement."""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT DISTINCT ticker FROM (
                       SELECT json_extract(payload_json, '$.ticker') AS ticker
                       FROM observations WHERE entity_type='mlb_late_lead_candidate'
                       UNION
                       SELECT ticker FROM paper_fills
                   ) WHERE ticker IS NOT NULL
                   EXCEPT SELECT ticker FROM settlements
                   ORDER BY ticker"""
            ).fetchall()
        return [str(row[0]) for row in rows]

    def record_settlement(self, ticker: str, result: str, stamp: SourceStamp,
                          raw: Mapping[str, Any]) -> None:
        if result not in {"yes", "no"}:
            raise ValueError("settlement result must be 'yes' or 'no'")
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO settlements
                   (ticker, result, settled_at, source, payload_sha256, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (ticker, result, self._iso(stamp.source_at), stamp.source,
                 stamp.payload_sha256, self._json(raw)),
            )

    def summary(self) -> dict[str, int]:
        with self.connect() as conn:
            tables = ("observations", "signals", "paper_orders", "paper_fills", "paper_marks", "settlements")
            return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
