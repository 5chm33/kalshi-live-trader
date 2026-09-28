"""Finite, restart-safe, public-data-only Kalshi research collector.

Runs the existing bounded observer in separate private UTC-stamped segments. A
reboot leaves its interrupted segment explicit and starts a new one; nothing
merges a partial journal into a clean performance claim. No API key is loaded.
No exchange order endpoint is imported or callable by this module.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from observe_30m import run
from summarize_monitor import summarize
import json


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def collect(until: datetime, output_dir: Path, *, interval: float = 10.0,
            segment_seconds: int = 1800, sleep=time.sleep) -> int:
    if until.tzinfo is None or not 5 <= interval <= 300 or not 60 <= segment_seconds <= 7200:
        raise ValueError('UTC deadline, interval, or segment duration invalid')
    now = utcnow()
    if until <= now + timedelta(seconds=60):
        raise ValueError('Research collector deadline must be more than 60 seconds in the future')
    if until - now > timedelta(days=7, minutes=2):
        raise ValueError('Research collector may not run more than seven days from launch')
    if output_dir.is_symlink():
        raise PermissionError('Journal directory cannot be a symlink')
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output_dir.stat().st_mode & 0o077:
        raise PermissionError('Journal directory must be owner-only')
    lock_fd = os.open(output_dir / '.single_writer.lock',
                      os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while (left := (until - utcnow()).total_seconds()) >= 60:
            duration = min(segment_seconds, int(left))
            stamp = utcnow().strftime('%Y%m%dT%H%M%S%fZ')
            journal = output_dir / f'{stamp}.jsonl'
            print(f'collector_segment={journal.name} duration={duration}s', flush=True)
            result = run(duration, interval, journal)
            rows = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]
            summary = summarize(rows)
            (output_dir / f'{stamp}.md').write_text(summary)
            print('segment_complete scans=', result['totals']['cycles'],
                  'candidate_count=', result['totals']['candidates'],
                  'source_errors=', result['totals']['source_errors'],
                  'exchange_orders=', result['totals']['real_orders'], flush=True)
        left = (until - utcnow()).total_seconds()
        if left > 0:
            sleep(left)
        print('collector_deadline_reached: no order writes were ever enabled', flush=True)
        return 0
    finally:
        os.close(lock_fd)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--until-utc', required=True, help='Absolute ISO-8601 deadline')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--interval-seconds', type=float, default=10.0)
    parser.add_argument('--segment-seconds', type=int, default=1800)
    args = parser.parse_args()
    try:
        until = datetime.fromisoformat(args.until_utc.replace('Z', '+00:00'))
        return collect(until, args.output_dir,
                       interval=args.interval_seconds, segment_seconds=args.segment_seconds)
    except Exception as exc:
        print(f'collector_failed: {type(exc).__name__}: {str(exc)[:200]}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
