"""Verify and summarize one COMPLETE public-only first-three-innings journal.

Every quote is replayed from its original public event, series, and books. A
legacy, truncated, altered, or execution-bearing journal is not accepted.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from decimal import Decimal
from pathlib import Path

from scan_mlb_f3_partitions import SCHEMA_VERSION, parsed_timestamp, screen_event

KINDS={'partition_quote','partition_source_error','partition_ineligible',
       'partition_liquidity_unavailable','cycle_error','partition_cycle','partition_end'}
EVENT_KINDS=KINDS-{'cycle_error','partition_cycle','partition_end'}


def replay_quote(row: dict) -> None:
    if row.get('not_a_locked_profit') is not True:
        raise ValueError('Quote lacks non-atomic/non-profit warning')
    needed=('raw_event','raw_series','raw_post_event','raw_post_series','raw_orderbooks_fp',
            'book_read_order','book_receipts_utc','books_started_utc','books_completed_utc',
            'slippage_buffer_dollars','rule_sha256','pre_post_contract_sha256','baskets',
            'fee_type','fee_multiplier','provisional_status_verified','evidence_sha256')
    if any(k not in row for k in needed):
        raise ValueError('Missing raw proof in versioned quote')
    try:
        age=(parsed_timestamp(row['observed_utc'])-
             parsed_timestamp(row['books_completed_utc'])).total_seconds()
        if not 0 <= age <= 2:
            raise ValueError('Quote observation is not adjacent to its book receipts')
        replay=screen_event(row['raw_event'],row['raw_series'],row['raw_orderbooks_fp'],
             book_read_order=row['book_read_order'],book_receipts=row['book_receipts_utc'],
             started=row['books_started_utc'],completed=row['books_completed_utc'],
             post_event=row['raw_post_event'],post_series=row['raw_post_series'],
             slippage_buffer=Decimal(row['slippage_buffer_dollars']))
        for field in ('event_ticker','series_ticker','rule_sha256','pre_post_contract_sha256',
                      'provisional_status_verified','evidence_sha256','fee_type','fee_multiplier','baskets',
                      'indicative_only_nonatomic_candidate'):
            if row.get(field)!=replay[field]:
                raise ValueError(f'Quote {field} differs from raw rule/book replay')
        if row['indicative_only_nonatomic_candidate'] and not row['provisional_status_verified']:
            raise ValueError('Unknown provisional status cannot promote price anomaly')
    except (KeyError, TypeError, ArithmeticError) as exc:
        raise ValueError('Malformed quote proof') from exc


def verified_records(lines: list[str]) -> tuple[list[dict],list[dict],list[dict],list[dict],list[dict]]:
    try:
        rows=[json.loads(x) for x in lines if x.strip()]
    except (ValueError,TypeError) as exc:
        raise ValueError('Truncated or malformed JSONL') from exc
    if not rows or any(not isinstance(r,dict) or r.get('schema_version')!=SCHEMA_VERSION or
                       r.get('type') not in KINDS or r.get('orders')!=0 or r.get('fills')!=0
                       for r in rows):
        raise ValueError('Unversioned, unknown, or execution-bearing journal')
    if sum(r['type']=='partition_end' for r in rows)!=1 or rows[-1]['type']!='partition_end':
        raise ValueError('Exactly one terminal record is required')
    counts=Counter({'cycles':0,'events':0,'valid_books':0,'positive_indicative':0,
        'ineligible':0,'liquidity_unavailable':0,'source_errors':0,'cycle_errors':0,
        'orders':0,'fills':0})
    cycles=[];quotes=[];source=[];bad=[];liquid=[];pending=[]
    prev_end=None
    for row in rows[:-1]:
        kind=row['type'];number=counts['cycles']+1
        if row.get('cycle_number')!=number:
            raise ValueError('Cycle numbering inconsistent')
        if kind in EVENT_KINDS or kind=='cycle_error':
            pending.append(row)
            if kind=='partition_quote':
                replay_quote(row);quotes.append(row)
            elif kind=='partition_source_error' or kind=='cycle_error':source.append(row)
            elif kind=='partition_liquidity_unavailable':liquid.append(row)
            else:bad.append(row)
            continue
        if kind!='partition_cycle':
            raise ValueError('Unexpected record before terminal cycle')
        begin=parsed_timestamp(row.get('started_utc'))
        end=parsed_timestamp(row.get('observed_utc'))
        if begin>end or (prev_end is not None and begin<prev_end):
            raise ValueError('Overlapping or reversed polling cycles')
        prev_end=end
        if any(not begin<=parsed_timestamp(r.get('observed_utc'))<=end for r in pending):
            raise ValueError('Data receipt timestamp outside its polling cycle')
        errors=[r for r in pending if r['type']=='cycle_error']
        events=[r for r in pending if r['type'] in EVENT_KINDS]
        if (row.get('status')=='complete' and errors) or (row.get('status')=='error' and
            (len(errors)!=1 or events)) or row.get('status') not in ('complete','error'):
            raise ValueError('Cycle status does not match records')
        if len({r['event_ticker'] for r in events})!=len(events):
            raise ValueError('Repeated event in one polling cycle')
        counts.update({'cycles':1,'events':len(events),
            'valid_books':sum(r['type']=='partition_quote' for r in events),
            'positive_indicative':sum(r.get('indicative_only_nonatomic_candidate') is True for r in events),
            'ineligible':sum(r['type']=='partition_ineligible' for r in events),
            'liquidity_unavailable':sum(r['type']=='partition_liquidity_unavailable' for r in events),
            'source_errors':sum(r['type']=='partition_source_error' for r in events),
            'cycle_errors':len(errors)})
        if row.get('totals')!=dict(counts):
            raise ValueError('Cycle counters disagree with raw records')
        cycles.append(row);pending=[]
    if pending or not cycles or rows[-1].get('totals')!=dict(counts):
        raise ValueError('Incomplete terminal counter reconciliation')
    if parsed_timestamp(rows[-1].get('observed_utc'))<prev_end:
        raise ValueError('Terminal timestamp predates last cycle')
    return cycles,quotes,source,bad,liquid


def render(lines: list[str]) -> str:
    cycles,quotes,source,bad,liquid=verified_records(lines)
    counts=Counter(r['event_ticker'] for r in quotes)
    indicative=[(r,side) for r in quotes for side in ('yes','no')
                if r['baskets'][side]['indicative_only_nonatomic_candidate'] is True]
    blocked=[(r,side) for r in quotes for side in ('yes','no')
             if r['baskets'][side]['price_anomaly_after_costs'] is True and
             not r['baskets'][side]['indicative_only_nonatomic_candidate']]
    unknown=sum(r['provisional_status_verified'] is False for r in quotes)
    results=['# First-three-innings full-partition book screen', '',
             f"Observed **{cycles[0]['started_utc']} to {cycles[-1]['observed_utc']}**. "
             '**No orders or fills were submitted** by this collector.',
             '', f'Completed polling cycles: **{len(cycles)}**; terminal record: **verified**. '
             f'Eligible independent events with a displayed book: **{len(counts)}**; '
             f'event/book snapshots: **{len(quotes)}**. Repeated snapshots of one game are not independent trials.',
             f'**{len(source)}** venue/source errors, **{len(bad)}** semantic exclusions, '
             f'and **{len(liquid)}** valid-but-unavailable liquidity records. '
             'A source error is not a clean no-opportunity observation.',
             f'**{unknown}** book snapshots lacked an explicit `is_provisional=false` metadata field. '
             'Their arithmetic can be archived but **no positive signal may be promoted** from them. '
             f'Fee-adjusted price anomalies suppressed by this gate: **{len(blocked)}**.',
             '', 'Every quoted row was recomputed from its original rules, pre/post market and fee metadata, '
             'three raw public books, request receipts, one full share at each opposite-side ask, and the '
             'original $0.03 per-basket buffer. The sequential client receipt times are **not venue timestamps** '
             'or atomic fills. The exact reviewed rule text models only an ordinary scored first-three-innings '
             'result: an all-YES basket then pays $1 and an all-NO basket $2. Exceptional settlement, changed '
             'book depth, or one unfilled leg can defeat any projected payout.', '']
    for side in ('yes','no'):
        if quotes:
            best=max(quotes,key=lambda r:Decimal(r['baskets'][side]['one_set_fee_and_buffer_net_dollars']))
            x=best['baskets'][side]
            results.append(f'- Best displayed {side.upper()} basket after modeled taker fees and buffer: '
                           f"**${x['one_set_fee_and_buffer_net_dollars']}** on `{best['event_ticker']}` "
                           f"(pre-fee gross ${x['one_set_gross_dollars']}); a quote, not a fill.")
    results += [f'- Positive *indicative non-atomic* basket snapshots: **{len(indicative)}** across '
                f'**{len({r["event_ticker"] for r,_ in indicative})} distinct events**. '
                'Even a positive mark is not a guaranteed or realized gain.',
                '', '**No win percentage or profit claim is made.** The three market legs cannot be matched '
                'atomically by the account; fills/fees/settlement outcomes are not in this journal. '
                'This study does not authorize an account write.', '']
    if indicative:
        results += ['## Indicative snapshots for manual review', '']
        for r,side in indicative[:15]:
            x=r['baskets'][side]
            results.append(f"- `{r['event_ticker']}` {side.upper()} observed {r['books_completed_utc']}: "
                           f"${x['one_set_fee_and_buffer_net_dollars']} after fee and buffer; "
                           f"rule hash `{r['rule_sha256'][:16]}…`; **non-atomic, not traded**.")
    return '\n'.join(results)+'\n'


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('journal',type=Path)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    text=render(args.journal.read_text().splitlines())
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError('Research report output must be new')
    if args.output.parent.stat().st_mode & 0o077:
        raise PermissionError('Research report directory must be owner-only')
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w',encoding='utf8') as f:
        f.write(text);f.flush();os.fsync(f.fileno())
    print('report=',args.output,'orders=0',flush=True)


if __name__=='__main__':main()
