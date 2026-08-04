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
    
    # 1. Apply gap up mode
    gm = s.get('gap_up_modes', {}).get('gap_up_sl_target_update', {})
    if gm:
        s.update(gm)
    
    # 2. Basic rejected filters
    if s.get('entry_rejected') or s.get('valid') is False: continue
    
    # 3. Live UI Filters
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
        # Pre-final passed! In the UI, if close_lf_active is true (which it is here), we apply replay
        replay = s.get('close_lf_replay', {})
        if replay and replay.get('valid'):
            # The UI applies specific keys, or Object.assign?
            # It uses a specific mapping for replay in updated_backtester.html (around line 7800)
            # but then it basically overwrites target_hit, stoploss_hit, etc.
            s.update(replay)
            s['target_hit'] = bool(replay.get('target_hit'))
            s['stoploss_hit'] = bool(replay.get('stoploss_hit'))
        accepted_signals.append(s)

targetHits = [s for s in accepted_signals if s.get('target_hit')]
stoplossHits = [s for s in accepted_signals if s.get('stoploss_hit')]

posExcTarget = [s for s in accepted_signals if not s.get('target_hit') and not s.get('stoploss_hit') and (getTradeOutcomeMetric(s) or 0) > 0]
negExcStoploss = [s for s in accepted_signals if not s.get('target_hit') and not s.get('stoploss_hit') and (getTradeOutcomeMetric(s) or 0) < 0]

# UI Bug reproduction: double counting stoploss_hit if it had partial targets
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

print(f"Total Trades: {len(accepted_signals)}")
print(f"Pre_Final Trades: {len(filtered_signals)}")
print(f"Final Confirmed: {len(accepted_signals)}")
print(f"Pre_Final Rejected: {len(filtered_signals) - len(accepted_signals)}")
print(f"Target Hits (Count / %): {len(targetHits)} / {(len(targetHits)/len(accepted_signals)*100 if accepted_signals else 0):.2f}%")
print(f"Stoploss Hits (Count / %): {len(stoplossHits)} / {(len(stoplossHits)/len(accepted_signals)*100 if accepted_signals else 0):.2f}%")
print(f"Pos / Target / Total Positive: {len(posExcTarget)} / {len(targetHits)} / {total_positive}")
print(f"Neg / Stoploss / Total Negative: {len(negExcStoploss)} / {len(stoplossHits)} / {total_negative}")
print(f"Win Rate (Target Hit): {(len(targetHits)/len(accepted_signals)*100 if accepted_signals else 0):.2f}%")
print(f"Avg Return / Trade: {avgReturn:.2f}%")
