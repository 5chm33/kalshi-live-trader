"""Read-only weather series/source inventory. No forecasts, probabilities, or orders."""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from core.public_market import PublicMarketClient, MarketDataError


def inventory(client: PublicMarketClient, *, check_open: bool = False, sleep=time.sleep):
    rows = client._get('/series', {'category': 'Climate and Weather'}).get('series')
    if not isinstance(rows, list):
        raise MarketDataError('Missing weather series list')
    result = []
    for row in rows:
        if not isinstance(row, dict) or row.get('frequency') != 'daily':
            continue
        title = row.get('title', '')
        if not isinstance(title, str) or not any(x in title.lower() for x in ('temperature', 'highest', 'lowest')):
            continue
        sources = [s.get('name', '') for s in (row.get('settlement_sources') or []) if isinstance(s, dict)]
        item = {'ticker': row.get('ticker'), 'title': title,
                'settlement_sources': sources, 'fee_type': row.get('fee_type'),
                'fee_multiplier': row.get('fee_multiplier')}
        if check_open:
            ticker = item['ticker']
            if not isinstance(ticker, str) or not ticker.isalnum():
                raise MarketDataError('Invalid weather series ticker')
            response = client._get('/markets', {'series_ticker': ticker, 'status': 'open', 'limit': 1})
            markets = response.get('markets')
            if not isinstance(markets, list):
                raise MarketDataError('Missing weather market list')
            item['has_open_market'] = bool(markets)
            sleep(0.2)
        result.append(item)
    counts = Counter('NWS/NOAA' if any('weather service' in s.lower() or 'noaa' in s.lower() or s.strip().lower().startswith('nws') for s in r['settlement_sources'])
                     else 'The Weather Company' if any('weather company' in s.lower() for s in r['settlement_sources'])
                     else 'Other/unknown' for r in result)
    return {'series_examined': len(rows), 'matching_daily_temperature_series': len(result),
            'source_counts': dict(counts),
            'open_source_counts': dict(Counter('NWS/NOAA' if any('weather service' in s.lower() or 'noaa' in s.lower() or s.strip().lower().startswith('nws') for s in r['settlement_sources'])
                                               else 'The Weather Company' if any('weather company' in s.lower() for s in r['settlement_sources']) else 'Other/unknown'
                                               for r in result if r.get('has_open_market'))) if check_open else None,
            'series': sorted(result, key=lambda x: str(x['ticker']))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--check-open', action='store_true', help='Additional bounded public GET for each daily series')
    args = parser.parse_args()
    result = inventory(PublicMarketClient(), check_open=args.check_open)
    if args.output.is_symlink():
        raise PermissionError('Output cannot be a symlink')
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    args.output.chmod(0o600)
    print('weather_series=', result['matching_daily_temperature_series'],
          'source_counts=', result['source_counts'],
          'open_source_counts=', result['open_source_counts'],
          'no_trades_or_forecast_edge_claimed=True')


if __name__ == '__main__':
    main()
