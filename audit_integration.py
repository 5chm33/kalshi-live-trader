"""Read-only integrity checks for Kalshi Live Trader v10.
Does not authenticate, fetch balances, or place/cancel orders.
"""
from __future__ import annotations

import inspect
from pathlib import Path

from strategies.weather_ensemble import EnsembleWeatherEngine
from strategies.tennis_value import TennisValueStrategy
from strategies.latency_sniper import LatencySniper


def check(condition: bool, name: str, detail: str) -> bool:
    state = "PASS" if condition else "FAIL"
    print(f"{state}: {name} — {detail}")
    return condition


def main() -> int:
    failures = 0
    root = Path(__file__).resolve().parent
    main_src = (root / "main.py").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    weather_params = set(inspect.signature(EnsembleWeatherEngine.analyze_market).parameters)
    weather_call_uses_valid_keywords = (
        "ticker=" not in main_src
        or "ticker" in weather_params
    ) and (
        "market_type=" not in main_src
        or "market_type" in weather_params
    )
    if not check(
        weather_call_uses_valid_keywords,
        "Weather scanner / engine interface",
        f"main.py calls ticker= and market_type=; engine accepts {sorted(weather_params)}",
    ):
        failures += 1

    check(
        "WebSocketApp(" not in (root / "core" / "kalshi_client.py").read_text(encoding="utf-8"),
        "WebSocket implementation absent",
        "Repository defines WebSocket URL/header helpers only; no active subscription loop was found.",
    )

    sniper_src = (root / "strategies" / "latency_sniper.py").read_text(encoding="utf-8")
    check(
        "sport != 'mlb'" in sniper_src,
        "Latency sniper implementation scope",
        "Static routing shows the active sniper strategy is MLB-only, despite broader product wording.",
    )

    tennis_src = (root / "strategies" / "tennis_value.py").read_text(encoding="utf-8")
    check(
        "set_a" not in tennis_src and "set_b" not in tennis_src,
        "Tennis set-state limitation",
        "Strategy does not receive or check a first-set score; it uses an aggregate leader state.",
    )

    check(
        "209" in readme and "independent" in (root / "strategies" / "weather_ensemble.py").read_text(encoding="utf-8"),
        "Weather claim needs empirical validation",
        "Code advertises a 209-member ensemble, but its returned members must be validated against each Open-Meteo response.",
    )

    requirements = (root / "requirements.txt").read_text(encoding="utf-8")
    if not check(
        "scipy" in requirements,
        "SciPy fallback dependency declared",
        "weather_ensemble imports scipy.stats on fallback but requirements.txt does not list scipy.",
    ):
        failures += 1

    print(f"\nAudit complete. Blocking integration failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
