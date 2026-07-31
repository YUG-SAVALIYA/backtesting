"""
Trade Store
-----------
JSON-backed persistence for live trade state.
All active and historical trades are stored in live_trades.json.

Status flow:
  ENTRY_PENDING  → AMO SL entry order placed, waiting for fill
  ENTRY_FILLED   → Entry confirmed (transitional, immediately → ACTIVE)
  ACTIVE         → Target + SL orders live on exchange
  CLOSED_WIN     → Target hit, SL cancelled
  CLOSED_LOSS    → SL hit, Target cancelled
  SKIPPED        → 2-day window exhausted, no fill
  CANCELLED      → SL price touched before entry; AMO auto-cancelled
  REJECTED       → Entry rejected by exchange/broker
  ERROR          → Unexpected failure (retryable)
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

_STORE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "live_trades.json"
_lock = threading.Lock()


# ── Status constants ─────────────────────────────────────────────────────────
class TradeStatus:
    ENTRY_PENDING = "ENTRY_PENDING"
    ENTRY_FILLED  = "ENTRY_FILLED"
    ACTIVE        = "ACTIVE"
    CLOSED_WIN    = "CLOSED_WIN"
    CLOSED_LOSS   = "CLOSED_LOSS"
    SKIPPED       = "SKIPPED"
    CANCELLED     = "CANCELLED"
    REJECTED      = "REJECTED"
    ERROR         = "ERROR"


def _load_raw() -> list[dict]:
    if not _STORE_PATH.exists():
        return []
    try:
        with open(_STORE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _save_raw(trades: list[dict]) -> None:
    with open(_STORE_PATH, "w") as f:
        json.dump(trades, f, indent=2, default=str)


# ── Public API ───────────────────────────────────────────────────────────────

def create_trade(
    company: str,
    security_id: str,
    quantity: int,
    entry_price: float,
    target_price: float,
    stoploss_price: float,
    signal_date: str,
    entry_order_id: str,
) -> dict[str, Any]:
    """Create and persist a new trade in ENTRY_PENDING state."""
    trade: dict[str, Any] = {
        "trade_id":       str(uuid.uuid4()),
        "company":        company,
        "security_id":    security_id,
        "quantity":       quantity,
        "entry_price":    entry_price,
        "target_price":   target_price,
        "stoploss_price": stoploss_price,
        "signal_date":    signal_date,
        "status":         TradeStatus.ENTRY_PENDING,
        "day_attempt":    1,
        "entry_order_id": entry_order_id,
        "target_order_id": None,
        "sl_order_id":     None,
        "oco_correlation_id": None,
        "placed_at":      datetime.now().isoformat(),
        "filled_at":      None,
        "filled_quantity": 0,
        "oco_quantity":   0,
        "closed_at":      None,
        "exit_price":     None,
        "exit_reason":    None,
        "notes":          [],
    }
    with _lock:
        trades = _load_raw()
        trades.append(trade)
        _save_raw(trades)
    return trade


def load_all_trades() -> list[dict[str, Any]]:
    """Return all trades (active + historical)."""
    with _lock:
        return _load_raw()


def load_active_trades() -> list[dict[str, Any]]:
    """Return only trades that need monitoring (ENTRY_PENDING or ACTIVE)."""
    active_statuses = {TradeStatus.ENTRY_PENDING, TradeStatus.ACTIVE}
    return [t for t in load_all_trades() if t.get("status") in active_statuses]


def get_trade(trade_id: str) -> dict[str, Any] | None:
    for t in load_all_trades():
        if t["trade_id"] == trade_id:
            return t
    return None


def get_trade_by_order_id(order_id: str) -> dict[str, Any] | None:
    """Find a trade by any of its order IDs (entry, target, or SL)."""
    for t in load_all_trades():
        if order_id in (
            t.get("entry_order_id"),
            t.get("target_order_id"),
            t.get("sl_order_id"),
        ):
            return t
    return None


def update_trade(trade_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Apply a dict of field updates to a trade and persist."""
    with _lock:
        trades = _load_raw()
        for trade in trades:
            if trade["trade_id"] == trade_id:
                trade.update(updates)
                _save_raw(trades)
                return trade
    return None


def append_note(trade_id: str, note: str) -> None:
    """Append a timestamped note to a trade's notes list."""
    with _lock:
        trades = _load_raw()
        for trade in trades:
            if trade["trade_id"] == trade_id:
                trade.setdefault("notes", []).append(
                    f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {note}"
                )
                _save_raw(trades)
                return


def delete_trade(trade_id: str) -> bool:
    """Hard-delete a trade record (use only for manual cleanup)."""
    with _lock:
        trades = _load_raw()
        before = len(trades)
        trades = [t for t in trades if t["trade_id"] != trade_id]
        _save_raw(trades)
        return len(trades) < before
