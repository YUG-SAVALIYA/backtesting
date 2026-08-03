import json
import glob
import os
import math
from datetime import datetime
from collections import defaultdict
import multiprocessing

# Market caps directly from UI
COMPANY_MARKET_CAPS = {}
html_path = os.path.join(os.path.dirname(__file__), 'static', 'updated_backtester.html')
if os.path.exists(html_path):
    import re
    with open(html_path, 'r', encoding='utf-8') as f:
        content = f.read()
        match = re.search(r'const\s+MARKET_CAP_RS_CR\s*=\s*({.*?});', content, re.DOTALL)
        if match:
            pairs = re.findall(r'"([^"]+)"\s*:\s*([0-9.]+)', match.group(1))
            for comp, cap in pairs:
                COMPANY_MARKET_CAPS[comp] = float(cap)

def to_finite(val, default):
    if val is None:
        return default
    try:
        return float(val)
    except:
        return default

def get_trade_outcome_metric(s, gm, pre_final_active):
    source = gm.get('close_lf_replay', {}) if pre_final_active else gm
    
    thit = source.get('target_hit') if source.get('target_hit') is not None else s.get('target_hit')
    shit = source.get('stoploss_hit') if source.get('stoploss_hit') is not None else s.get('stoploss_hit')
    tm = source.get('target_hit_metrics') if source.get('target_hit_metrics') is not None else s.get('target_hit_metrics')
    sm = source.get('stoploss_hit_metrics') if source.get('stoploss_hit_metrics') is not None else s.get('stoploss_hit_metrics')
    em = source.get('expired_metrics') if source.get('expired_metrics') is not None else s.get('expired_metrics')
    
    if thit: return to_finite(tm, 0)
    if shit: return to_finite(sm, 0)
    return to_finite(em, 0)

def parse_sim_date(date_str):
    if not date_str: return None
    try:
        # e.g. "2026-06-15 09:15:00" -> timestamp
        return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").timestamp() * 1000
    except:
        return None

def get_sim_day_key(ts):
    if not ts: return ""
    dt = datetime.fromtimestamp(ts / 1000.0)
    return dt.strftime("%Y-%m-%d")

def get_trade_entry_price(s, gm, pre_final_active):
    source = gm.get('close_lf_replay', {}) if pre_final_active else gm
    return to_finite(source.get('new_entry') if source.get('new_entry') is not None else (source.get('entry') if source.get('entry') is not None else s.get('entry')), None)

def run_portfolio_simulation(accepted_trades):
    if not accepted_trades:
        return 0, 0, 0
    
    events = []
    for idx, (s, gm, pre_final_active) in enumerate(accepted_trades):
        company = s.get('company', 'Unknown')
        
        source = gm.get('close_lf_replay', {}) if pre_final_active else gm
        entry_time = source.get('entry_time') if source.get('entry_time') is not None else s.get('entry_time')
        exit_time = source.get('exit_time') if source.get('exit_time') is not None else s.get('exit_time')
        
        key = f"{company}|{idx}|{entry_time}|{exit_time}"
        
        entry_date = parse_sim_date(entry_time)
        exit_date = parse_sim_date(exit_time)
        if not entry_date: continue
        
        events.append({'type': 'buy', 'dt': entry_date, 'company': company, 'key': key, 's': s, 'gm': gm, 'pfa': pre_final_active})
        
        # Trade Management Partial Booking
        partial_booked = source.get('trade_management_partial_booked') if source.get('trade_management_partial_booked') is not None else gm.get('trade_management_partial_booked')
        if partial_booked:
            hit_time = source.get('trade_management_hit_time') if source.get('trade_management_hit_time') is not None else gm.get('trade_management_hit_time')
            booked_pct = source.get('trade_management_booked_qty_pct') if source.get('trade_management_booked_qty_pct') is not None else gm.get('trade_management_booked_qty_pct')
            trigger_pct = source.get('trade_management_trigger_pct') if source.get('trade_management_trigger_pct') is not None else gm.get('trade_management_trigger_pct')
            hit_date = parse_sim_date(hit_time)
            if hit_date:
                events.append({
                    'type': 'partial_sell', 
                    'dt': hit_date, 
                    'company': company, 
                    'key': key, 
                    's': s, 'gm': gm, 'pfa': pre_final_active,
                    'book_fraction': to_finite(booked_pct, 0) / 100.0,
                    'return_pct': to_finite(trigger_pct, 0)
                })
        
        if exit_date:
            events.append({'type': 'final_sell', 'dt': exit_date, 'company': company, 'key': key, 's': s, 'gm': gm, 'pfa': pre_final_active})
            
    # Priority: buy=1, partial_sell=2, final_sell=3
    def event_priority(t):
        if t == 'buy': return 1
        if t == 'partial_sell': return 2
        return 3
    events.sort(key=lambda x: (x['dt'], event_priority(x['type'])))
    
    events_by_day = defaultdict(list)
    for e in events:
        events_by_day[get_sim_day_key(e['dt'])].append(e)
        
    initial_capital = 100000
    fee_rate = 0.0015 # 0.15%
    cap_fraction = 0.25 # 25%
    mtf_enabled = True
    leverage = 4
    mtf_daily_rate = 0.0004 # 0.04%
    equity_fraction = 1.0 / leverage if mtf_enabled else 1.0
    
    free_cash = initial_capital
    peak_equity = initial_capital
    max_drawdown_pct = 0
    
    positions = {}
    per_company_used = defaultdict(float)
    
    sorted_days = sorted(list(events_by_day.keys()))
    for day_key in sorted_days:
        day_events = events_by_day[day_key]
        day_events.sort(key=lambda x: (x['dt'], event_priority(x['type'])))
        
        for event in day_events:
            s, gm, pfa = event['s'], event['gm'], event['pfa']
            company = event['company']
            entry = get_trade_entry_price(s, gm, pfa)
            
            if event['type'] in ['final_sell', 'partial_sell']:
                if event['key'] not in positions: continue
                pos = positions[event['key']]
                
                sell_qty = pos['qty']
                if event['type'] == 'partial_sell':
                    fraction = event.get('book_fraction', 0.5)
                    sell_qty = min(pos['qty'], max(1, math.floor(pos['original_qty'] * fraction)))
                
                if sell_qty <= 0: continue
                
                pct_return = (event['return_pct'] if event['type'] == 'partial_sell' else to_finite(get_trade_outcome_metric(s, gm, pfa), 0)) / 100.0
                gross_proceeds = sell_qty * pos['entry_price'] * (1 + pct_return)
                sell_fee = gross_proceeds * fee_rate
                
                interest_start = pos['last_interest_date']
                days = 0
                if not (pos['interest_checkpointed'] and interest_start == event['dt']):
                    days = max(0, math.ceil((event['dt'] - interest_start) / 86400000.0))
                interest = pos['borrowed'] * mtf_daily_rate * days if mtf_enabled else 0
                
                borrowed_released = pos['borrowed'] * (sell_qty / pos['qty']) if pos['qty'] > 0 else 0
                free_cash += gross_proceeds - sell_fee - borrowed_released - interest
                
                used = max(0, per_company_used[company] - (sell_qty * pos['entry_price']))
                per_company_used[company] = used
                
                pos['qty'] -= sell_qty
                pos['borrowed'] = max(0, pos['borrowed'] - borrowed_released)
                pos['last_interest_date'] = event['dt']
                pos['interest_checkpointed'] = True
                
                if pos['qty'] <= 0 or event['type'] == 'final_sell':
                    del positions[event['key']]
                continue
                
            if event['type'] == 'buy':
                if not entry or entry <= 0: continue
                
                # get current equity
                demat_val = sum(p['qty'] * p['entry_price'] for p in positions.values())
                borrowed_tot = sum(p['borrowed'] for p in positions.values())
                interest_tot = 0
                for p in positions.values():
                    if p['qty'] > 0:
                        days = max(0, math.ceil((event['dt'] - p['last_interest_date']) / 86400000.0))
                        interest_tot += p['borrowed'] * mtf_daily_rate * days
                
                cur_equity = free_cash + demat_val - borrowed_tot - interest_tot
                
                per_company_cap = cur_equity * cap_fraction * (leverage if mtf_enabled else 1)
                rem_notional = max(0, per_company_cap - per_company_used[company])
                
                equity_per_share = entry * equity_fraction if mtf_enabled else entry
                cash_per_share = equity_per_share + (entry * fee_rate)
                
                max_cash = math.floor(free_cash / cash_per_share) if cash_per_share > 0 else 0
                max_notional = math.floor(rem_notional / entry) if entry > 0 else 0
                qty = max(0, min(max_cash, max_notional))
                
                if qty <= 0: continue
                
                notional = qty * entry
                buy_fee = notional * fee_rate
                equity_cash = notional * equity_fraction if mtf_enabled else notional
                borrowed = notional - equity_cash if mtf_enabled else 0
                
                free_cash -= (equity_cash + buy_fee)
                per_company_used[company] += notional
                positions[event['key']] = {
                    'qty': qty,
                    'original_qty': qty,
                    'entry_price': entry,
                    'borrowed': borrowed,
                    'last_interest_date': event['dt'],
                    'interest_checkpointed': False
                }
                
        # End of day snapshot
        demat_val = sum(p['qty'] * p['entry_price'] for p in positions.values())
        net_position_equity = sum(p['qty'] * p['entry_price'] * (equity_fraction if mtf_enabled else 1.0) for p in positions.values())
                
        net_equity = free_cash + net_position_equity
        peak_equity = max(peak_equity, net_equity)
        if peak_equity > 0:
            drawdown = ((peak_equity - net_equity) / peak_equity) * 100
            max_drawdown_pct = max(max_drawdown_pct, drawdown)
            
    final_equity = free_cash
    for p in positions.values():
        final_equity += (p['qty'] * p['entry_price'] - p['borrowed'])
        
    return final_equity - initial_capital, max_drawdown_pct

def evaluate_combination(args):
    ltf_min, ltf_max, htf_min, htf_max, adx_min, cr_min, cr_max, mcap_min, max_high_lf_min, close_lf_min, signals = args
    
    accepted = []
    
    sum_thit = 0
    sum_shit = 0
    t_hits = 0
    s_hits = 0
    
    for s in signals:
        if s.get('entry_rejected'): continue
        gm = s.get('gap_up_modes', {}).get('gap_up_sl_target_update', {})
        if gm.get('entry_rejected') or gm.get('valid') is False: continue
        
        rsiL = to_finite(s.get('rsi'), None)
        rsiH = to_finite(s.get('rsi_HTF'), None)
        adx = to_finite(s.get('adx'), None)
        if rsiL is None or not (ltf_min <= rsiL <= ltf_max): continue
        if rsiH is None or not (htf_min <= rsiH <= htf_max): continue
        if adx is None or adx < adx_min: continue
        
        if s.get('signal_open') and s.get('signal_open') > 0:
            cr = (s['signal_high'] - s['signal_low']) / s['signal_open'] * 100
            if not (cr_min <= cr <= cr_max): continue
            
        mcap = COMPANY_MARKET_CAPS.get(s['company'], 0)
        if mcap < mcap_min: continue
        
        # Pre-Final
        baseRef = gm.get('original_entry') or s.get('signal_high') or s.get('entry')
        
        maxH = gm.get('max_high_lookahead') if gm.get('max_high_lookahead') is not None else s.get('max_high_lookahead')
        maxHighLfPct = None
        if maxH is not None and baseRef and baseRef > 0:
            maxHighLfPct = (maxH - baseRef) / baseRef * 100
            
        closeH = gm.get('close_lookahead') if gm.get('close_lookahead') is not None else s.get('close_lookahead')
        closeLfPct = None
        if closeH is not None and baseRef and baseRef > 0:
            closeLfPct = (closeH - baseRef) / baseRef * 100
            
        sl_hit = gm.get('sl_hit_lookahead') if gm.get('sl_hit_lookahead') is not None else s.get('sl_hit_lookahead')
        
        # === THE CRITICAL PRE-FINAL FILTERS FROM THE LEFT PANEL ===
        # The UI applies these implicitly based on the Pre-Final Confirmation panel
        pre_final_active = (max_high_lf_min is not None) or (close_lf_min is not None)
        if max_high_lf_min is not None and close_lf_min is not None:
            if sl_hit is True: continue
            if maxHighLfPct is None or maxHighLfPct < max_high_lf_min: continue
            if closeLfPct is None or closeLfPct < close_lf_min: continue
        elif max_high_lf_min is not None:
            if sl_hit is True: continue
            if maxHighLfPct is None or maxHighLfPct < max_high_lf_min: continue
        elif close_lf_min is not None:
            if sl_hit is True: continue
            if closeLfPct is None or closeLfPct < close_lf_min: continue

        accepted.append((s, gm, pre_final_active))
        
        thit = gm.get('close_lf_replay', {}).get('target_hit') if pre_final_active and gm.get('close_lf_replay', {}).get('target_hit') is not None else gm.get('target_hit') if gm.get('target_hit') is not None else s.get('target_hit')
        shit = gm.get('close_lf_replay', {}).get('stoploss_hit') if pre_final_active and gm.get('close_lf_replay', {}).get('stoploss_hit') is not None else gm.get('stoploss_hit') if gm.get('stoploss_hit') is not None else s.get('stoploss_hit')
        tm = gm.get('close_lf_replay', {}).get('target_hit_metrics') if pre_final_active and gm.get('close_lf_replay', {}).get('target_hit_metrics') is not None else gm.get('target_hit_metrics') if gm.get('target_hit_metrics') is not None else s.get('target_hit_metrics')
        sm = gm.get('close_lf_replay', {}).get('stoploss_hit_metrics') if pre_final_active and gm.get('close_lf_replay', {}).get('stoploss_hit_metrics') is not None else gm.get('stoploss_hit_metrics') if gm.get('stoploss_hit_metrics') is not None else s.get('stoploss_hit_metrics')
        
        if thit:
            t_hits += 1
            sum_thit += max(to_finite(tm, 0), 0)
        elif shit:
            s_hits += 1
            sum_shit += abs(to_finite(sm, 0))

    c = len(accepted)
    if c == 0:
        return (0, 0, 0, 0, (ltf_min, ltf_max, htf_min, htf_max, adx_min, cr_min, cr_max, mcap_min, max_high_lf_min, close_lf_min))
        
    net_profit_pct = sum_thit - sum_shit
    avg_ret = net_profit_pct / c
    
    final_pnl, max_dd = run_portfolio_simulation(accepted)
    
    return (c, avg_ret, max_dd, final_pnl, (ltf_min, ltf_max, htf_min, htf_max, adx_min, cr_min, cr_max, mcap_min, max_high_lf_min, close_lf_min))

if __name__ == '__main__':
    output_dir = r'd:\backtesting\backtesting\output'
    json_files = glob.glob(os.path.join(output_dir, '*.json'))
    latest_file = max(json_files, key=os.path.getctime)
    
    print(f"\nLoading data from: {os.path.basename(latest_file)}")
    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    signals = data.get('signals', [])
    
    # Grid Search space
    ltf_mins = [50, 60, 65]
    ltf_maxs = [80, 85]
    htf_mins = [40, 50, 60]
    htf_maxs = [85]
    adx_mins = [15, 18, 20, 21, 25]
    cr_mins = [2, 3]
    cr_maxs = [15, 20, 25, 30]
    mcap_mins = [1000, 2000, 5000, 10000]
    max_high_lf_mins = [None, 1.0, 2.0, 3.0]
    close_lf_mins = [None, -2.0, -1.0, 0.0]
    
    combinations = []
    for ltf_min in ltf_mins:
        for ltf_max in ltf_maxs:
            for htf_min in htf_mins:
                for htf_max in htf_maxs:
                    for adx_min in adx_mins:
                        for cr_min in cr_mins:
                            for cr_max in cr_maxs:
                                for mcap_min in mcap_mins:
                                    for mhl in max_high_lf_mins:
                                        for clf in close_lf_mins:
                                            combinations.append((ltf_min, ltf_max, htf_min, htf_max, adx_min, cr_min, cr_max, mcap_min, mhl, clf, signals))
                                            
    print(f"Evaluating {len(combinations)} combinations strictly matching your UI's simulation...\n")
    with multiprocessing.Pool() as pool:
        results = pool.map(evaluate_combination, combinations)
        
    results_valid = [r for r in results if r[0] >= 15] # Trades >= 15
    
    print("=== TOP 10 COMBINATIONS BY SIMULATED FINAL PNL ===")
    results_pnl = sorted(results_valid, key=lambda x: x[3], reverse=True)
    for i, r in enumerate(results_pnl[:10]):
        c, avg_ret, max_dd, pnl, args = r
        print(f"{i+1}. Trades: {c}, UI Avg Ret: {avg_ret:.2f}%, Max DD: {max_dd:.2f}%, Final PNL: Rs {pnl:,.2f}")
        print(f"    LTF RSI {args[0]}-{args[1]}, HTF RSI {args[2]}-{args[3]}, ADX >= {args[4]}")
        print(f"    Range: {args[5]}% to {args[6]}%, Mcap >= {args[7]} Cr")
        print(f"    Max High LF >= {args[8]}%, Close LF >= {args[9]}%\n")

    print("=== TOP 10 COMBINATIONS BY LOWEST MAX DRAWDOWN ===")
    results_dd = sorted(results_valid, key=lambda x: x[2])
    for i, r in enumerate(results_dd[:10]):
        c, avg_ret, max_dd, pnl, args = r
        print(f"{i+1}. Trades: {c}, UI Avg Ret: {avg_ret:.2f}%, Max DD: {max_dd:.2f}%, Final PNL: Rs {pnl:,.2f}")
        print(f"    LTF RSI {args[0]}-{args[1]}, HTF RSI {args[2]}-{args[3]}, ADX >= {args[4]}")
        print(f"    Range: {args[5]}% to {args[6]}%, Mcap >= {args[7]} Cr")
        print(f"    Max High LF >= {args[8]}%, Close LF >= {args[9]}%\n")

    print("=== TOP 10 COMBINATIONS BY BEST RISK-ADJUSTED RETURN (PNL / Max DD) ===")
    # Avoid division by zero, though DD is usually > 0
    results_ratio = sorted(results_valid, key=lambda x: x[3] / max(x[2], 0.01), reverse=True)
    for i, r in enumerate(results_ratio[:10]):
        c, avg_ret, max_dd, pnl, args = r
        ratio = pnl / max(max_dd, 0.01)
        print(f"{i+1}. Trades: {c}, UI Avg Ret: {avg_ret:.2f}%, Max DD: {max_dd:.2f}%, Final PNL: Rs {pnl:,.2f} (Ratio: {ratio:,.2f})")
        print(f"    LTF RSI {args[0]}-{args[1]}, HTF RSI {args[2]}-{args[3]}, ADX >= {args[4]}")
        print(f"    Range: {args[5]}% to {args[6]}%, Mcap >= {args[7]} Cr")
        print(f"    Max High LF >= {args[8]}%, Close LF >= {args[9]}%\n")

    print("=== TOP 10 COMBINATIONS BY MAX TRADES ===")
    results_trades = sorted(results_valid, key=lambda x: x[0], reverse=True)
    for i, r in enumerate(results_trades[:10]):
        c, avg_ret, max_dd, pnl, args = r
        print(f"{i+1}. Trades: {c}, UI Avg Ret: {avg_ret:.2f}%, Max DD: {max_dd:.2f}%, Final PNL: Rs {pnl:,.2f}")
        print(f"    LTF RSI {args[0]}-{args[1]}, HTF RSI {args[2]}-{args[3]}, ADX >= {args[4]}")
        print(f"    Range: {args[5]}% to {args[6]}%, Mcap >= {args[7]} Cr")
        print(f"    Max High LF >= {args[8]}%, Close LF >= {args[9]}%\n")
