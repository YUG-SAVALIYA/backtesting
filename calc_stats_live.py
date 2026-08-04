import json, glob, os
from test_diff import COMPANY_MARKET_CAPS

f = max(glob.glob('output/*.json'), key=os.path.getctime)
data = json.load(open(f, 'r', encoding='utf-8'))
signals = data.get('signals', [])

def toFiniteNumber(val, default):
    try:
        if val is None: return default
        return float(val)
    except:
        return default

def hasTradeManagementPartialBook(s):
    booked = s.get('trade_management_booked_qty_pct')
    return booked is not None and float(booked) > 0

def getTradeOutcomeMetric(s):
    tm_ret = s.get('trade_management_weighted_return_pct')
    if tm_ret is not None and hasTradeManagementPartialBook(s):
        return toFiniteNumber(tm_ret, 0)
        
    thit = s.get('target_hit')
    shit = s.get('stoploss_hit')
    tm = s.get('target_hit_metrics')
    sm = s.get('stoploss_hit_metrics')
    em = s.get('expired_metrics')
    
    if thit:
        return toFiniteNumber(tm, 0)
    if shit:
        return toFiniteNumber(sm, 0)
    return toFiniteNumber(em, 0)

filtered_signals = []
for s_orig in signals:
    s = s_orig.copy()
    
    gm = s.get('gap_up_modes', {}).get('gap_up_sl_target_update', {})
    if gm:
        s.update(gm)
    
    if s.get('entry_rejected') or s.get('valid') is False: continue
    
    rsiL = toFiniteNumber(s.get('rsi'), None)
    rsiH = toFiniteNumber(s.get('rsi_HTF'), None)
    if rsiL is None or not (55 <= rsiL <= 85): continue
    if rsiH is None or not (65 <= rsiH <= 85): continue
    
    cr = None
    if s.get('signal_open') and s.get('signal_open') > 0:
        cr = (s['signal_high'] - s['signal_low']) / s['signal_open'] * 100
    if cr is None or not (3 <= cr <= 8): continue
        
    mcap = COMPANY_MARKET_CAPS.get(s.get('company'), 0)
    if mcap < 8000: continue
    
    filtered_signals.append(s)

# IN LIVE SCAN, THERE IS NO PRE-FINAL LOOKAHEAD FILTER!
accepted_signals = filtered_signals

pos_count = 0
neg_count = 0
sum_return = 0

target_hits_true = 0
stoploss_hits_true = 0
trailing_sl_winners = 0

for s in accepted_signals:
    ret = getTradeOutcomeMetric(s) or 0
    sum_return += ret
    
    if ret > 0:
        pos_count += 1
    elif ret < 0:
        neg_count += 1
        
    thit = s.get('target_hit')
    shit = s.get('stoploss_hit')
    
    if thit:
        target_hits_true += 1
    elif shit:
        if ret > 0:
            trailing_sl_winners += 1
        else:
            stoploss_hits_true += 1

avg_return = sum_return / len(accepted_signals) if len(accepted_signals) > 0 else 0
win_rate = (pos_count / len(accepted_signals) * 100) if len(accepted_signals) > 0 else 0

print(f"--- REAL LIVE SCAN EQUIVALENT RESULTS (No Lookahead/Pre-Final) ---")
print(f"Total Trades Taken: {len(accepted_signals)}")
print(f"Full Target Hits: {target_hits_true}")
print(f"Trailing SL Winners: {trailing_sl_winners}")
print(f"True Stoploss Hits (Losers): {stoploss_hits_true}")
print(f"Total Positive Trades: {pos_count}")
print(f"Total Negative Trades: {neg_count}")
print(f"True Win Rate: {win_rate:.2f}%")
print(f"True Avg Return / Trade: {avg_return:.2f}%")
