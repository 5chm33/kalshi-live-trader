"""SQLite journal for an eventual supervised trader; NO API calls in this module.

A crash or timeout after submit is UNKNOWN, never an invitation to re-submit.
Acknowledgement is not a fill; a canceled order may still have partial fills.
This ledger is a foundation for exchange reconciliation, not permission to
trade or evidence of completed settlement.
"""
from __future__ import annotations

import fcntl
import os
import sqlite3
import stat
from decimal import Decimal
from pathlib import Path

from core.order_math import V2OrderPlan


class LedgerError(RuntimeError):
    pass


class OrderLedger:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or (path.exists() and stat.S_IMODE(path.stat().st_mode) & 0o077):
            raise PermissionError("Ledger must be a private regular file")
        lock = Path(str(path) + ".lock")
        if lock.is_symlink() or (lock.exists() and stat.S_IMODE(lock.stat().st_mode) & 0o077):
            raise PermissionError("Ledger lock must be private")
        self._lock_fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            os.close(self._lock_fd)
            raise LedgerError("Another process owns the order journal")
        self.db = sqlite3.connect(path, isolation_level=None)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=DELETE")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS intents (
            client_id TEXT PRIMARY KEY, ticker TEXT NOT NULL,
            outcome TEXT NOT NULL, action TEXT NOT NULL, book_side TEXT NOT NULL,
            count TEXT NOT NULL, yes_limit TEXT NOT NULL,
            phase TEXT NOT NULL, order_id TEXT UNIQUE, parent_client_id TEXT,
            exchange_fill_count TEXT, exchange_remaining TEXT, exchange_status TEXT,
            error TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS fills (
            fill_id TEXT PRIMARY KEY, client_id TEXT NOT NULL,
            order_id TEXT NOT NULL, count TEXT NOT NULL,
            yes_price TEXT NOT NULL, fee TEXT NOT NULL,
            FOREIGN KEY(client_id) REFERENCES intents(client_id)
        )""")
        self.db.execute("PRAGMA foreign_keys=ON")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if getattr(self, "db", None):
            self.db.close()
            self.db = None
        if getattr(self, "_lock_fd", None) is not None:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            os.close(self._lock_fd)
            self._lock_fd = None

    def _row(self, client_id: str) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM intents WHERE client_id=?", (client_id,)).fetchone()
        if row is None:
            raise LedgerError("Unknown client order ID")
        return row

    def assert_no_unresolved(self) -> None:
        rows = self.db.execute("SELECT client_id, phase FROM intents WHERE phase != 'verified_flat'").fetchall()
        if rows:
            raise LedgerError("Unresolved order/position exists; block all new entries")

    def unresolved(self) -> list[dict]:
        rows = self.db.execute("""SELECT client_id, ticker, outcome, action, phase,
            order_id, parent_client_id FROM intents WHERE phase != 'verified_flat'
            ORDER BY created_at, client_id""").fetchall()
        return [dict(row) for row in rows]

    def prepare(self, client_id: str, ticker: str, item: V2OrderPlan,
                *, verified_position_size: Decimal | None = None) -> None:
        if not client_id or not ticker:
            raise ValueError("Missing client ID or ticker")
        parent_id = None
        if item.action == "buy":
            self.assert_no_unresolved()
        else:
            entries = self.db.execute("""SELECT * FROM intents
                WHERE ticker=? AND outcome=? AND action='buy' AND phase='reconcile'""",
                (ticker, item.outcome)).fetchall()
            pending_exits = self.db.execute("""SELECT count(*) FROM intents
                WHERE ticker=? AND action='sell' AND phase NOT IN ('verified_flat', 'partial_verified')""",
                (ticker,)).fetchone()[0]
            prior_partial = self.db.execute("""SELECT client_id FROM intents
                WHERE ticker=? AND action='sell' AND phase='partial_verified'""",
                (ticker,)).fetchall()
            prior_exited = sum((self.filled_quantity(record['client_id'])
                                for record in prior_partial), Decimal(0))
            if (len(entries) != 1 or pending_exits or
                    entries[0]['exchange_status'] not in {'executed', 'canceled'} or
                    self.filled_quantity(entries[0]['client_id']) != Decimal(entries[0]['exchange_fill_count']) or
                    not isinstance(verified_position_size, Decimal) or
                    not verified_position_size.is_finite() or
                    (verified_position_size <= 0 if item.outcome == 'yes'
                     else verified_position_size >= 0) or
                    abs(verified_position_size) < item.count or
                    self.filled_quantity(entries[0]['client_id']) - prior_exited != abs(verified_position_size)):
                raise LedgerError("Exit requires bot-owned fills and a verified venue position")
            parent_id = entries[0]['client_id']
        try:
            self.db.execute("""INSERT INTO intents
                (client_id, ticker, outcome, action, book_side, count, yes_limit, phase, parent_client_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'prepared', ?)""",
                (client_id, ticker, item.outcome, item.action, item.side,
                 str(item.count), str(item.yes_limit), parent_id))
        except sqlite3.IntegrityError as exc:
            raise LedgerError("Duplicate client ID") from exc

    def begin_submit(self, client_id: str) -> None:
        if self._row(client_id)["phase"] != "prepared":
            raise LedgerError("Cannot submit an already-submitted intent")
        self.db.execute("UPDATE intents SET phase='submitting' WHERE client_id=?", (client_id,))

    def abandon_prepared(self, client_id: str) -> None:
        """Clear only a persisted intent for which no submission began."""
        if self._row(client_id)['phase'] != 'prepared':
            raise LedgerError('Cannot abandon an attempted or acknowledged order')
        self.db.execute("UPDATE intents SET phase='verified_flat' WHERE client_id=?",
                        (client_id,))

    def record_ack(self, client_id: str, response: dict) -> None:
        row = self._row(client_id)
        if row["phase"] != "submitting":
            raise LedgerError("Unexpected acknowledgement; never retry a write blindly")
        try:
            if not isinstance(response, dict):
                raise ValueError("ACK is not an object")
            if response.get("client_order_id") != client_id or not response.get("order_id"):
                raise ValueError("ACK ID mismatch")
            filled = Decimal(str(response["fill_count"]))
            remaining = Decimal(str(response["remaining_count"]))
            if (not filled.is_finite() or not remaining.is_finite() or filled < 0
                    or remaining < 0 or filled > Decimal(row["count"]) or
                    remaining > Decimal(row["count"]) or
                    filled + remaining > Decimal(row["count"])):
                raise ValueError("ACK count invalid")
        except (KeyError, ValueError, TypeError) as exc:
            self.mark_uncertain(client_id, "malformed acknowledgement")
            raise LedgerError("Malformed order acknowledgement") from exc
        self.db.execute("""UPDATE intents SET phase='reconcile', order_id=?,
                        exchange_fill_count=?, exchange_remaining=? WHERE client_id=?""",
                        (response["order_id"], str(filled), str(remaining), client_id))

    def mark_uncertain(self, client_id: str, reason: str) -> None:
        row = self._row(client_id)
        if row["phase"] == "verified_flat":
            raise LedgerError("Cannot make a verified closed order uncertain")
        self.db.execute("UPDATE intents SET phase='uncertain', error=? WHERE client_id=?",
                        (str(reason)[:150], client_id))

    def attach_observed_order(self, client_id: str, order: dict) -> None:
        """Recover a timeout only via a real, uniquely matched exchange order."""
        row = self._row(client_id)
        if row['phase'] not in {'submitting', 'uncertain', 'reconcile'}:
            raise LedgerError('No submitted order to reconcile')
        try:
            if (order.get('client_order_id') != client_id or not order.get('order_id')
                    or order.get('ticker') != row['ticker']
                    or order.get('book_side') != row['book_side']
                    or (row['order_id'] is not None and row['order_id'] != order['order_id'])):
                raise ValueError('Identity mismatch')
            initial = Decimal(str(order['initial_count_fp']))
            filled = Decimal(str(order['fill_count_fp']))
            remaining = Decimal(str(order['remaining_count_fp']))
            yes_price = Decimal(str(order['yes_price_dollars']))
            status = order['status']
            if (not all(x.is_finite() for x in (initial, filled, remaining, yes_price))
                    or initial != Decimal(row['count']) or filled < 0 or remaining < 0
                    or filled + remaining > initial
                    or yes_price != Decimal(row['yes_limit'])
                    or order.get('subaccount_number') != 0
                    or (row['exchange_fill_count'] is not None
                        and filled < Decimal(row['exchange_fill_count']))
                    or status not in {'resting', 'canceled', 'executed'}):
                raise ValueError('Invalid exchange order state')
        except (KeyError, TypeError, ValueError) as exc:
            self.mark_uncertain(client_id, 'observed order conflicts with intent')
            raise LedgerError('Exchange order did not validate') from exc
        self.db.execute("""UPDATE intents SET phase='reconcile', order_id=?,
            exchange_fill_count=?, exchange_remaining=?, exchange_status=?, error=NULL
            WHERE client_id=?""",
            (order['order_id'], str(filled), str(remaining), status, client_id))

    def record_fill(self, client_id: str, fill: dict) -> None:
        row = self._row(client_id)
        if row["phase"] == "prepared" or row["phase"] == "verified_flat":
            raise LedgerError("Unexpected fill lifecycle")
        try:
            if (fill["order_id"] != row["order_id"] or not fill["fill_id"]
                    or fill.get('subaccount_number') != 0):
                raise ValueError("Fill order ID mismatch")
            count = Decimal(str(fill["count_fp"]))
            price = Decimal(str(fill["yes_price_dollars"]))
            fee = Decimal(str(fill["fee_cost"]))
            if (not all(x.is_finite() for x in (count, price, fee)) or count <= 0 or
                    not Decimal(0) < price < Decimal(1) or fee < 0):
                raise ValueError("Invalid fill numbers")
            limit = Decimal(row['yes_limit'])
            if (row['book_side'] == 'bid' and price > limit) or (row['book_side'] == 'ask' and price < limit):
                raise ValueError('Fill violates intended YES-book price limit')
        except (KeyError, TypeError, ValueError) as exc:
            self.mark_uncertain(client_id, "invalid fill")
            raise LedgerError("Malformed fill") from exc
        prior = self.db.execute("SELECT * FROM fills WHERE fill_id=?", (fill['fill_id'],)).fetchone()
        if prior is not None:
            if (prior['client_id'] == client_id and prior['count'] == str(count) and
                    prior['yes_price'] == str(price) and prior['fee'] == str(fee)):
                return
            self.mark_uncertain(client_id, "conflicting fill ID")
            raise LedgerError("Conflicting duplicate fill")
        if self.filled_quantity(client_id) + count > Decimal(row['count']):
            self.mark_uncertain(client_id, "overfill")
            raise LedgerError("Reported fills exceed requested size")
        self.db.execute("INSERT INTO fills VALUES (?, ?, ?, ?, ?, ?)",
                        (fill["fill_id"], client_id, fill["order_id"],
                         str(count), str(price), str(fee)))

    def filled_quantity(self, client_id: str) -> Decimal:
        self._row(client_id)
        records = self.db.execute("SELECT count FROM fills WHERE client_id=?", (client_id,)).fetchall()
        return sum((Decimal(record["count"]) for record in records), Decimal(0))

    def record_verified_flat(self, client_id: str, *, order_terminal: bool,
                             exchange_position_size: Decimal) -> None:
        """Release reservation only after terminal order and a fresh flat venue position.

        This method intentionally cannot infer 'terminal' from an IOC ACK. The
        caller must first verify actual order status and all fills through GETs.
        """
        row = self._row(client_id)
        if (row["phase"] != "reconcile" or not order_terminal
                or row['exchange_status'] not in {'executed', 'canceled'}
                or exchange_position_size != 0):
            raise LedgerError("Cannot release capital from an open or uncertain position")
        if row["exchange_fill_count"] is None or self.filled_quantity(client_id) != Decimal(row["exchange_fill_count"]):
            raise LedgerError("Unreconciled fills; cannot mark flat")
        if row["action"] == "buy" and self.filled_quantity(client_id) != 0:
            raise LedgerError("A filled entry needs a verified owned exit")
        if row["action"] == "sell" and self.filled_quantity(client_id) != Decimal(row["count"]):
            # The last IOC may fill fewer than requested if another verified
            # position change occurs; block rather than infer that it closed.
            raise LedgerError("Partial exit is not a flat position")
        if row["parent_client_id"]:
            parent = self._row(row['parent_client_id'])
            if (parent['phase'] != 'reconcile' or
                    parent['exchange_status'] not in {'executed', 'canceled'} or
                    self.filled_quantity(parent['client_id']) != Decimal(parent['exchange_fill_count'])):
                raise LedgerError('Parent entry order is not terminal and reconciled')
            prior = self.db.execute("""SELECT client_id FROM intents
                WHERE parent_client_id=? AND phase='partial_verified'""",
                (row["parent_client_id"],)).fetchall()
            exited = self.filled_quantity(client_id) + sum(
                (self.filled_quantity(other["client_id"]) for other in prior), Decimal(0))
            if exited != self.filled_quantity(row["parent_client_id"]):
                raise LedgerError("Exit fills do not equal bot-owned inventory")
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute("UPDATE intents SET phase='verified_flat' WHERE client_id=?", (client_id,))
            if row["parent_client_id"]:
                self.db.execute("UPDATE intents SET phase='verified_flat' WHERE client_id=?",
                                (row["parent_client_id"],))
                self.db.execute("""UPDATE intents SET phase='verified_flat'
                    WHERE parent_client_id=? AND phase='partial_verified'""",
                    (row["parent_client_id"],))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def record_partial_exit_terminal(self, client_id: str, *, order_terminal: bool,
                                     verified_position_size: Decimal) -> None:
        row = self._row(client_id)
        if (row['phase'] != 'reconcile' or row['action'] != 'sell' or not order_terminal
                or row['exchange_status'] not in {'executed', 'canceled'}):
            raise LedgerError('Exit must be exchange-terminal before partial-release')
        if row['exchange_fill_count'] is None or self.filled_quantity(client_id) != Decimal(row['exchange_fill_count']):
            raise LedgerError('Incomplete exit fills')
        prior = self.db.execute("""SELECT client_id FROM intents
            WHERE parent_client_id=? AND phase='partial_verified'""",
            (row['parent_client_id'],)).fetchall()
        exited = self.filled_quantity(client_id) + sum(
            (self.filled_quantity(other['client_id']) for other in prior), Decimal(0))
        entry_qty = self.filled_quantity(row['parent_client_id'])
        if (not isinstance(verified_position_size, Decimal) or
                not verified_position_size.is_finite() or
                (verified_position_size <= 0 if row['outcome'] == 'yes' else verified_position_size >= 0)
                or entry_qty - exited != abs(verified_position_size)):
            raise LedgerError('Verified residual inventory disagrees with fills')
        self.db.execute("UPDATE intents SET phase='partial_verified' WHERE client_id=?", (client_id,))

    def snapshot(self, client_id: str) -> dict:
        row = self._row(client_id)
        return {"client_id": row["client_id"], "ticker": row["ticker"],
                "phase": row["phase"], "order_id": row["order_id"],
                "requested_count": row["count"],
                "exchange_fill_count": row["exchange_fill_count"],
                "confirmed_fill_count": str(self.filled_quantity(client_id)),
                "error": row["error"]}
