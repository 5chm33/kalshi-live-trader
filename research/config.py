"""Configuration for V11 research. Production execution is intentionally unsupported."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Any

from research.guards import paper_only_guard


@dataclass(frozen=True)
class ResearchConfig:
    mode: str
    environment: str
    database_path: Path
    allowed_series: tuple[str, ...]
    max_paper_contracts: Decimal
    max_spread: Decimal
    min_net_edge: Decimal
    mlb_enabled: bool
    weather_enabled: bool
    tennis_enabled: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ResearchConfig":
        mode = str(value.get("mode", "paper")).lower()
        guard = paper_only_guard(mode)
        if not guard.allowed:
            raise ValueError(guard.reason)
        environment = str(value.get("environment", "production")).lower()
        if environment not in {"production", "demo"}:
            raise ValueError("environment must be 'production' or 'demo'")
        return cls(
            mode=mode,
            environment=environment,
            database_path=Path(value.get("database_path", "data/research_v11.sqlite3")),
            allowed_series=tuple(value.get("allowed_series", ["KXMLBGAME"])),
            max_paper_contracts=Decimal(str(value.get("max_paper_contracts", "2.00"))),
            max_spread=Decimal(str(value.get("max_spread", "0.03"))),
            min_net_edge=Decimal(str(value.get("min_net_edge", "0.03"))),
            mlb_enabled=bool(value.get("mlb_enabled", True)),
            weather_enabled=bool(value.get("weather_enabled", False)),
            tennis_enabled=bool(value.get("tennis_enabled", False)),
        )


DEFAULT_CONFIG = {
    "mode": "paper",
    "environment": "production",
    "database_path": "data/research_v11.sqlite3",
    "allowed_series": ["KXMLBGAME"],
    "max_paper_contracts": "2.00",
    "max_spread": "0.03",
    "min_net_edge": "0.03",
    "mlb_enabled": True,
    "weather_enabled": False,
    "tennis_enabled": False,
}
