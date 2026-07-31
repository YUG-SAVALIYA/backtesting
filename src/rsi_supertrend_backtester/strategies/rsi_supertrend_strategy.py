from __future__ import annotations
from dataclasses import dataclass
from typing import Any
import numpy as np
import pandas as pd
from rsi_supertrend_backtester.core.indicators import add_macd, add_rsi, add_supertrend, add_atr, add_rel_vol, add_cmf, add_adx, add_ema
from rsi_supertrend_backtester.core.models import TradeSignal
GAP_UP_MODE_EXISTING = 'existing_entry'
GAP_UP_MODE_PULLBACK = 'pull_back_entry'
GAP_UP_MODE_GAP_ENTRY = 'gap_up_entry'
GAP_UP_MODE_GAP_UPDATE = 'gap_up_sl_target_update'
STOPLOSS_MODE_SIGNAL_LOW = 'signal_candle_low'
STOPLOSS_MODE_LF_LOW = 'lf_candle_low'
STOPLOSS_MODE_DAILY_SUPERTREND = 'daily_supertrend'
STOPLOSS_MODES = {STOPLOSS_MODE_SIGNAL_LOW, STOPLOSS_MODE_LF_LOW, STOPLOSS_MODE_DAILY_SUPERTREND}
GAP_UP_MODE_LABELS = {GAP_UP_MODE_EXISTING: 'Existing Entry', GAP_UP_MODE_PULLBACK: 'Pull Back Entry', GAP_UP_MODE_GAP_ENTRY: 'Gap-Up Entry', GAP_UP_MODE_GAP_UPDATE: 'Gap-Up + SL/Target Update'}

@dataclass
class StrategySettings:
    rsi_period: int = 21
    rsi_min: float = 60.0
    rsi_max: float = 90.0
    htf_rsi_period: int = 21
    htf_rsi_min: float = 60.0
    htf_rsi_max: float = 90.0
    supertrend_period: int = 21
    supertrend_multiplier: float = 1.5
    htf_supertrend_period: int = 21
    htf_supertrend_multiplier: float = 1.5
    entry_lookahead_bars: int = 2
    max_stoploss_pct: float = 0.05
    stoploss_mode: str = STOPLOSS_MODE_SIGNAL_LOW
    stoploss_supertrend_period: int | None = None
    stoploss_supertrend_multiplier: float = 1.5
    look_forward_limit: int = 1460
    target_mode: str = 'fixed'
    atr_multiplier: float = 2.0
    entry_offset_pct: float = 0.0
    trade_management_enabled: bool = False
    trade_management_book_pct: float = 0.0
    trade_management_trigger_pct: float = 0.0
    trade_management_targets: list[dict[str, float]] | None = None
    min_cmf: float = -1.0
    min_rel_vol: float = 0.0
    min_adx: float = 0.0
    min_candle_range: float = 0.0
    max_candle_range: float = 100.0

class RSISupertrendStrategy:

    def _stoploss_mode(self) -> str:
        if getattr(self.settings, 'stoploss_mode', None):
            return self.settings.stoploss_mode
        return 'signal_low'

    def _stoploss_basis_for_signal(self, df, idx, signal_low):
        if self._stoploss_mode() == 'daily_supertrend':
            return float(df.iloc[idx]['final_lowerband'])
        return signal_low

    def _stoploss_basis_for_entry(self, df, idx, entry_time, signal_low):
        if self._stoploss_mode() == 'daily_supertrend':
            import pandas as pd
            df_datetime_arr = df['datetime'].to_numpy()
            if entry_time is not None:
                entry_date_str = str(entry_time)[:10]
                for j in range(idx, len(df)):
                    dt_str = str(df_datetime_arr[j])[:10]
                    if dt_str == entry_date_str:
                        return float(df.iloc[j]['final_lowerband'])
                    if dt_str > entry_date_str:
                        break
            return float(df.iloc[idx]['final_lowerband'])
        return signal_low

    def _apply_max_stoploss_cap(self, entry_price, stoploss_basis):
        if entry_price > 0 and (entry_price - stoploss_basis) / entry_price > getattr(self.settings, 'max_stoploss_pct', 0.05):
            return round(entry_price * (1 - getattr(self.settings, 'max_stoploss_pct', 0.05)), 2)
        return stoploss_basis

    def _calculate_target(self, entry_price, target_level, atr_val):
        target_mode = getattr(self.settings, 'target_mode', 'fixed')
        if target_mode == 'dynamic' and atr_val is not None and (atr_val > 0):
            target = round(entry_price + atr_val * getattr(self.settings, 'atr_multiplier', 2.0), 2)
        else:
            target = round(entry_price * (1 + target_level / 100.0), 2)
        effective_pct = (target - entry_price) / entry_price * 100.0
        return (target, effective_pct)

    def __init__(self, settings: StrategySettings):
        self.settings = settings

    def prepare_frames(self, signal_df: pd.DataFrame, execution_df: pd.DataFrame, htf_df: pd.DataFrame | None=None):
        signal_df = add_rsi(signal_df, self.settings.rsi_period, 'rsi')
        signal_df = add_macd(signal_df)
        signal_df = add_supertrend(signal_df, period=self.settings.supertrend_period, multiplier=self.settings.supertrend_multiplier)
        if self._stoploss_mode() == STOPLOSS_MODE_DAILY_SUPERTREND:
            sl_st_df = add_supertrend(signal_df[['datetime', 'open', 'high', 'low', 'close']].copy(), period=self.settings.stoploss_supertrend_period or self.settings.supertrend_period, multiplier=self.settings.stoploss_supertrend_multiplier)
            signal_df['stoploss_supertrend_lowerband'] = sl_st_df['final_lowerband'].to_numpy()
        signal_df = add_atr(signal_df, 14)
        signal_df = add_rel_vol(signal_df, 20)
        signal_df = add_cmf(signal_df, 20)
        signal_df = add_adx(signal_df, 14)
        signal_df = add_ema(signal_df, 20)
        signal_df['candle_range'] = (signal_df['high'] - signal_df['low']) / signal_df['low'] * 100
        execution_df = execution_df.copy()
        execution_df['datetime'] = pd.to_datetime(execution_df['datetime']).dt.tz_localize(None)
        execution_df = execution_df.set_index('datetime')
        if htf_df is not None:
            htf_df = htf_df.copy()
            htf_df['datetime'] = pd.to_datetime(htf_df['datetime']).dt.tz_localize(None)
            htf_df = add_rsi(htf_df, self.settings.htf_rsi_period, 'rsi_htf_raw')
            htf_df = add_supertrend(htf_df, period=self.settings.htf_supertrend_period, multiplier=self.settings.htf_supertrend_multiplier)
            htf_df.rename(columns={'in_uptrend': 'in_uptrend_htf_raw'}, inplace=True)
            htf_df['rsi_htf'] = htf_df['rsi_htf_raw'].shift(1)
            htf_df['in_uptrend_htf'] = htf_df['in_uptrend_htf_raw'].shift(1)
            htf_df['final_lowerband_htf'] = htf_df['final_lowerband'].shift(1)
            htf_df['final_upperband_htf'] = htf_df['final_upperband'].shift(1)
            signal_df = signal_df.sort_values('datetime')
            htf_df = htf_df.sort_values('datetime')
            signal_df = pd.merge_asof(signal_df, htf_df[['datetime', 'rsi_htf', 'in_uptrend_htf', 'final_lowerband_htf', 'final_upperband_htf']], on='datetime', direction='backward')
        return (signal_df.reset_index(drop=True), execution_df)

    def generate_signals(self, company: str, signal_df: pd.DataFrame, execution_df: pd.DataFrame, target_level: int) -> list[TradeSignal]:
        signals: list[TradeSignal] = []
        i = 0
        has_htf_rsi = 'rsi_htf' in signal_df.columns
        simulation_context = self._build_simulation_context(signal_df)
        _np_uptrend = signal_df['in_uptrend'].to_numpy()
        _np_rsi = signal_df['rsi'].to_numpy() if 'rsi' in signal_df.columns else None
        _np_rsi_htf = signal_df['rsi_htf'].to_numpy() if has_htf_rsi else None
        _np_cmf = signal_df['cmf'].to_numpy() if 'cmf' in signal_df.columns else None
        _np_rel_vol = signal_df['rel_vol'].to_numpy() if 'rel_vol' in signal_df.columns else None
        _np_adx = signal_df['adx'].to_numpy() if 'adx' in signal_df.columns else None
        _np_candle_range = signal_df['candle_range'].to_numpy() if 'candle_range' in signal_df.columns else None
        _np_low = signal_df['low'].to_numpy()
        _np_high = signal_df['high'].to_numpy()
        _np_open = signal_df['open'].to_numpy()
        _np_datetime = signal_df['datetime'].to_numpy()
        _np_atr = signal_df['ATR'].to_numpy() if 'ATR' in signal_df.columns else None
        _df_len = len(signal_df)
        _exec_times = execution_df.index.to_numpy()
        _exec_opens = execution_df['open'].to_numpy(dtype=float)
        _exec_highs = execution_df['high'].to_numpy(dtype=float)
        _exec_lows = execution_df['low'].to_numpy(dtype=float)
        _exec_closes = execution_df['close'].to_numpy(dtype=float) if 'close' in execution_df.columns else None
        while i + self.settings.entry_lookahead_bars < _df_len:
            if not bool(_np_uptrend[i]):
                i += 1
                continue
            row = signal_df.iloc[i]
            _rsi_raw = _np_rsi[i] if _np_rsi is not None else float('nan')
            rsi_value = float(_rsi_raw) if not np.isnan(_rsi_raw) else None
            _rsi_htf_raw = _np_rsi_htf[i] if _np_rsi_htf is not None else float('nan')
            rsi_htf = float(_rsi_htf_raw) if not np.isnan(_rsi_htf_raw) else None
            ltf_rsi_ok = rsi_value is not None and self.settings.rsi_min <= rsi_value < self.settings.rsi_max
            htf_rsi_ok = not has_htf_rsi
            if rsi_htf is not None:
                htf_rsi_ok = self.settings.htf_rsi_min <= rsi_htf < self.settings.htf_rsi_max
            cmf_val = float(_np_cmf[i]) if _np_cmf is not None and (not np.isnan(_np_cmf[i])) else 0
            rel_vol_val = float(_np_rel_vol[i]) if _np_rel_vol is not None and (not np.isnan(_np_rel_vol[i])) else 0
            adx_val = float(_np_adx[i]) if _np_adx is not None and (not np.isnan(_np_adx[i])) else 0
            c_range = float(_np_candle_range[i]) if _np_candle_range is not None and (not np.isnan(_np_candle_range[i])) else 0
            filters_ok = cmf_val >= self.settings.min_cmf and rel_vol_val >= self.settings.min_rel_vol and (adx_val >= self.settings.min_adx) and (self.settings.min_candle_range <= c_range <= self.settings.max_candle_range)
            if not (ltf_rsi_ok and htf_rsi_ok and filters_ok):
                i = self._skip_trend_block_fast(_np_uptrend, i, _df_len)
                continue
            signal_low = float(_np_low[i])
            signal_high = float(_np_high[i])
            provisional_sl_basis = self._stoploss_basis_for_signal(signal_df, i, signal_low)
            provisional_sl = provisional_sl_basis
            if (signal_high - provisional_sl) / signal_high > self.settings.max_stoploss_pct:
                provisional_sl = signal_high * (1.0 - self.settings.max_stoploss_pct)
            entry_level = signal_high
            if self.settings.entry_offset_pct > 0:
                entry_level = round(signal_high * (1.0 + self.settings.entry_offset_pct / 100.0), 2)
            original_entry = entry_level
            entry_price, entry_time, gap_up_open, pullback_within_lookahead = self._find_entry(signal_df, i, execution_df, provisional_sl, entry_level, exec_times=_exec_times, exec_opens=_exec_opens, exec_highs=_exec_highs, exec_lows=_exec_lows, exec_closes=_exec_closes)
            if entry_price is None or entry_time is None:
                i = self._skip_trend_block_fast(_np_uptrend, i, _df_len)
                continue
            stoploss_basis = self._stoploss_basis_for_entry(signal_df, i, entry_time, float(row['low']))
            stoploss = self._apply_max_stoploss_cap(entry_price, stoploss_basis)
            original_stoploss = stoploss
            atr_val_for_target = float(_np_atr[i]) if _np_atr is not None and (not np.isnan(_np_atr[i])) else None
            target, effective_target_pct = self._calculate_target(entry_price, target_level, atr_val_for_target)
            original_target = target
            future_step = self.settings.entry_lookahead_bars
            if i + future_step + 1 < _df_len:
                lookahead_end_time = pd.Timestamp(_np_datetime[i + future_step + 1])
            else:
                lookahead_end_time = pd.Timestamp(_np_datetime[-1]) + pd.Timedelta(days=1)
            trade_result = self._simulate_trade(signal_df=signal_df, execution_df=execution_df, entry_time=entry_time, entry_price=entry_price, stoploss=stoploss, target=target, lookahead_end_time=lookahead_end_time, simulation_context=simulation_context, exec_times=_exec_times, exec_opens=_exec_opens, exec_highs=_exec_highs, exec_lows=_exec_lows, exec_closes=_exec_closes)
            self._attach_close_lf_replay(signal_df=signal_df, execution_df=execution_df, trade_result=trade_result, original_stoploss=original_stoploss, target=original_target, lookahead_end_time=lookahead_end_time, simulation_context=simulation_context, exec_times=_exec_times, exec_opens=_exec_opens, exec_highs=_exec_highs, exec_lows=_exec_lows, exec_closes=_exec_closes)
            close_lf_replay = trade_result.get('close_lf_replay') or {}
            trade_management_fields = {key: trade_result.get(key) for key in ('exit_type', 'exit_reason_detail', 'trade_management_enabled', 'trade_management_book_pct', 'trade_management_trigger_pct', 'trade_management_targets', 'trade_management_partial_booked', 'trade_management_partial_exit_price', 'trade_management_partial_exit_time', 'trade_management_stoploss_moved_to_breakeven', 'trade_management_remaining_exit_pct', 'trade_management_remaining_exit_type', 'trade_management_remaining_exit_reason', 'trade_management_weighted_return_pct', 'trade_management_booked_qty_pct', 'trade_management_remaining_qty_pct')}
            entry_open_info = self._find_entry_open_event(signal_df, i, execution_df, provisional_sl, original_entry, exec_times=_exec_times, exec_opens=_exec_opens, exec_highs=_exec_highs, exec_lows=_exec_lows)
            trend_val = None
            if 'in_uptrend' in row:
                trend_val = 'Uptrend' if row['in_uptrend'] else 'Downtrend'
            rsi_htf = float(row['rsi_htf']) if 'rsi_htf' in row and pd.notna(row['rsi_htf']) else None
            atr_val = float(row['ATR']) if 'ATR' in row and pd.notna(row['ATR']) else None
            rel_vol_val = float(row['rel_vol']) if 'rel_vol' in row and pd.notna(row['rel_vol']) else None
            cmf_val = float(row['cmf']) if 'cmf' in row and pd.notna(row['cmf']) else None
            adx_val = float(row['adx']) if 'adx' in row and pd.notna(row['adx']) else None
            ema_20_val = float(row['ema_20']) if 'ema_20' in row and pd.notna(row['ema_20']) else None
            price_vs_ema = None
            if ema_20_val is not None:
                price_vs_ema = 'Above' if float(row['close']) > ema_20_val else 'Below'
            st_ltf_val = float(row['final_lowerband']) if row['in_uptrend'] else float(row['final_upperband'])
            st_htf_val = None
            if 'in_uptrend_htf' in row and pd.notna(row['in_uptrend_htf']):
                st_htf_val = float(row['final_lowerband_htf']) if row['in_uptrend_htf'] else float(row['final_upperband_htf'])
            gap_up_modes = self._build_gap_up_modes(signal_df=signal_df, execution_df=execution_df, signal_idx=i, lookahead_end_time=lookahead_end_time, original_entry=original_entry, original_stoploss=original_stoploss, original_target=original_target, original_effective_target_pct=effective_target_pct, target_level=target_level, atr_value=atr_val_for_target, signal_low=float(row['low']), base_entry_time=entry_time, base_trade_result=trade_result, entry_open_info=entry_open_info, gap_up_open=gap_up_open, pullback_within_lookahead=pullback_within_lookahead, simulation_context=simulation_context, exec_times=_exec_times, exec_opens=_exec_opens, exec_highs=_exec_highs, exec_lows=_exec_lows, exec_closes=_exec_closes, signal_datetime_arr=_np_datetime, signal_open_arr=_np_open, signal_high_arr=_np_high, signal_low_arr=_np_low)
            existing_mode = gap_up_modes[GAP_UP_MODE_EXISTING]
            signals.append(TradeSignal(company=company, signal_time=str(row['datetime']), entry_time=str(entry_time), exit_time=str(trade_result['exit_time']), entry=entry_price, target=target, stoploss=stoploss, target_hit=trade_result['target_hit'], stoploss_hit=trade_result['stoploss_hit'], expired=trade_result['expired'], expired_metrics=trade_result['expired_metrics'], stoploss_hit_metrics=trade_result['stoploss_hit_metrics'], target_hit_metrics=trade_result['target_hit_metrics'], target_level=target_level, effective_target_pct=effective_target_pct, days_held=trade_result['days_held'], rsi=rsi_value, rsi_htf=rsi_htf, in_uptrend_htf=bool(row['in_uptrend_htf']) if 'in_uptrend_htf' in row and pd.notna(row['in_uptrend_htf']) else None, supertrend_trend=trend_val, supertrend_ltf=st_ltf_val, supertrend_htf=st_htf_val, atr=atr_val, rel_vol=rel_vol_val, cmf=cmf_val, adx=adx_val, ema_20=ema_20_val, price_vs_ema20=price_vs_ema, exit_reason=trade_result['exit_reason'], exit_price=trade_result.get('exit_price'), signal_open=float(row['open']), signal_high=float(row['high']), signal_low=float(row['low']), signal_close=float(row['close']), signal_volume=float(row['volume']) if 'volume' in row else None, max_high_reached=trade_result['max_high_reached'], max_high_pct=round((trade_result['max_high_reached'] - entry_price) / entry_price * 100, 3) if entry_price > 0 else 0, min_low_reached=trade_result['min_low_reached'], sl_hit_lookahead=trade_result['sl_hit_lookahead'], max_high_lookahead=trade_result['max_high_lookahead'], max_high_lookahead_time=trade_result.get('max_high_lookahead_time'), max_high_lookahead_pct=trade_result['max_high_lookahead_pct'], close_lookahead=trade_result['close_lookahead'], close_lookahead_time=trade_result.get('close_lookahead_time'), close_lookahead_pct=trade_result['close_lookahead_pct'], close_lf_replay=trade_result.get('close_lf_replay'), stoploss_mode=self._stoploss_mode(), stoploss_source=trade_result.get('stoploss_source'), lf_candle_low=close_lf_replay.get('lf_candle_low'), daily_supertrend_stoploss=close_lf_replay.get('daily_supertrend_stoploss'), gap_up_open=gap_up_open, pullback_within_lookahead=pullback_within_lookahead, entry_open=entry_open_info.get('entry_open') if entry_open_info else None, entry_open_time=str(entry_open_info.get('entry_open_time')) if entry_open_info and entry_open_info.get('entry_open_time') is not None else None, entry_open_relation=entry_open_info.get('entry_open_relation') if entry_open_info else None, entry_open_day=entry_open_info.get('entry_open_day') if entry_open_info else None, entry_difference=0.0, entry_difference_pct=0.0, original_entry=original_entry, original_target=original_target, original_stoploss=original_stoploss, new_entry=existing_mode.get('new_entry'), new_stoploss=existing_mode.get('new_stoploss'), new_target=existing_mode.get('new_target'), selected_gap_up_mode=GAP_UP_MODE_EXISTING, gap_up_handling_mode=GAP_UP_MODE_LABELS[GAP_UP_MODE_EXISTING], entry_source=existing_mode.get('entry_source'), open_compared_with_entry=existing_mode.get('open_compared_with_entry'), open_check_day=existing_mode.get('open_check_day'), entry_rejected=False, reject_reason=None, gap_up_modes=gap_up_modes, **trade_management_fields))
            i = self._skip_trend_block_fast(_np_uptrend, i, _df_len)
        return signals

    def _stoploss_mode(self) -> str:
        mode = str(self.settings.stoploss_mode or STOPLOSS_MODE_SIGNAL_LOW).strip()
        return mode if mode in STOPLOSS_MODES else STOPLOSS_MODE_SIGNAL_LOW

    @staticmethod
    def _finite_float(value: Any, fallback: float | None=None) -> float | None:
        if value is None or pd.isna(value):
            return fallback
        try:
            return float(value)
        except (TypeError, ValueError):
            return fallback

    def _apply_max_stoploss_cap(self, entry_price: float, stoploss_basis: float | None) -> float:
        stoploss = float(stoploss_basis) if stoploss_basis is not None else entry_price
        if entry_price > 0 and (entry_price - stoploss) / entry_price > self.settings.max_stoploss_pct:
            stoploss = entry_price * (1.0 - self.settings.max_stoploss_pct)
        return stoploss

    def _calculate_stoploss(self, entry_price: float, signal_low: float) -> float:
        return self._apply_max_stoploss_cap(entry_price, signal_low)

    @staticmethod
    def _signal_frame_duration(signal_df: pd.DataFrame) -> pd.Timedelta:
        gaps = signal_df['datetime'].diff().dropna()
        if not gaps.empty:
            return gaps.mode().iloc[0]
        return pd.Timedelta(days=1)

    def _signal_row_for_time(self, signal_df: pd.DataFrame, when) -> pd.Series | None:
        if signal_df.empty or when is None:
            return None
        timestamp = pd.to_datetime(when)
        if getattr(timestamp, 'tzinfo', None) is not None:
            timestamp = timestamp.tz_localize(None)
        times = pd.to_datetime(signal_df['datetime']).to_numpy()
        pos = times.searchsorted(timestamp.to_datetime64(), side='right') - 1
        if pos < 0:
            return None
        return signal_df.iloc[int(pos)]

    def _completed_signal_row_for_time(self, signal_df: pd.DataFrame, when) -> pd.Series | None:
        if signal_df.empty or when is None:
            return None
        timestamp = pd.to_datetime(when)
        if getattr(timestamp, 'tzinfo', None) is not None:
            timestamp = timestamp.tz_localize(None)
        completed_times = (signal_df['datetime'] + self._signal_frame_duration(signal_df)).to_numpy()
        pos = completed_times.searchsorted(timestamp.to_datetime64(), side='right') - 1
        if pos < 0:
            return None
        return signal_df.iloc[int(pos)]

    def _daily_supertrend_stoploss_from_row(self, row: pd.Series | None, fallback: float | None=None) -> float | None:
        if row is None:
            return fallback
        preferred = self._finite_float(row.get('stoploss_supertrend_lowerband'), None)
        if preferred is not None:
            return preferred
        return self._finite_float(row.get('final_lowerband'), fallback)

    def _stoploss_basis_for_signal(self, signal_df: pd.DataFrame, signal_idx: int, fallback_low: float) -> float:
        return fallback_low

    def _stoploss_basis_for_entry(self, signal_df: pd.DataFrame, signal_idx: int, entry_time, fallback_low: float) -> float:
        return fallback_low

    def _signal_low_for_time(self, signal_datetime_arr, signal_low_arr, when) -> float | None:
        if when is None or len(signal_datetime_arr) == 0:
            return None
        timestamp = pd.Timestamp(when)
        if getattr(timestamp, 'tzinfo', None) is not None:
            timestamp = timestamp.tz_localize(None)
        pos = np.searchsorted(signal_datetime_arr, timestamp.to_datetime64(), side='right') - 1
        if pos < 0:
            return None
        return float(signal_low_arr[pos])

    def _daily_st_stoploss_for_time(self, completed_times, signal_st_stop_arr, when) -> float | None:
        if when is None or len(completed_times) == 0:
            return None
        timestamp = pd.Timestamp(when)
        if getattr(timestamp, 'tzinfo', None) is not None:
            timestamp = timestamp.tz_localize(None)
        pos = np.searchsorted(completed_times, timestamp.to_datetime64(), side='right') - 1
        if pos < 0:
            return None
        return float(signal_st_stop_arr[pos])

    def _close_lf_stoploss_basis(self, signal_df: pd.DataFrame, close_lf_time, original_stoploss: float | None, simulation_context: dict[str, Any] | None=None) -> tuple[float | None, str, float | None, float | None]:
        mode = self._stoploss_mode()
        if simulation_context is not None:
            completed_times = simulation_context['completed_signal_times']
            signal_st_stop_arr = simulation_context['signal_supertrend_stop_values']
            signal_datetime_arr = signal_df['datetime'].to_numpy()
            signal_low_arr = signal_df['low'].to_numpy()
            lf_candle_low = self._signal_low_for_time(signal_datetime_arr, signal_low_arr, close_lf_time)
            daily_st_stoploss = self._daily_st_stoploss_for_time(completed_times, signal_st_stop_arr, close_lf_time)
        else:
            lf_row = self._signal_row_for_time(signal_df, close_lf_time)
            completed_daily_row = self._completed_signal_row_for_time(signal_df, close_lf_time)
            lf_candle_low = self._finite_float(lf_row.get('low'), None) if lf_row is not None else None
            daily_st_stoploss = self._daily_supertrend_stoploss_from_row(completed_daily_row, None)
        if mode == STOPLOSS_MODE_LF_LOW and lf_candle_low is not None:
            return (lf_candle_low, 'LF candle low', lf_candle_low, daily_st_stoploss)
        if mode == STOPLOSS_MODE_DAILY_SUPERTREND and daily_st_stoploss is not None:
            return (daily_st_stoploss, 'Daily Supertrend lower band', lf_candle_low, daily_st_stoploss)
        return (original_stoploss, 'Signal candle low', lf_candle_low, daily_st_stoploss)

    def _calculate_target(self, entry_price: float, target_level: int, atr_value: float | None) -> tuple[float, float]:
        if self.settings.target_mode == 'dynamic' and atr_value is not None:
            target = entry_price + atr_value * self.settings.atr_multiplier
            effective_target_pct = round((target - entry_price) / entry_price * 100, 2) if entry_price > 0 else 0.0
        else:
            target = entry_price * (1.0 + target_level / 100.0)
            effective_target_pct = target_level
        return (target, effective_target_pct)

    def _build_close_lf_replay(self, *, signal_df: pd.DataFrame, execution_df: pd.DataFrame, trade_result: dict[str, Any] | None, original_stoploss: float | None, target: float | None, lookahead_end_time, simulation_context: dict[str, Any] | None=None, exec_times=None, exec_opens=None, exec_highs=None, exec_lows=None, exec_closes=None) -> dict[str, Any] | None:
        if trade_result is None or target is None:
            return None
        close_lf_entry = trade_result.get('close_lookahead')
        close_lf_time_raw = trade_result.get('close_lookahead_time')
        if close_lf_entry is None or close_lf_time_raw is None:
            return None
        close_lf_entry = float(close_lf_entry)
        target = float(target)
        if close_lf_entry <= 0 or target <= close_lf_entry:
            return {'valid': False, 'reject_reason': 'Close LF entry is at/above target', 'entry': self._maybe_round(close_lf_entry), 'entry_time': str(close_lf_time_raw), 'Target': self._maybe_round(target)}
        close_lf_time = pd.to_datetime(close_lf_time_raw)
        if getattr(close_lf_time, 'tzinfo', None) is not None:
            close_lf_time = close_lf_time.tz_localize(None)
        base_stoploss, stoploss_source, lf_candle_low, daily_supertrend_stoploss = self._close_lf_stoploss_basis(signal_df, close_lf_time, float(original_stoploss) if original_stoploss is not None else None, simulation_context=simulation_context)
        final_stoploss = self._apply_max_stoploss_cap(close_lf_entry, base_stoploss)
        replay_result = self._simulate_trade(signal_df=signal_df, execution_df=execution_df, entry_time=close_lf_time, entry_price=close_lf_entry, stoploss=final_stoploss, target=target, lookahead_end_time=lookahead_end_time, simulation_context=simulation_context, include_entry_bar=False, use_daily_supertrend_stoploss=self._stoploss_mode() == STOPLOSS_MODE_DAILY_SUPERTREND, exec_times=exec_times, exec_opens=exec_opens, exec_highs=exec_highs, exec_lows=exec_lows, exec_closes=exec_closes)
        max_high_reached = replay_result.get('max_high_reached')
        max_high_pct = None
        if max_high_reached is not None:
            max_high_pct = round((float(max_high_reached) - close_lf_entry) / close_lf_entry * 100, 3)
        return {'valid': True, 'entry_source': 'Close (LF) Confirmed', 'entry': self._maybe_round(close_lf_entry), 'entry_time': str(close_lf_time), 'Target': self._maybe_round(target), 'Stoploss': self._maybe_round(final_stoploss), 'original_stoploss': self._maybe_round(original_stoploss), 'new_entry': self._maybe_round(close_lf_entry), 'new_target': self._maybe_round(target), 'new_stoploss': self._maybe_round(final_stoploss), 'stoploss_mode': self._stoploss_mode(), 'stoploss_source': stoploss_source, 'lf_candle_low': self._maybe_round(lf_candle_low), 'daily_supertrend_stoploss': self._maybe_round(daily_supertrend_stoploss), 'effective_target_pct': round((target - close_lf_entry) / close_lf_entry * 100, 3), 'target_hit': replay_result['target_hit'], 'stoploss_hit': replay_result['stoploss_hit'], 'expired': replay_result['expired'], 'expired_metrics': replay_result['expired_metrics'], 'stoploss_hit_metrics': replay_result['stoploss_hit_metrics'], 'target_hit_metrics': replay_result['target_hit_metrics'], 'exit_time': replay_result['exit_time'], 'days_held': replay_result['days_held'], 'exit_reason': replay_result['exit_reason'], 'exit_type': replay_result.get('exit_type', replay_result.get('exit_reason')), 'exit_reason_detail': replay_result.get('exit_reason_detail'), 'exit_price': self._maybe_round(replay_result.get('exit_price')), 'max_high_reached': self._maybe_round(replay_result.get('max_high_reached')), 'max_high_pct': max_high_pct, 'min_low_reached': self._maybe_round(replay_result.get('min_low_reached')), 'sl_hit_lookahead': replay_result.get('sl_hit_lookahead'), 'max_high_lookahead': self._maybe_round(replay_result.get('max_high_lookahead')), 'max_high_lookahead_time': replay_result.get('max_high_lookahead_time'), 'max_high_lookahead_pct': replay_result.get('max_high_lookahead_pct'), 'close_lookahead': self._maybe_round(replay_result.get('close_lookahead')), 'close_lookahead_time': replay_result.get('close_lookahead_time'), 'close_lookahead_pct': replay_result.get('close_lookahead_pct'), 'trade_management_enabled': replay_result.get('trade_management_enabled', False), 'trade_management_book_pct': replay_result.get('trade_management_book_pct'), 'trade_management_trigger_pct': replay_result.get('trade_management_trigger_pct'), 'trade_management_targets': replay_result.get('trade_management_targets'), 'trade_management_partial_booked': replay_result.get('trade_management_partial_booked', False), 'trade_management_partial_exit_price': self._maybe_round(replay_result.get('trade_management_partial_exit_price')), 'trade_management_partial_exit_time': replay_result.get('trade_management_partial_exit_time'), 'trade_management_stoploss_moved_to_breakeven': replay_result.get('trade_management_stoploss_moved_to_breakeven', False), 'trade_management_remaining_exit_pct': replay_result.get('trade_management_remaining_exit_pct'), 'trade_management_remaining_exit_type': replay_result.get('trade_management_remaining_exit_type'), 'trade_management_remaining_exit_reason': replay_result.get('trade_management_remaining_exit_reason'), 'trade_management_weighted_return_pct': replay_result.get('trade_management_weighted_return_pct'), 'trade_management_booked_qty_pct': replay_result.get('trade_management_booked_qty_pct'), 'trade_management_remaining_qty_pct': replay_result.get('trade_management_remaining_qty_pct')}

    def _attach_close_lf_replay(self, *, signal_df: pd.DataFrame, execution_df: pd.DataFrame, trade_result: dict[str, Any] | None, original_stoploss: float | None, target: float | None, lookahead_end_time, simulation_context: dict[str, Any] | None=None, exec_times=None, exec_opens=None, exec_highs=None, exec_lows=None, exec_closes=None) -> dict[str, Any] | None:
        if trade_result is None:
            return None
        trade_result['close_lf_replay'] = self._build_close_lf_replay(signal_df=signal_df, execution_df=execution_df, trade_result=trade_result, original_stoploss=original_stoploss, target=target, lookahead_end_time=lookahead_end_time, simulation_context=simulation_context, exec_times=exec_times, exec_opens=exec_opens, exec_highs=exec_highs, exec_lows=exec_lows, exec_closes=exec_closes)
        return trade_result

    def _iter_lookahead_execution_bars(self, df: pd.DataFrame, idx: int, execution_df: pd.DataFrame, exec_times=None, exec_opens=None, exec_highs=None, exec_lows=None):
        if exec_times is None:
            exec_times = execution_df.index.to_numpy()
            exec_opens = execution_df['open'].to_numpy(dtype=float)
            exec_highs = execution_df['high'].to_numpy(dtype=float)
            exec_lows = execution_df['low'].to_numpy(dtype=float)
        df_datetime_arr = df['datetime'].to_numpy()
        df_open_arr = df['open'].to_numpy()
        df_high_arr = df['high'].to_numpy()
        df_low_arr = df['low'].to_numpy()
        df_len = len(df)
        for step in range(1, self.settings.entry_lookahead_bars + 1):
            future_idx = idx + step
            future_start = df_datetime_arr[future_idx]
            if future_idx + 1 < df_len:
                future_end = df_datetime_arr[future_idx + 1]
                start_i = np.searchsorted(exec_times, future_start, side='left')
                end_i = np.searchsorted(exec_times, future_end, side='left')
            else:
                start_i = np.searchsorted(exec_times, future_start, side='left')
                end_i = len(exec_times)
            if start_i >= end_i:
                yield (pd.Timestamp(future_start), {'open': float(df_open_arr[future_idx]), 'high': float(df_high_arr[future_idx]), 'low': float(df_low_arr[future_idx])}, True)
                continue
            first_bar = True
            for bar_i in range(start_i, end_i):
                yield (pd.Timestamp(exec_times[bar_i]), {'open': exec_opens[bar_i], 'high': exec_highs[bar_i], 'low': exec_lows[bar_i]}, first_bar)
                first_bar = False

    @staticmethod
    def _entry_open_relation(open_price: float, entry_level: float) -> str:
        if open_price > entry_level:
            return 'higher'
        if open_price < entry_level:
            return 'lower'
        return 'equal'

    def _find_entry_open_event(self, df: pd.DataFrame, idx: int, execution_df: pd.DataFrame, signal_low: float, entry_level: float, exec_times=None, exec_opens=None, exec_highs=None, exec_lows=None):
        day_number = 0
        current_open = None
        for bar_time, bar, is_session_open in self._iter_lookahead_execution_bars(df, idx, execution_df, exec_times=exec_times, exec_opens=exec_opens, exec_highs=exec_highs, exec_lows=exec_lows):
            bar_open = float(bar['open'])
            bar_high = float(bar['high'])
            bar_low = float(bar['low'])
            if is_session_open:
                day_number += 1
                current_open = {'entry_level': entry_level, 'entry_open': bar_open, 'entry_open_time': bar_time, 'entry_open_relation': self._entry_open_relation(bar_open, entry_level), 'entry_open_day': day_number}
                if bar_open > entry_level:
                    return {**current_open, 'entry_open_event': 'gap_up'}
            if current_open is None:
                continue
            if bar_low <= signal_low and bar_high >= entry_level:
                event = 'rejected' if bar_open <= signal_low else 'normal_entry'
                return {**current_open, 'entry_open_event': event}
            if bar_low <= signal_low:
                return {**current_open, 'entry_open_event': 'rejected'}
            if bar_high >= entry_level:
                return {**current_open, 'entry_open_event': 'normal_entry'}
        if current_open is None:
            return None
        return {**current_open, 'entry_open_event': 'no_entry'}

    @staticmethod
    def _maybe_round(value: float | None, digits: int=3) -> float | None:
        if value is None or pd.isna(value):
            return None
        return round(float(value), digits)

    @staticmethod
    def _open_relation_label(relation: str | None) -> str | None:
        mapping = {'higher': 'Higher Than Entry', 'lower': 'Lower Than Entry', 'equal': 'Equal To Entry'}
        return mapping.get(relation) if relation else None

    @staticmethod
    def _entry_day_label(day_number: int | None) -> str | None:
        return f'Day-{day_number}' if day_number is not None else None

    def _find_pullback_entry_time(self, df: pd.DataFrame, idx: int, execution_df: pd.DataFrame, entry_level: float, start_day: int, exec_times=None, exec_opens=None, exec_highs=None, exec_lows=None):
        day_number = 0
        for bar_time, bar, is_session_open in self._iter_lookahead_execution_bars(df, idx, execution_df, exec_times=exec_times, exec_opens=exec_opens, exec_highs=exec_highs, exec_lows=exec_lows):
            if is_session_open:
                day_number += 1
            if day_number < start_day:
                continue
            if float(bar['low']) <= entry_level:
                return bar_time
        return None

    def _build_mode_payload(self, *, mode_key: str, original_entry: float, original_stoploss: float, original_target: float, target_level: int, entry_open_info: dict[str, Any] | None, entry_source: str, entry_price: float | None, entry_time, stoploss: float | None, target: float | None, trade_result: dict[str, Any] | None, gap_up_open: float | None, pullback_within_lookahead: bool, reject_reason: str | None=None) -> dict[str, Any]:
        relation = entry_open_info.get('entry_open_relation') if entry_open_info else None
        entry_open_day = entry_open_info.get('entry_open_day') if entry_open_info else None
        entry_open = self._maybe_round(entry_open_info.get('entry_open')) if entry_open_info else None
        entry_open_time = str(entry_open_info.get('entry_open_time')) if entry_open_info and entry_open_info.get('entry_open_time') is not None else None
        mode_label = GAP_UP_MODE_LABELS[mode_key]
        effective_target_pct = None
        entry_difference = None
        entry_difference_pct = None
        if entry_price is not None:
            entry_difference = round(float(entry_price) - float(original_entry), 3)
            if original_entry > 0:
                entry_difference_pct = round((float(entry_price) - float(original_entry)) / float(original_entry) * 100, 3)
        if entry_price is not None and target is not None and (float(entry_price) > 0):
            effective_target_pct = round((float(target) - float(entry_price)) / float(entry_price) * 100, 3)
        payload: dict[str, Any] = {'selected_gap_up_mode': mode_key, 'gap_up_handling_mode': mode_label, 'valid': trade_result is not None and reject_reason is None, 'entry_rejected': reject_reason is not None, 'rejected': reject_reason is not None, 'reject_reason': reject_reason, 'entry_source': entry_source, 'entry_reason': entry_source, 'entry': self._maybe_round(entry_price), 'new_entry': self._maybe_round(entry_price), 'entry_time': str(entry_time) if entry_time is not None else None, 'Target': self._maybe_round(target), 'Stoploss': self._maybe_round(stoploss), 'new_target': self._maybe_round(target), 'new_stoploss': self._maybe_round(stoploss), 'stoploss_mode': self._stoploss_mode(), 'stoploss_source': 'Signal candle low', 'original_entry': self._maybe_round(original_entry), 'original_target': self._maybe_round(original_target), 'original_stoploss': self._maybe_round(original_stoploss), 'entry_difference': entry_difference, 'entry_difference_pct': entry_difference_pct, 'target_level': target_level, 'effective_target_pct': effective_target_pct, 'gap_up_open': self._maybe_round(gap_up_open), 'pullback_within_lookahead': bool(pullback_within_lookahead), 'entry_open': entry_open, 'entry_open_time': entry_open_time, 'entry_open_relation': relation, 'entry_open_day': entry_open_day, 'open_compared_with_entry': self._open_relation_label(relation), 'open_check_day': self._entry_day_label(entry_open_day)}
        if trade_result is None:
            payload.update({'target_hit': False, 'stoploss_hit': False, 'expired': False, 'expired_metrics': None, 'stoploss_hit_metrics': None, 'target_hit_metrics': None, 'exit_time': None, 'days_held': None, 'exit_reason': reject_reason, 'exit_type': reject_reason, 'exit_reason_detail': reject_reason, 'exit_price': None, 'max_high_reached': None, 'max_high_pct': None, 'min_low_reached': None, 'sl_hit_lookahead': False, 'max_high_lookahead': None, 'max_high_lookahead_time': None, 'max_high_lookahead_pct': None, 'close_lookahead': None, 'close_lookahead_time': None, 'close_lookahead_pct': None, 'close_lf_replay': None, 'trade_management_enabled': bool(self.settings.trade_management_enabled), **self._empty_trade_management_fields(bool(self.settings.trade_management_enabled) and bool(self._trade_management_plan()), self._trade_management_plan()), 'trade_management_partial_booked': False, 'trade_management_partial_exit_price': None, 'trade_management_partial_exit_time': None, 'trade_management_stoploss_moved_to_breakeven': False, 'trade_management_remaining_exit_pct': None, 'trade_management_remaining_exit_type': None, 'trade_management_remaining_exit_reason': None, 'trade_management_weighted_return_pct': None})
            return payload
        max_high_reached = trade_result.get('max_high_reached')
        max_high_pct = None
        if entry_price is not None and max_high_reached is not None and (float(entry_price) > 0):
            max_high_pct = round((float(max_high_reached) - float(entry_price)) / float(entry_price) * 100, 3)
        payload.update({'target_hit': trade_result['target_hit'], 'stoploss_hit': trade_result['stoploss_hit'], 'expired': trade_result['expired'], 'expired_metrics': trade_result['expired_metrics'], 'stoploss_hit_metrics': trade_result['stoploss_hit_metrics'], 'target_hit_metrics': trade_result['target_hit_metrics'], 'exit_time': str(trade_result['exit_time']) if trade_result.get('exit_time') is not None else None, 'days_held': trade_result['days_held'], 'exit_reason': trade_result['exit_reason'], 'exit_type': trade_result.get('exit_type', trade_result.get('exit_reason')), 'exit_reason_detail': trade_result.get('exit_reason_detail'), 'exit_price': self._maybe_round(trade_result.get('exit_price')), 'max_high_reached': self._maybe_round(trade_result.get('max_high_reached')), 'max_high_pct': max_high_pct, 'min_low_reached': self._maybe_round(trade_result.get('min_low_reached')), 'sl_hit_lookahead': trade_result['sl_hit_lookahead'], 'max_high_lookahead': self._maybe_round(trade_result.get('max_high_lookahead')), 'max_high_lookahead_time': trade_result.get('max_high_lookahead_time'), 'max_high_lookahead_pct': trade_result['max_high_lookahead_pct'], 'close_lookahead': self._maybe_round(trade_result.get('close_lookahead')), 'close_lookahead_time': trade_result.get('close_lookahead_time'), 'close_lookahead_pct': trade_result['close_lookahead_pct'], 'close_lf_replay': trade_result.get('close_lf_replay'), 'trade_management_enabled': trade_result.get('trade_management_enabled', False), 'trade_management_book_pct': trade_result.get('trade_management_book_pct'), 'trade_management_trigger_pct': trade_result.get('trade_management_trigger_pct'), 'trade_management_targets': trade_result.get('trade_management_targets'), 'trade_management_partial_booked': trade_result.get('trade_management_partial_booked', False), 'trade_management_partial_exit_price': self._maybe_round(trade_result.get('trade_management_partial_exit_price')), 'trade_management_partial_exit_time': str(trade_result.get('trade_management_partial_exit_time')) if trade_result.get('trade_management_partial_exit_time') is not None else None, 'trade_management_stoploss_moved_to_breakeven': trade_result.get('trade_management_stoploss_moved_to_breakeven', False), 'trade_management_remaining_exit_pct': trade_result.get('trade_management_remaining_exit_pct'), 'trade_management_remaining_exit_type': trade_result.get('trade_management_remaining_exit_type'), 'trade_management_remaining_exit_reason': trade_result.get('trade_management_remaining_exit_reason'), 'trade_management_weighted_return_pct': trade_result.get('trade_management_weighted_return_pct'), 'trade_management_booked_qty_pct': trade_result.get('trade_management_booked_qty_pct'), 'trade_management_remaining_qty_pct': trade_result.get('trade_management_remaining_qty_pct')})
        return payload

    def _build_gap_up_modes(self, *, signal_df: pd.DataFrame, execution_df: pd.DataFrame, signal_idx: int, lookahead_end_time, original_entry: float, original_stoploss: float, original_target: float, original_effective_target_pct: float, target_level: int, atr_value: float | None, signal_low: float, base_entry_time, base_trade_result: dict[str, Any], entry_open_info: dict[str, Any] | None, gap_up_open: float | None, pullback_within_lookahead: bool, simulation_context: dict[str, Any] | None=None, exec_times=None, exec_opens=None, exec_highs=None, exec_lows=None, exec_closes=None, signal_datetime_arr=None, signal_open_arr=None, signal_high_arr=None, signal_low_arr=None) -> dict[str, dict[str, Any]]:
        open_relation = entry_open_info.get('entry_open_relation') if entry_open_info else None
        entry_day = entry_open_info.get('entry_open_day') if entry_open_info else None
        normal_entry_source = f'Day-{entry_day} Entry Reached' if entry_day is not None else 'Entry Reached'
        existing_entry_source = 'Existing Entry' if open_relation == 'higher' else normal_entry_source
        modes: dict[str, dict[str, Any]] = {}
        modes[GAP_UP_MODE_EXISTING] = self._build_mode_payload(mode_key=GAP_UP_MODE_EXISTING, original_entry=original_entry, original_stoploss=original_stoploss, original_target=original_target, target_level=target_level, entry_open_info=entry_open_info, entry_source=existing_entry_source, entry_price=original_entry, entry_time=base_entry_time, stoploss=original_stoploss, target=original_target, trade_result=base_trade_result, gap_up_open=gap_up_open, pullback_within_lookahead=pullback_within_lookahead)
        modes[GAP_UP_MODE_EXISTING]['effective_target_pct'] = round(float(original_effective_target_pct), 3)
        if open_relation != 'higher' or entry_open_info is None:
            for mode_key in (GAP_UP_MODE_PULLBACK, GAP_UP_MODE_GAP_ENTRY, GAP_UP_MODE_GAP_UPDATE):
                cloned = dict(modes[GAP_UP_MODE_EXISTING])
                cloned['selected_gap_up_mode'] = mode_key
                cloned['gap_up_handling_mode'] = GAP_UP_MODE_LABELS[mode_key]
                modes[mode_key] = cloned
            return modes
        gap_entry_price = float(entry_open_info['entry_open'])
        gap_entry_time = entry_open_info['entry_open_time']
        gap_day = int(entry_open_info['entry_open_day'])
        pullback_time = self._find_pullback_entry_time(signal_df, signal_idx, execution_df, original_entry, gap_day, exec_times=exec_times, exec_opens=exec_opens, exec_highs=exec_highs, exec_lows=exec_lows)
        if pullback_time is None:
            modes[GAP_UP_MODE_PULLBACK] = self._build_mode_payload(mode_key=GAP_UP_MODE_PULLBACK, original_entry=original_entry, original_stoploss=original_stoploss, original_target=original_target, target_level=target_level, entry_open_info=entry_open_info, entry_source='Rejected: Pull Back Not Reached', entry_price=original_entry, entry_time=None, stoploss=original_stoploss, target=original_target, trade_result=None, gap_up_open=gap_up_open or gap_entry_price, pullback_within_lookahead=False, reject_reason='Pull Back Not Reached')
        else:
            pullback_trade_result = self._simulate_trade(signal_df=signal_df, execution_df=execution_df, entry_time=pullback_time, entry_price=original_entry, stoploss=original_stoploss, target=original_target, lookahead_end_time=lookahead_end_time, simulation_context=simulation_context, exec_times=exec_times, exec_opens=exec_opens, exec_highs=exec_highs, exec_lows=exec_lows, exec_closes=exec_closes)
            self._attach_close_lf_replay(signal_df=signal_df, execution_df=execution_df, trade_result=pullback_trade_result, original_stoploss=original_stoploss, target=original_target, lookahead_end_time=lookahead_end_time, simulation_context=simulation_context, exec_times=exec_times, exec_opens=exec_opens, exec_highs=exec_highs, exec_lows=exec_lows, exec_closes=exec_closes)
            modes[GAP_UP_MODE_PULLBACK] = self._build_mode_payload(mode_key=GAP_UP_MODE_PULLBACK, original_entry=original_entry, original_stoploss=original_stoploss, original_target=original_target, target_level=target_level, entry_open_info=entry_open_info, entry_source='Pull Back Entry', entry_price=original_entry, entry_time=pullback_time, stoploss=original_stoploss, target=original_target, trade_result=pullback_trade_result, gap_up_open=gap_up_open or gap_entry_price, pullback_within_lookahead=True)
        gap_stoploss = max(float(original_stoploss), gap_entry_price * (1.0 - self.settings.max_stoploss_pct))
        if gap_entry_price >= float(original_target):
            modes[GAP_UP_MODE_GAP_ENTRY] = self._build_mode_payload(mode_key=GAP_UP_MODE_GAP_ENTRY, original_entry=original_entry, original_stoploss=original_stoploss, original_target=original_target, target_level=target_level, entry_open_info=entry_open_info, entry_source='Rejected: Gap-Up Open At/Above Target', entry_price=gap_entry_price, entry_time=None, stoploss=gap_stoploss, target=original_target, trade_result=None, gap_up_open=gap_up_open or gap_entry_price, pullback_within_lookahead=pullback_time is not None, reject_reason='Gap-Up Open At/Above Target')
        else:
            gap_trade_result = self._simulate_trade(signal_df=signal_df, execution_df=execution_df, entry_time=gap_entry_time, entry_price=gap_entry_price, stoploss=gap_stoploss, target=original_target, lookahead_end_time=lookahead_end_time, simulation_context=simulation_context, exec_times=exec_times, exec_opens=exec_opens, exec_highs=exec_highs, exec_lows=exec_lows, exec_closes=exec_closes)
            self._attach_close_lf_replay(signal_df=signal_df, execution_df=execution_df, trade_result=gap_trade_result, original_stoploss=gap_stoploss, target=original_target, lookahead_end_time=lookahead_end_time, simulation_context=simulation_context, exec_times=exec_times, exec_opens=exec_opens, exec_highs=exec_highs, exec_lows=exec_lows, exec_closes=exec_closes)
            modes[GAP_UP_MODE_GAP_ENTRY] = self._build_mode_payload(mode_key=GAP_UP_MODE_GAP_ENTRY, original_entry=original_entry, original_stoploss=original_stoploss, original_target=original_target, target_level=target_level, entry_open_info=entry_open_info, entry_source='Gap-Up Entry', entry_price=gap_entry_price, entry_time=gap_entry_time, stoploss=gap_stoploss, target=original_target, trade_result=gap_trade_result, gap_up_open=gap_up_open or gap_entry_price, pullback_within_lookahead=pullback_time is not None)
        updated_stoploss_basis = self._stoploss_basis_for_entry(signal_df, signal_idx, gap_entry_time, signal_low)
        updated_stoploss = self._apply_max_stoploss_cap(gap_entry_price, updated_stoploss_basis)
        updated_target, _ = self._calculate_target(gap_entry_price, target_level, atr_value)
        updated_trade_result = self._simulate_trade(signal_df=signal_df, execution_df=execution_df, entry_time=gap_entry_time, entry_price=gap_entry_price, stoploss=updated_stoploss, target=updated_target, lookahead_end_time=lookahead_end_time, simulation_context=simulation_context, exec_times=exec_times, exec_opens=exec_opens, exec_highs=exec_highs, exec_lows=exec_lows, exec_closes=exec_closes)
        self._attach_close_lf_replay(signal_df=signal_df, execution_df=execution_df, trade_result=updated_trade_result, original_stoploss=updated_stoploss, target=updated_target, lookahead_end_time=lookahead_end_time, simulation_context=simulation_context, exec_times=exec_times, exec_opens=exec_opens, exec_highs=exec_highs, exec_lows=exec_lows, exec_closes=exec_closes)
        modes[GAP_UP_MODE_GAP_UPDATE] = self._build_mode_payload(mode_key=GAP_UP_MODE_GAP_UPDATE, original_entry=original_entry, original_stoploss=original_stoploss, original_target=original_target, target_level=target_level, entry_open_info=entry_open_info, entry_source='Gap-Up Entry', entry_price=gap_entry_price, entry_time=gap_entry_time, stoploss=updated_stoploss, target=updated_target, trade_result=updated_trade_result, gap_up_open=gap_up_open or gap_entry_price, pullback_within_lookahead=pullback_time is not None)
        return modes

    def _find_entry(self, df, idx, execution_df, signal_low, entry_level=None, exec_times=None, exec_opens=None, exec_highs=None, exec_lows=None, exec_closes=None):
        import pandas as pd
        import numpy as np
        signal_high = float(df.iloc[idx]['high'])
        if entry_level is None:
            entry_level = signal_high
        if exec_times is None:
            exec_times = execution_df.index.to_numpy()
            exec_opens = execution_df['open'].to_numpy(dtype=float)
            exec_highs = execution_df['high'].to_numpy(dtype=float)
            exec_lows = execution_df['low'].to_numpy(dtype=float)
            exec_closes = execution_df['close'].to_numpy(dtype=float)
        df_datetime_arr = df['datetime'].to_numpy()
        df_high_arr = df['high'].to_numpy()
        df_low_arr = df['low'].to_numpy()
        df_open_arr = df['open'].to_numpy()
        df_len = len(df)
        for step in range(1, self.settings.entry_lookahead_bars + 1):
            future_idx = idx + step
            if future_idx >= df_len:
                break
            future_start = df_datetime_arr[future_idx]
            day_open = float(df_open_arr[future_idx])
            if future_idx + 1 < df_len:
                future_end = df_datetime_arr[future_idx + 1]
                start_i = np.searchsorted(exec_times, future_start, side='left')
                end_i = np.searchsorted(exec_times, future_end, side='left')
            else:
                start_i = np.searchsorted(exec_times, future_start, side='left')
                end_i = len(exec_times)
            if start_i >= end_i:
                day_low = float(df_low_arr[future_idx])
                day_close = float(df['close'].iloc[future_idx])
                if day_low <= signal_low:
                    return (None, None, None, False)
                if day_close >= entry_level:
                    return (day_close, pd.Timestamp(future_start) + pd.Timedelta(hours=15, minutes=25), day_open, False)
                return (None, None, None, False)
            target_dt = pd.Timestamp(future_start) + pd.Timedelta(hours=15, minutes=25)
            tick_1525_idx = -1
            for bar_i in range(start_i, end_i):
                bar_time = pd.Timestamp(exec_times[bar_i])
                if bar_time == target_dt:
                    tick_1525_idx = bar_i
                    break
            if tick_1525_idx == -1:
                tick_1525_idx = end_i - 1
            if tick_1525_idx >= start_i:
                tick_close = exec_closes[tick_1525_idx]
                tick_time = pd.Timestamp(exec_times[tick_1525_idx])
                sl_hit = False
                for bar_i in range(start_i, tick_1525_idx + 1):
                    if exec_lows[bar_i] <= signal_low:
                        sl_hit = True
                        break
                if sl_hit:
                    return (None, None, None, False)
                if tick_close >= entry_level:
                    return (tick_close, tick_time, day_open, False)
            return (None, None, None, False)
        return (None, None, None, False)

    @staticmethod
    def _build_simulation_context(signal_df) -> dict[str, Any]:
        gaps = signal_df['datetime'].diff().dropna()
        if not gaps.empty:
            duration = gaps.mode().iloc[0]
        else:
            duration = pd.Timedelta(days=1)
        return {'completed_signal_times': (signal_df['datetime'] + duration).to_numpy(), 'signal_uptrend_values': signal_df['in_uptrend'].to_numpy(), 'signal_close_values': signal_df['close'].to_numpy(), 'signal_supertrend_stop_values': signal_df['stoploss_supertrend_lowerband'].to_numpy() if 'stoploss_supertrend_lowerband' in signal_df.columns else signal_df['final_lowerband'].to_numpy()}

    @staticmethod
    def _exit_reason_detail(exit_type: str | None) -> str:
        details = {'Target Hit': 'Target price was hit', 'Stoploss Hit': 'Stoploss price was hit', 'Trend Reversal': 'LTF trend reversed before target or stoploss', 'Time Limit': 'Look-forward holding period ended before target or stoploss', 'Trade Mgmt Breakeven': 'Partial booked and remaining quantity exited at breakeven', 'Trade Mgmt Stoploss': 'Partial booked and remaining quantity exited at the managed stoploss', 'Trade Mgmt Booked': 'Full position was booked at the trade management trigger', 'Daily Supertrend Stoploss': 'Previous completed Daily Supertrend lower band was hit', 'Data End': 'No execution data was available after entry'}
        return details.get(exit_type or '', str(exit_type or ''))

    def _trade_management_exit_detail(self, remaining_exit_type: str | None) -> str:
        remaining_type = remaining_exit_type or 'N/A'
        remaining_reason = self._exit_reason_detail(remaining_exit_type)
        return f'Partial booked; remaining quantity exit type: {remaining_type}; reason: {remaining_reason}'

    def _trade_management_plan(self) -> list[dict[str, float]]:
        raw_targets = self.settings.trade_management_targets or []
        targets: list[dict[str, float]] = []
        if raw_targets:
            for target in raw_targets:
                try:
                    book_pct = float(target.get('book_pct', 0.0))
                    trigger_pct = float(target.get('trigger_pct', 0.0))
                    stoploss_pct_raw = target.get('stoploss_pct')
                    stoploss_pct = float(stoploss_pct_raw) if stoploss_pct_raw is not None else None
                except (TypeError, ValueError, AttributeError):
                    continue
                if book_pct < 0 or trigger_pct <= 0:
                    continue
                targets.append({'book_pct': book_pct, 'trigger_pct': trigger_pct, 'stoploss_pct': stoploss_pct})
        else:
            try:
                book_pct = float(self.settings.trade_management_book_pct or 0.0)
                trigger_pct = float(self.settings.trade_management_trigger_pct or 0.0)
            except (TypeError, ValueError):
                book_pct = 0.0
                trigger_pct = 0.0
            if book_pct > 0 and trigger_pct > 0:
                targets.append({'book_pct': book_pct, 'trigger_pct': trigger_pct, 'stoploss_pct': 0.0})
        normalized: list[dict[str, float]] = []
        remaining_book_pct = 100.0
        for target in sorted(targets, key=lambda item: item['trigger_pct']):
            if remaining_book_pct <= 0:
                break
            book_pct = min(max(0.0, target['book_pct']), remaining_book_pct)
            trigger_pct = max(0.0, target['trigger_pct'])
            stoploss_pct = target.get('stoploss_pct')
            stoploss_pct = 0.0 if stoploss_pct is None else min(float(stoploss_pct), trigger_pct)
            if book_pct < 0 or trigger_pct <= 0:
                continue
            normalized.append({'book_pct': round(book_pct, 3), 'trigger_pct': round(trigger_pct, 3), 'stoploss_pct': round(stoploss_pct, 3)})
            remaining_book_pct -= book_pct
        return normalized

    @staticmethod
    def _empty_trade_management_fields(tm_enabled: bool, tm_plan: list[dict[str, float]]) -> dict[str, Any]:
        first_target = tm_plan[0] if tm_plan else {}
        return {'trade_management_enabled': tm_enabled, 'trade_management_book_pct': first_target.get('book_pct', 0.0), 'trade_management_trigger_pct': first_target.get('trigger_pct', 0.0), 'trade_management_targets': [{'book_pct': target['book_pct'], 'trigger_pct': target['trigger_pct'], 'stoploss_pct': target.get('stoploss_pct', 0.0), 'hit': False, 'exit_price': None, 'exit_time': None, 'return_pct': None, 'stoploss_price': None} for target in tm_plan], 'trade_management_partial_booked': False, 'trade_management_partial_exit_price': None, 'trade_management_partial_exit_time': None, 'trade_management_stoploss_moved_to_breakeven': False, 'trade_management_remaining_exit_pct': None, 'trade_management_remaining_exit_type': None, 'trade_management_remaining_exit_reason': None, 'trade_management_weighted_return_pct': None, 'trade_management_booked_qty_pct': 0.0, 'trade_management_remaining_qty_pct': 100.0 if tm_enabled else None}

    def _simulate_trade(self, signal_df, execution_df, entry_time, entry_price, stoploss, target, lookahead_end_time, simulation_context: dict[str, Any] | None=None, include_entry_bar: bool=True, use_daily_supertrend_stoploss: bool=False, exec_times=None, exec_opens=None, exec_highs=None, exec_lows=None, exec_closes=None):
        if exec_times is None:
            exec_times = execution_df.index.to_numpy()
            exec_opens = execution_df['open'].to_numpy(dtype=float)
            exec_highs = execution_df['high'].to_numpy(dtype=float)
            exec_lows = execution_df['low'].to_numpy(dtype=float)
            exec_closes = execution_df['close'].to_numpy(dtype=float) if 'close' in execution_df.columns else None
        entry_timestamp = pd.Timestamp(entry_time)
        if getattr(entry_timestamp, 'tzinfo', None) is not None:
            entry_timestamp = entry_timestamp.tz_localize(None)
        start_idx = np.searchsorted(exec_times, entry_timestamp.to_datetime64(), side='left')
        end_idx = min(start_idx + self.settings.look_forward_limit + 1, len(exec_times))
        exit_start_idx = start_idx
        if not include_entry_bar and start_idx < end_idx:
            if exec_times[start_idx] == entry_timestamp.to_datetime64():
                exit_start_idx = start_idx + 1
        target_hit = False
        stoploss_hit = False
        expired = False
        expired_metrics = None
        stoploss_hit_metrics = None
        target_hit_metrics = None
        exit_time = entry_time
        exit_price = entry_price
        days_held = None
        exit_reason = None
        exit_type = None
        exit_reason_detail = None

        def _set_exit(new_exit_type: str, detail: str | None=None) -> None:
            nonlocal exit_type, exit_reason, exit_reason_detail
            exit_type = new_exit_type
            exit_reason = new_exit_type
            exit_reason_detail = detail if detail is not None else self._exit_reason_detail(new_exit_type)
        lookahead_end_timestamp = pd.Timestamp(lookahead_end_time)
        if getattr(lookahead_end_timestamp, 'tzinfo', None) is not None:
            lookahead_end_timestamp = lookahead_end_timestamp.tz_localize(None)
        lookahead_end_dt64 = lookahead_end_timestamp.to_datetime64()
        lookahead_end_idx = np.searchsorted(exec_times, lookahead_end_dt64, side='left')
        lookahead_bars_start = start_idx
        lookahead_bars_end = min(end_idx, lookahead_end_idx)
        lookahead_empty = lookahead_bars_start >= lookahead_bars_end
        if not lookahead_empty:
            close_lookahead = float(exec_closes[lookahead_bars_end - 1]) if exec_closes is not None else entry_price
            close_lookahead_time = pd.Timestamp(exec_times[lookahead_bars_end - 1])
            lookahead_highs_slice = exec_highs[lookahead_bars_start:lookahead_bars_end]
            max_high_idx_relative = np.argmax(lookahead_highs_slice)
            max_high_lookahead = float(lookahead_highs_slice[max_high_idx_relative])
            max_high_lookahead_time = pd.Timestamp(exec_times[lookahead_bars_start + max_high_idx_relative])
            lookahead_lows_slice = exec_lows[lookahead_bars_start:lookahead_bars_end]
            sl_hit_lookahead = bool(np.min(lookahead_lows_slice) <= float(stoploss))
        else:
            close_lookahead = entry_price
            close_lookahead_time = entry_time
            max_high_lookahead = entry_price
            max_high_lookahead_time = entry_time
            sl_hit_lookahead = False
        close_lookahead_pct = round((close_lookahead - entry_price) / entry_price * 100, 3) if entry_price > 0 else 0.0
        tm_plan = self._trade_management_plan()
        tm_possible = bool(self.settings.trade_management_enabled) and bool(tm_plan) and (entry_price > 0) and (target > entry_price)
        if start_idx >= end_idx or exit_start_idx >= end_idx:
            return {'target_hit': False, 'stoploss_hit': False, 'expired': True, 'expired_metrics': 0.0, 'stoploss_hit_metrics': None, 'target_hit_metrics': None, 'exit_time': entry_time, 'days_held': 0, 'exit_reason': 'Data End', 'exit_type': 'Data End', 'exit_reason_detail': self._exit_reason_detail('Data End'), 'exit_price': entry_price, 'max_high_reached': entry_price, 'min_low_reached': entry_price, 'sl_hit_lookahead': False, 'max_high_lookahead': entry_price, 'max_high_lookahead_time': str(entry_time) if entry_time is not None else None, 'max_high_lookahead_pct': 0.0, 'close_lookahead': close_lookahead, 'close_lookahead_time': str(close_lookahead_time) if close_lookahead_time is not None else None, 'close_lookahead_pct': close_lookahead_pct, 'stoploss_mode': self._stoploss_mode(), 'stoploss_source': 'Daily Supertrend lower band' if use_daily_supertrend_stoploss else 'Signal candle low', 'lf_candle_low': None, 'daily_supertrend_stoploss': None, **self._empty_trade_management_fields(tm_possible, tm_plan)}
        if simulation_context is None:
            simulation_context = self._build_simulation_context(signal_df)
        completed_signal_times = simulation_context['completed_signal_times']
        signal_uptrend_values = simulation_context['signal_uptrend_values']
        signal_close_values = simulation_context['signal_close_values']
        signal_supertrend_stop_values = simulation_context.get('signal_supertrend_stop_values')
        max_high_reached = entry_price
        min_low_reached = float('inf')
        tm_enabled = tm_possible
        tm_legs = [{'book_pct': target_cfg['book_pct'], 'trigger_pct': target_cfg['trigger_pct'], 'stoploss_pct': target_cfg.get('stoploss_pct', 0.0), 'book_fraction': target_cfg['book_pct'] / 100.0, 'trigger_price': entry_price * (1.0 + target_cfg['trigger_pct'] / 100.0), 'stoploss_price': entry_price * (1.0 + target_cfg.get('stoploss_pct', 0.0) / 100.0), 'hit': False, 'exit_price': None, 'exit_time': None} for target_cfg in tm_plan]
        tm_partial_booked = False
        tm_partial_exit_price = None
        tm_partial_exit_time = None
        tm_stage_triggered = False
        tm_stoploss_moved_to_breakeven = False
        tm_remaining_exit_pct = None
        tm_remaining_exit_type = None
        tm_remaining_exit_reason = None
        tm_weighted_return_pct = None
        active_stoploss = stoploss

        def _booked_fraction() -> float:
            return sum((leg['book_fraction'] for leg in tm_legs if leg['hit']))

        def _remaining_fraction() -> float:
            return max(0.0, 1.0 - _booked_fraction())

        def _weighted_return(remaining_exit_pct: float) -> float:
            booked_return = sum((leg['book_fraction'] * leg['trigger_pct'] for leg in tm_legs if leg['hit']))
            return round(booked_return + _remaining_fraction() * remaining_exit_pct, 3)

        def _mark_tm_hits(high_price: float, exit_time) -> bool:
            nonlocal tm_partial_booked, tm_partial_exit_price, tm_partial_exit_time
            nonlocal tm_stage_triggered, tm_stoploss_moved_to_breakeven, active_stoploss
            if not tm_enabled:
                return False
            newly_booked = False
            newly_triggered = False
            for leg in tm_legs:
                if leg['hit'] or high_price < leg['trigger_price']:
                    continue
                leg['hit'] = True
                leg['exit_price'] = leg['trigger_price']
                leg['exit_time'] = exit_time
                active_stoploss = max(active_stoploss, leg['stoploss_price'])
                newly_triggered = True
                if leg['book_fraction'] > 0:
                    newly_booked = True
                if leg['book_fraction'] > 0 and tm_partial_exit_price is None:
                    tm_partial_exit_price = leg['trigger_price']
                    tm_partial_exit_time = exit_time
            if newly_triggered:
                tm_stage_triggered = True
                tm_stoploss_moved_to_breakeven = _remaining_fraction() > 0
            if newly_booked:
                tm_partial_booked = True
            return newly_triggered

        def _set_tm_remaining_exit(remaining_exit_type: str) -> None:
            nonlocal tm_remaining_exit_type, tm_remaining_exit_reason
            tm_remaining_exit_type = remaining_exit_type
            tm_remaining_exit_reason = self._exit_reason_detail(remaining_exit_type)
        for _ei in range(exit_start_idx, end_idx):
            idx = pd.Timestamp(exec_times[_ei])
            current_high = float(exec_highs[_ei])
            current_low = float(exec_lows[_ei])
            if current_high > max_high_reached:
                max_high_reached = current_high
            if current_low < min_low_reached:
                min_low_reached = current_low
            completed_pos = completed_signal_times.searchsorted(exec_times[_ei], side='right')
            if completed_pos == 0:
                in_uptrend = True
                ltf_close = None
            else:
                signal_pos = completed_pos - 1
                in_uptrend = bool(signal_uptrend_values[signal_pos])
                ltf_close = float(signal_close_values[signal_pos])
                if use_daily_supertrend_stoploss and signal_supertrend_stop_values is not None:
                    st_stop = self._finite_float(signal_supertrend_stop_values[signal_pos], None)
                    if st_stop is not None:
                        active_stoploss = max(active_stoploss, st_stop)
            days_held = (idx - entry_timestamp).days + 1
            if current_low <= active_stoploss:
                if tm_enabled and (tm_partial_booked or (tm_stage_triggered and active_stoploss > stoploss)):
                    expired = True
                    exit_time = idx
                    exit_price = active_stoploss
                    _set_tm_remaining_exit('Stoploss Hit')
                    tm_remaining_exit_pct = round((active_stoploss - entry_price) / entry_price * 100, 3)
                    managed_exit_type = 'Trade Mgmt Breakeven' if abs(tm_remaining_exit_pct) < 0.0005 else 'Trade Mgmt Stoploss'
                    _set_exit(managed_exit_type, self._trade_management_exit_detail(tm_remaining_exit_type))
                    tm_weighted_return_pct = _weighted_return(tm_remaining_exit_pct)
                    expired_metrics = tm_weighted_return_pct
                    break
                stoploss_hit = True
                exit_time = idx
                exit_price = active_stoploss
                if use_daily_supertrend_stoploss and active_stoploss > stoploss:
                    stoploss_hit = False
                    expired = True
                    _set_exit('Daily Supertrend Stoploss')
                    expired_metrics = round((active_stoploss - entry_price) / entry_price * 100, 3)
                else:
                    _set_exit('Stoploss Hit')
                    stoploss_hit_metrics = round((active_stoploss - entry_price) / entry_price * 100, 3)
                if exec_times[_ei] < lookahead_end_dt64:
                    sl_hit_lookahead = True
                break
            if current_high >= target:
                target_hit = True
                exit_time = idx
                exit_price = target
                _set_exit('Target Hit')
                target_exit_pct = (target - entry_price) / entry_price * 100
                if tm_enabled:
                    _mark_tm_hits(target, idx)
                    if tm_partial_booked:
                        if _remaining_fraction() <= 0:
                            target_hit = False
                            expired = True
                            exit_price = max((leg['exit_price'] for leg in tm_legs if leg['hit'] and leg['exit_price'] is not None), default=entry_price)
                            _set_exit('Trade Mgmt Booked')
                            tm_remaining_exit_pct = 0.0
                            tm_weighted_return_pct = _weighted_return(tm_remaining_exit_pct)
                            expired_metrics = tm_weighted_return_pct
                            break
                        _set_tm_remaining_exit('Target Hit')
                        tm_remaining_exit_pct = round(target_exit_pct, 3)
                        tm_weighted_return_pct = _weighted_return(tm_remaining_exit_pct)
                        target_hit_metrics = tm_weighted_return_pct
                    else:
                        target_hit_metrics = round(target_exit_pct, 3)
                else:
                    target_hit_metrics = round(target_exit_pct, 3)
                break
            if tm_enabled:
                _mark_tm_hits(current_high, idx)
                if tm_partial_booked and _remaining_fraction() <= 0:
                    expired = True
                    exit_time = idx
                    exit_price = max((leg['exit_price'] for leg in tm_legs if leg['hit'] and leg['exit_price'] is not None), default=entry_price)
                    _set_exit('Trade Mgmt Booked')
                    tm_remaining_exit_pct = 0.0
                    tm_weighted_return_pct = _weighted_return(tm_remaining_exit_pct)
                    expired_metrics = tm_weighted_return_pct
                    break
            if not in_uptrend:
                expired = True
                exit_time = idx
                exit_price = ltf_close if ltf_close is not None else entry_price
                _set_exit('Trend Reversal')
                raw_exit_pct = (ltf_close - entry_price) / entry_price * 100 if ltf_close is not None else 0.0
                if tm_enabled and tm_partial_booked:
                    _set_tm_remaining_exit('Trend Reversal')
                    tm_remaining_exit_pct = round(max(raw_exit_pct, 0.0), 3)
                    tm_weighted_return_pct = _weighted_return(tm_remaining_exit_pct)
                    expired_metrics = tm_weighted_return_pct
                else:
                    expired_metrics = round(raw_exit_pct, 3)
                break
        if not (target_hit or stoploss_hit or expired):
            expired = True
            exit_time = pd.Timestamp(exec_times[end_idx - 1])
            _set_exit('Time Limit')
            exit_close = max(float(exec_closes[end_idx - 1]) if exec_closes is not None else entry_price, active_stoploss)
            exit_price = exit_close
            raw_exit_pct = (exit_close - entry_price) / entry_price * 100
            if tm_enabled and tm_partial_booked:
                _set_tm_remaining_exit('Time Limit')
                tm_remaining_exit_pct = round(max(raw_exit_pct, 0.0), 3)
                tm_weighted_return_pct = _weighted_return(tm_remaining_exit_pct)
                expired_metrics = tm_weighted_return_pct
            else:
                expired_metrics = round(raw_exit_pct, 3)
            days_held = (pd.Timestamp(exec_times[end_idx - 1]) - entry_timestamp).days + 1
        max_high_lookahead_pct = round((max_high_lookahead - entry_price) / entry_price * 100, 3) if entry_price > 0 else 0
        return {'target_hit': target_hit, 'stoploss_hit': stoploss_hit, 'expired': expired, 'expired_metrics': expired_metrics, 'stoploss_hit_metrics': stoploss_hit_metrics, 'target_hit_metrics': target_hit_metrics, 'exit_time': str(exit_time), 'days_held': days_held, 'exit_reason': exit_reason, 'exit_type': exit_type or exit_reason, 'exit_reason_detail': exit_reason_detail or self._exit_reason_detail(exit_type or exit_reason), 'exit_price': exit_price, 'max_high_reached': max_high_reached, 'min_low_reached': min_low_reached if min_low_reached != float('inf') else entry_price, 'sl_hit_lookahead': sl_hit_lookahead, 'max_high_lookahead': max_high_lookahead, 'max_high_lookahead_time': str(max_high_lookahead_time) if max_high_lookahead_time is not None else None, 'max_high_lookahead_pct': max_high_lookahead_pct, 'close_lookahead': close_lookahead, 'close_lookahead_time': str(close_lookahead_time) if close_lookahead_time is not None else None, 'close_lookahead_pct': close_lookahead_pct, 'stoploss_mode': self._stoploss_mode(), 'stoploss_source': 'Daily Supertrend lower band' if use_daily_supertrend_stoploss else 'Signal candle low', 'lf_candle_low': None, 'daily_supertrend_stoploss': None, 'trade_management_enabled': tm_enabled, 'trade_management_book_pct': tm_plan[0]['book_pct'] if tm_plan else 0.0, 'trade_management_trigger_pct': tm_plan[0]['trigger_pct'] if tm_plan else 0.0, 'trade_management_targets': [{'book_pct': leg['book_pct'], 'trigger_pct': leg['trigger_pct'], 'stoploss_pct': leg['stoploss_pct'], 'hit': bool(leg['hit']), 'exit_price': leg['exit_price'], 'exit_time': str(leg['exit_time']) if leg['exit_time'] is not None else None, 'return_pct': leg['trigger_pct'] if leg['hit'] else None, 'stoploss_price': leg['stoploss_price'] if leg['hit'] else None} for leg in tm_legs], 'trade_management_partial_booked': tm_partial_booked, 'trade_management_partial_exit_price': tm_partial_exit_price, 'trade_management_partial_exit_time': str(tm_partial_exit_time) if tm_partial_exit_time is not None else None, 'trade_management_stoploss_moved_to_breakeven': tm_stoploss_moved_to_breakeven, 'trade_management_remaining_exit_pct': tm_remaining_exit_pct, 'trade_management_remaining_exit_type': tm_remaining_exit_type, 'trade_management_remaining_exit_reason': tm_remaining_exit_reason, 'trade_management_weighted_return_pct': tm_weighted_return_pct, 'trade_management_booked_qty_pct': round(_booked_fraction() * 100.0, 3), 'trade_management_remaining_qty_pct': round(_remaining_fraction() * 100.0, 3) if tm_enabled else None}

    @staticmethod
    def _skip_trend_block(df: pd.DataFrame, i: int) -> int:
        i += 1
        while i < len(df) and bool(df.iloc[i]['in_uptrend']):
            i += 1
        while i < len(df) and (not bool(df.iloc[i]['in_uptrend'])):
            i += 1
        return i

    @staticmethod
    def _skip_trend_block_fast(uptrend_arr, i: int, length: int) -> int:
        """Same logic as _skip_trend_block but uses pre-extracted numpy array."""
        i += 1
        while i < length and bool(uptrend_arr[i]):
            i += 1
        while i < length and (not bool(uptrend_arr[i])):
            i += 1
        return i