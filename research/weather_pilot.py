"""Settlement-mapped, paper-only weather pilot.

The pilot collects forecast-member data only for explicitly mapped Kalshi series
whose public Weather Company station is known. It records raw market and
forecast provenance but intentionally contains no probability, signal, or order
method. Mapping must be expanded only with a documented station source.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.kalshi_readonly import ReadOnlyKalshiClient
from research.models import SourceStamp, payload_hash
from research.run_mlb_paper import load_config
from research.store import ResearchStore
from research.weather import OpenMeteoEnsembleFeed, WeatherMarketDefinition

# Public Weather Company Kalshi portal exposes these station identifiers. The
# coordinate is only a forecast grid point; settlement is the named station.
PILOT_SERIES = {
    "KXHIGHNY": {"city": "New York City", "station": "KNYC", "latitude": 40.7829, "longitude": -73.9654, "timezone": "America/New_York", "kind": "high"},
    "KXLOWNY": {"city": "New York City", "station": "KNYC", "latitude": 40.7829, "longitude": -73.9654, "timezone": "America/New_York", "kind": "low"},
    "KXHIGHTDC": {"city": "Washington, DC", "station": "KDCA", "latitude": 38.8512, "longitude": -77.0402, "timezone": "America/New_York", "kind": "high"},
    "KXLOWTDC": {"city": "Washington, DC", "station": "KDCA", "latitude": 38.8512, "longitude": -77.0402, "timezone": "America/New_York", "kind": "low"},
}


def target_date_from_market(market: dict, timezone_name: str) -> str:
    close = str(market.get("close_time", ""))
    if not close:
        raise ValueError("market lacks close_time")
    return datetime.fromisoformat(close.replace("Z", "+00:00")).astimezone(ZoneInfo(timezone_name)).date().isoformat()


def run_cycle(client: ReadOnlyKalshiClient, store: ResearchStore) -> dict:
    feed = OpenMeteoEnsembleFeed()
    collected = markets_seen = errors = 0
    error_samples: list[str] = []
    for series_ticker, mapping in PILOT_SERIES.items():
        try:
            response = client.markets(series_ticker, limit=200)
            markets = [market for market in response.get("markets", []) if isinstance(market, dict)]
            markets_seen += len(markets)
            by_date: dict[str, list[dict]] = {}
            for market in markets:
                by_date.setdefault(target_date_from_market(market, mapping["timezone"]), []).append(market)
            for target_date, group in by_date.items():
                ensemble = feed.daily_temperature(
                    city=str(mapping["city"]), latitude=float(mapping["latitude"]), longitude=float(mapping["longitude"]),
                    timezone_name=str(mapping["timezone"]), target_date=target_date, forecast_kind=str(mapping["kind"]),
                )
                record = {
                    "mode": "paper_only_no_orders", "series_ticker": series_ticker,
                    "settlement_source": "The Weather Company Kalshi Climate Data Portal",
                    "settlement_station": mapping["station"], "forecast_grid_point": {"latitude": mapping["latitude"], "longitude": mapping["longitude"]},
                    "target_date": target_date, "forecast_kind": mapping["kind"],
                    "actual_member_count": ensemble.member_count,
                    "members_by_model": {name: [str(value) for value in values] for name, values in ensemble.members_by_model.items()},
                    "markets": [{
                        "ticker": definition.ticker, "title": definition.title, "market_kind": definition.market_kind,
                        "floor_strike": str(definition.floor_strike) if definition.floor_strike is not None else None,
                        "cap_strike": str(definition.cap_strike) if definition.cap_strike is not None else None,
                    } for definition in (WeatherMarketDefinition.from_market(market, str(mapping["kind"])) for market in group)],
                    "ensemble_payload": ensemble.raw,
                }
                stamp = SourceStamp("weather_settlement_mapped_pilot", ensemble.stamp.received_at, None, payload_hash(record))
                collected += int(store.record_observation(stamp, "weather_settlement_mapped_pilot", f"{series_ticker}:{target_date}", record))
        except Exception as exc:
            errors += 1
            error_samples.append(f"{series_ticker}: {type(exc).__name__}: {exc}")
    return {"mode": "paper_only_no_orders", "series": len(PILOT_SERIES), "markets_seen": markets_seen, "observations_stored": collected, "errors": errors, "error_samples": error_samples}


def main() -> None:
    parser = argparse.ArgumentParser(description="V11 settlement-mapped weather pilot; no signal or order path")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--database", type=Path, default=Path("data/research_v11.sqlite3"))
    args = parser.parse_args()
    api_config, config = load_config(args.config)
    print(json.dumps(run_cycle(ReadOnlyKalshiClient(api_config, environment=config.environment), ResearchStore(args.database)), sort_keys=True))


if __name__ == "__main__":
    main()
