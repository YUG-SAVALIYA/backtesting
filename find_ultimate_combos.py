import json
import glob
import os
import multiprocessing
from test_user_params import COMPANY_MARKET_CAPS
from find_best_filters import run_portfolio_simulation, to_finite

def fast_evaluate(args):
    ltf_min, ltf_max, htf_min, htf_max, adx_min, cr_min, cr_max, mcap_min, max_high_lf_min, close_lf_min, compact_signals = args
    
    accepted = []
    sum_thit = 0
    sum_shit = 0
    
    for sig in compact_signals:
        rsiL, rsiH, adx, cr, mcap, sl_hit, maxHighLfPct, closeLfPct, thit, shit, tm, sm, s, gm = sig
        
        if rsiL < ltf_min or rsiL > ltf_max: continue
        if rsiH < htf_min or rsiH > htf_max: continue
        if adx < adx_min: continue
        if cr is not None and (cr < cr_min or cr > cr_max): continue
        if mcap < mcap_min: continue
        
        # Pre-Final
        if max_high_lf_min is not None and close_lf_min is not None:
            if sl_hit: continue
            if maxHighLfPct is None or maxHighLfPct < max_high_lf_min: continue
            if closeLfPct is None or closeLfPct < close_lf_min: continue
        elif max_high_lf_min is not None:
            if sl_hit: continue
            if maxHighLfPct is None or maxHighLfPct < max_high_lf_min: continue
        elif close_lf_min is not None:
            if sl_hit: continue
            if closeLfPct is None or closeLfPct < close_lf_min: continue

        accepted.append((s, gm, True))
        
        if thit:
            sum_thit += max(to_finite(tm, 0), 0)
        elif shit:
            sum_shit += abs(to_finite(sm, 0))
        
    c = len(accepted)
    # Target trades >= 180
    if c < 180 or c > 350:
        return None
        
    avg_ret = (sum_thit - sum_shit) / c if c > 0 else 0
    
    final_pnl, max_dd = run_portfolio_simulation(accepted)
    
    return (c, max_dd, final_pnl, avg_ret, (ltf_min, ltf_max, htf_min, htf_max, adx_min, cr_min, cr_max, mcap_min, max_high_lf_min, close_lf_min))

if __name__ == '__main__':
    output_dir = r'd:\backtesting\backtesting\output'
    json_files = glob.glob(os.path.join(output_dir, '*.json'))
    latest_file = max(json_files, key=os.path.getctime)
    
    print(f"\nLoading data from: {os.path.basename(latest_file)}")
    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    signals = data.get('signals', [])
    
    # Pre-process signals
    compact_signals = []
    for s in signals:
        if s.get('entry_rejected'): continue
        gm = s.get('gap_up_modes', {}).get('gap_up_sl_target_update', {})
        if gm.get('entry_rejected') or gm.get('valid') is False: continue
        
        rsiL = s.get('rsi')
        rsiH = s.get('rsi_HTF')
        adx = s.get('adx')
        if rsiL is None or rsiH is None or adx is None: continue
        
        cr = None
        if s.get('signal_open') and s.get('signal_open') > 0:
            cr = (s['signal_high'] - s['signal_low']) / s['signal_open'] * 100
            
        mcap = COMPANY_MARKET_CAPS.get(s['company'], 0)
        
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
        
        # Metrics for avg return (assuming Pre-Final active always)
        source = gm.get('close_lf_replay', {})
        thit = source.get('target_hit') if source.get('target_hit') is not None else gm.get('target_hit') if gm.get('target_hit') is not None else s.get('target_hit')
        shit = source.get('stoploss_hit') if source.get('stoploss_hit') is not None else gm.get('stoploss_hit') if gm.get('stoploss_hit') is not None else s.get('stoploss_hit')
        tm = source.get('target_hit_metrics') if source.get('target_hit_metrics') is not None else gm.get('target_hit_metrics') if gm.get('target_hit_metrics') is not None else s.get('target_hit_metrics')
        sm = source.get('stoploss_hit_metrics') if source.get('stoploss_hit_metrics') is not None else gm.get('stoploss_hit_metrics') if gm.get('stoploss_hit_metrics') is not None else s.get('stoploss_hit_metrics')
        
        compact_signals.append((rsiL, rsiH, adx, cr, mcap, sl_hit is True, maxHighLfPct, closeLfPct, thit, shit, tm, sm, s, gm))

    # Grid Search space - focused on maximizing trades >= 180 with solid parameters
    ltf_mins = [50, 60, 65]
    ltf_maxs = [80, 85]
    htf_mins = [40, 50, 60, 65]
    htf_maxs = [80, 85]
    adx_mins = [15, 20, 25]
    cr_mins = [2, 3]
    cr_maxs = [8, 10, 15, 20, 25]
    mcap_mins = [2000, 5000, 8000]
    max_high_lf_mins = [None, 1.0, 2.0, 3.0]
    close_lf_mins = [None, -1.0, 0.0]
    
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
                                            combinations.append((ltf_min, ltf_max, htf_min, htf_max, adx_min, cr_min, cr_max, mcap_min, mhl, clf, compact_signals))
                                            
    print(f"Evaluating {len(combinations)} combinations strictly matching >= 180 trades...\n")
    
    # Process in chunks
    with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as pool:
        results = pool.map(fast_evaluate, combinations, chunksize=5000)
        
    results_valid = [r for r in results if r is not None]
    
    # Sort for absolute lowest DD while having >= 180 trades
    def score_combo(r):
        c, max_dd, pnl, avg_ret, args = r
        return max_dd

    results_sorted = sorted(results_valid, key=score_combo)
    
    print("=== TOP 3 ULTIMATE COMBINATIONS (>= 180 TRADES, HIGH RETURN, LOW DD) ===")
    seen_combos = set()
    count = 0
    for r in results_sorted:
        c, max_dd, pnl, avg_ret, args = r
        # Deduplicate very similar results
        key = (args[4], args[7], args[8], args[9]) # ADX, Mcap, MHLF, CLF
        if key in seen_combos:
            continue
        seen_combos.add(key)
        
        count += 1
        print(f"Rank {count}:")
        print(f"  Final Confirmed Trades: {c}")
        print(f"  Max Drawdown (4x MTF): {max_dd:.2f}%")
        print(f"  Avg Return per Trade: {avg_ret:.2f}%")
        print(f"  Simulated Final PNL: Rs {pnl:,.2f}")
        print(f"  Parameters:")
        print(f"    LTF RSI: {args[0]} - {args[1]} | HTF RSI: {args[2]} - {args[3]}")
        print(f"    ADX >= {args[4]} | Range (%): {args[5]} - {args[6]}")
        print(f"    Market Cap >= {args[7]}")
        print(f"    Max High LF >= {args[8]}% | Close LF >= {args[9]}%\n")
        
        if count >= 3:
            break

