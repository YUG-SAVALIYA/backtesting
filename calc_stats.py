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

def hasTradeManagementPartialBook(s, gm):
    booked = gm.get('trade_management_booked_qty_pct') if gm.get('trade_management_booked_qty_pct') is not None else s.get('trade_management_booked_qty_pct')
    return booked is not None and float(booked) > 0

def getTradeOutcomeMetric(s, gm):
    tm_ret = gm.get('trade_management_weighted_return_pct') if gm.get('trade_management_weighted_return_pct') is not None else s.get('trade_management_weighted_return_pct')
    
    if tm_ret is not None and hasTradeManagementPartialBook(s, gm):
        return toFiniteNumber(tm_ret, 0)
        
    thit = gm.get('target_hit') if gm.get('target_hit') is not None else s.get('target_hit')
    shit = gm.get('stoploss_hit') if gm.get('stoploss_hit') is not None else s.get('stoploss_hit')
    tm = gm.get('target_hit_metrics') if gm.get('target_hit_metrics') is not None else s.get('target_hit_metrics')
    sm = gm.get('stoploss_hit_metrics') if gm.get('stoploss_hit_metrics') is not None else s.get('stoploss_hit_metrics')
    em = gm.get('expired_metrics') if gm.get('expired_metrics') is not None else s.get('expired_metrics')
    
    if thit:
        return toFiniteNumber(tm, 0)
    if shit:
        return toFiniteNumber(sm, 0)
    return toFiniteNumber(em, 0)

raw_trades = []
pre_final_trades = []
final_trades = []

for s in signals:
    if s.get('entry_rejected'): continue
    gm = s.get('gap_up_modes', {}).get('gap_up_sl_target_update', {})
    if gm.get('entry_rejected') or gm.get('valid') is False: continue
    raw_trades.append(s)

for s in raw_trades:
    gm = s.get('gap_up_modes', {}).get('gap_up_sl_target_update', {})
    
    baseRef = gm.get('original_entry') or s.get('signal_high') or s.get('entry')
    closeH = gm.get('close_lookahead') if gm.get('close_lookahead') is not None else s.get('close_lookahead')
    closeLfPct = None
    if closeH is not None and baseRef and baseRef > 0:
        closeLfPct = (closeH - baseRef) / baseRef * 100
        
    maxH = gm.get('max_high_lookahead') if gm.get('max_high_lookahead') is not None else s.get('max_high_lookahead')
    maxHighLfPct = None
    if maxH is not None and baseRef and baseRef > 0:
        maxHighLfPct = (maxH - baseRef) / baseRef * 100
        
    sl_hit = gm.get('sl_hit_lookahead') if gm.get('sl_hit_lookahead') is not None else s.get('sl_hit_lookahead')
    if sl_hit is True: continue
    if maxHighLfPct is None or maxHighLfPct < 3.0: continue
    if closeLfPct is None or closeLfPct < 0.0: continue
    
    pre_final_trades.append(s)

for s in pre_final_trades:
    rsiL = toFiniteNumber(s.get('rsi'), None)
    rsiH = toFiniteNumber(s.get('rsi_HTF'), None)
    
    if rsiL is None or not (55 <= rsiL <= 85): continue
    if rsiH is None or not (65 <= rsiH <= 85): continue
    
    cr = None
    if s.get('signal_open') and s.get('signal_open') > 0:
        cr = (s['signal_high'] - s['signal_low']) / s['signal_open'] * 100
    if cr is None or not (3 <= cr <= 8): continue
        
    mcap = COMPANY_MARKET_CAPS.get(s['company'], 0)
    if mcap < 8000: continue
    
    final_trades.append(s)

pos_count = 0
neg_count = 0
sum_return = 0

for s in final_trades:
    gm = s.get('gap_up_modes', {}).get('gap_up_sl_target_update', {})
    ret = getTradeOutcomeMetric(s, gm)
    sum_return += ret
    if ret > 0:
        pos_count += 1
    elif ret < 0:
        neg_count += 1

avg_return = sum_return / len(final_trades) if len(final_trades) > 0 else 0

print(f"Raw Trades: {len(raw_trades)}")
print(f"Pre-Final Trades: {len(pre_final_trades)}")
print(f"Final Trades: {len(final_trades)}")
print(f"Pos: {pos_count}")
print(f"Neg: {neg_count}")
print(f"Avg Return: {avg_return:.2f}%")
