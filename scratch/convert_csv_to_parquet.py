import os
import pandas as pd
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

def convert_file(csv_path: Path):
    parquet_path = csv_path.with_suffix('.parquet')
    if parquet_path.exists():
        return f"Skipped (already exists): {csv_path.name}"
    
    try:
        # Read the csv, mirroring the logic in MarketDataLoader
        df = pd.read_csv(csv_path)
        
        # If no header (5m fix)
        if 'date' not in df.columns and 'datetime' not in df.columns:
            df = pd.read_csv(csv_path, header=None, names=['datetime','open','high','low','close','volume'])
        
        if 'date' in df.columns:
            df.rename(columns={'date': 'datetime'}, inplace=True)
            
        raw_dt = df["datetime"].astype(str).str[:19]
        parsed = pd.to_datetime(raw_dt, format="%Y-%m-%d %H:%M:%S", errors="coerce")
        bad_mask = parsed.isna()
        if bad_mask.any():
            parsed[bad_mask] = pd.to_datetime(raw_dt[bad_mask], errors="coerce")
            
        df["datetime"] = parsed
        df = df.dropna(subset=["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        
        # Convert all standard columns to numeric explicitly to ensure parquet types are clean
        for col in ['open', 'high', 'low', 'close']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        if 'volume' in df.columns:
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce')

        # Save to parquet
        df.to_parquet(parquet_path, engine='pyarrow', index=False)
        return f"Converted: {csv_path.name}"
    except Exception as e:
        return f"Error converting {csv_path.name}: {e}"

if __name__ == "__main__":
    data_dir = Path("C:/Users/Yug/Desktop/Data")
    csv_files = list(data_dir.glob("*.csv"))
    print(f"Found {len(csv_files)} CSV files. Converting to Parquet...")
    
    # We will process large files (5min) and small files together
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(convert_file, path): path for path in csv_files}
        
        completed = 0
        for future in as_completed(futures):
            res = future.result()
            completed += 1
            if completed % 100 == 0:
                print(f"Progress: {completed}/{len(csv_files)}")
                
    print("Done converting!")
