import httpx
import pandas as pd
from datetime import datetime, timezone
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from sqlalchemy import create_engine

# Load ALL unique companies and their earliest daily candle date from the PostgreSQL database
engine = create_engine('postgresql://postgres:postgres@localhost:5432/trade_signal')
print(f"Loading active companies and their start dates from database...")
query = """
    SELECT s.symbol, MIN(c.datetime) as start_date 
    FROM stock_master s 
    LEFT JOIN market_candles_cleaned c ON s.symbol = c.symbol 
    WHERE s.active = true 
    GROUP BY s.symbol
"""
df_master = pd.read_sql(query, engine)
# Map of symbol -> start_date (as pandas Timestamp)
start_dates = {}
for _, row in df_master.iterrows():
    if pd.notna(row['start_date']):
        start_dates[row['symbol']] = pd.to_datetime(row['start_date']).replace(tzinfo=timezone.utc)
    else:
        start_dates[row['symbol']] = datetime(2021, 1, 1, tzinfo=timezone.utc)

companies = df_master['symbol'].unique().tolist()
print(f"Found {len(companies)} unique companies.")

output_dir = r"C:\Users\Yug\Desktop\rsi\data\5min_historical"
os.makedirs(output_dir, exist_ok=True)

companies_to_fetch = [c for c in companies]
print(f"Total {len(companies_to_fetch)} companies to process and update.")

client = httpx.Client(
    timeout=15.0,
    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    limits=httpx.Limits(max_connections=200, max_keepalive_connections=50)
)

def fetch_5min(symbol):
    clean = symbol.replace(".NS", "").strip().upper()
    csv_file = os.path.join(output_dir, f"{clean}_5m.csv")
    
    symbol_start_date = start_dates.get(clean, datetime(2021, 1, 1, tzinfo=timezone.utc))
    end_date = datetime.now(timezone.utc)
    
    start_ms = int(symbol_start_date.timestamp() * 1000)
    end_ms = int(end_date.timestamp() * 1000)
    
    # We will fetch the full requested range
    url = (
        f"https://groww.in/v1/api/charting_service/v2/chart/"
        f"exchange/NSE/segment/CASH/{clean}"
        f"?intervalInMinutes=5&minimal=false"
        f"&startTimeInMillis={start_ms}&endTimeInMillis={end_ms}"
    )
    try:
        res = client.get(url)
        if res.status_code == 200:
            raw = res.json().get("candles", [])
            candles = []
            for c in raw:
                if not isinstance(c, (list, tuple)) or len(c) < 5:
                    continue
                if c[1] is None or c[2] is None or c[3] is None or c[4] is None:
                    continue
                ts = c[0]
                if ts >= 10_000_000_000:
                    ts = ts / 1000.0
                dt = datetime.fromtimestamp(ts)
                candles.append({
                    "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "volume": int(c[5]) if len(c) > 5 and c[5] is not None else 0
                })
            
            df_new = pd.DataFrame(candles)
            if not df_new.empty:
                df_new['dt_obj'] = pd.to_datetime(df_new['datetime'])
                end_str = end_date.strftime("%Y-%m-%d %H:%M:%S")
                start_str = symbol_start_date.strftime("%Y-%m-%d")
                df_new = df_new[(df_new['dt_obj'] >= start_str) & (df_new['dt_obj'] <= end_str)]
                df_new.drop(columns=['dt_obj'], inplace=True)
            
            # Merge with existing data
            if os.path.exists(csv_file):
                df_existing = pd.read_csv(csv_file)
                if not df_new.empty:
                    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                else:
                    df_combined = df_existing
            else:
                df_combined = df_new
                
            if not df_combined.empty:
                # Drop duplicates based on datetime and sort
                df_combined.drop_duplicates(subset=['datetime'], keep='last', inplace=True)
                df_combined.sort_values(by='datetime', inplace=True)
                df_combined.to_csv(csv_file, index=False)
                return f"Success: {clean} (Total {len(df_combined)} rows)"
            else:
                return f"Empty: {clean}"
        return f"Failed: {clean} (Status {res.status_code})"
    except Exception as e:
        return f"Error: {clean} - {str(e)}"

def main():
    if not companies_to_fetch:
        print("Nothing left to fetch!")
        return

    print(f"Updating 5m data for {len(companies_to_fetch)} companies...")
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(fetch_5min, sym): sym for sym in companies_to_fetch}
        success_count = 0
        for future in as_completed(futures):
            res = future.result()
            print(res)
            if "Success" in res:
                success_count += 1
    print(f"\nDone! Successfully updated data for {success_count}/{len(companies_to_fetch)} companies.")

if __name__ == "__main__":
    main()