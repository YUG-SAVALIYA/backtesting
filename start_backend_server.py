import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

# Keep the local backtester UI/API available even when Dhan live sockets are
# blocked by Windows/network permissions. Live trading can start its own feed.
os.environ.setdefault("RSI_DISABLE_DHAN_BACKGROUND", "1")

import uvicorn

if __name__ == "__main__":
    uvicorn.run("rsi_supertrend_backtester.api:app", host="127.0.0.1", port=8000, workers=1)
