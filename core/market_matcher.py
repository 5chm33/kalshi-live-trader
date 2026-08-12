"""
Market Matcher — v10
=====================
Links ESPN live games to Kalshi market tickers.
Maintains a cache of active Kalshi sports markets and matches
them to ESPN games by team name/abbreviation.
"""

import time
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

log = logging.getLogger('KALSHI')

# Kalshi series tickers for sports
SERIES = {
    'mlb': 'KXMLBGAME',
    'nba': 'KXNBAGAME',
    'nhl': 'KXNHLTM',
    'atp': 'KXATPMATCH',
    'wta': 'KXWTAMATCH',
    'mls': 'KXSOCGAME',
}

# Team name aliases for fuzzy matching
ALIASES = {
    'NYY': ['YANKEES', 'NEW YORK YANKEES'],
    'NYM': ['METS', 'NEW YORK METS'],
    'LAD': ['DODGERS', 'LOS ANGELES DODGERS'],
    'LAA': ['ANGELS', 'LOS ANGELES ANGELS'],
    'CHC': ['CUBS', 'CHICAGO CUBS'],
    'CWS': ['WHITE SOX', 'CHICAGO WHITE SOX'],
    'SF': ['GIANTS', 'SAN FRANCISCO GIANTS'],
    'SD': ['PADRES', 'SAN DIEGO PADRES'],
    'TB': ['RAYS', 'TAMPA BAY RAYS'],
    'KC': ['ROYALS', 'KANSAS CITY ROYALS'],
    'MIL': ['BREWERS', 'MILWAUKEE BREWERS'],
    'MIN': ['TWINS', 'MINNESOTA TWINS'],
    'CLE': ['GUARDIANS', 'CLEVELAND GUARDIANS'],
    'DET': ['TIGERS', 'DETROIT TIGERS'],
    'CIN': ['REDS', 'CINCINNATI REDS'],
    'PIT': ['PIRATES', 'PITTSBURGH PIRATES'],
    'STL': ['CARDINALS', 'ST. LOUIS CARDINALS'],
    'MIA': ['MARLINS', 'MIAMI MARLINS'],
    'ATL': ['BRAVES', 'ATLANTA BRAVES'],
    'WSH': ['NATIONALS', 'WASHINGTON NATIONALS'],
    'PHI': ['PHILLIES', 'PHILADELPHIA PHILLIES'],
    'BOS': ['RED SOX', 'BOSTON RED SOX'],
    'HOU': ['ASTROS', 'HOUSTON ASTROS'],
    'TEX': ['RANGERS', 'TEXAS RANGERS'],
    'SEA': ['MARINERS', 'SEATTLE MARINERS'],
    'TOR': ['BLUE JAYS', 'TORONTO BLUE JAYS'],
    'BAL': ['ORIOLES', 'BALTIMORE ORIOLES'],
    'COL': ['ROCKIES', 'COLORADO ROCKIES'],
    'ARI': ['DIAMONDBACKS', 'ARIZONA DIAMONDBACKS'],
    'OAK': ['ATHLETICS', 'OAKLAND ATHLETICS'],
    # NBA
    'NYK': ['KNICKS', 'NEW YORK KNICKS'],
    'BKN': ['NETS', 'BROOKLYN NETS'],
    'LAL': ['LAKERS', 'LOS ANGELES LAKERS'],
    'LAC': ['CLIPPERS', 'LA CLIPPERS'],
    'GSW': ['WARRIORS', 'GOLDEN STATE WARRIORS'],
    'OKC': ['THUNDER', 'OKLAHOMA CITY THUNDER'],
}


@dataclass
class KalshiMarket:
    """A Kalshi market linked to a team/player."""
    ticker: str
    event_ticker: str
    team_key: str        # Team abbreviation this market represents
    yes_bid: float       # Best YES bid in dollars
    yes_ask: float       # Best YES ask in dollars (derived from NO bid)
    last_price: float
    status: str


@dataclass
class MatchedGame:
    """An ESPN game matched to Kalshi markets."""
    game_id: str
    sport: str
    team_a: str
    team_b: str
    score_a: int
    score_b: int
    period: int
    period_half: str
    lead: int
    leader: str
    market_a: Optional[KalshiMarket] = None  # Market for team A
    market_b: Optional[KalshiMarket] = None  # Market for team B


class MarketMatcher:
    """Matches ESPN games to Kalshi markets."""

    def __init__(self, client):
        self.client = client
        self._market_cache: Dict[str, List[dict]] = {}  # series -> markets
        self._cache_time: Dict[str, float] = {}
        self._cache_ttl = 30  # Refresh market list every 30s

    def match_games(self, games) -> List[MatchedGame]:
        """Match a list of ESPN GameState objects to Kalshi markets."""
        matched = []

        # Group games by sport
        by_sport: Dict[str, list] = {}
        for g in games:
            by_sport.setdefault(g.sport, []).append(g)

        for sport, sport_games in by_sport.items():
            series = SERIES.get(sport)
            if not series:
                continue

            markets = self._get_markets(series)
            if not markets:
                continue

            # Group Kalshi markets by event_ticker
            events: Dict[str, List[dict]] = {}
            for m in markets:
                et = m.get('event_ticker', '')
                if et:
                    events.setdefault(et, []).append(m)

            for game in sport_games:
                mg = self._match_one(game, events)
                if mg:
                    matched.append(mg)

        return matched

    def _get_markets(self, series: str) -> List[dict]:
        """Get markets for a series, with caching."""
        now = time.time()
        if series in self._cache_time and now - self._cache_time[series] < self._cache_ttl:
            return self._market_cache.get(series, [])

        markets = self.client.get_markets(series_ticker=series, status='open', limit=200)
        self._market_cache[series] = markets
        self._cache_time[series] = now
        log.debug(f"[MATCHER] Refreshed {series}: {len(markets)} markets")
        return markets

    def _match_one(self, game, events: Dict[str, List[dict]]) -> Optional[MatchedGame]:
        """Try to match one ESPN game to Kalshi event markets."""
        ta, tb = game.team_a.upper(), game.team_b.upper()

        best_match = None
        best_score = 0

        for et, ev_markets in events.items():
            market_a = None
            market_b = None
            score = 0

            for m in ev_markets:
                ticker = m.get('ticker', '').upper()
                sub = (m.get('yes_sub_title') or '').upper()

                # The ticker suffix IS the team (e.g., KXMLBGAME-26AUG131335SEANYY-NYY)
                ticker_suffix = ticker.split('-')[-1] if '-' in ticker else ''

                # Match by suffix first (authoritative)
                for team, is_a in [(ta, True), (tb, False)]:
                    if (is_a and market_a) or (not is_a and market_b):
                        continue

                    matched = False

                    # Exact suffix match (strongest signal)
                    if ticker_suffix == team:
                        matched = True
                        score += 5
                    # For tennis: last name in suffix or sub_title
                    elif game.sport in ('atp', 'wta'):
                        # Tennis uses player last names
                        if team[:3] in ticker_suffix or team in sub:
                            matched = True
                            score += 2
                        else:
                            for alias in ALIASES.get(team, []):
                                if alias in sub:
                                    matched = True
                                    score += 1
                                    break

                    if matched:
                        km = self._parse_market(m, team)
                        if is_a:
                            market_a = km
                        else:
                            market_b = km

            if market_a and market_b and score > best_score:
                best_score = score
                best_match = MatchedGame(
                    game_id=game.game_id,
                    sport=game.sport,
                    team_a=ta, team_b=tb,
                    score_a=game.score_a, score_b=game.score_b,
                    period=game.period, period_half=game.period_half,
                    lead=game.lead, leader=game.leader,
                    market_a=market_a, market_b=market_b,
                )

        return best_match

    def _parse_market(self, m: dict, team_key: str) -> KalshiMarket:
        """Parse raw Kalshi market dict into KalshiMarket."""
        def to_dollars(val) -> float:
            if val is None:
                return 0.0
            try:
                f = float(val)
                return f if f <= 1.0 else f / 100.0
            except (ValueError, TypeError):
                return 0.0

        return KalshiMarket(
            ticker=m.get('ticker', ''),
            event_ticker=m.get('event_ticker', ''),
            team_key=team_key,
            yes_bid=to_dollars(m.get('yes_bid_dollars')),
            yes_ask=to_dollars(m.get('yes_ask_dollars')),
            last_price=to_dollars(m.get('last_price_dollars')),
            status=m.get('status', 'open'),
        )
