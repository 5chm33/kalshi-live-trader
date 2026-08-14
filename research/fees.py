"""Fee calculations for research and paper execution.

The default taker model follows Kalshi's fee schedule effective July 7, 2026:
    ceil_to_0.0001(multiplier * 0.07 * count * price * (1 - price))

The paper engine treats this as a conservative estimate. Actual fills must
always use the fee returned by the exchange's fill record.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING

from research.models import MONEY_QUANTUM, ONE, ZERO, decimal

TAKER_RATE = Decimal("0.07")
MAKER_RATE = Decimal("0.0175")


def ceil_to_centicent(value: Decimal) -> Decimal:
    """Round a nonnegative dollar amount upward to $0.0001."""
    if value <= ZERO:
        return ZERO
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_CEILING)


def estimate_fee(
    price: Decimal | str | float,
    contracts: Decimal | str | float,
    multiplier: Decimal | str | float | None,
    liquidity: str,
) -> Decimal:
    """Return documented fee estimate or raise for an unknown fee schedule.

    Args:
        price: YES-leg fixed-point contract price in [0, 1].
        contracts: Positive fixed-point count.
        multiplier: Series-specific multiplier. None is intentionally rejected.
        liquidity: ``taker`` or ``maker``.
    """
    p = decimal(price)
    c = decimal(contracts)
    if not (ZERO <= p <= ONE):
        raise ValueError(f"price must be in [0, 1], received {p}")
    if c <= ZERO:
        raise ValueError(f"contracts must be positive, received {c}")
    if multiplier is None:
        raise ValueError("fee multiplier unavailable; paper fill rejected")
    m = decimal(multiplier)
    if m < ZERO:
        raise ValueError(f"multiplier must be nonnegative, received {m}")
    if liquidity not in {"taker", "maker"}:
        raise ValueError("liquidity must be 'taker' or 'maker'")

    rate = TAKER_RATE if liquidity == "taker" else MAKER_RATE
    return ceil_to_centicent(m * rate * c * p * (ONE - p))


def conservative_rounding_reserve(contracts: Decimal | str | float) -> Decimal:
    """Reserve up to one cent per paper order for non-direct balance rounding.

    This is deliberately a reserve—not a claimed exchange fee formula. It is
    kept separate from the documented trade-fee estimate and can be replaced by
    observed account-specific rounding behavior.
    """
    c = decimal(contracts)
    if c <= ZERO:
        return ZERO
    return Decimal("0.01")
