"""Read-only, finite first-three-innings partition screen. NEVER routes orders.

A YES on each team or tie pays one dollar *only* when the referenced first
three innings are actually scored and the exact three binding rules remain
unchanged. Even a positive fee-adjusted quote is NOT executable arbitrage:
three independent legs cannot be filled atomically. No Kalshi key is loaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import requests

from core.microstructure import _grid_check, effective_fees, fee_estimate
from core.public_market import MarketDataError, PublicMarketClient, quote_from_orderbook

SERIES = 'KXMLBF3'
CENT = Decimal('0.01')
SCHEMA_VERSION = 2


class Ineligible(MarketDataError):
    """A syntactically readable contract is outside the reviewed payout set."""


class LiquidityUnavailable(MarketDataError):
    """Valid market and book, but the requested one-share side is not displayed."""


WHEN = r'[A-Z][a-z]{2} \d{1,2}, 20\d{2} at \d{1,2}:\d{2} [AP]M (?:EDT|EST|CDT|CST|MDT|MST|PDT|PST)'
TEAM = re.compile(r'If (?P<who>.+?) wins the first 3 innings of the (?P<a>.+?) vs (?P<b>.+?) professional baseball game originally scheduled for (?P<when>' + WHEN + r'), then the market resolves to Yes\.')
TIE = re.compile(r'If (?P<a>.+?) and (?P<b>.+?) tie in the first 3 innings of the (?P<c>.+?) vs (?P<d>.+?) professional baseball game originally scheduled for (?P<when>' + WHEN + r'), then the market resolves to Yes\.')
BRAND = ('Kalshi is not affiliated, associated, authorized, endorsed by, or in any way officially '
         'connected with the Governing League. All trademarks, logos, and brand names are the '
         'property of their respective owners.')


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def strict_rules(event: dict, markets: list[dict]) -> str:
    """Exact, intentionally narrow allowlist; a new exchange rule needs review."""
    if not isinstance(event,dict) or not isinstance(markets,list):
        raise MarketDataError('Missing event or market metadata')
    eid = event.get('event_ticker')
    if (event.get('series_ticker') != SERIES or event.get('mutually_exclusive') is not True
            or event.get('collateral_return_type') != 'MECNET'
            or event.get('exchange_index') != 3 or len(markets) != 3
            or len({m.get('ticker') for m in markets}) != 3):
        raise Ineligible('Incomplete or changed three-way event partition')
    teams, ties, context, secondaries = set(), 0, None, set()
    for m in markets:
        if not isinstance(m,dict) or any(k not in m for k in
               ('ticker','event_ticker','exchange_index','status','market_type','notional_value_dollars',
                'price_level_structure','price_ranges','can_close_early','early_close_condition',
                'expected_expiration_time','close_time','updated_time',
                'rules_primary','rules_secondary','yes_sub_title')):
            raise MarketDataError('Missing required market metadata')
        parsed_timestamp(m['updated_time'])
        if 'is_provisional' in m and m['is_provisional'] is not False:
            raise Ineligible('Provisional or malformed provisional-state value')
        if (m.get('event_ticker') != eid or m.get('exchange_index') != 3 or
                m.get('status') != 'active' or
                m.get('market_type') != 'binary' or m.get('notional_value_dollars') != '1.0000' or
                m.get('price_level_structure') != 'linear_cent' or
                m.get('price_ranges') != [{'start':'0.0000','end':'1.0000','step':'0.0100'}] or
                m.get('can_close_early') is not True or
                m.get('early_close_condition') != 'This market will close and expire after a winner is declared.'):
            raise Ineligible('Market identity, payout, grid or eligibility changed')
        ticker = m['ticker']
        if not ticker.startswith(eid+'-'):
            raise Ineligible('Market ticker disagrees with event')
        try:
            end = datetime.fromisoformat(m['expected_expiration_time'].replace('Z','+00:00'))
            close = datetime.fromisoformat(m['close_time'].replace('Z','+00:00'))
        except (KeyError, ValueError, AttributeError) as exc:
            raise MarketDataError('Missing valid expiry') from exc
        if not (end.tzinfo and close.tzinfo and end <= close):
            raise Ineligible('Missing or reversed game expiry')
        text = m.get('rules_primary')
        one = TEAM.fullmatch(text) if isinstance(text, str) else None
        tie = TIE.fullmatch(text) if isinstance(text, str) else None
        if (one is None) == (tie is None):
            raise Ineligible('Unknown or ambiguous first-three-innings rule')
        x = one or tie
        a, b, when = x['a'], x['b'], x['when']
        if (not a or not b or a == b or a != a.strip() or b != b.strip()
                or ' vs ' in a or ' vs ' in b):
            raise MarketDataError('Invalid or ambiguous team identity')
        match_context = (a, b, when)
        if context is not None and context != match_context:
            raise Ineligible('Different games or scheduled starts in three rules')
        context = match_context
        try:
            datetime.strptime(when[:-4], '%b %d, %Y at %I:%M %p')
        except ValueError as exc:
            raise MarketDataError('Invalid game date in rule') from exc
        if tie:
            if x['c'] != a or x['d'] != b or ticker != eid+'-TIE' or m.get('yes_sub_title') != 'Tie first 3 innings':
                raise Ineligible('Tie rule conflicts with team game')
            ties += 1
        else:
            who=x['who']
            if who not in (a,b) or who in teams or ticker == eid+'-TIE' or m.get('yes_sub_title') != who+' wins first 3 innings':
                raise Ineligible('Missing or duplicate team winner')
            teams.add(who)
        expected = (f'This market refers to the first 3 innings of the {a} vs {b} professional baseball '
                    f'game originally scheduled for {when}. If the score at the end of the first 3 innings '
                    'is tied, the "Tie" strike will resolve to Yes and all team strikes will resolve to No. '
                    'If this game is postponed or delayed, the market will remain open and close after the '
                    'rescheduled game has finished (within two days).\n\n' + BRAND)
        if m.get('rules_secondary') != expected:
            raise Ineligible('Unknown exception or changed secondary rule')
        secondaries.add(expected)
    if ties != 1 or teams != {context[0],context[1]} or len(secondaries) != 1:
        raise Ineligible('Partition is not exactly team A / team B / tie')
    return hashlib.sha256(('\n'.join(sorted(m['rules_primary'] for m in markets)) + '\n' + secondaries.pop()).encode()).hexdigest()


def one_unit_ask(market: dict, book: dict, side: str) -> tuple[Decimal, Decimal]:
    """Require a full share on the opposite bid: one price/fill fee model."""
    if side not in ('yes','no'):
        raise MarketDataError('Invalid contract side')
    quote = quote_from_orderbook(book)
    if quote is None:
        raise LiquidityUnavailable('One-sided or empty book')
    levels = book['no_dollars' if side=='yes' else 'yes_dollars']
    available: list[tuple[Decimal,Decimal]] = []
    for row in levels:
        if not isinstance(row,list) or len(row) < 2:
            raise MarketDataError('Malformed NO level')
        price=Decimal(str(row[0])); qty=Decimal(str(row[1])); _grid_check(price,market)
        if not qty.is_finite() or qty < 0 or (qty*100)%1 != 0:
            raise MarketDataError('Invalid orderbook quantity')
        if qty > 0:
            available.append((Decimal('1')-price,qty))
    available.sort(key=lambda pair: pair[0])
    if not available or available[0][1] < 1:
        raise LiquidityUnavailable('Less than one share at the best '+side.upper()+' ask; cannot model one fill')
    return available[0]


def one_unit_yes_ask(market: dict, book: dict) -> tuple[Decimal, Decimal]:
    return one_unit_ask(market,book,'yes')


def contract_signature(event: dict, series: dict) -> str:
    markets=event.get('markets')
    rule_hash=strict_rules(event,markets)
    fees=effective_fees(series,event)
    fields=('ticker','event_ticker','exchange_index','status','is_provisional','notional_value_dollars',
            'expected_expiration_time','close_time','updated_time','price_ranges','rules_primary','rules_secondary')
    stable={'event_ticker':event['event_ticker'],'rule_sha256':rule_hash,
            'fees':[fees[0],str(fees[1])],
            'markets':[{field:m.get(field) for field in fields} for m in sorted(markets,key=lambda x:x['ticker'])]}
    return hashlib.sha256(json.dumps(stable,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def parsed_timestamp(value: str) -> datetime:
    if not isinstance(value,str):
        raise MarketDataError('Missing or malformed book timestamp')
    try:
        ts=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError as exc:
        raise MarketDataError('Malformed book timestamp') from exc
    if ts.tzinfo is None:
        raise MarketDataError('Book timestamp missing timezone')
    return ts.astimezone(timezone.utc)


def screen_event(event: dict, series: dict, books: dict[str,dict], *,
                 started: str, completed: str, slippage_buffer: Decimal=Decimal('0.03'),
                 book_receipts: dict[str,str]|None=None, post_event: dict|None=None,
                 post_series: dict|None=None, book_read_order: list[str]|None=None) -> dict:
    if slippage_buffer < 0 or not slippage_buffer.is_finite():
        raise MarketDataError('Invalid slippage buffer')
    markets=event['markets']
    rule_hash=strict_rules(event,markets)
    if {m['ticker'] for m in markets} != set(books):
        raise MarketDataError('Incomplete orderbook set')
    if not isinstance(book_receipts,dict) or set(book_receipts) != set(books):
        raise MarketDataError('Incomplete book receipt timestamps')
    if not isinstance(book_read_order,list) or len(book_read_order)!=3 or set(book_read_order)!=set(books):
        raise MarketDataError('Missing actual book read order')
    if post_event is None or post_series is None:
        raise MarketDataError('No post-book rule/fee revalidation')
    original_signature=contract_signature(event,series)
    if contract_signature(post_event,post_series) != original_signature:
        raise Ineligible('Contract rules, status, market update or fees changed after books')
    begin=parsed_timestamp(started)
    finish=parsed_timestamp(completed)
    receipt_times=[parsed_timestamp(book_receipts[ticker]) for ticker in book_read_order]
    if not (0 <= (finish-begin).total_seconds() <= 8 and
            begin <= receipt_times[0] <= receipt_times[1] <= receipt_times[2] <= finish and
            (receipt_times[-1]-receipt_times[0]).total_seconds() <= 4):
        raise MarketDataError('Book collection not fresh enough for same-event screen')
    if any(parsed_timestamp(m['expected_expiration_time'])<=finish for m in markets):
        raise Ineligible('Game expected expiration elapsed during quote collection')
    fee_type, multiplier=effective_fees(series,event)
    provisional_verified=all(m.get('is_provisional') is False for m in markets)
    baskets={}
    for side,payout in (('yes',Decimal('1')),('no',Decimal('2'))):
        legs=[]
        for market in sorted(markets,key=lambda x:x['ticker']):
            ask,depth=one_unit_ask(market,books[market['ticker']],side)
            fee=fee_estimate(ask,fee_type,multiplier,maker=False)
            legs.append({'ticker':market['ticker'],'ask_dollars':str(ask),
                         'displayed_ask_depth_fp':str(depth),'estimated_taker_fee_dollars':str(fee)})
        cost=sum((Decimal(x['ask_dollars'])+Decimal(x['estimated_taker_fee_dollars']) for x in legs),Decimal('0'))
        gross=payout-sum((Decimal(x['ask_dollars']) for x in legs),Decimal('0'))
        net=payout-cost-slippage_buffer
        baskets[side]={'conditional_scored_game_payout_dollars':str(payout),'legs':legs,
                       'one_set_gross_dollars':str(gross),'one_set_fee_and_buffer_net_dollars':str(net),
                       'price_anomaly_after_costs':net>0,
                       'indicative_only_nonatomic_candidate':bool(net>0 and provisional_verified)}
    raw_proof={'raw_event':event,'raw_series':series,'raw_post_event':post_event,
               'raw_post_series':post_series,'raw_orderbooks_fp':books,
               'book_receipts_utc':book_receipts,'book_read_order':book_read_order,
               'books_started_utc':started,'books_completed_utc':completed,
               'slippage_buffer_dollars':str(slippage_buffer)}
    evidence_sha256=hashlib.sha256(json.dumps(raw_proof,sort_keys=True,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()
    return {'event_ticker':event['event_ticker'],'series_ticker':SERIES,
            'schema_version':SCHEMA_VERSION,'pre_post_contract_sha256':original_signature,
            'provisional_status_verified':provisional_verified,'evidence_sha256':evidence_sha256,
            'rule_sha256':rule_hash,**raw_proof,
            'binding_rules':[{'ticker':m['ticker'],'rules_primary':m['rules_primary'],
                              'rules_secondary':m['rules_secondary'],'market_updated_utc':m.get('updated_time')}
                             for m in sorted(markets,key=lambda x:x['ticker'])],
            'fee_type':fee_type,'fee_multiplier':str(multiplier),'baskets':baskets,
            'indicative_only_nonatomic_candidate':any(v['indicative_only_nonatomic_candidate'] for v in baskets.values()),
            'orders':0,'fills':0,'not_a_locked_profit':True}


def scan_one(ticker: str, expected: set[str], slippage_buffer: Decimal) -> dict:
    client=PublicMarketClient();started=stamp()
    try:
        event=client.get_event(ticker);markets=event['markets']
        if {m.get('ticker') for m in markets} != expected:
            raise MarketDataError('Open discovery and nested event disagree')
        strict_rules(event,markets)  # Reject mismatched outcomes before books.
        if any(datetime.fromisoformat(m['expected_expiration_time'].replace('Z','+00:00'))
               <= datetime.now(timezone.utc) for m in markets):
            raise MarketDataError('Expected game expiration passed; no ordinary active result')
        series=client.get_series(SERIES)
        books={};receipts={};book_read_order=[]
        for m in markets:
            book_read_order.append(m['ticker'])
            books[m['ticker']]=client.get_orderbook(m['ticker'],depth=20)
            receipts[m['ticker']]=stamp()
        post_event=client.get_event(ticker)
        post_series=client.get_series(SERIES)
        result=screen_event(event,series,books,started=started,completed=stamp(),
                            slippage_buffer=slippage_buffer,book_receipts=receipts,
                            book_read_order=book_read_order,post_event=post_event,post_series=post_series)
        return {'type':'partition_quote','observed_utc':stamp(),**result}
    except (requests.RequestException, TimeoutError) as exc:
        return {'type':'partition_source_error','observed_utc':stamp(),'event_ticker':ticker,
                'reason':type(exc).__name__, 'detail':str(exc)[:180], 'orders':0,'fills':0}
    except Ineligible as exc:
        return {'type':'partition_ineligible','observed_utc':stamp(), 'event_ticker':ticker,
                'reason':type(exc).__name__, 'detail':str(exc)[:180],
                'orders':0,'fills':0}
    except LiquidityUnavailable as exc:
        return {'type':'partition_liquidity_unavailable','observed_utc':stamp(), 'event_ticker':ticker,
                'reason':type(exc).__name__, 'detail':str(exc)[:180],
                'orders':0,'fills':0}
    except MarketDataError as exc:
        return {'type':'partition_source_error','observed_utc':stamp(),'event_ticker':ticker,
                'reason':type(exc).__name__, 'detail':str(exc)[:180], 'orders':0,'fills':0}
    except Exception as exc:
        return {'type':'partition_source_error','observed_utc':stamp(),'event_ticker':ticker,
                'reason':type(exc).__name__, 'detail':str(exc)[:180], 'orders':0,'fills':0}


def scan_cycle(*, max_events: int, workers: int=4, slippage_buffer: Decimal=Decimal('0.03')) -> list[dict]:
    client=PublicMarketClient()
    markets=client.get_markets(SERIES)
    grouped: dict[str,set[str]]=defaultdict(set)
    for m in markets:
        ticker=m.get('event_ticker');name=m.get('ticker')
        if not isinstance(ticker,str) or not ticker.startswith(SERIES+'-') or not isinstance(name,str):
            raise MarketDataError('Malformed first-three-innings discovery')
        if name in grouped[ticker]:
            raise MarketDataError('Duplicate market in discovery')
        grouped[ticker].add(name)
    if len(grouped)>max_events:
        raise MarketDataError('Discovery exceeds explicitly bounded event count')
    results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        jobs={pool.submit(scan_one,ticker,names,slippage_buffer):ticker
              for ticker,names in sorted(grouped.items())}
        for job in as_completed(jobs):
            results.append(job.result())
    return sorted(results,key=lambda r:r['event_ticker'])


def run(*, output: Path, cycles: int, interval: float, max_events: int, workers: int,
        until_utc: datetime|None=None) -> dict:
    if not (1<=cycles<=1000 and 15<=interval<=3600 and 1<=max_events<=100 and 1<=workers<=6):
        raise ValueError('Invalid finite polling or rate bound')
    if until_utc is not None and (until_utc.tzinfo is None or not datetime.now(timezone.utc) < until_utc <= datetime.now(timezone.utc)+timedelta(hours=36)):
        raise ValueError('Use a future, timezone-aware stop within 36 hours')
    output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if output.parent.stat().st_mode & 0o077:
        raise PermissionError('Journal directory must be owner-only')
    fd=os.open(output,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    totals={'cycles':0,'events':0,'valid_books':0,'positive_indicative':0,'ineligible':0,
            'liquidity_unavailable':0,'source_errors':0,'cycle_errors':0,'orders':0,'fills':0}
    with os.fdopen(fd,'w',encoding='utf8') as out:
        for i in range(cycles):
            if until_utc is not None and datetime.now(timezone.utc)>=until_utc:
                break
            begin=time.monotonic(); started=stamp()
            try:
                results=scan_cycle(max_events=max_events,workers=workers)
                for row in results:
                    row['schema_version']=SCHEMA_VERSION
                    row['cycle_number']=i+1
                    out.write(json.dumps(row,sort_keys=True)+'\n')
                totals['events']+=len(results)
                totals['valid_books']+=sum(r['type']=='partition_quote' for r in results)
                totals['positive_indicative']+=sum(r.get('indicative_only_nonatomic_candidate') is True for r in results)
                totals['ineligible']+=sum(r['type']=='partition_ineligible' for r in results)
                totals['liquidity_unavailable']+=sum(r['type']=='partition_liquidity_unavailable' for r in results)
                totals['source_errors']+=sum(r['type']=='partition_source_error' for r in results)
                status='complete'
            except Exception as exc:
                status='error';totals['cycle_errors']+=1
                out.write(json.dumps({'type':'cycle_error','schema_version':SCHEMA_VERSION,
                    'cycle_number':i+1,'observed_utc':stamp(),
                    'reason':type(exc).__name__,'detail':str(exc)[:180],'orders':0,'fills':0})+'\n')
            totals['cycles']+=1
            out.write(json.dumps({'type':'partition_cycle','schema_version':SCHEMA_VERSION,'observed_utc':stamp(),
                'started_utc':started,'status':status,'cycle_number':i+1,'totals':totals.copy(),
                'orders':0,'fills':0},sort_keys=True)+'\n')
            out.flush();os.fsync(out.fileno())
            print(f"cycle={i+1} status={status} valid={totals['valid_books']} indicative={totals['positive_indicative']} ineligible={totals['ineligible']} liquidity_unavailable={totals['liquidity_unavailable']} source_errors={totals['source_errors']} cycle_errors={totals['cycle_errors']}",flush=True)
            if i+1<cycles:
                remain=interval-(time.monotonic()-begin)
                if remain>0:time.sleep(min(remain,max(0,(until_utc-datetime.now(timezone.utc)).total_seconds())) if until_utc else remain)
        out.write(json.dumps({'type':'partition_end','schema_version':SCHEMA_VERSION,
                              'observed_utc':stamp(),'totals':totals,
                              'orders':0,'fills':0,'not_profit_evidence':True},sort_keys=True)+'\n')
        out.flush();os.fsync(out.fileno())
    return totals


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cycles',type=int,default=1)
    p.add_argument('--interval',type=float,default=120)
    p.add_argument('--max-events',type=int,default=30)
    p.add_argument('--workers',type=int,default=4)
    p.add_argument('--until-utc',type=lambda s:datetime.fromisoformat(s.replace('Z','+00:00')))
    args=p.parse_args()
    print(run(output=args.output,cycles=args.cycles,interval=args.interval,
              max_events=args.max_events,workers=args.workers,until_utc=args.until_utc))


if __name__=='__main__':main()
