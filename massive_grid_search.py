import json
import glob
import os
import multiprocessing
from test_user_params import COMPANY_MARKET_CAPS
from find_best_filters import run_portfolio_simulation, get_sim_day_key, parse_sim_date

def fast_evaluate(args):
    ltf_min, ltf_max, htf_min, htf_max, adx_min, cr_min, cr_max, mcap_min, max_high_lf_min, close_lf_min, compact_signals = args
    
    accepted = []
    
    for sig in compact_signals:
        rsiL, rsiH, adx, cr, mcap, sl_hit, maxHighLfPct, closeLfPct, s, gm = sig
        
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
        
    c = len(accepted)
    # Fast exit if trades not in target range (around 200 trades)
    if c < 150 or c > 280:
        return None
        
    final_pnl, max_dd = run_portfolio_simulation(accepted)
    
    return (c, max_dd, final_pnl, (ltf_min, ltf_max, htf_min, htf_max, adx_min, cr_min, cr_max, mcap_min, max_high_lf_min, close_lf_min))

if __name__ == '__main__':
    output_dir = r'd:\backtesting\backtesting\output'
    json_files = glob.glob(os.path.join(output_dir, '*.json'))
    latest_file = max(json_files, key=os.path.getctime)
    
    print(f"\nLoading data from: {os.path.basename(latest_file)}")
    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    signals = data.get('signals', [])
    
    # Pre-process signals into compact tuples for maximum loop speed
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

    print(f"Pre-processed {len(compact_signals)} valid base signals.")

    # Grid Search space
    ltf_mins = [50, 60, 65, 70]
    ltf_maxs = [80, 85]
    htf_mins = [40, 50, 60, 65, 70]
    htf_maxs = [80, 85]
    adx_mins = [15, 20, 25, 26]
    cr_mins = [2, 3, 4]
    cr_maxs = [8, 10, 15, 20, 25]
    mcap_mins = [5000, 8000, 10000, 20000]
    max_high_lf_mins = [None, 2.0, 3.0, 4.0]
    close_lf_mins = [None, -1.0, 0.0, 1.0]
    
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
                                            
    print(f"Evaluating {len(combinations)} combinations strictly matching your UI's simulation...\n")
    
    # Process in chunks
    with multiprocessing.Pool(processes=multiprocessing.cpu_count()) as pool:
        results = pool.map(fast_evaluate, combinations, chunksize=5000)
        
    results_valid = [r for r in results if r is not None]
    
    print("=== TOP 15 COMBINATIONS BY LOWEST MAX DRAWDOWN (~200 TRADES) ===")
    results_dd = sorted(results_valid, key=lambda x: x[1])
    for i, r in enumerate(results_dd[:15]):
        c, max_dd, pnl, args = r
        print(f"{i+1}. Trades: {c}, Max DD: {max_dd:.2f}%, Final PNL: Rs {pnl:,.2f}")
        print(f"    LTF RSI {args[0]}-{args[1]}, HTF RSI {args[2]}-{args[3]}, ADX >= {args[4]}")
        print(f"    Range: {args[5]}% to {args[6]}%, Mcap >= {args[7]} Cr")
        print(f"    Max High LF >= {args[8]}%, Close LF >= {args[9]}%\n")

    print("=== TOP 15 COMBINATIONS BY SIMULATED FINAL PNL (~200 TRADES) ===")
    results_pnl = sorted(results_valid, key=lambda x: x[2], reverse=True)
    for i, r in enumerate(results_pnl[:15]):
        c, max_dd, pnl, args = r
        print(f"{i+1}. Trades: {c}, Max DD: {max_dd:.2f}%, Final PNL: Rs {pnl:,.2f}")
        print(f"    LTF RSI {args[0]}-{args[1]}, HTF RSI {args[2]}-{args[3]}, ADX >= {args[4]}")
        print(f"    Range: {args[5]}% to {args[6]}%, Mcap >= {args[7]} Cr")
        print(f"    Max High LF >= {args[8]}%, Close LF >= {args[9]}%\n")
