# Technical Analysis Logic Flaws Report

Based on a deep-dive audit of the calculation engines (`scanner_engine.py`, `pattern_engine.py`, `indicator_engine.py`), I have found several major logical flaws where the code takes "lazy" shortcuts that violate proper Technical Analysis rules. 

Here are the most significant issues that will cause false signals in live trading:

## 1. Fake "Golden Cross" (EMA Crossover)
*   **File:** `scanner_engine.py` (`scan_ema_crossover`)
*   **The Issue:** To detect an EMA 20 / EMA 50 crossover, the code simply checks if the distance between the two moving averages is less than 0.3%.
*   **Why it's wrong:** It **never actually checks if a cross happened**. If the 20 EMA and 50 EMA are just moving parallel to each other and are very close, the scanner will falsely fire "Golden Cross Imminent" every single day. A true crossover scanner must check yesterday's values (e.g., Yesterday EMA20 < EMA50 AND Today EMA20 > EMA50).

## 2. The "Forever Breakout" Bug
*   **File:** `pattern_engine.py` (`detect_breakout`)
*   **The Issue:** It defines Resistance simply as the "Highest High of the last 20 candles". If the current price closes above that, it triggers a Breakout.
*   **Why it's wrong:** In a strong, healthy uptrend, a stock makes a new high almost every day. Because the "last 20 days high" trails behind the current price, this logic will spam a "Breakout Confirmed" signal **every single day of an uptrend**. A real breakout should only trigger when price breaks out of a *consolidation zone* or a previously tested swing high.

## 3. Flawed Trendline Slopes for Triangles
*   **File:** `pattern_engine.py` (`detect_triangle`)
*   **The Issue:** To figure out if a triangle is pointing up or down, it calculates the slope of the trendline using the formula: `(last_price - first_price) / number_of_points`.
*   **Why it's wrong:** This completely ignores time (the X-axis on a chart). The first and last swing points could be 5 days apart, or they could be 50 days apart. By ignoring the time elapsed, the calculated slope angle is mathematically incorrect and will detect false triangles.

## 4. Oversimplified Volume Pressure
*   **File:** `indicator_engine.py` (`buying_selling_pressure`)
*   **The Issue:** If a candle's Close is strictly less than its Open, 100% of the volume for that candle is marked as "Bearish Selling Volume".
*   **Why it's wrong:** What if a stock opens at ₹100, crashes down to ₹80, but buyers step in aggressively and push the price all the way back up to close at ₹99? That is a massive Bullish Hammer showing huge buying pressure. However, because the close (99) is less than the open (100), your system marks it as a massive bearish sell-off.

## 5. Support Levels Instantly Vanish
*   **File:** `indicator_engine.py` (`dynamic_support_resistance`)
*   **The Issue:** To find Support, it filters all recent swing lows and only keeps the ones where `price < current_price`. 
*   **Why it's wrong:** Support is a zone, not a razor-thin line. If the price drops just 1 single tick below the support level, that support level is instantly deleted from the list. The system then assumes the *next* support level is the only valid one (which might be 15% lower), causing the Stop Loss logic to place wildly inaccurate stops.

## 6. The "Gap Up" is actually just "Price Up"
*   **File:** `scanner_engine.py` (`scan_gap_up`)
*   **The Issue:** As discussed previously, it calculates gaps by comparing the Current Live Price to Yesterday's Close, rather than comparing Today's Open to Yesterday's Close.
