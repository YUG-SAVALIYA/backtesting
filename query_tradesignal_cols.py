import pandas as pd
from sqlalchemy import create_engine
engine = create_engine('postgresql://postgres:postgres@localhost:5432/trade_signal')

df = pd.read_sql("SELECT symbol, signal_date, status, entry_price, stop_loss, target_price FROM rsi_signals", engine)
df['signal_date'] = pd.to_datetime(df['signal_date'], unit='ms')
df = df[(df['signal_date'] >= '2026-06-15') & (df['signal_date'] <= '2026-07-28')]
print('--- SIGNALS ---')
print(f'Total: {len(df)}')
if len(df) > 0:
    print(df.to_string())

df_pos = pd.read_sql("SELECT * FROM rsi_positions", engine)
df_pos['entry_time'] = pd.to_datetime(df_pos['entry_time'], unit='ms')
df_pos = df_pos[(df_pos['entry_time'] >= '2026-06-15') & (df_pos['entry_time'] <= '2026-07-28')]
print('\n--- POSITIONS ---')
print(f'Total: {len(df_pos)}')
if len(df_pos) > 0:
    print("Columns:", df_pos.columns.tolist())
    print(df_pos[['symbol', 'entry_time', 'status', 'entry_price']].to_string())
