from __future__ import annotations

import json
import math
from collections import OrderedDict, defaultdict
from datetime import datetime
from pathlib import Path


def _parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def _format_date(d: datetime) -> str:
    return d.strftime("%d/%m/%Y")


def _ceil_days(delta_seconds: float) -> int:
    return max(1, math.ceil(delta_seconds / 86400.0))


def _percent_return_for_trade(tr: dict) -> float:
    if tr.get("target_hit"):
        return float(tr.get("target_level", 0)) / 100.0
    if tr.get("stoploss_hit"):
        m = tr.get("stoploss_hit_metrics")
        if m is not None:
            return float(m) / 100.0
    if tr.get("expired"):
        m = tr.get("expired_metrics")
        if m is not None:
            return float(m) / 100.0
    return 0.0


def _current_equity(free_cash_now, positions_map, mtf_enabled, equity_fraction):
    eq_in_positions = 0.0
    for p in positions_map.values():
        notional = p["qty"] * p["entry_price"]
        eq_in_positions += notional * equity_fraction if mtf_enabled else notional
    return free_cash_now + eq_in_positions


def _per_company_notional_cap(current_equity, mtf_enabled, leverage, cap_fraction):
    base = current_equity * cap_fraction
    return base * leverage if mtf_enabled else base


class PortfolioBacktester:
    def __init__(
        self,
        initial_capital: float,
        fee_rate: float,
        mtf_enabled: bool,
        mtf_leverage: float,
        mtf_daily_rate: float,
        cap_fraction: float,
        rsi_filter: tuple[float, float],
        htf_rsi_filter: tuple[float, float],
    ):
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate
        self.mtf_enabled = mtf_enabled
        self.mtf_leverage = mtf_leverage
        self.mtf_daily_rate = mtf_daily_rate
        self.cap_fraction = cap_fraction
        self.rsi_filter = rsi_filter
        self.htf_rsi_filter = htf_rsi_filter

    def load_filtered_trades(self, file_path: str | Path) -> list[dict]:
        path = Path(file_path)
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        out = []
        for t in data:
            if not t.get("entry_time") or not t.get("exit_time"):
                continue
            rsi = float(t.get("rsi", 0))
            drsi = float(t.get("rsi_HTF", 0))
            if self.rsi_filter[0] <= rsi < self.rsi_filter[1] and self.htf_rsi_filter[0] <= drsi < self.htf_rsi_filter[1]:
                out.append(t)
        return out

    def simulate(self, trades_by_company: dict[str, list[dict]]) -> OrderedDict:
        events = []
        for company, trades in trades_by_company.items():
            for tr in trades:
                try:
                    e_dt = _parse_dt(tr["entry_time"])
                    x_dt = _parse_dt(tr["exit_time"])
                except Exception:
                    continue
                key = f"{company}|{tr.get('target_level')}|{tr['entry_time']}|{tr['exit_time']}"
                events.append(("buy", e_dt, company, key, tr))
                events.append(("sell", x_dt, company, key, tr))

        events.sort(key=lambda x: (x[1], 0 if x[0] == "sell" else 1))

        free_cash = self.initial_capital
        equity_fraction = 1.0 / self.mtf_leverage if self.mtf_enabled else 1.0
        per_company_notional_used = defaultdict(float)
        positions = {}
        daily_activity = defaultdict(lambda: {"buys": [], "sells": []})
        broker_cost_running = 0.0
        mtf_cost_running = 0.0

        for typ, dt, comp, key, tr in events:
            date_key = _format_date(dt)
            if typ == "sell":
                pos = positions.pop(key, None)
                if pos:
                    qty = pos["qty"]
                    entry = pos["entry_price"]
                    pct_ret = _percent_return_for_trade(tr)
                    gross_proceeds = qty * entry * (1.0 + pct_ret)
                    sell_fee = gross_proceeds * self.fee_rate
                    broker_cost_running += sell_fee
                    net_before_mtf = gross_proceeds - sell_fee

                    borrowed = pos.get("borrowed_principal", 0.0)
                    days = _ceil_days((_parse_dt(tr["exit_time"]) - _parse_dt(tr["entry_time"])).total_seconds())
                    mtf_interest = borrowed * self.mtf_daily_rate * days if self.mtf_enabled else 0.0
                    mtf_cost_running += mtf_interest

                    free_cash += net_before_mtf - borrowed - mtf_interest
                    per_company_notional_used[comp] -= qty * entry
                    daily_activity[date_key]["sells"].append(comp)
            else:
                entry = float(tr["entry"])
                current_equity = _current_equity(free_cash, positions, self.mtf_enabled, equity_fraction)
                company_cap = _per_company_notional_cap(current_equity, self.mtf_enabled, self.mtf_leverage, self.cap_fraction)
                remaining_notional_cap = max(0.0, company_cap - per_company_notional_used[comp])

                equity_per_share = entry * equity_fraction if self.mtf_enabled else entry
                fee_per_share = entry * self.fee_rate
                cash_per_share = equity_per_share + fee_per_share

                max_by_cash = math.floor(free_cash / cash_per_share) if cash_per_share > 0 else 0
                max_by_notional = math.floor(remaining_notional_cap / entry) if entry > 0 else 0
                qty = int(min(max_by_cash, max_by_notional))

                if qty > 0:
                    notional = qty * entry
                    buy_fee = notional * self.fee_rate
                    if self.mtf_enabled:
                        equity_cash = notional * equity_fraction
                        borrowed = notional - equity_cash
                        cash_out = equity_cash + buy_fee
                    else:
                        borrowed = 0.0
                        cash_out = notional + buy_fee

                    free_cash -= cash_out
                    broker_cost_running += buy_fee
                    per_company_notional_used[comp] += notional
                    positions[key] = {
                        "company": comp,
                        "qty": qty,
                        "entry_price": entry,
                        "borrowed_principal": borrowed,
                    }
                    daily_activity[date_key]["buys"].append(comp)

        return self._replay_day_end(events, daily_activity)

    def _replay_day_end(self, events, daily_activity):
        free_cash = self.initial_capital
        equity_fraction = 1.0 / self.mtf_leverage if self.mtf_enabled else 1.0
        per_company_notional_used = defaultdict(float)
        positions = {}
        broker_cost_running = 0.0
        mtf_cost_running = 0.0
        events_by_day = defaultdict(list)
        for typ, dt, comp, key, tr in events:
            events_by_day[dt.date()].append((typ, dt, comp, key, tr))

        snapshots = OrderedDict()
        for day in sorted(events_by_day.keys()):
            day_events = sorted(events_by_day[day], key=lambda x: (x[1], 0 if x[0] == "sell" else 1))
            for typ, dt, comp, key, tr in day_events:
                if typ == "sell":
                    pos = positions.pop(key, None)
                    if pos:
                        qty = pos["qty"]
                        entry = pos["entry_price"]
                        pct_ret = _percent_return_for_trade(tr)
                        gross_proceeds = qty * entry * (1.0 + pct_ret)
                        sell_fee = gross_proceeds * self.fee_rate
                        broker_cost_running += sell_fee
                        net_before_mtf = gross_proceeds - sell_fee
                        borrowed = pos.get("borrowed_principal", 0.0)
                        days = _ceil_days((_parse_dt(tr["exit_time"]) - _parse_dt(tr["entry_time"])).total_seconds())
                        mtf_interest = borrowed * self.mtf_daily_rate * days if self.mtf_enabled else 0.0
                        mtf_cost_running += mtf_interest
                        free_cash += net_before_mtf - borrowed - mtf_interest
                        per_company_notional_used[comp] -= qty * entry
                else:
                    entry = float(tr["entry"])
                    current_equity = _current_equity(free_cash, positions, self.mtf_enabled, equity_fraction)
                    company_cap = _per_company_notional_cap(current_equity, self.mtf_enabled, self.mtf_leverage, self.cap_fraction)
                    remaining_notional_cap = max(0.0, company_cap - per_company_notional_used[comp])
                    equity_per_share = entry * equity_fraction if self.mtf_enabled else entry
                    fee_per_share = entry * self.fee_rate
                    cash_per_share = equity_per_share + fee_per_share
                    max_by_cash = math.floor(free_cash / cash_per_share) if cash_per_share > 0 else 0
                    max_by_notional = math.floor(remaining_notional_cap / entry) if entry > 0 else 0
                    qty = int(min(max_by_cash, max_by_notional))
                    if qty > 0:
                        notional = qty * entry
                        buy_fee = notional * self.fee_rate
                        if self.mtf_enabled:
                            equity_cash = notional * equity_fraction
                            borrowed = notional - equity_cash
                            cash_out = equity_cash + buy_fee
                        else:
                            borrowed = 0.0
                            cash_out = notional + buy_fee
                        free_cash -= cash_out
                        broker_cost_running += buy_fee
                        per_company_notional_used[comp] += notional
                        positions[key] = {
                            "company": comp,
                            "qty": qty,
                            "entry_price": entry,
                            "borrowed_principal": borrowed,
                        }

            shares = defaultdict(int)
            demat_value = 0.0
            for p in positions.values():
                shares[p["company"]] += p["qty"]
                demat_value += p["qty"] * p["entry_price"]

            date_key = _format_date(datetime.combine(day, datetime.min.time()))
            total_amount = round(demat_value + free_cash, 2)
            total_cost = round(broker_cost_running + mtf_cost_running, 2)
            snapshots[date_key] = {
                "buys": sorted(set(daily_activity[date_key]["buys"])),
                "sells": sorted(set(daily_activity[date_key]["sells"])),
                "shares": dict(shares),
                "demat_value": round(demat_value, 2),
                "free_cash": round(free_cash, 2),
                "broker_cost": round(broker_cost_running, 2),
                "mtf_cost": round(mtf_cost_running, 2),
                "total_cost": total_cost,
                "total_amount": total_amount,
                "final_pnl": round(total_amount - self.initial_capital, 2),
            }
        return snapshots
