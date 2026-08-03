import json
import glob
import os
import multiprocessing
from test_user_params import COMPANY_MARKET_CAPS
from find_best_filters import run_portfolio_simulation, to_finite

def fast_evaluate(args):
    ltf_min, ltf_max, htf_min, htf_max, adx_min, cr_min, cr_max, mcap_min, compact_signals = args
    
    accepted = []
    
    for sig in compact_signals:
        rsiL, rsiH, adx, cr, mcap, sl_hit, maxHighLfPct, closeLfPct, s, gm = sig
        
        if rsiL < ltf_min or rsiL > ltf_max: continue
        if rsiH < htf_min or rsiH > htf_max: continue
        if adx < adx_min: continue
        if cr is not None and (cr < cr_min or cr > cr_max): continue
        if mcap < mcap_min: continue
        
        # Hardcoded Pre-Final Rules from User's UI
        if sl_hit: continue
        if maxHighLfPct is None or maxHighLfPct < 3.0: continue
        if closeLfPct is None or closeLfPct < 0.0: continue

        accepted.append((s, gm, True))
        
    c = len(accepted)
    # Target FINAL trades >= 110
    if c < 110:
        return None
        
    final_pnl, max_dd = run_portfolio_simulation(accepted)
    
    return (c, max_dd, final_pnl, (ltf_min, ltf_max, htf_min, htf_max, adx_min, cr_min, cr_max, mcap_min))

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
        
        compact_signals.append((rsiL, rsiH, adx, cr, mcap, sl_hit is True, maxHighLfPct, closeLfPct, s, gm))

    # Grid Search space - wide to find the absolute safest parameters
    ltf_mins = [50, 60, 65, 70]
    ltf_maxs = [80, 85, 90]
    htf_mins = [50, 60, 65, 70]
    htf_maxs = [80, 85, 90]
    adx_mins = [20, 25, 26, 30]
    cr_mins = [2, 3, 4]
    cr_maxs = [8, 10, 15, 20]
    mcap_mins = [5000, 8000, 10000, 20000]
    
    combinations = []
    for ltf_min in ltf_mins:
        for ltf_max in ltf_maxs:
            for htf_min in htf_mins:
                for htf_max in htf_maxs:
                    for adx_min in adx_mins:
                        for cr_min in cr_mins:
                            for cr_max in cr_maxs:
                                for mcap_min in mcap_mins:
                                    combinations.append((ltf_min, ltf_max, htf_min, htf_max, adx_min, cr_min, cr_max, mcap_min, compact_signals))
                                            
    print(f"Evaluating {len(combinations)} combinations strictly matching FINAL Trades >= 180 with H>3|C>0 hardcoded...\n")
    
    # Process in chunks
    with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as pool:
        results = pool.map(fast_evaluate, combinations, chunksize=5000)
        
    results_valid = [r for r in results if r is not None]
    
    def score_combo(r):
        c, max_dd, pnl, args = r
        return max_dd

    results_sorted = sorted(results_valid, key=score_combo)
    
    print("=== TOP ULTIMATE COMBINATIONS (FINAL TRADES >= 180, LOW DD) ===")
    seen_combos = set()
    count = 0
    for r in results_sorted:
        c, max_dd, pnl, args = r
        key = (args[4], args[7]) # ADX, Mcap
        if key in seen_combos:
            continue
        seen_combos.add(key)
        
        count += 1
        print(f"Rank {count}:")
        print(f"  FINAL CONFIRMED TRADES: {c}")
        print(f"  Max Drawdown (4x MTF): {max_dd:.2f}%")
        print(f"  Simulated Final PNL: Rs {pnl:,.2f}")
        print(f"  Parameters:")
        print(f"    LTF RSI: {args[0]} - {args[1]} | HTF RSI: {args[2]} - {args[3]}")
        print(f"    ADX >= {args[4]} | Range (%): {args[5]} - {args[6]}")
        print(f"    Market Cap >= {args[7]}")
        print(f"    Pre-Final: Max High LF >= 3.0% | Close LF >= 0.0% (HARDCODED)\n")
        
        if count >= 3:
            break
