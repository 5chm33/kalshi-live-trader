"""Report actual forward quote coverage; never report displayed paired marks as fills or P&L."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path


def moment(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def valid_sample(sample, target):
    books = sample.get("books")
    if not isinstance(books, list) or len(books) != 2:
        return False
    try:
        before = [moment(b["before_utc"]) for b in books]
        after = [moment(b["after_utc"]) for b in books]
    except (KeyError, TypeError, ValueError):
        return False
    if any(a < b or abs((t - target).total_seconds()) > 5 for b, a in zip(before, after)
           for t in (b, a)):
        return False
    return abs((after[0] - after[1]).total_seconds()) <= 2


def summarize(rows, as_of=None):
    as_of = as_of or datetime.now(timezone.utc)
    starts, endings = [], []
    selected, samples, settled = {}, defaultdict(list), {}
    errors = Counter()
    snapshot_count = 0
    for row in rows:
        kind = row.get("type")
        if kind == "study_start":
            starts.append(row)
        elif kind == "study_end":
            endings.append(row)
        elif kind == "event_selected":
            ticker = row["event_ticker"]
            if ticker in selected:
                raise ValueError("Duplicate selected game")
            selected[ticker] = row
        elif kind == "book_snapshot":
            if row.get("real_orders") != 0 or row.get("real_fills") != 0:
                raise ValueError("Journal contains claimed real orders or fills")
            ticker = row["event_ticker"]
            if ticker not in selected:
                raise ValueError("Snapshot predates or is outside original cohort")
            snapshot_count += 1
            anchor = moment(selected[ticker]["scheduled_start_utc"]) - timedelta(minutes=30)
            if abs((moment(row["sample_at_utc"]) - anchor).total_seconds()) <= 35:
                samples[ticker].append(row)
        elif kind == "event_settlement":
            ticker = row["event_ticker"]
            if ticker in settled:
                raise ValueError("Duplicate settlement record")
            settled[ticker] = row
        elif kind in ("book_error", "cycle_error", "settlement_error"):
            errors[kind] += 1
    if len(starts) != 1 or len(endings) > 1:
        raise ValueError("Missing or duplicated original study registration/end")
    if (any(t not in selected for t in samples) or any(t not in selected for t in settled)
            or len(selected) > 120):
        raise ValueError("Unexpected snapshots or invalid cohort size")
    decision_eligible = persistent = fee_surviving = persistent_and_fee = 0
    statuses = Counter()
    for ticker, event in selected.items():
        anchor = moment(event["scheduled_start_utc"]) - timedelta(minutes=30)
        nearby = [s for s in samples[ticker]
                  if abs((moment(s["sample_at_utc"]) - anchor).total_seconds()) <= 5
                  and valid_sample(s, anchor)]
        if not nearby:
            statuses["future_decision_pending" if anchor > as_of else "missing_fixed_decision_snapshot"] += 1
            continue
        decision = min(nearby, key=lambda s: (abs((moment(s["sample_at_utc"]) - anchor).total_seconds()), s["sample_at_utc"]))
        if decision.get("conditional_quote", {}).get("eligible") is not True:
            statuses["one_sided_thin_or_ineligible"] += 1
            continue
        decision_eligible += 1
        mark = Decimal(decision["conditional_quote"]["conditional_paired_mark_dollars"])
        if mark >= Decimal("0.01"):
            fee_surviving += 1
        ticks = []
        for offset in (-30, -20, -10, 0, 10, 20, 30):
            target = anchor + timedelta(seconds=offset)
            admissible = [s for s in samples[ticker]
                          if abs((moment(s["sample_at_utc"]) - target).total_seconds()) <= 5
                          and valid_sample(s, target)
                          and s.get("conditional_quote", {}).get("eligible") is True]
            ticks.append(bool(admissible))
        if all(ticks):
            persistent += 1
            if mark >= Decimal("0.01"):
                persistent_and_fee += 1
        statuses["decision_eligible"] += 1
    n = len(selected)
    outcome_exceptions = sum(1 for r in settled.values()
                             if sorted(str(o.get("settlement_value_dollars")) for o in r.get("outcomes", []))
                             not in (["0.0000", "1.0000"], ["0", "1"], ["0.00", "1.00"]))
    adequate = (n == 120 and len(endings) == 1 and set(settled) == set(selected)
                and persistent_and_fee >= 80
                and not outcome_exceptions and errors["cycle_error"] == 0)
    lines = ["# Forward MLB microstructure evidence (read-only)", "",
             f"- Original study start: {starts[0]['start_at_utc']}",
             f"- Fixed study deadline: {starts[0]['until_utc']}",
             f"- Complete study-end record present: {bool(endings)}",
             f"- Distinct future selected games: **{n}/120**",
             f"- Actual book snapshots: {snapshot_count}",
             f"- Games with a valid nearest-30-minute two-sided decision snapshot: **{decision_eligible}**",
             f"- Games with 60-second persistence at fixed ±30-second slots: **{persistent}/120**",
             f"- Games with conditional non-direct-member paired mark ≥ $0.01: **{fee_surviving}/120**",
             f"- Games meeting both fixed gates: **{persistent_and_fee}/120**",
             f"- Later settled games: {len(settled)}; exceptional or nonbinary payouts: {outcome_exceptions}",
             f"- Logged book/cycle/settlement errors: {dict(errors)}",
             f"- Future decision times not yet reached: {statuses['future_decision_pending']}; missing after due: {statuses['missing_fixed_decision_snapshot']}; one-sided/thin/invalid: {statuses['one_sided_thin_or_ineligible']}",
             "- **Bot orders: 0; bot fills: 0; realized bot P&L: undefined.**",
             "", "**Feasibility screen:** " + ("basic displayed-book conditions met; still not a profitable trading result." if adequate
                      else "not met or incomplete; no basis to start trading."),
             "", "A displayed bid can disappear, two passive bids need not both fill, and one filled leg is directional risk. "
             "No quote-level mark is an execution or an investment return. The MLB series fee multiplier and event overrides are captured "
             "per snapshot; estimates include conservative cent-aligned rounding without assumed rebates. "
             "Original event rule time, not occurrence/expiration time, anchors the pregame screen. See MLB_MICROSTRUCTURE_STUDY.md.", ""]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("journal", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    rows = (json.loads(line) for line in args.journal.open() if line.strip())
    report = summarize(rows)
    if args.output.is_symlink():
        raise PermissionError("Report path cannot be symlink")
    args.output.write_text(report)
    args.output.chmod(0o600)
    print(report)


if __name__ == "__main__":
    main()
