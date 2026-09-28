"""Irreversible retirement gate for the completed one-contract pilot.

The historical pilot is retained only for forensic reconciliation and offline tests.
No application code may revive its funding, entry, or cancellation endpoints by
supplying a different ledger pathname or command-line flag.
"""
from __future__ import annotations


class PilotRetiredError(RuntimeError):
    """Raised before any network write for the permanently completed pilot."""


PILOT_WRITES_RETIRED = True
RETIREMENT_REASON = (
    "Completed one-contract pilot is permanently retired; no further funding, "
    "entry, exit, or cancellation writes are authorized by this codebase"
)


def require_pilot_write_retired() -> None:
    """Always fail before a historical pilot write boundary is reached."""
    if PILOT_WRITES_RETIRED:
        raise PilotRetiredError(RETIREMENT_REASON)
    raise PilotRetiredError("Pilot write policy is invalid; refusing network write")
