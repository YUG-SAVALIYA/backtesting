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
        
    mcap = COMPANY_MARKET_CAPS.get(s['company'], 0)
    if mcap < 8000: continue
    
    filtered_signals.append(s)

accepted_signals = []
for s in filtered_signals:
    baseRef = s.get('original_entry') or s.get('signal_high') or s.get('entry')
    closeH = s.get('close_lookahead')
    closeLfPct = None
    if closeH is not None and baseRef and baseRef > 0:
        closeLfPct = (closeH - baseRef) / baseRef * 100
        
    maxH = s.get('max_high_lookahead')
    maxHighLfPct = None
    if maxH is not None and baseRef and baseRef > 0:
        maxHighLfPct = (maxH - baseRef) / baseRef * 100
        
    sl_hit = s.get('sl_hit_lookahead')
    
    fails = False
    if sl_hit is True: fails = True
    elif maxHighLfPct is None or maxHighLfPct < 3.0: fails = True
    elif closeLfPct is None or closeLfPct < 0.0: fails = True
    
    if not fails:
        accepted_signals.append(s)

targetHits = [s for s in accepted_signals if s.get('target_hit')]
stoplossHits = [s for s in accepted_signals if s.get('stoploss_hit')]

posExcTarget = [s for s in accepted_signals if not s.get('target_hit') and not s.get('stoploss_hit') and (getTradeOutcomeMetric(s) or 0) > 0]
negExcStoploss = [s for s in accepted_signals if not s.get('target_hit') and not s.get('stoploss_hit') and (getTradeOutcomeMetric(s) or 0) < 0]

sumTargetHitPct = sum([max(getTradeOutcomeMetric(s) or 0, 0) for s in targetHits])
sumStoplossHitPct = sum([abs(getTradeOutcomeMetric(s) or 0) for s in stoplossHits])
sumPosExcTargetPct = sum([abs(getTradeOutcomeMetric(s) or 0) for s in posExcTarget])
sumNegExcStoplossPct = sum([abs(getTradeOutcomeMetric(s) or 0) for s in negExcStoploss])

total_positive = len(posExcTarget) + len(targetHits)
total_negative = len(negExcStoploss) + len(stoplossHits)

sumPosPct = sumTargetHitPct + sumPosExcTargetPct
sumNegPct = sumStoplossHitPct + sumNegExcStoplossPct
netProfit = sumPosPct - sumNegPct
avgReturn = netProfit / len(accepted_signals) if len(accepted_signals) > 0 else 0

print(f"Final Confirmed: {len(accepted_signals)}")
print(f"Target Hits (Count): {len(targetHits)}")
print(f"Stoploss Hits (Count): {len(stoplossHits)}")
print(f"Pos / Target / Total Positive: {len(posExcTarget)} / {len(targetHits)} / {total_positive}")
print(f"Neg / Stoploss / Total Negative: {len(negExcStoploss)} / {len(stoplossHits)} / {total_negative}")
print(f"Avg Return: {avgReturn:.2f}%")
