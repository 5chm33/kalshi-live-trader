"""ONE-TIME, $2 MAX funding of a dedicated Kalshi MLB shard-3 subaccount.

Sequence per Kalshi's official exchange-sharding guide: primary shard 0 ->
primary shard 3 -> create numbered subaccount on shard 3 -> transfer to it.
Each write is single-shot and preceded by a durable owner-only stage record.
If a response is ambiguous, do not re-run the write: inspect account state.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from account_preflight import secure_config
from core.kalshi_client import KalshiClient
from core.pilot_venue import MLB_SHARD, VenueError, money
from core.pilot_retirement import PilotRetiredError, require_pilot_write_retired

CAP = Decimal('2.00')
TRANSFER_CENTICENTS = 20000  # Kalshi intra_exchange_instance_transfer 'amount' is 1/100 of one cent.
TRANSFER_CENTS = 200         # Kalshi subaccount transfer amount_cents.


def save_stage(path: Path, record: dict) -> None:
    if (path.is_symlink() or (path.exists() and
            (not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077))):
        raise PermissionError('Funding journal must be owner-only regular file')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix('.new')
    if temp.exists() or temp.is_symlink():
        raise FileExistsError('Pending journal temp file requires inspection')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            out.write(json.dumps(record, sort_keys=True) + '\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
        folder = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def private_get(client: KalshiClient, path: str) -> dict:
    data = client._request('GET', path)
    if not isinstance(data, dict) or '_error' in data:
        raise VenueError('Funding GET unavailable')
    return data


def balance(client: KalshiClient, sub: int, shard: int) -> Decimal:
    data = private_get(client, f'/portfolio/balance?subaccount={sub}&exchange_index={shard}')
    value = money(data.get('balance_dollars'), 'balance_dollars')
    if value < 0:
        raise VenueError('Invalid negative cash')
    return value


def once_post(client: KalshiClient, endpoint: str, body: dict) -> dict:
    require_pilot_write_retired()
    headers = client._auth_headers('POST', endpoint)
    try:
        response = client.session.post(client.base_url + '/trade-api/v2' + endpoint,
                                       json=body, headers=headers, timeout=12,
                                       allow_redirects=False, verify=True)
    except Exception as exc:
        raise VenueError(f'Funding POST outcome uncertain ({type(exc).__name__}); do not repeat') from None
    if response.status_code not in (200, 201, 202):
        raise VenueError(f'Funding POST returned HTTP {response.status_code}; do not repeat blindly')
    try:
        data = response.json()
    except (ValueError, TypeError):
        raise VenueError('Funding response unreadable; do not repeat') from None
    if not isinstance(data, dict):
        raise VenueError('Funding response malformed; do not repeat')
    return data


def fund(client: KalshiClient, path: Path) -> dict:
    if path.exists():
        if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise PermissionError('Unsafe existing funding journal')
        record = json.loads(path.read_text())
        if record.get('stage') == 'funded':
            if (balance(client, record['subaccount'], MLB_SHARD) < Decimal('0.55') or
                    balance(client, record['subaccount'], MLB_SHARD) > CAP):
                raise VenueError('Already-funded pilot account has unexpected balance')
            return record
        if record.get('stage') != 'cross_shard_pending':
            raise VenueError('Prior funding write could be in-flight; stop and inspect private journal')
        if (record.get('amount_dollars') != str(CAP) or record.get('source_shard') != 0
                or record.get('target_shard') != MLB_SHARD or not isinstance(record.get('transfer_id'), str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', record['transfer_id'])):
            raise VenueError('Existing transfer intent fails original $2 identity check')
        account = private_get(client, '/portfolio/subaccounts/balances')
        records = account.get('subaccount_balances')
        if not isinstance(records, list) or any(r.get('subaccount_number') != 0 for r in records):
            raise VenueError('Unexpected new subaccount since cross-shard transfer')
        transfer_id = record['transfer_id']
    else:
        if client.get_api_limits()['usage_tier'] not in {'advanced', 'expert', 'premier', 'paragon', 'prime', 'prestige'}:
            raise VenueError('Advanced tier required for numbered subaccount')
        account = private_get(client, '/portfolio/subaccounts/balances')
        records = account.get('subaccount_balances')
        if not isinstance(records, list) or any(r.get('subaccount_number') != 0 for r in records):
            raise VenueError('Unexpected existing numbered subaccount; do not reuse for pilot')
        primary0, primary3 = balance(client, 0, 0), balance(client, 0, MLB_SHARD)
        if primary0 < CAP or primary3 != 0:
            raise VenueError('Primary exchange cash no longer matches isolated funding preflight')
        record = {'stage': 'cross_shard_submitting', 'amount_dollars': str(CAP),
                  'source_shard': 0, 'target_shard': MLB_SHARD}
        save_stage(path, record)  # durable BEFORE irreversible POST
        result = once_post(client, '/portfolio/intra_exchange_instance_transfer',
                           {'source': 'event_contract', 'destination': 'event_contract',
                            'amount': TRANSFER_CENTICENTS, 'source_exchange_shard': 0,
                            'destination_exchange_shard': MLB_SHARD,
                            'source_subaccount': 0, 'destination_subaccount': 0})
        transfer_id = result.get('transfer_id')
        if not isinstance(transfer_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', transfer_id):
            raise VenueError('Cross-shard transfer ACK ambiguous; inspect journal and venue')
        record.update(stage='cross_shard_pending', transfer_id=transfer_id)
        save_stage(path, record)
    for _ in range(20):
        try:
            view = private_get(client, '/portfolio/intra_exchange_instance_transfers/' + transfer_id).get('transfer')
        except VenueError:
            time.sleep(3)
            continue
        if not isinstance(view, dict) or view.get('transfer_id') != transfer_id:
            raise VenueError('Cross-shard transfer GET identity mismatch')
        if (view.get('source') != 'event_contract' or view.get('destination') != 'event_contract'
                or view.get('source_exchange_shard') != 0
                or view.get('destination_exchange_shard') != MLB_SHARD
                or money(view.get('amount'), 'venue transfer amount') != CAP):
            raise VenueError('Exchange transfer source, shard, or $2 amount mismatch')
        if view.get('status') in ('complete', 'completed', 'success', 'succeeded'):
            break
        if view.get('status') not in ('pending', 'processing', 'in_progress'):
            raise VenueError('Cross-shard transfer failed or has unknown status; no retry')
        time.sleep(3)
    else:
        raise VenueError('Cross-shard transfer still pending; do not repeat')
    if balance(client, 0, MLB_SHARD) != CAP:
        raise VenueError('Primary shard-3 cash not exactly $2 after transfer')
    record['stage'] = 'create_subaccount_submitting'
    save_stage(path, record)
    result = once_post(client, '/portfolio/subaccounts', {'exchange_index': MLB_SHARD})
    number = result.get('subaccount_number')
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 63:
        raise VenueError('Subaccount creation ambiguous; do not create another')
    record.update(stage='created', subaccount=number)
    save_stage(path, record)
    if balance(client, number, MLB_SHARD) != 0:
        raise VenueError('New subaccount unexpectedly has cash; stop before transfer')
    record.update(stage='subaccount_transfer_submitting', client_transfer_id=str(uuid4()))
    save_stage(path, record)
    result = once_post(client, '/portfolio/subaccounts/transfer',
                       {'client_transfer_id': record['client_transfer_id'],
                        'from_subaccount': 0, 'to_subaccount': number,
                        'amount_cents': TRANSFER_CENTS, 'exchange_index': MLB_SHARD})
    if result != {}:
        raise VenueError('Unexpected subaccount transfer response; inspect balances')
    for _ in range(10):
        if balance(client, number, MLB_SHARD) == CAP and balance(client, 0, MLB_SHARD) == 0:
            record['stage'] = 'funded'
            save_stage(path, record)
            return record
        time.sleep(2)
    raise VenueError('Subaccount transfer not verifiably complete; do not repeat')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--journal', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print('FUNDING DISABLED: --execute required', file=sys.stderr)
        return 2
    try:
        require_pilot_write_retired()
    except PilotRetiredError as exc:
        print(f'FUNDING RETIRED: {exc}', file=sys.stderr)
        return 2
    try:
        client = KalshiClient(secure_config(args.config))
        result = fund(client, args.journal)
        print(f'Private pilot account #{result["subaccount"]} funded with exactly $2 on shard {MLB_SHARD}.')
        return 0
    except Exception as exc:
        print(f'FUNDING HALTED (DO NOT REPEAT): {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
