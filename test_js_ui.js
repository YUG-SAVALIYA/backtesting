const fs = require('fs');
const html = fs.readFileSync('static/index.html', 'utf-8');

// Extract the MARKET_CAP_RS_CR variable
const mcapMatch = html.match(/const MARKET_CAP_RS_CR\s*=\s*(\{.*?\});/s);
let MARKET_CAP_RS_CR = {};
if (mcapMatch) {
    MARKET_CAP_RS_CR = eval('(' + mcapMatch[1] + ')');
}

function getCompanyMarketCapCr(symbol) {
    const key = String(symbol || '').trim().toUpperCase();
    return Object.prototype.hasOwnProperty.call(MARKET_CAP_RS_CR, key) ? MARKET_CAP_RS_CR[key] : null;
}

// Load JSON
const data = JSON.parse(fs.readFileSync('output/backtest_2026-07-31_22-16-17_2102stocks.json', 'utf-8'));
const allSignals = data.signals || [];

// Mock UI filter values based on the screenshot
const rsiMin = 65;
const rsiMax = 80;
const rsiHtfMin = 65;
const rsiHtfMax = 85;
const cmfMin = null;
const relVolMin = null;
const atrMin = null;
const adxMin = 26;
const rangeMin = 3;
const rangeMax = 8;
const bodyMin = 0;
const bodyMax = 1000;
const maxHighThreshold = null;
const maxHighLfThreshold = null;
const closeLfMin = null;
const closeLfMax = null;
const closeLfActive = false;
const entryDiffActive = false;
const entryDiffMin = null;
const entryDiffMax = null;
const gapUpModeFilter = 'gap_up_sl_target_update';
const emaFilter = 'ALL';
const htfTrendFilter = 'ALL';
const openVsEntryFilter = 'ALL';
const entryDayFilter = 'ALL';
const niftyIndexFilter = 'ALL';
const marketCapMin = 8000;
const marketCapMax = null;

function getOpenComparedWithEntryLabel(relation) {
    if (relation === 'higher') return 'Higher';
    if (relation === 'lower') return 'Lower';
    if (relation === 'equal') return 'Equal';
    return null;
}

function getGapUpModeKeys(mode) {
    return [mode, mode.replace('gap_up_', '')];
}

function getGapUpModeLabel(mode) {
    return mode;
}

function normalizeTradeDerivedMetrics(t) { return t; }

function materializeTradeForGapUpMode(signal, modeKey) {
    if (!signal) return null;
    const normalizedMode = modeKey || 'existing_entry';
    const baseTrade = { ...signal };
    const originalEntry = parseFloat(baseTrade.original_entry ?? baseTrade.entry);
    
    const selectedModeKey = baseTrade.gap_up_modes 
        ? getGapUpModeKeys(normalizedMode).find(key => baseTrade.gap_up_modes[key]) 
        : null;
    const selectedMode = selectedModeKey ? { ...baseTrade.gap_up_modes[selectedModeKey] } : null;
    
    const resolvedTrade = selectedMode ? { ...baseTrade, ...selectedMode } : baseTrade;
    resolvedTrade.selected_gap_up_mode = normalizedMode;
    resolvedTrade.gap_up_handling_mode = resolvedTrade.gap_up_handling_mode || getGapUpModeLabel(normalizedMode);
    resolvedTrade.original_entry = Number.isFinite(originalEntry) ? originalEntry : (resolvedTrade.original_entry ?? null);
    resolvedTrade.original_target = resolvedTrade.original_target ?? baseTrade.Target;
    resolvedTrade.original_stoploss = resolvedTrade.original_stoploss ?? baseTrade.Stoploss;
    resolvedTrade.new_entry = resolvedTrade.new_entry ?? resolvedTrade.entry;
    resolvedTrade.new_stoploss = resolvedTrade.new_stoploss ?? resolvedTrade.Stoploss;
    resolvedTrade.new_target = resolvedTrade.new_target ?? resolvedTrade.Target;
    resolvedTrade.entry_source = resolvedTrade.entry_source || resolvedTrade.entry_reason || getGapUpModeLabel(normalizedMode);
    resolvedTrade.open_compared_with_entry = resolvedTrade.open_compared_with_entry || getOpenComparedWithEntryLabel(resolvedTrade.entry_open_relation);
    resolvedTrade.open_check_day = resolvedTrade.open_check_day || (resolvedTrade.entry_open_day != null ? `Day-${resolvedTrade.entry_open_day}` : null);
    resolvedTrade.entry_rejected = !!resolvedTrade.entry_rejected;
    resolvedTrade.reject_reason = resolvedTrade.reject_reason || null;
    resolvedTrade.valid = resolvedTrade.valid !== false;
    return normalizeTradeDerivedMetrics(resolvedTrade);
}

function toFiniteNumber(v, fallback) {
    if (v == null) return fallback;
    const n = Number(v);
    return Number.isFinite(n) ? n : fallback;
}

let processedSignals = allSignals.map(s => {
    if (!s) return null;
    let trade = materializeTradeForGapUpMode(s, gapUpModeFilter);
    const originalEntry = parseFloat(trade.original_entry ?? trade.entry);
    trade.original_entry = isNaN(originalEntry) ? null : originalEntry;
    trade.selected_gap_up_mode = trade.selected_gap_up_mode || gapUpModeFilter;
    trade.gap_up_handling_mode = trade.gap_up_handling_mode || getGapUpModeLabel(trade.selected_gap_up_mode);
    return normalizeTradeDerivedMetrics(trade);
}).filter(s => s !== null);

let filteredSignals = processedSignals.filter(s => {
    let pass = true;

    // RSI LTF
    if (rsiMin !== null && (s.rsi == null || s.rsi < rsiMin)) pass = false;
    if (rsiMax !== null && (s.rsi == null || s.rsi > rsiMax)) pass = false;

    // RSI HTF
    if (rsiHtfMin !== null && (s.rsi_HTF == null || s.rsi_HTF < rsiHtfMin)) pass = false;
    if (rsiHtfMax !== null && (s.rsi_HTF == null || s.rsi_HTF > rsiHtfMax)) pass = false;

    // CMF
    if (cmfMin !== null && (s.cmf == null || s.cmf < cmfMin)) pass = false;

    // Rel Vol
    if (relVolMin !== null && (s.rel_vol == null || s.rel_vol < relVolMin)) pass = false;

    // ATR
    if (atrMin !== null && (s.atr == null || s.atr < atrMin)) pass = false;

    // ADX
    if (adxMin !== null && (s.adx == null || s.adx < adxMin)) pass = false;

    // Range calculation
    if (rangeMin > 0 || rangeMax < 1000) {
        const signalOpen = toFiniteNumber(s.signal_open, null);
        if (signalOpen != null && signalOpen > 0) {
            const signalHigh = toFiniteNumber(s.signal_high, null);
            const signalLow = toFiniteNumber(s.signal_low, null);
            if (signalHigh != null && signalLow != null) {
                const candleRangePct = ((signalHigh - signalLow) / signalOpen) * 100;
                if (candleRangePct < rangeMin || candleRangePct > rangeMax) pass = false;
            } else pass = false;
        } else pass = false;
    }

    // Body calculation
    if (bodyMin > 0 || bodyMax < 1000) {
        const signalOpen = toFiniteNumber(s.signal_open, null);
        const signalClose = toFiniteNumber(s.signal_close, null);
        if (signalOpen != null && signalOpen > 0 && signalClose != null) {
            const bodyPct = (Math.abs(signalClose - signalOpen) / signalOpen) * 100;
            if (bodyPct < bodyMin || bodyPct > bodyMax) pass = false;
        } else pass = false;
    }

    // Max High Lookforward Filter
    if (maxHighThreshold !== null && s.max_high_pct > maxHighThreshold) {
        pass = false;
    }
    
    // EMA
    if (emaFilter !== 'ALL') {
        if (s.price_vs_ema20 !== emaFilter) pass = false;
    }
    
    // HTF Trend
    if (htfTrendFilter !== 'ALL') {
        if (htfTrendFilter === 'UPTREND' && s.in_uptrend_htf !== true) pass = false;
        if (htfTrendFilter === 'DOWNTREND' && s.in_uptrend_htf === true) pass = false;
    }

    // Open vs Entry
    if (openVsEntryFilter !== 'ALL' && s.entry_open_relation !== openVsEntryFilter) {
        pass = false;
    }

    // Entry Day
    if (entryDayFilter !== 'ALL' && String(s.entry_open_day) !== entryDayFilter) {
        pass = false;
    }
    
    // Market Cap
    if (marketCapMin !== null || marketCapMax !== null) {
        const marketCapCr = getCompanyMarketCapCr(s.company);
        if (marketCapCr == null) pass = false;
        if (marketCapMin !== null && marketCapCr < marketCapMin) pass = false;
        if (marketCapMax !== null && marketCapCr > marketCapMax) pass = false;
    }

    if (!pass) return false;
    
    // VALIDITY checks
    if (s.valid === false) return false;
    return true;
});

const acceptedSignals = filteredSignals.filter(s => !s.entry_rejected);
console.log("Total Trades based strictly on JS code:", acceptedSignals.length);
