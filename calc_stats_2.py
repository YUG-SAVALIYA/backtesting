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
    # In JS:
    # const hitQty = toFiniteNumber(trade?.trade_management_booked_qty_pct, ...)
    # return hitQty > 0;
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

filtered_signals = []
for s in signals:
    if s.get('entry_rejected'): continue
    gm = s.get('gap_up_modes', {}).get('gap_up_sl_target_update', {})
    if gm.get('entry_rejected') or gm.get('valid') is False: continue
    
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
    
    filtered_signals.append(s)

pre_final_rejected = []
accepted_signals = []

for s in filtered_signals:
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
    
    fails = False
    if sl_hit is True: fails = True
    elif maxHighLfPct is None or maxHighLfPct < 3.0: fails = True
    elif closeLfPct is None or closeLfPct < 0.0: fails = True
    
    if fails:
        pre_final_rejected.append(s)
    else:
        accepted_signals.append(s)

targetHits = []
stoplossHits = []
posExcTarget = []
negExcStoploss = []

sumTargetHitPct = 0
sumStoplossHitPct = 0
sumPosExcTargetPct = 0
sumNegExcStoplossPct = 0

for s in accepted_signals:
    gm = s.get('gap_up_modes', {}).get('gap_up_sl_target_update', {})
    thit = gm.get('target_hit') if gm.get('target_hit') is not None else s.get('target_hit')
    shit = gm.get('stoploss_hit') if gm.get('stoploss_hit') is not None else s.get('stoploss_hit')
    ret = getTradeOutcomeMetric(s, gm)
    
    if thit:
        targetHits.append(s)
        sumTargetHitPct += max(ret, 0)
    elif shit:
        stoplossHits.append(s)
        sumStoplossHitPct += abs(ret)
    else:
        if ret > 0:
            posExcTarget.append(s)
            sumPosExcTargetPct += abs(ret)
        elif ret < 0:
            negExcStoploss.append(s)
            sumNegExcStoplossPct += abs(ret)

total_positive = len(posExcTarget) + len(targetHits)
total_negative = len(negExcStoploss) + len(stoplossHits)

sumPosPct = sumTargetHitPct + sumPosExcTargetPct
sumNegPct = sumStoplossHitPct + sumNegExcStoplossPct
netProfit = sumPosPct - sumNegPct
avgReturn = netProfit / len(accepted_signals) if len(accepted_signals) > 0 else 0

print(f"Pre_Final Trades: {len(filtered_signals)}")
print(f"Final Confirmed: {len(accepted_signals)}")
print(f"Pre_Final Rejected: {len(pre_final_rejected)}")
print(f"Target Hits (Count): {len(targetHits)}")
print(f"Stoploss Hits (Count): {len(stoplossHits)}")
print(f"Pos / Target / Total Positive: {len(posExcTarget)} / {len(targetHits)} / {total_positive}")
print(f"Neg / Stoploss / Total Negative: {len(negExcStoploss)} / {len(stoplossHits)} / {total_negative}")
print(f"Avg Return: {avgReturn:.2f}%")
