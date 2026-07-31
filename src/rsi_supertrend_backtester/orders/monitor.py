"""
Order Monitor
-------------
Background asyncio task that connects to the DhanHQ Order Update WebSocket
(wss://api-order-update.dhan.co) and reacts to order events in real time.

No polling. Event-driven only.

State machine per trade:
  ENTRY_PENDING
      └─ order TRADED     → place Target + SL  → ACTIVE
      └─ order EXPIRED    → check SL breach
              ├─ SL touched (day 1 or 2) → auto-cancel → CANCELLED
              ├─ day_attempt == 1        → re-place AMO → ENTRY_PENDING (day 2)
              └─ day_attempt == 2        → SKIPPED

  ACTIVE
      └─ target_order TRADED → cancel sl_order  → CLOSED_WIN
      └─ sl_order TRADED     → cancel target     → CLOSED_LOSS
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, date
from pathlib import Path
from typing import Callable, Any

import websockets

from rsi_supertrend_backtester.orders import dhan_client, trade_store
from rsi_supertrend_backtester.orders.trade_store import TradeStatus
from rsi_supertrend_backtester.data_collection.core.instrument_master import InstrumentMaster

_instrument_master = InstrumentMaster()

logger = logging.getLogger(__name__)

DHAN_ORDER_WSS = "wss://api-order-update.dhan.co"

# Set of Dhan order IDs already used to reconcile trades via polling
_processed_poll_oids: set[str] = set()

# Broadcast callback: set by api.py so the monitor can push events to the UI
_broadcast_fn: Callable[[dict], None] | None = None

def set_broadcast(fn: Callable[[dict], None]) -> None:
    global _broadcast_fn
    _broadcast_fn = fn


def _broadcast(event: dict) -> None:
    if _broadcast_fn:
        try:
            _broadcast_fn(event)
        except Exception as e:
            logger.warning(f"Broadcast error: {e}")


# ── Dhan order status constants (from API docs) ──────────────────────────────
_TRADED   = {"TRADED", "FILLED", "COMPLETE", "PART_TRADED", "PARTIALLY_TRADED", "FULLY_EXECUTED"}
_EXPIRED  = {"EXPIRED"}
_UNFILLED_CLOSED = {"CANCELLED", "EXPIRED"}
_PENDING  = {"PENDING", "TRANSIT", "OPEN", "PARTIALLY_TRADED_AND_CANCELLED"}


def _normalize_order_status(raw_status: Any) -> str:
    status = str(raw_status or "").upper().strip()
    aliases = {
        "PARTIALLY_TRADED": "PART_TRADED",
        "PARTIAL_TRADED": "PART_TRADED",
        "PARTIALLY FILLED": "PART_TRADED",
        "FILLED": "TRADED",
        "COMPLETE": "TRADED",
        "FULLY_EXECUTED": "TRADED",
    }
    return aliases.get(status, status)


def _extract_event_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _build_oco_correlation_id(trade_id: str) -> str:
    """Dhan allows up to 30 chars for correlationId."""
    return trade_id.replace("-", "")[:30]


def _mark_entry_rejected(trade: dict, reason: str | None = None) -> None:
    company = trade["company"]
    trade_id = trade["trade_id"]
    exit_reason = reason or "Entry order rejected by exchange"

    trade_store.update_trade(trade_id, {
        "status": TradeStatus.REJECTED,
        "closed_at": datetime.now().isoformat(),
        "exit_reason": exit_reason,
    })
    trade_store.append_note(trade_id, exit_reason)
    _broadcast({
        "type": "trade_update",
        "trade_id": trade_id,
        "status": TradeStatus.REJECTED,
        "company": company,
        "exit_reason": exit_reason,
    })


def _is_sl_breached(trade: dict) -> bool:
    """
    Check whether today's candle for the company has already touched the
    stoploss price. Uses Dhan API directly for accurate live low price.
    Returns False if data is not available (fail-safe: don't cancel).
    """
    try:
        today_low = dhan_client.get_today_low(trade["security_id"])
        if today_low is not None:
            logger.debug(f"[{trade.get('company')}] SL guard: today_low={today_low} sl={trade['stoploss_price']}")
            return today_low <= trade["stoploss_price"]
        return False
    except Exception as e:
        logger.warning(f"SL breach check failed for {trade.get('company')}: {e}")
        return False


def check_sl_breach_on_tick(security_id: str, ltp: float) -> None:
    """
    Called on every incoming live price tick for a given security.
    Purely event-driven — no polling, no extra API calls.

    For every ENTRY_PENDING trade matching this security_id:
      - If ltp <= stoploss_price → send a cancel request for the pending entry
        order on Dhan, and wait for broker confirmation before marking the trade
        CANCELLED locally.

    This is the correct way to guard against SL breaches before entry:
    react to the existing live price stream rather than polling.
    """
    trades = trade_store.load_all_trades()
    pending = [
        t for t in trades
        if t.get("status") == TradeStatus.ENTRY_PENDING
        and str(t.get("security_id")) == str(security_id)
    ]

    for trade in pending:
        company   = trade.get("company", "?")
        trade_id  = trade["trade_id"]
        sl_price  = trade["stoploss_price"]

        if ltp > sl_price:
            continue

        entry_oid = trade.get("entry_order_id")
        if not entry_oid:
            continue

        _request_entry_cancel_due_to_sl(trade, source="tick", ltp=ltp)


def _request_entry_cancel_due_to_sl(trade: dict, *, source: str, ltp: float | None = None) -> bool:
    """Send a throttled cancel request for a pending entry whose SL is already breached."""
    company = trade.get("company", "?")
    trade_id = trade["trade_id"]
    entry_oid = trade.get("entry_order_id")
    sl_price = trade.get("stoploss_price")
    if not entry_oid:
        return False

    last_sent = trade.get("sl_cancellation_sent_at")
    if last_sent:
        try:
            dt_last = datetime.fromisoformat(last_sent)
            if (datetime.now() - dt_last).total_seconds() < 15:
                return False
        except Exception:
            pass

    context = f"LTP {ltp} <= SL {sl_price}" if ltp is not None else f"SL {sl_price} already breached"
    logger.warning(f"[{company}] SL Guard ({source}): {context}. Sending Dhan cancel for entry {entry_oid}.")

    try:
        resp = dhan_client.cancel_order(entry_oid)
        if resp.get("status") == "failure":
            logger.error(f"[{company}] SL Guard ({source}): API rejected cancellation for {entry_oid}: {resp}")
            trade_store.append_note(trade_id, f"SL guard tried to cancel entry {entry_oid}, but Dhan rejected the request.")
            return False

        trade_store.update_trade(trade_id, {
            "sl_cancellation_sent_at": datetime.now().isoformat(),
        })
        note = (
            f"SL guard sent cancel request to Dhan for entry {entry_oid} after LTP {ltp} touched SL {sl_price}."
            if ltp is not None else
            f"SL guard sent cancel request to Dhan for entry {entry_oid} because SL {sl_price} was already breached."
        )
        trade_store.append_note(trade_id, note)
        logger.info(f"[{company}] SL Guard ({source}): Dhan accepted cancel request for entry {entry_oid}. Awaiting broker confirmation.")
        return True
    except Exception as ce:
        logger.error(f"[{company}] SL Guard ({source}): failed to cancel order {entry_oid}: {ce}")
        return False


def _mark_day2_retry_requested(trade_id: str, entry_order_id: str) -> bool:
    """Set a dedupe marker so Day 2 AMO placement only happens once per Day 1 order."""
    fresh_trade = trade_store.get_trade(trade_id)
    if not fresh_trade:
        return False
    if fresh_trade.get("status") != TradeStatus.ENTRY_PENDING:
        return False
    if int(fresh_trade.get("day_attempt") or 1) != 1:
        return False
    if str(fresh_trade.get("entry_order_id") or "") != str(entry_order_id):
        return False
    if str(fresh_trade.get("day2_retry_for_entry_order_id") or "") == str(entry_order_id):
        return False

    trade_store.update_trade(trade_id, {
        "day2_retry_for_entry_order_id": str(entry_order_id),
        "day2_retry_requested_at": datetime.now().isoformat(),
        "day2_retry_due_at": None,
    })
    return True


async def _handle_entry_expired(trade: dict) -> None:
    """Called when the AMO entry order expired or was cancelled without fill."""
    trade_id = trade["trade_id"]
    fresh_trade = trade_store.get_trade(trade_id) or trade
    company = fresh_trade["company"]
    day_attempt = int(fresh_trade.get("day_attempt", 1) or 1)
    current_status = fresh_trade.get("status")
    current_entry_order_id = str(fresh_trade.get("entry_order_id") or "")

    if current_status != TradeStatus.ENTRY_PENDING:
        logger.info(f"[{company}] Ignoring entry-expired handler because trade is already {current_status}.")
        return

    sl_breached = _is_sl_breached(fresh_trade)

    if sl_breached:
        # Auto-cancel scenario: SL price touched before entry
        logger.info(f"[{company}] SL breached before entry (Day {day_attempt}). Auto-cancelling.")
        trade_store.update_trade(trade_id, {
            "status":      TradeStatus.CANCELLED,
            "closed_at":   datetime.now().isoformat(),
            "exit_reason": f"SL breached before entry on Day {day_attempt}",
        })
        trade_store.append_note(trade_id, f"SL price {fresh_trade['stoploss_price']} touched on Day {day_attempt}. Trade auto-cancelled.")
        _broadcast({"type": "trade_update", "trade_id": trade_id, "status": TradeStatus.CANCELLED, "company": company})
        return

    if day_attempt >= 2:
        # 2-day window exhausted
        logger.info(f"[{company}] Day 2 expired unfilled. Marking SKIPPED.")
        trade_store.update_trade(trade_id, {
            "status":      TradeStatus.SKIPPED,
            "closed_at":   datetime.now().isoformat(),
            "exit_reason": "2-day window exhausted, no fill",
        })
        trade_store.append_note(trade_id, "AMO order expired on Day 2. Trade skipped.")
        _broadcast({"type": "trade_update", "trade_id": trade_id, "status": TradeStatus.SKIPPED, "company": company})
        return

    # Day 1 clean — automatically re-place AMO for Day 2
    if not current_entry_order_id:
        logger.warning(f"[{company}] Cannot re-place Day 2 AMO because Day 1 entry_order_id is missing.")
        return
    if not _mark_day2_retry_requested(trade_id, current_entry_order_id):
        logger.info(f"[{company}] Day 2 AMO retry already requested for entry order {current_entry_order_id}. Skipping duplicate.")
        return

    logger.info(f"[{company}] Day 1 expired unfilled (SL not hit). Re-placing AMO for Day 2.")
    
    from datetime import time as dt_time
    now = datetime.now().time()
    
    if dt_time(15, 30) <= now < dt_time(15, 46):
        target = datetime.now().replace(hour=15, minute=46, second=0, microsecond=0)
        sleep_seconds = (target - datetime.now()).total_seconds()
        logger.info(f"[{company}] Waiting {sleep_seconds:.0f}s for Dhan AMO window to open at 15:45...")
        trade_store.update_trade(trade_id, {"day2_retry_due_at": target.isoformat()})
        
        async def delayed_place():
            await asyncio.sleep(sleep_seconds)
            _place_day2_amo(trade_id, expected_prev_order_id=current_entry_order_id)
            
        asyncio.create_task(delayed_place())
        trade_store.append_note(trade_id, f"Queued Day 2 AMO placement for order {current_entry_order_id} when Dhan AMO window opens.")
    else:
        _place_day2_amo(trade_id, expected_prev_order_id=current_entry_order_id)


def _place_day2_amo(trade_id: str, expected_prev_order_id: str | None = None) -> None:
    fresh_trade = trade_store.get_trade(trade_id)
    if not fresh_trade:
        return

    company = fresh_trade["company"]
    current_status = fresh_trade.get("status")
    current_entry_order_id = str(fresh_trade.get("entry_order_id") or "")
    day_attempt = int(fresh_trade.get("day_attempt", 1) or 1)

    if current_status != TradeStatus.ENTRY_PENDING:
        logger.info(f"[{company}] Skipping Day 2 AMO placement because trade is now {current_status}.")
        return
    if day_attempt != 1:
        logger.info(f"[{company}] Skipping Day 2 AMO placement because trade is already on day_attempt={day_attempt}.")
        return
    if expected_prev_order_id and current_entry_order_id != str(expected_prev_order_id):
        logger.info(
            f"[{company}] Skipping Day 2 AMO placement because entry order changed from "
            f"{expected_prev_order_id} to {current_entry_order_id}."
        )
        return
    if str(fresh_trade.get("day2_retry_for_entry_order_id") or "") != current_entry_order_id:
        logger.info(f"[{company}] Skipping Day 2 AMO placement because retry marker no longer matches entry order {current_entry_order_id}.")
        return

    try:
        tick_size = _instrument_master.get_tick_size(fresh_trade["security_id"])
        resp = dhan_client.place_amo_sl_entry(
            security_id=fresh_trade["security_id"],
            quantity=fresh_trade["quantity"],
            entry_price=fresh_trade["entry_price"],
            tick_size=tick_size,
        )
        new_order_id = dhan_client.extract_order_id(resp)
        if not new_order_id:
            raise ValueError(f"No order ID in response: {resp}")

        trade_store.update_trade(trade_id, {
            "entry_order_id": new_order_id,
            "day_attempt":    2,
            "sl_cancellation_sent_at": None,
            "day2_retry_for_entry_order_id": None,
            "day2_retry_requested_at": None,
            "day2_retry_due_at": None,
        })
        trade_store.append_note(trade_id, f"AMO re-placed for Day 2. New order_id={new_order_id}")
        _broadcast({
            "type":      "trade_update",
            "trade_id":  trade_id,
            "status":    TradeStatus.ENTRY_PENDING,
            "company":   company,
            "note":      "AMO re-placed for Day 2",
        })
    except Exception as e:
        logger.error(f"[{company}] Failed to re-place AMO for Day 2: {e}")
        trade_store.update_trade(trade_id, {
            "status":      TradeStatus.ERROR,
            "exit_reason": f"Failed to re-place Day 2 AMO: {e}",
            "day2_retry_for_entry_order_id": None,
            "day2_retry_requested_at": None,
            "day2_retry_due_at": None,
        })
        trade_store.append_note(trade_id, f"ERROR re-placing Day 2 AMO: {e}")
        _broadcast({"type": "trade_update", "trade_id": trade_id, "status": TradeStatus.ERROR, "company": company})


def _run_due_day2_retries(trades: list[dict[str, Any]]) -> None:
    """Recover queued Day 2 AMO retries after reconnects/restarts."""
    now = datetime.now()
    for trade in trades:
        if trade.get("status") != TradeStatus.ENTRY_PENDING:
            continue
        if int(trade.get("day_attempt") or 1) != 1:
            continue
        marker = str(trade.get("day2_retry_for_entry_order_id") or "")
        if not marker:
            continue
        due_at_raw = trade.get("day2_retry_due_at")
        if not due_at_raw:
            continue
        try:
            due_at = datetime.fromisoformat(str(due_at_raw))
        except Exception:
            due_at = now
        if due_at <= now:
            _place_day2_amo(trade["trade_id"], expected_prev_order_id=marker)


async def _handle_entry_filled(trade: dict, fill_price: float | None, traded_qty: int | None, order_status: str) -> None:
    """Entry order confirmed TRADED or PARTIALLY_TRADED. Place or modify Target + SL orders."""
    company  = trade["company"]
    trade_id = trade["trade_id"]

    full_quantity = int(trade["quantity"])
    qty_to_use = int(traded_qty) if traded_qty is not None else full_quantity
    qty_to_use = max(0, min(qty_to_use, full_quantity))

    # Fetch exact tick size for this security to prevent EXCH:16316 rejections
    tick_size = _instrument_master.get_tick_size(trade["security_id"])

    # ── IMPORTANT: always re-read fresh trade state from the store to avoid
    # stale-snapshot bugs (the dict passed in may have been read before a prior
    # partial update changed the status to ENTRY_FILLED or ACTIVE).
    fresh_trade = trade_store.get_trade(trade_id) or trade
    current_status = fresh_trade.get("status", "")
    current_oco_qty = int(fresh_trade.get("oco_quantity") or 0)
    oco_order_id = (
        fresh_trade.get("target_order_id")
        or fresh_trade.get("sl_order_id")
    )
    oco_correlation_id = fresh_trade.get("oco_correlation_id") or _build_oco_correlation_id(trade_id)

    if qty_to_use <= 0:
        logger.warning(f"[{company}] Entry fill event received with no traded quantity. Skipping OCO handling.")
        return

    if current_status == TradeStatus.ACTIVE and oco_order_id and qty_to_use <= current_oco_qty:
        logger.info(f"[{company}] Duplicate/older entry fill event ignored. filled_qty={qty_to_use}, oco_qty={current_oco_qty}.")
        return

    logger.info(f"[{company}] Entry fill event received. cumulative_filled_qty={qty_to_use}.")
    trade_store.update_trade(trade_id, {
        "status":   TradeStatus.ENTRY_FILLED,
        "filled_at": datetime.now().isoformat(),
        "filled_quantity": qty_to_use,
        "exit_price": fill_price,   # temporary, cleared after target/sl
    })
    _broadcast({"type": "trade_update", "trade_id": trade_id, "status": TradeStatus.ENTRY_FILLED, "company": company})

    errors = []

    if oco_order_id:
        try:
            dhan_client.modify_forever_oco(
                order_id=oco_order_id,
                quantity=qty_to_use,
                target_price=trade["target_price"],
                stoploss_price=trade["stoploss_price"],
                tick_size=tick_size,
            )
            logger.info(f"[{company}] Forever OCO order modified to qty={qty_to_use}: {oco_order_id}")
        except Exception as e:
            logger.error(f"[{company}] Failed to modify Forever OCO order: {e}")
            errors.append(f"OCO modify failed: {e}")
    else:
        try:
            trade_store.update_trade(trade_id, {"oco_correlation_id": oco_correlation_id})
            resp = dhan_client.place_oco_forever_order(
                security_id=trade["security_id"],
                quantity=qty_to_use,
                target_price=trade["target_price"],
                stoploss_price=trade["stoploss_price"],
                tick_size=tick_size,
                tag=oco_correlation_id,
            )
            oco_order_id = dhan_client.extract_order_id(resp)
            if not oco_order_id and oco_correlation_id:
                lookup = dhan_client.get_order_by_correlation_id(oco_correlation_id)
                oco_order_id = dhan_client.extract_order_id(lookup)
            if not oco_order_id:
                raise ValueError(f"No order ID in Forever OCO response: {resp}")
            logger.info(f"[{company}] Forever OCO order placed: {oco_order_id}")
        except Exception as e:
            logger.error(f"[{company}] Failed to place Forever OCO order: {e}")
            errors.append(f"OCO order failed: {e}")

    protected_qty = qty_to_use if oco_order_id else current_oco_qty
    next_status = TradeStatus.ACTIVE if oco_order_id else TradeStatus.ENTRY_FILLED
    updates: dict = {
        "status":          next_status,
        "target_order_id": oco_order_id,
        "sl_order_id":     oco_order_id,
        "oco_quantity":    protected_qty,
        "filled_quantity": max(int(fresh_trade.get("filled_quantity") or 0), qty_to_use),
        "oco_correlation_id": oco_correlation_id,
        "exit_price":      None,
    }
    if errors:
        for err in errors:
            trade_store.append_note(trade_id, f"WARNING: {err}")

    trade_store.update_trade(trade_id, updates)
    _broadcast({
        "type":             "trade_update",
        "trade_id":         trade_id,
        "status":           next_status,
        "company":          company,
        "target_order_id":  oco_order_id,
        "sl_order_id":      oco_order_id,
    })


async def _handle_target_filled(trade: dict, fill_price: float | None) -> None:
    """Target order TRADED. Cancel SL, mark CLOSED_WIN."""
    company  = trade["company"]
    trade_id = trade["trade_id"]
    logger.info(f"[{company}] Target hit! Cancelling SL order.")

    if trade.get("sl_order_id"):
        try:
            dhan_client.cancel_forever_order(trade["sl_order_id"])
            logger.info(f"[{company}] Forever SL leg cancelled after target hit.")
        except Exception as e:
            logger.warning(f"[{company}] Could not cancel SL order: {e}")
            trade_store.append_note(trade_id, f"Warning: SL cancel failed: {e}")

    trade_store.update_trade(trade_id, {
        "status":      TradeStatus.CLOSED_WIN,
        "closed_at":   datetime.now().isoformat(),
        "exit_price":  fill_price or trade["target_price"],
        "exit_reason": "Target Hit",
    })
    trade_store.append_note(trade_id, f"Target hit at {fill_price}. Trade closed WIN.")
    _broadcast({"type": "trade_update", "trade_id": trade_id, "status": TradeStatus.CLOSED_WIN, "company": company})


async def _handle_sl_filled(trade: dict, fill_price: float | None) -> None:
    """SL order TRADED. Cancel Target, mark CLOSED_LOSS."""
    company  = trade["company"]
    trade_id = trade["trade_id"]
    logger.info(f"[{company}] SL hit! Cancelling Target order.")

    if trade.get("target_order_id"):
        try:
            dhan_client.cancel_forever_order(trade["target_order_id"])
            logger.info(f"[{company}] Forever target leg cancelled after SL hit.")
        except Exception as e:
            logger.warning(f"[{company}] Could not cancel Target order: {e}")
            trade_store.append_note(trade_id, f"Warning: Target cancel failed: {e}")

    trade_store.update_trade(trade_id, {
        "status":      TradeStatus.CLOSED_LOSS,
        "closed_at":   datetime.now().isoformat(),
        "exit_price":  fill_price or trade["stoploss_price"],
        "exit_reason": "Stoploss Hit",
    })
    trade_store.append_note(trade_id, f"SL hit at {fill_price}. Trade closed LOSS.")
    _broadcast({"type": "trade_update", "trade_id": trade_id, "status": TradeStatus.CLOSED_LOSS, "company": company})


async def _process_order_event(event: dict) -> None:
    """Route a single Dhan order event to the correct handler."""
    payload = event.get("Data") if isinstance(event.get("Data"), dict) else event

    order_id = str(_extract_event_value(payload, "OrderNo", "orderId", "order_id") or "")
    order_status = _normalize_order_status(_extract_event_value(payload, "Status", "orderStatus", "status"))
    fill_price_raw = _extract_event_value(payload, "TradedPrice", "tradedPrice", "averageTradedPrice")
    fill_price: float | None = float(fill_price_raw) if fill_price_raw else None

    if not order_id:
        return

    trade = trade_store.get_trade_by_order_id(order_id)
    if trade is None:
        # Check if it's a child order from a Forever OCO order.
        corr_id = str(_extract_event_value(payload, "CorrelationId", "correlationId") or "")
        if corr_id:
            for t in trade_store.load_active_trades():
                expected_corr_id = t.get("oco_correlation_id") or _build_oco_correlation_id(t["trade_id"])
                if corr_id == expected_corr_id or t["trade_id"][:8] in corr_id:
                    trade = t
                    break
        if trade is None:
            return  # Not our order

    trade_id = trade["trade_id"]
    company  = trade["company"]
    status   = trade.get("status", "")

    logger.debug(f"[{company}] Order event: order={order_id} status={order_status} trade_status={status}")

    traded_qty_raw = _extract_event_value(payload, "TradedQty", "tradedQuantity", "tradedQty", "filledQty")
    traded_qty: int | None = int(traded_qty_raw) if traded_qty_raw else None

    # ── Entry order events ───────────────────────────────────────────────────
    if order_id == trade.get("entry_order_id"):
        if order_status in _TRADED and status in (TradeStatus.ENTRY_PENDING, TradeStatus.ENTRY_FILLED, TradeStatus.ACTIVE):
            await _handle_entry_filled(trade, fill_price, traded_qty, order_status)
        elif order_status == "REJECTED" and status == TradeStatus.ENTRY_PENDING:
            logger.warning(f"[{company}] Entry order REJECTED by exchange. Marking trade as REJECTED.")
            reject_reason = _extract_event_value(
                payload,
                "OmsErrorDescription",
                "omsErrorDescription",
                "Remarks",
                "remarks",
                "ErrorMessage",
                "errorMessage",
            )
            _mark_entry_rejected(trade, str(reject_reason).strip() if reject_reason else None)
        elif order_status in _UNFILLED_CLOSED and status == TradeStatus.ENTRY_PENDING:
            await _handle_entry_expired(trade)

    # ── Target / SL order events (OCO Child Orders) ──────────────────────────
    # Since we use Forever OCO orders, target_order_id and sl_order_id store the Forever Order ID.
    # The actual order executed will have a NEW order_id, but it matches the trade via correlationId.
    elif status == TradeStatus.ACTIVE and order_status in _TRADED:
        leg_no = _extract_event_value(payload, "LegNo", "legNo")
        if str(leg_no) == "3":
            logger.info(f"[{company}] Child order {order_id} identified as Target via LegNo=3")
            await _handle_target_filled(trade, fill_price)
        elif str(leg_no) == "2":
            logger.info(f"[{company}] Child order {order_id} identified as SL via LegNo=2")
            await _handle_sl_filled(trade, fill_price)
        elif fill_price is not None:
            dist_to_target = abs(fill_price - trade["target_price"])
            dist_to_sl = abs(fill_price - trade["stoploss_price"])

            if dist_to_target < dist_to_sl:
                logger.info(f"[{company}] Child order {order_id} identified as Target by price match (fill={fill_price})")
                await _handle_target_filled(trade, fill_price)
            else:
                logger.info(f"[{company}] Child order {order_id} identified as SL by price match (fill={fill_price})")
                await _handle_sl_filled(trade, fill_price)


# ── REST Polling Fallback ────────────────────────────────────────────────────

async def _poll_pending_trades() -> None:
    """
    Fallback polling loop: every 10s, check all ENTRY_PENDING and ENTRY_FILLED
    trades against the Dhan REST order list. This catches fill events that the
    Order Update WebSocket may have missed during disconnects.
    """
    logger.info("Order poll loop started (10s interval fallback).")
    while True:
        try:
            await asyncio.sleep(10)
            # load_active_trades() returns ENTRY_PENDING + ACTIVE.
            # We also need ENTRY_FILLED (transitional — placed but Target/SL not yet set).
            all_trades = trade_store.load_all_trades()
            _run_due_day2_retries(all_trades)
            pending = [
                t for t in all_trades
                if t.get("status") in (
                    TradeStatus.ENTRY_PENDING,
                    TradeStatus.ENTRY_FILLED,
                    TradeStatus.ACTIVE,
                )
            ]
            if not pending:
                continue

            try:
                resp = dhan_client.get_order_list()
            except Exception as e:
                logger.warning(f"Poll: failed to fetch Dhan order list: {e}")
                continue

            if resp.get("status") != "success":
                continue

            # Build order_id → {status, tradedPrice, tradedQty, ...} map
            dhan_map: dict[str, dict] = {}
            for o in (resp.get("data") or []):
                oid = str(o.get("orderId") or o.get("order_id") or "")
                if oid:
                    dhan_map[oid] = o

            for trade in pending:
                status = trade.get("status")
                company = trade.get("company", "?")
                trade_id = trade["trade_id"]

                if status in (TradeStatus.ENTRY_PENDING, TradeStatus.ENTRY_FILLED):
                    eid = trade.get("entry_order_id")
                    if not eid or eid not in dhan_map:
                        continue
                    dhan_order = dhan_map[eid]
                    dhan_status = _normalize_order_status(dhan_order.get("orderStatus") or dhan_order.get("order_status"))

                    if dhan_status in _TRADED:
                        logger.info(f"[Poll] [{company}] Entry order {eid} is {dhan_status} on Dhan. trade status={status}. Placing Target+SL now.")
                        fill_price_raw = dhan_order.get("tradedPrice") or dhan_order.get("averageTradedPrice")
                        fill_price = float(fill_price_raw) if fill_price_raw else None
                        traded_qty_raw = (
                            dhan_order.get("tradedQuantity")
                            or dhan_order.get("tradedQty")
                            or dhan_order.get("filledQty")
                            or dhan_order.get("TradedQty")
                        )
                        traded_qty = int(traded_qty_raw) if traded_qty_raw else None
                        await _handle_entry_filled(trade, fill_price, traded_qty, dhan_status)

                    elif dhan_status == "REJECTED":
                        reject_reason = (
                            dhan_order.get("omsErrorDescription")
                            or dhan_order.get("remarks")
                            or dhan_order.get("errorMessage")
                        )
                        logger.info(f"[Poll] [{company}] Entry order {eid} is REJECTED on Dhan. Preserving broker reject locally.")
                        _mark_entry_rejected(trade, str(reject_reason).strip() if reject_reason else None)

                    elif dhan_status in _UNFILLED_CLOSED:
                        logger.info(f"[Poll] [{company}] Entry order {eid} is {dhan_status} (unfilled order closed). Handling cancellation.")
                        await _handle_entry_expired(trade)

                    elif status == TradeStatus.ENTRY_PENDING and _is_sl_breached(trade):
                        logger.info(f"[Poll] [{company}] Entry order {eid} is still {dhan_status or 'PENDING'} on Dhan but SL is breached. Sending/refreshing cancel request.")
                        _request_entry_cancel_due_to_sl(trade, source="poll")

                elif status == TradeStatus.ACTIVE:
                    eid = trade.get("entry_order_id")
                    if eid and eid in dhan_map:
                        dhan_order = dhan_map[eid]
                        traded_qty_raw = (
                            dhan_order.get("tradedQuantity")
                            or dhan_order.get("tradedQty")
                            or dhan_order.get("filledQty")
                            or dhan_order.get("TradedQty")
                        )
                        traded_qty = int(traded_qty_raw) if traded_qty_raw else None
                        if traded_qty and traded_qty > int(trade.get("oco_quantity") or 0):
                            logger.info(
                                f"[Poll] [{company}] Entry fill increased to {traded_qty} while OCO protects "
                                f"{trade.get('oco_quantity') or 0}. Resyncing Forever OCO."
                            )
                            fill_price_raw = dhan_order.get("tradedPrice") or dhan_order.get("averageTradedPrice")
                            fill_price = float(fill_price_raw) if fill_price_raw else None
                            await _handle_entry_filled(trade, fill_price, traded_qty, "TRADED")

                    # Dhan's Forever OCO triggers create child limit orders without correlationId.
                    # We match by tradingSymbol and transactionType == SELL
                    for oid, o in dhan_map.items():
                        if oid in _processed_poll_oids:
                            continue
                        if o.get("tradingSymbol") == trade.get("security_id") or o.get("tradingSymbol") == company:
                            if o.get("transactionType") == "SELL" and _normalize_order_status(o.get("orderStatus") or o.get("order_status")) in _TRADED:
                                _processed_poll_oids.add(oid)
                                fill_price = float(o.get("tradedPrice") or o.get("averageTradedPrice") or 0.0)
                                if fill_price > 0:
                                    logger.info(f"[Poll] [{company}] Found TRADED SELL order {oid} for ACTIVE trade. Closing trade.")
                                    entry = float(trade.get("entry_price", 0.0))
                                    if fill_price >= entry:
                                        new_status = TradeStatus.CLOSED_WIN
                                        reason = f"Target hit (Poll fallback) @ {fill_price}"
                                    else:
                                        new_status = TradeStatus.CLOSED_LOSS
                                        reason = f"SL hit (Poll fallback) @ {fill_price}"
                                    
                                    trade_store.update_trade(trade_id, {
                                        "status": new_status,
                                        "exit_price": fill_price,
                                        "closed_at": datetime.now().isoformat(),
                                        "exit_reason": reason,
                                    })
                                    trade_store.append_note(trade_id, f"Poll matched child order {oid} → {new_status}")
                                    _broadcast({
                                        "type": "trade_update",
                                        "trade_id": trade_id,
                                        "status": new_status,
                                        "exit_price": fill_price,
                                        "company": company,
                                        "exit_reason": reason,
                                    })
                                    break

        except asyncio.CancelledError:
            logger.info("Poll loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Poll loop error: {e}", exc_info=True)


_poll_task: asyncio.Task | None = None
_monitor_task: asyncio.Task | None = None


async def _monitor_loop() -> None:
    """
    WebSocket loop that connects to DhanHQ Order Update stream.

    Dhan auth flow (from official docs):
      1. Connect to wss://api-order-update.dhan.co  (plain URL, no params)
      2. Send a JSON LoginReq message immediately after connection:
         { "LoginReq": { "MsgCode": 42, "ClientId": "...", "Token": "..." }, "UserType": "SELF" }
      3. Then receive order-event JSON messages on the same connection.
    """
    access_token = dhan_client.DHAN_ACCESS_TOKEN
    client_id = dhan_client.DHAN_CLIENT_ID

    if not access_token or not client_id:
        logger.error("Dhan credentials missing. Order monitor cannot start.")
        return

    auth_payload = json.dumps({
        "LoginReq": {
            "MsgCode": 42,
            "ClientId": client_id,
            "Token": access_token,
        },
        "UserType": "SELF",
    })

    logger.info("Connecting to Dhan Order Update WebSocket...")
    while True:
        try:
            async with websockets.connect(
                DHAN_ORDER_WSS,
                ping_interval=30,
                ping_timeout=10,
                open_timeout=15,
            ) as ws:
                # Step 2: send auth immediately after connect
                await ws.send(auth_payload)
                logger.info("Dhan Order WS: auth sent, waiting for order events...")

                async for message in ws:
                    try:
                        if isinstance(message, bytes):
                            message = message.decode("utf-8", errors="replace")
                        event = json.loads(message)
                        logger.debug(f"Dhan Order WS event: {event}")
                        await _process_order_event(event)
                    except json.JSONDecodeError:
                        logger.warning(f"Dhan Order WS: non-JSON message: {message!r}")
                    except Exception as e:
                        logger.error(f"Dhan Order WS: error processing event: {e}", exc_info=True)
        except asyncio.CancelledError:
            logger.info("Order monitor loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Dhan Order WS: connection error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)


def ensure_monitor_running() -> None:
    """
    Start the order monitor WebSocket task and the REST polling fallback
    if not already running.
    """
    global _monitor_task, _poll_task
    try:
        loop = asyncio.get_event_loop()
        if _monitor_task is None or _monitor_task.done():
            _monitor_task = loop.create_task(_monitor_loop())
            logger.info("Order monitor (WebSocket) task created.")
        if _poll_task is None or _poll_task.done():
            _poll_task = loop.create_task(_poll_pending_trades())
            logger.info("Order monitor (REST poll fallback) task created.")
    except RuntimeError:
        pass


def stop_monitor() -> None:
    global _monitor_task, _poll_task
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        _monitor_task = None
    if _poll_task and not _poll_task.done():
        _poll_task.cancel()
        _poll_task = None
