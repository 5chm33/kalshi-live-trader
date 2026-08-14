"""Read-only live weather-engine check. Makes a public Open-Meteo/NWS request only."""
from __future__ import annotations

from datetime import date, timedelta
from strategies.weather_ensemble import EnsembleWeatherEngine


def main() -> None:
    target = (date.today() + timedelta(days=1)).isoformat()
    engine = EnsembleWeatherEngine()
    forecast = engine.get_ensemble_probability(
        city="new_york",
        date=target,
        threshold=70.0,
        forecast_type="high",
        market_type="above",
    )
    print(f"target_date={target}")
    print(f"total_members={forecast.total_members}")
    print(f"ecmwf_plus_aifs={len(forecast.ecmwf_members or [])}")
    print(f"gfs={len(forecast.gfs_members or [])}")
    print(f"icon={len(forecast.icon_members or [])}")
    print(f"nws_point={forecast.nws_point_forecast}")
    print(f"probability={forecast.probability_above_threshold}")
    print(f"confidence={forecast.forecast_confidence}")


if __name__ == "__main__":
    main()
