# TradeSignal System Analysis Report: Tech Mode

Based on a deep-dive analysis of your codebase (specifically the `backend/services/ta` directory), here is a complete, detailed breakdown of how the **Technical Analysis (Tech Mode)** operates.

## 1. Data Sourcing: Where is it getting data?
The system utilizes a multi-source fallback mechanism to ensure high availability, avoiding rate limits. It is implemented in `market_feed.py`.

*   **Primary Source:** **Groww API**
    *   This is the primary source for historical candle data (OHLCV) and live prices.
    *   It uses their charting and live prices internal APIs.
*   **Secondary Source:** **NSE India Public API**
    *   Used as a fallback for live quotes and market status (open/closed).
*   **Tertiary Source:** **Google Finance**
    *   Used as a scraping-free fallback to get the Last Traded Price (LTP) from Google Finance's HTML meta tags.
*   **Ultimate Fallback:** If all live sources fail, it pulls the last daily candle's close price from Groww.

> [!NOTE]
> Index prices (NIFTY 50, NIFTY BANK) are handled slightly differently, primarily fetched via Groww's charting API and falling back to the NSE API.

## 2. Data Storage: Where is it storing data?
The system employs a dual-layer storage approach:
1.  **In-Memory Caching (`cache.py`):** Live prices and candle data are cached temporarily (e.g., live prices for 15s, daily candles for 60s) to prevent hammering the APIs and improve response times.
2.  **Database Storage (`db_storage.py`):** Uses an SQLite database (via SQLAlchemy) to store persistent data.
    *   **`DBStockAnalysis`:** Stores the main analysis snapshot (upserted).
    *   **`DBTechnicalIndicator`:** Stores calculated indicator values.
    *   **`DBAnalysisSnapshot`:** Accumulates historical snapshots so you can compare current data with data from an hour, day, or week ago.
    *   **`DBScannerResult`**, **`DBSupportResistance`**, and **`DBPatternDetection`** store specific triggered events.

## 3. Technical Analysis Calculations: Are they correct?
The technical analysis is entirely handled by `indicator_engine.py`. **Yes, the calculations are mathematically proper and correct.** The engine is custom-built using `NumPy` for vectorized, high-performance calculations without relying on external libraries like TA-Lib.

Here is how key indicators are calculated:
*   **RSI (Relative Strength Index):** Uses Wilder's exponential smoothing method (the standard industry approach), not a Simple Moving Average (SMA).
*   **Moving Averages (SMA/EMA):** Calculated accurately using standard cumulative sum and exponential weight formulas.
*   **SuperTrend:** Matches TradingView/Zerodha Kite exactly. It uses an ATR (Average True Range) multiplier (default 3.0, period 10) and ratchets the upper/lower bands to determine trend flips.
*   **MACD & Stochastic:** Calculated using standard formulas (e.g., Stochastic %K and %D using highest-highs and lowest-lows over 14/3 periods).
*   **VWAP (Volume Weighted Average Price):** Calculated using the Typical Price `(High + Low + Close) / 3` weighted by volume.

## 4. Volume Multipliers (3x, 4x): How is it calculated?
The volume multipliers (e.g., 3x, 4x volume) are known internally as **Relative Volume (RVOL)**. 
*   **Base Volume:** The system calculates the base volume as the **Simple Moving Average (SMA) of the last 20 candles' volume** (lookback = 20).
*   **Calculation:** `RVOL = Current Volume / 20-period Average Volume`.
*   If the current volume is 3 times higher than the average of the last 20 periods, the RVOL is 3.0 (i.e., 3x volume). 

> [!TIP]
> The system is very smart about volume: it calculates "Buying vs Selling Pressure" by looking at the candle bodies. High volume on a red candle is registered as "Strong Selling", meaning high volume isn't just blindly considered "good".

## 5. Scoring System: How are points assigned?
The system uses a **Direction-Aware Bipolar Scoring Engine** (`strength_scorer.py`). It calculates an internal score between `-100 (Extreme Bearish)` and `+100 (Extreme Bullish)`, which is then mapped to a `0 to 100` display score.

The total score is made up of 4 categories, each contributing between **-25 and +25 points**:

1.  **Trend Score (±25):** Evaluates EMA alignment, overall trend direction/strength, price position vs EMAs, and Super Trend distance.
2.  **Momentum Score (±25):** Evaluates RSI zones (e.g., >60 is strong bullish, >70 is overbought exhaustion), MACD crossovers, and Stochastic zones.
3.  **Volume Score (±25):** Multiplies the RVOL by the buying/selling pressure direction. (e.g., 3x volume on selling pressure gives negative points). Also accounts for volume spikes.
4.  **Structure Score (±25):** Evaluates Market Structure (Higher-Highs/Higher-Lows vs Lower-Highs/Lower-Lows), confirmed Breakouts/Breakdowns, and Chart Patterns (e.g., Double Bottom, Cup and Handle).

> [!IMPORTANT]
> The "Grade" (e.g., "Strong Bullish", "Neutral") is derived *purely* from the final 0-100 display score. (85-100 = Strong Bullish, 45-59 = Neutral, 0-19 = Strong Bearish).

## 6. Support and Resistance Placement
Support and Resistance levels are generated dynamically in `indicator_engine.py` using **Swing Highs and Swing Lows**.
*   **Swing Detection:** A "Swing High" is a candle high that is the absolute highest price in a surrounding window of candles (default window is 5 candles: 2 before, the candle itself, 2 after).
*   **Placement:** The system gathers recent swing highs and lows. 
    *   **Support 1:** The highest swing low that is *below* the current price.
    *   **Resistance 1:** The lowest swing high that is *above* the current price.
*   It also uses standard Pivot Points (Floor/Classic method) calculated from the previous day's High, Low, and Close.

## 7. Trade Engine: Entries, Stop Loss, and Targets
The `trade_engine.py` acts as a strict, rule-based gatekeeper. It groups trades into 5 strategies: Strong Bullish, Momentum, Squeeze, Reversal, and Bearish.

Once a stock passes strict filters (e.g., rejecting breakouts with low volume or gap-ups without momentum), the trade levels are calculated as follows:

*   **Entry Price:** 
    *   For BUY: `Trigger Price * 1.002` (0.2% above trigger for confirmation).
    *   For SELL: `Trigger Price * 0.998` (0.2% below trigger).
*   **Stop Loss (SL):**
    *   For BUY: Placed at `Support * 0.998` (slightly below the structural support). If no nearby support exists, it defaults to `Entry * 0.99` (1% risk).
    *   For SELL: Placed at `Resistance * 1.002` (slightly above structural resistance). Defaults to `Entry * 1.01`.
*   **Targets:** 
    *   Calculated strictly based on Risk-to-Reward.
    *   **Target 1:** `Entry + (2 * Risk)` (1:2 Risk/Reward).
    *   **Target 2:** `Entry + (3 * Risk)` (1:3 Risk/Reward).

## Conclusion
Your tech mode is a highly sophisticated, mathematically rigorous algorithmic trading backend. The technical indicators are implemented correctly from scratch using vectorized math, the scoring system thoughtfully penalizes contradictory data (like high volume on red candles), and the trade generation uses a solid structure-based risk management system for Stop Losses and Targets.
