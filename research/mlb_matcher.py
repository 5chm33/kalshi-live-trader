"""Deterministic matching of MLB games to team-specific Kalshi game contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from research.models import GameState, MarketMapping, normalize_team

# MLB Stats API full team names to Kalshi/standard ticker suffixes. This is
# explicit rather than fuzzy to avoid assigning both teams to one contract.
TEAM_CODES = {
    "ARIZONADIAMONDBACKS": "ARI", "ATLANTABRAVES": "ATL", "BALTIMOREORIOLES": "BAL",
    "BOSTONREDSOX": "BOS", "CHICAGOCUBS": "CHC", "CHICAGOWHITESOX": "CWS",
    "CINCINNATIREDS": "CIN", "CLEVELANDGUARDIANS": "CLE", "COLORADOROCKIES": "COL",
    "DETROITTIGERS": "DET", "HOUSTONASTROS": "HOU", "KANSASCITYROYALS": "KC",
    "LOSANGELESANGELS": "LAA", "LOSANGELESDODGERS": "LAD", "MIAMIMARLINS": "MIA",
    "MILWAUKEEBREWERS": "MIL", "MINNESOTATWINS": "MIN", "NEWYORKMETS": "NYM",
    "NEWYORKYANKEES": "NYY", "ATHLETICS": "ATH", "OAKLANDATHLETICS": "ATH",
    "PHILADELPHIAPHILLIES": "PHI", "PITTSBURGHPIRATES": "PIT", "SAN DIEGOPADRES": "SD",
    "SANDIEGOPADRES": "SD", "SANFRANCISCOGIANTS": "SF", "SEATTLEMARINERS": "SEA",
    "STLOUISCARDINALS": "STL", "TAMPABAYRAYS": "TB", "TEXASRANGERS": "TEX",
    "TORONTOBLUEJAYS": "TOR", "WASHINGTONNATIONALS": "WSH",
}


def team_code(team_name: str) -> str | None:
    return TEAM_CODES.get(normalize_team(team_name))


def market_team_code(market: Mapping[str, Any]) -> str | None:
    ticker = str(market.get("ticker", ""))
    if not ticker or "-" not in ticker:
        return None
    return ticker.rsplit("-", 1)[-1].upper()


def match_game_markets(game: GameState, markets: list[Mapping[str, Any]]) -> list[MarketMapping]:
    """Match only exact game/team contracts; do not use substring fallbacks."""
    away_code, home_code = team_code(game.away_team), team_code(game.home_team)
    if not away_code or not home_code:
        return []

    expected = {away_code: game.away_team, home_code: game.home_team}
    mappings: list[MarketMapping] = []
    for market in markets:
        if str(market.get("series_ticker", "")) != "KXMLBGAME":
            continue
        code = market_team_code(market)
        if code not in expected:
            continue
        ticker = str(market.get("ticker", ""))
        # The shared game body must contain both team codes. This protects
        # against matching a contract from an unrelated game with the same code.
        body = ticker.rsplit("-", 1)[0].upper()
        if away_code not in body or home_code not in body:
            continue
        mappings.append(MarketMapping(
            source_game_id=game.source_game_id,
            ticker=ticker,
            team=expected[code],
            confidence=Decimal("1.00"),
            mapping_method="exact_ticker_suffix_and_pair",
            created_at=datetime.now(timezone.utc),
        ))
    # A valid binary event needs one distinct contract per team.
    if {mapping.team for mapping in mappings} != {game.away_team, game.home_team}:
        return []
    return mappings
