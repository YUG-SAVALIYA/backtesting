import sys
import os
import pandas as pd
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from rsi_supertrend_backtester.io.data_loader import MarketDataLoader

loader = MarketDataLoader("d:/AT/AI_Trading/data")

print("Loading data for 360ONE...")
try:
    df = loader._read_csv(Path("d:/AT/AI_Trading/data/360ONE_daily.csv"))
    print(df.head())
    print("Total rows:", len(df))
    print("Start date:", df['datetime'].min())
    print("End date:", df['datetime'].max())
except Exception as e:
    print("Error:", e)
