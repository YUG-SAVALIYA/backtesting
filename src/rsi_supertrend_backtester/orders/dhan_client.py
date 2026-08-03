"""
DhanHQ Order Client
-------------------
Thin wrapper around the dhanhq SDK for placing, cancelling, and querying
CNC equity orders used by the live trade monitor.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta, time as dtime
from pathlib import Path
from typing import Any

from dhanhq import dhanhq, DhanContext
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ── Load credentials ────────────────────────────────────────────────────────
_BASE = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(_BASE / ".env")

DHAN_CLIENT_ID    = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")


def _client() -> dhanhq:
    """Return a fresh dhanhq SDK client (stateless, one per call)."""
    return dhanhq(DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN))


# ── NSE tick size constants & helpers ───────────────────────────────────────

# Standard tick size for NSE equities (exchange-mandated minimum price movement)
NSE_TICK = 0.05


def round_to_tick(price: float, tick: float = NSE_TICK) -> float:
    """Round price to the nearest valid tick size multiple.
    NSE equity tick size varies per stock — always use the value from the
    instrument master (TICK_SIZE column) rather than assuming 0.05.
    """
    return round(round(price / tick) * tick, 2)


# ── Order placement helpers ──────────────────────────────────────────────────

def place_amo_sl_entry(
    security_id: str,
    quantity: int,
    entry_price: float,
    tick_size: float = NSE_TICK,
) -> dict[str, Any]:
    """
    Place an AMO Stop-Loss Limit BUY order on Dhan.

    For a BUY SL-Limit breakout order:
      Trigger Price = entry_price rounded to nearest tick
                      (order activates when market price REACHES this level)
      Limit  Price  = trigger_price + 1 tick
                      (ensures fill just above trigger; avoids missing the breakout)
    Product       = CNC (delivery)
    Validity      = DAY
    after_market_order = True

    Returns the full Dhan API response dict.
    """
    dhan = _client()
    trigger_price = round_to_tick(entry_price, tick_size)                    # activates at entry price
    limit_price   = round_to_tick(trigger_price + tick_size, tick_size)      # fills just above trigger

    # Sanity check: for a BUY SL-Limit, limit_price MUST be >= trigger_price.
    # If limit_price < trigger_price, Dhan treats it as a plain LIMIT order and fills immediately.
    if limit_price < trigger_price:
        logger.error(
            f"AMO SL entry: limit_price ({limit_price}) < trigger_price ({trigger_price}). "
            f"Correcting to trigger_price + tick ({tick_size})."
        )
        limit_price = round_to_tick(trigger_price + tick_size, tick_size)

    logger.info(
        f"Placing AMO SL-LMT BUY — sec={security_id} qty={quantity} "
        f"entry_input={entry_price} trigger={trigger_price} limit={limit_price} tick={tick_size}"
    )
    response = dhan.place_order(
        transaction_type=dhan.BUY,
        exchange_segment=dhan.NSE,
        product_type=dhan.CNC,
        order_type=dhan.SL,
        validity=dhan.DAY,
        security_id=security_id,
        quantity=quantity,
        price=limit_price,
        trigger_price=trigger_price,
        after_market_order=True,
        amo_time="OPEN",
    )
    logger.info(f"AMO SL-LMT BUY response → {response}")
    return response


def is_market_open() -> bool:
    """Return True if current IST time is within NSE trading hours (9:15–15:30)."""
    ist = timezone(timedelta(hours=5, minutes=30))
    now_time = datetime.now(ist).time()
    return dtime(9, 15) <= now_time <= dtime(15, 30)


def place_entry_smart(
    security_id: str,
    quantity: int,
    entry_price: float,
    tick_size: float = NSE_TICK,
) -> tuple[dict[str, Any], str]:
    """
    Smart order placement: auto-detects market hours and places:
    - During market hours (9:15–15:30 IST): Regular SL-Limit BUY order (after_market_order=False)
    - Outside market hours: AMO SL-Limit BUY order (after_market_order=True, amo_time="OPEN")

    For a BUY SL-Limit breakout order:
      Trigger Price = entry_price  (order ACTIVATES when market price reaches this level)
      Limit  Price  = trigger_price + 1 tick (ensures fill just above breakout; never below trigger)

    tick_size: actual tick size for this security from the instrument master.
    Returns: (response_dict, order_type_label)
    """
    ist = timezone(timedelta(hours=5, minutes=30))
    now_time = datetime.now(ist).time()
    market_open = dtime(9, 15) <= now_time <= dtime(15, 30)

    dhan = _client()
    # Trigger = entry snapped to tick; Limit = trigger + 1 tick (fills just above breakout)
    trigger_price = round_to_tick(entry_price, tick_size)
    limit_price   = round_to_tick(trigger_price + tick_size, tick_size)

    # Sanity check: for a BUY SL-Limit, limit_price MUST be >= trigger_price.
    # If limit_price < trigger_price, Dhan treats it as a plain LIMIT and fills immediately.
    if limit_price < trigger_price:
        logger.error(
            f"Smart entry: limit_price ({limit_price}) < trigger_price ({trigger_price}). "
            f"Correcting to trigger_price + tick ({tick_size})."
        )
        limit_price = round_to_tick(trigger_price + tick_size, tick_size)

    logger.info(
        f"Placing SL-LMT BUY — market_open={market_open} sec={security_id} qty={quantity} "
        f"entry_input={entry_price} trigger={trigger_price} limit={limit_price} tick={tick_size}"
    )

    if market_open:
        # Regular delivery SL-Limit BUY order during live market
        response = dhan.place_order(
            transaction_type=dhan.BUY,
            exchange_segment=dhan.NSE,
            product_type=dhan.CNC,
            order_type=dhan.SL,
            validity=dhan.DAY,
            security_id=security_id,
            quantity=quantity,
            price=limit_price,
            trigger_price=trigger_price,
            after_market_order=False,
        )
        label = "Regular SL-Limit order (market is open)"
    else:
        # AMO order outside market hours
        response = dhan.place_order(
            transaction_type=dhan.BUY,
            exchange_segment=dhan.NSE,
            product_type=dhan.CNC,
            order_type=dhan.SL,
            validity=dhan.DAY,
            security_id=security_id,
            quantity=quantity,
            price=limit_price,
            trigger_price=trigger_price,
            after_market_order=True,
            amo_time="OPEN",
        )
        label = "AMO SL-Limit order (after-market)"

    logger.info(f"Smart entry [{label}] response → {response}")
    return response, label


def place_oco_forever_order(
    security_id: str,
    quantity: int,
    target_price: float,
    stoploss_price: float,
    tick_size: float = NSE_TICK,
    tag: str = None,
) -> dict[str, Any]:
    """
    Place a Forever (GTT) OCO (One-Cancels-Other) order for Target and Stoploss.
    Leg 1 / base payload: Stoploss SELL at stoploss_price (trigger)
    with a protective SL-Limit price below the trigger.
    Leg 2 / secondary payload: Target SELL at target_price.

    Although Dhan's modify API refers to TARGET_LEG and STOP_LOSS_LEG explicitly,
    live behavior for create calls in this project/account maps the base payload
    to the stoploss leg and the secondary payload to the target leg.
    """
    target_price = round_to_tick(target_price, tick_size)
    stoploss_price = round_to_tick(stoploss_price, tick_size)
    sl_limit_price = round_to_tick(stoploss_price * 0.995, tick_size)

    dhan = _client()
    response = dhan.place_forever(
        security_id=security_id,
        exchange_segment=dhan.NSE,
        transaction_type=dhan.SELL,
        product_type=dhan.CNC,
        order_type=dhan.LIMIT,
        quantity=quantity,

        # Leg 1: Stoploss
        price=sl_limit_price,
        trigger_Price=stoploss_price,

        order_flag="OCO",
        disclosed_quantity=0,
        validity=dhan.DAY,

        # Leg 2: Target
        price1=target_price,
        trigger_Price1=target_price,
        quantity1=quantity,

        tag=tag,
    )
    logger.info(
        f"Forever OCO order placed — sec={security_id} qty={quantity} "
        f"target={target_price} sl={stoploss_price} sl_limit={sl_limit_price} → {response}"
    )
    return response


def cancel_order(order_id: str) -> dict[str, Any]:
    """Cancel an open order by its Dhan order ID."""
    dhan = _client()
    response = dhan.cancel_order(order_id)
    logger.info(f"Order cancelled — order_id={order_id} → {response}")
    return response


def cancel_forever_order(order_id: str) -> dict[str, Any]:
    """Cancel a Forever (GTT) order."""
    dhan = _client()
    response = dhan.cancel_forever(order_id)
    logger.info(f"Forever order cancelled — order_id={order_id} → {response}")
    return response


def modify_forever_oco(
    order_id: str,
    quantity: int,
    target_price: float,
    stoploss_price: float,
    tick_size: float = NSE_TICK,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Modify both legs of an existing Forever OCO order to the supplied quantity.
    Returns (target_leg_response, stoploss_leg_response).
    """
    target_price = round_to_tick(target_price, tick_size)
    stoploss_price = round_to_tick(stoploss_price, tick_size)
    sl_limit_price = round_to_tick(stoploss_price * 0.995, tick_size)

    dhan = _client()
    target_resp = dhan.modify_forever(
        order_id=order_id,
        order_flag="OCO",
        order_type=dhan.LIMIT,
        leg_name="TARGET_LEG",
        quantity=quantity,
        price=target_price,
        trigger_price=target_price,
        disclosed_quantity=0,
        validity=dhan.DAY,
    )
    stoploss_resp = dhan.modify_forever(
        order_id=order_id,
        order_flag="OCO",
        order_type="STOP_LOSS",
        leg_name="STOP_LOSS_LEG",
        quantity=quantity,
        price=sl_limit_price,
        trigger_price=stoploss_price,
        disclosed_quantity=0,
        validity=dhan.DAY,
    )
    logger.info(
        f"Forever OCO modified — order_id={order_id} qty={quantity} "
        f"target={target_price} sl={stoploss_price} sl_limit={sl_limit_price} "
        f"target_resp={target_resp} stoploss_resp={stoploss_resp}"
    )
    return target_resp, stoploss_resp



def modify_target_order(order_id: str, quantity: int, price: float, tick_size: float = NSE_TICK) -> dict[str, Any]:
    """Modify the quantity of an existing Target order."""
    price = round_to_tick(price, tick_size)
    dhan = _client()
    response = dhan.modify_order(
        order_id=order_id,
        order_type=dhan.LIMIT,
        leg_name="NA",
        quantity=quantity,
        price=price,
        trigger_price=0.0,
        disclosed_quantity=0,
        validity=dhan.DAY
    )
    logger.info(f"Target order modified — order_id={order_id} new_qty={quantity} new_price={price} → {response}")
    return response


def modify_sl_order(order_id: str, quantity: int, stoploss_price: float, tick_size: float = NSE_TICK) -> dict[str, Any]:
    """Modify the quantity of an existing SL order."""
    stoploss_price = round_to_tick(stoploss_price, tick_size)
    limit_price = round_to_tick(stoploss_price * 0.99, tick_size)
    
    dhan = _client()
    # For Sell SL limit order, limit price must be less than trigger price.
    response = dhan.modify_order(
        order_id=order_id,
        order_type=dhan.SL,
        leg_name="NA",
        quantity=quantity,
        price=limit_price,
        trigger_price=stoploss_price,
        disclosed_quantity=0,
        validity=dhan.DAY
    )
    logger.info(f"SL order modified — order_id={order_id} new_qty={quantity} → {response}")
    return response


def get_today_low(security_id: str) -> float | None:
    """Fetch today's low price directly from Dhan API."""
    dhan = _client()
    from datetime import date
    today_str = date.today().strftime("%Y-%m-%d")
    
    try:
        resp = dhan.intraday_minute_data(
            security_id=security_id,
            exchange_segment='NSE_EQ',
            instrument_type='EQUITY',
            from_date=today_str,
            to_date=today_str,
            interval=1
        )
        if resp.get("status") == "success" and "data" in resp and "low" in resp["data"]:
            lows = resp["data"]["low"]
            if lows:
                return min(lows)
    except Exception as e:
        logger.error(f"Failed to fetch today's low for {security_id}: {e}")
    return None


def get_order_status(order_id: str) -> dict[str, Any]:
    """Fetch current status of a single order."""
    dhan = _client()
    response = dhan.get_order_by_id(order_id)
    return response


def get_order_list() -> dict[str, Any]:
    """Fetch today's full order list from Dhan."""
    dhan = _client()
    return dhan.get_order_list()


def get_forever_orders() -> dict[str, Any]:
    """Fetch all Forever (GTT/OCO) orders directly from Dhan."""
    dhan = _client()
    return dhan.get_forever()


def get_holdings() -> dict[str, Any]:
    """Fetch demat holdings directly from Dhan."""
    dhan = _client()
    return dhan.get_holdings()


def get_positions() -> dict[str, Any]:
    """Fetch today's open/closed positions directly from Dhan."""
    dhan = _client()
    return dhan.get_positions()


def get_fund_limits() -> dict[str, Any]:
    """Fetch account fund/margin limits directly from Dhan."""
    dhan = _client()
    return dhan.get_fund_limits()


def get_trade_book(order_id: str | None = None) -> dict[str, Any]:
    """Fetch today's trade book, optionally filtered by order ID."""
    dhan = _client()
    return dhan.get_trade_book(order_id)


def place_market_exit(
    security_id: str,
    quantity: int,
    product_type: str = "CNC",
    exchange_segment: str = "NSE_EQ",
    transaction_type: str = "SELL",
    tag: str | None = None,
) -> dict[str, Any]:
    """Place a market order to exit an existing position."""
    dhan = _client()
    exchange = dhan.NSE if exchange_segment in {"NSE", "NSE_EQ"} else exchange_segment
    product = product_type or dhan.CNC
    transaction = dhan.BUY if str(transaction_type).upper() == "BUY" else dhan.SELL
    response = dhan.place_order(
        transaction_type=transaction,
        exchange_segment=exchange,
        product_type=product,
        order_type=dhan.MARKET,
        validity=dhan.DAY,
        security_id=security_id,
        quantity=quantity,
        price=0,
        trigger_price=0,
        after_market_order=False,
        tag=tag,
    )
    logger.info(
        f"Market exit {transaction} placed - sec={security_id} qty={quantity} "
        f"product={product} exchange={exchange} -> {response}"
    )
    return response


def get_order_by_correlation_id(correlation_id: str) -> dict[str, Any]:
    """Fetch an order using the caller-supplied correlation ID."""
    dhan = _client()
    return dhan.get_order_by_correlationID(correlation_id)


def extract_order_id(response: dict[str, Any]) -> str | None:
    """
    Extract the orderId string from a Dhan place_order / cancel_order response.
    Returns None if not found or on error.
    """
    if not isinstance(response, dict):
        return None
    direct_order_id = response.get("orderId") or response.get("order_id")
    if direct_order_id:
        return str(direct_order_id)
    data = response.get("data") or {}
    if isinstance(data, dict):
        nested_order_id = data.get("orderId") or data.get("order_id")
        if nested_order_id:
            return str(nested_order_id)
    return None
