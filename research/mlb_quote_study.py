"""Create a timestamped MLB-state/archived-Kalshi-quote study dataset.

The resulting rows are *not fills*: minute candlesticks have no displayed
order-book depth and cannot establish that a buy could be filled. They are used
only to measure quote availability and later test whether a calibrated model
would have exceeded the observed ask plus costs.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.mlb_matcher import team_code
from research.store import ResearchStore


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (AttributeError, ValueError):
        return None


def _event_date_token(value: str) -> str | None:
    stamp = _parse_time(value)
    return stamp.strftime("%y%b%d").upper() if stamp else None


def build_quote_study(database: str | Path, max_quote_delay_seconds: int = 120) -> dict[str, int]:
    if max_quote_delay_seconds <= 0:
        raise ValueError("max_quote_delay_seconds must be positive")
    store = ResearchStore(database)
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    states = conn.execute(
        """SELECT * FROM mlb_historical_states
           WHERE source_at IS NOT NULL AND away_team IS NOT NULL AND home_team IS NOT NULL"""
    ).fetchall()
    # Historical-market responses may omit `series_ticker`; this collector
    # itself is exclusively scoped to KXMLBGAME, so use only the exact ticker
    # identity fields required by the matching contract.
    markets = conn.execute(
        "SELECT ticker, event_ticker FROM kalshi_historical_markets WHERE event_ticker LIKE 'KXMLBGAME-%'"
    ).fetchall()
    matched = missing_market = missing_quote = 0
    # Pre-index the small archived market universe by its strict identity
    # contract: event date + unordered team codes + team-specific ticker suffix.
    market_index: dict[tuple[str, frozenset[str], str], list[str]] = {}
    for market in markets:
        ticker = str(market["ticker"])
        event_ticker = str(market["event_ticker"]).upper()
        parts = event_ticker.split("-")
        date_token = parts[1][:7] if len(parts) > 1 and len(parts[1]) >= 7 else ""
        suffix = ticker.rsplit("-", 1)[-1].upper()
        team_pair = frozenset(code for code in (
            "ARI", "ATL", "BAL", "BOS", "CHC", "CWS", "CIN", "CLE", "COL", "DET", "HOU", "KC",
            "LAA", "LAD", "MIA", "MIL", "MIN", "NYM", "NYY", "ATH", "PHI", "PIT", "SD", "SF",
            "SEA", "STL", "TB", "TEX", "TOR", "WSH"
        ) if code in event_ticker)
        if len(team_pair) == 2 and suffix:
            market_index.setdefault((date_token, team_pair, suffix), []).append(ticker)
    now = datetime.now(timezone.utc)
    pending_rows: list[dict[str, Any]] = []
    for state in states:
        state_time = _parse_time(state["source_at"])
        date_token = _event_date_token(state["source_at"])
        away_code, home_code = team_code(state["away_team"]), team_code(state["home_team"])
        leader_code = home_code if bool(state["leader_is_home"]) else away_code
        if not state_time or not date_token or not away_code or not home_code or not leader_code:
            continue
        candidates = market_index.get((date_token, frozenset({away_code, home_code}), leader_code), [])
        if len(candidates) != 1:
            missing_market += 1
            continue
        ticker = candidates[0]
        rows = conn.execute(
            """SELECT * FROM kalshi_historical_candles
               WHERE ticker = ? AND end_period_ts >= ? AND end_period_ts <= ?
               ORDER BY end_period_ts ASC LIMIT 1""",
            (ticker, int(state_time.timestamp()), int(state_time.timestamp()) + max_quote_delay_seconds),
        ).fetchall()
        if not rows or rows[0]["yes_ask_close"] is None:
            missing_quote += 1
            continue
        candle = rows[0]
        delay = candle["end_period_ts"] - state_time.timestamp()
        pending_rows.append({
            "game_pk": state["game_pk"], "at_bat_index": state["at_bat_index"], "ticker": ticker,
            "state_source_at": state["source_at"], "candle_end_period_ts": candle["end_period_ts"],
            "quote_delay_seconds": delay, "yes_bid_close": candle["yes_bid_close"],
            "yes_ask_close": candle["yes_ask_close"], "leader_won": state["leader_won"],
            "mapping_method": "exact_date_team_pair_ticker_suffix_then_first_post_state_minute_candle",
        })
        matched += 1
    store.record_mlb_quote_study_rows(pending_rows, now)
    return {
        "states_considered": len(states), "quote_study_rows_written": matched,
        "states_without_exact_archived_market": missing_market,
        "states_without_post_state_quote": missing_quote,
    }
