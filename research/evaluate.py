"""Paper-ledger evaluation with explicit sample-size and settlement constraints."""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from research.store import ResearchStore


@dataclass(frozen=True)
class BinStats:
    observations: int
    wins: int

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.observations if self.observations else None

    def wilson_interval_95(self) -> tuple[float, float] | None:
        """Wilson interval with z=1.96; do not use as a claim of edge."""
        if self.observations == 0:
            return None
        z = 1.96
        n = self.observations
        p = self.wins / n
        denominator = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denominator
        half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
        return center - half, center + half


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def evaluate(database_path: str | Path) -> dict[str, Any]:
    """Evaluate only settled candidates and paper fills. Never invent outcomes."""
    # Runs forward-compatible CREATE TABLE migrations before direct analytical reads.
    ResearchStore(database_path)
    with _connect(database_path) as conn:
        settlements = {
            row["ticker"]: row["result"]
            for row in conn.execute("SELECT ticker, result FROM settlements")
        }
        candidates = [
            json.loads(row["payload_json"])
            for row in conn.execute(
                "SELECT payload_json FROM observations WHERE entity_type='mlb_late_lead_candidate'"
            )
        ]
        resolved = [candidate for candidate in candidates if candidate.get("ticker") in settlements]
        buckets: dict[str, BinStats] = {}
        raw_bucket: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for candidate in resolved:
            # Candidate contract always denotes its current leader's YES position.
            won = settlements[candidate["ticker"]] == "yes"
            key = f"inning_{candidate.get('inning')}_lead_{candidate.get('lead_runs')}"
            raw_bucket[key][0] += 1
            raw_bucket[key][1] += int(won)
        for key, (observations, wins) in raw_bucket.items():
            buckets[key] = BinStats(observations, wins)

        fill_rows = conn.execute(
            """SELECT f.ticker, f.outcome_side, f.filled_contracts, f.total_debit
                 FROM paper_fills f"""
        ).fetchall()
        settled_fills = 0
        net_pnl = Decimal("0")
        gross_payout = Decimal("0")
        total_debit = Decimal("0")
        for row in fill_rows:
            result = settlements.get(row["ticker"])
            if result is None:
                continue
            settled_fills += 1
            contracts = Decimal(row["filled_contracts"])
            debit = Decimal(row["total_debit"])
            payout = contracts if result == row["outcome_side"] else Decimal("0")
            gross_payout += payout
            total_debit += debit
            net_pnl += payout - debit

    bucket_report = {
        key: {
            "observations": stat.observations,
            "wins": stat.wins,
            "win_rate": stat.win_rate,
            "wilson_95": stat.wilson_interval_95(),
        }
        for key, stat in sorted(buckets.items())
    }
    return {
        "candidate_count": len(candidates),
        "settled_candidate_count": len(resolved),
        "unsettled_candidate_count": len(candidates) - len(resolved),
        "candidate_buckets": bucket_report,
        "settled_paper_fill_count": settled_fills,
        "gross_payout": str(gross_payout),
        "total_debit": str(total_debit),
        "net_pnl": str(net_pnl),
        "status": "insufficient_data" if len(resolved) < 200 else "research_sample_available",
    }
