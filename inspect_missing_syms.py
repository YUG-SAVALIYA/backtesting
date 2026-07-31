import pandas as pd

json_symbols = ['CONFIPET', 'GALAPREC', 'KAMDHENU', 'XPROINDIA']
daily_csv_path = r"C:\Users\Yug\Desktop\rsi\data\companies_1yr_daily_candles.csv"

df_daily_all = pd.read_csv(daily_csv_path)
if 'date' in df_daily_all.columns:
    df_daily_all.rename(columns={'date': 'datetime'}, inplace=True)
df_daily_all['datetime'] = pd.to_datetime(df_daily_all['datetime'])

print("=== CHECKING SYMBOLS MISSING IN LIVE RUN ===")

for sym in json_symbols:
    df_sym = df_daily_all[df_daily_all['symbol'] == sym].sort_values('datetime').reset_index(drop=True)
    if df_sym.empty:
        print(f"Symbol {sym}: NOT FOUND IN DAILY CSV!")
    else:
        print(f"Symbol {sym}: Found {len(df_sym)} daily rows. Latest date = {df_sym['datetime'].iloc[-1].strftime('%Y-%m-%d')}")
