"""Weather forecast collection and validation for V11 research.

The module contains no trade signal. Its purpose is to record actual ensemble
members, market strike metadata, and later settlement-source alignment.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

import requests

from research.models import SourceStamp, decimal, payload_hash

ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
MODEL_REQUEST = (
    "icon_seamless,gfs_seamless,ecmwf_ifs025,ecmwf_aifs025,"
    "ukmo_global_ensemble_20km"
)


@dataclass(frozen=True)
class WeatherMarketDefinition:
    ticker: str
    title: str
    forecast_kind: str  # "high" or "low"
    floor_strike: Decimal | None
    cap_strike: Decimal | None

    @property
    def market_kind(self) -> str:
        if self.floor_strike is not None and self.cap_strike is not None:
            return "range"
        if self.floor_strike is not None:
            return "above"
        if self.cap_strike is not None:
            return "below"
        raise ValueError("weather market lacks both floor_strike and cap_strike")

    @classmethod
    def from_market(cls, market: Mapping[str, Any], forecast_kind: str) -> "WeatherMarketDefinition":
        floor = market.get("floor_strike")
        cap = market.get("cap_strike")
        return cls(
            ticker=str(market.get("ticker", "")),
            title=str(market.get("title", "")),
            forecast_kind=forecast_kind,
            floor_strike=decimal(floor) if floor is not None else None,
            cap_strike=decimal(cap) if cap is not None else None,
        )


@dataclass(frozen=True)
class EnsembleSnapshot:
    city: str
    target_date: str
    variable: str
    members_by_model: Mapping[str, tuple[Decimal, ...]]
    stamp: SourceStamp
    raw: Mapping[str, Any]

    @property
    def member_count(self) -> int:
        return sum(len(values) for values in self.members_by_model.values())

    @property
    def all_members(self) -> tuple[Decimal, ...]:
        return tuple(member for values in self.members_by_model.values() for member in values)


def _model_name(key: str, variable: str) -> str:
    prefix = variable + "_"
    if not key.startswith(prefix):
        raise ValueError(f"unexpected variable key {key}")
    suffix = key[len(prefix):]
    if suffix.startswith("member") and "_" in suffix:
        return suffix.split("_", 1)[1]
    return suffix


def parse_ensemble_payload(city: str, target_date: str, variable: str,
                           payload: Mapping[str, Any], stamp: SourceStamp) -> EnsembleSnapshot:
    """Extract all valid control/perturbed values and report actual model counts."""
    daily = payload.get("daily")
    if not isinstance(daily, Mapping):
        raise ValueError("Open-Meteo payload has no daily mapping")
    times = daily.get("time")
    if not isinstance(times, list) or target_date not in times:
        raise ValueError(f"target date {target_date} absent from weather payload")
    index = times.index(target_date)
    grouped: dict[str, list[Decimal]] = {}
    for key, values in daily.items():
        if not isinstance(key, str) or key == "time" or not key.startswith(variable + "_"):
            continue
        if not isinstance(values, list) or index >= len(values):
            continue
        value = values[index]
        if value is None:
            continue
        model = _model_name(key, variable)
        grouped.setdefault(model, []).append(decimal(value))
    if not grouped:
        raise ValueError("no ensemble values parsed from weather payload")
    return EnsembleSnapshot(
        city=city,
        target_date=target_date,
        variable=variable,
        members_by_model={name: tuple(values) for name, values in sorted(grouped.items())},
        stamp=stamp,
        raw=payload,
    )


class OpenMeteoEnsembleFeed:
    """Fetch live ensemble member data; no probability or trade methods."""

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "KalshiResearchV11/0.1 (paper-only)"})

    def daily_temperature(
        self,
        city: str,
        latitude: float,
        longitude: float,
        timezone_name: str,
        target_date: str,
        forecast_kind: str,
    ) -> EnsembleSnapshot:
        if forecast_kind not in {"high", "low"}:
            raise ValueError("forecast_kind must be 'high' or 'low'")
        variable = "temperature_2m_max" if forecast_kind == "high" else "temperature_2m_min"
        response = self.session.get(
            ENSEMBLE_URL,
            params={
                "latitude": latitude,
                "longitude": longitude,
                "daily": variable,
                "models": MODEL_REQUEST,
                "forecast_days": 7,
                "temperature_unit": "fahrenheit",
                "timezone": timezone_name,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        stamp = SourceStamp(
            source="open_meteo_ensemble",
            source_at=None,
            received_at=datetime.now(timezone.utc),
            payload_sha256=payload_hash(payload),
        )
        return parse_ensemble_payload(city, target_date, variable, payload, stamp)
