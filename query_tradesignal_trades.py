import sys
import pandas as pd
from sqlalchemy import create_engine
engine = create_engine('postgresql://postgres:postgres@localhost:5432/trade_signal')

try:
    df = pd.read_sql("SELECT * FROM rsi_signals WHERE signal_date >= '2026-06-15' AND signal_date <= '2026-07-28'", engine)
    print('--- SIGNALS ---')
    print(f'Total: {len(df)}')
    if len(df) > 0: print(df[['symbol', 'signal_date', 'status', 'trigger_price', 'stop_loss', 'target']].to_string())
    
    df_pos = pd.read_sql("SELECT * FROM rsi_positions WHERE entry_date >= '2026-06-15' AND entry_date <= '2026-07-28'", engine)
    print('\n--- POSITIONS ---')
    print(f'Total: {len(df_pos)}')
    if len(df_pos) > 0: print(df_pos[['symbol', 'entry_date', 'entry_price', 'status', 'exit_date', 'exit_price', 'pnl_percentage']].to_string())
except Exception as e:
    print(e)
