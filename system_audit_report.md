# System Audit Report: Detailed Field Breakdown

This report provides a granular breakdown of every single metric evaluated by the Discovery Engine across the Technical, Fundamental, and Macro pillars.

---

## 1. Top-Down Discovery Architecture

The system evaluates stocks at two distinct levels:
1. **The Group Level (Sectors/Industries):** Ranks entire industries to tell you *WHERE* the strongest market momentum and fundamentals are located.
2. **The Company Level (Specific Stocks):** Ranks individual stocks within their industries to tell you *WHAT* specific asset to buy.

The final score for any asset combines 3 dimensions:
- **Technical Score (40% Weight):** Price and Volume momentum.
- **Fundamental Score (40% Weight):** Financial health and efficiency.
- **Macro Score (20% Weight):** LLM-evaluated economic news and tailwinds.

---

## 2. Technical Analysis Fields (40% Weight)

Technical analysis measures price momentum and volume conviction relative to the NIFTY 500 benchmark.

### A. Return Score (40% Company Weight | 25% Group Weight)
- **What it measures:** Did the asset outperform the broader market?
- **Company Math (Continuous Scale):** Uses a linear scale capped at 10%. If a stock beats the benchmark by +5%, it scores 75.0. If it beats it by +10% or more, it scores 100.0. If it trails by -10% or more, it scores 0.0.
- **Group Math (Percentile Rank):** Finds the median return of the entire sector, then stack-ranks that median against all other sectors in the market (0 to 100).

### B. Consistency Score (40% Company Weight | 25% Group Weight)
- **What it measures:** Is the outperformance a steady trend, or a one-off spike?
- **Company Math (Raw %):** Divides the timeframe into blocks (e.g., 5 weeks). If the stock beat the market in 3 out of 5 blocks, it scores `60.0`.
- **Group Math (Average):** Calculates the simple average of all the consistency scores of the companies inside that sector.

### C. Volume Score (20% Company Weight | 25% Group Weight)
- **What it measures:** Are institutional buyers supporting the price move?
- **Company Math (Continuous Scale):** Uses a 50% scale based on price direction. 
  - *Price UP:* A +50% volume surge scores 100 (Bullish). A -50% volume drop scores 0 (Bearish Divergence).
  - *Price DOWN:* A +50% volume surge scores 0 (Bearish). A -50% volume drop scores 100 (Healthy Pullback).
- **Group Math (Raw %):** Evaluates what percentage of the stocks in the sector had high confirming volume. If 40% of the stocks saw high volume, the score is `40.0`.

### D. Breadth Score (N/A for Companies | 25% Group Weight)
- **What it measures:** Is the rally supported by most of the sector, or just one giant stock carrying the group?
- **Company Math:** N/A (A single stock cannot have breadth).
- **Group Math (Raw %):** Calculates two metrics: Absolute Breadth (% of stocks that went up) and Relative Breadth (% of stocks that beat the benchmark). It averages these two to get the final Breadth Score.

---

## 3. Fundamental Analysis Fields (40% Weight)

Fundamental analysis relies on **Peer Relative Comparisons**. The exact same 4 pillars (weighted 25% each) are used for both Companies and Groups. 

- **Company Math:** Compares the company's raw metric to the **median of its Basic Industry**, using the formula: `Score = 50.0 + ((Distance from Median) / Scale) * 50.0`.
- **Group Math:** Finds the median of the entire sector, then stack-ranks it against all other sector medians via **Percentile Rank**.

### Pillar 1: Growth (25%)
- **Sales Growth:** Evaluates top-line revenue expansion compared to peers. *(Company Scale: 20%)*
- **Net Profit Growth:** Evaluates bottom-line net profit expansion compared to peers. *(Company Scale: 20%)*
- *Transitions:* If standard growth % can't be calculated (e.g. going from a loss to a profit), hardcoded scores apply (e.g., `LOSS_TO_PROFIT` = 90, `LOSS_WIDENED` = 10).

### Pillar 2: Profitability (25%)
- **Operating Margin:** Evaluates profit efficiency relative to peers. *(Company Scale: 10%)*
- **Margin Trend:** Evaluates if the margin is expanding or shrinking year-over-year relative to peers. *(Company Scale: 5%)*

### Pillar 3: Financial Strength (25%)
- **Debt-to-Equity:** Evaluates balance sheet leverage. Lower is better, so the formula is reversed. *(Company Scale: 1.0 Ratio)*
- **Borrowing Trend:** Evaluates if the company is taking on more debt or paying it off compared to peers. *(Company Scale: 50%)*
- *(Note: Marked N/A for Banking/Financial groups, weight redistributed).*

### Pillar 4: Earnings Quality (25%)
- **Cash Conversion:** Evaluates Operating Cash Flow divided by Profit After Tax. A ratio > 1 means paper profits are becoming actual cash. *(Company Scale: 1.0 Ratio)*
- **Profit Volatility:** Evaluates how wildly profits jump up and down. Lower volatility is better (reversed formula). *(Company Scale: 50%)*
- **Profit History:** Simply the percentage of profitable years over the last 5 years (e.g., 5/5 = 100.0). *(No peer comparison, direct percentage).*

---

## 4. Macro Analysis Fields (20% Weight)

Macro Scoring evaluates the broader economic and geopolitical environment. It does not use numerical formulas; it uses qualitative LLM analysis.

### The Impact Evaluation
The system aggregates news articles, supply chain reports, regulatory updates, and economic indicators. It passes this text to an LLM, asking it to evaluate the specific impact on a Basic Industry, Industry, or Sector.

There are no sub-fields (like "inflation" or "rates"). The LLM returns a single overarching text rating, which the backend translates into the final Macro Score:
- **HIGH_POSITIVE** ➔ 100.0
- **LOW_POSITIVE** ➔ 75.0
- **NEUTRAL** ➔ 50.0
- **LOW_NEGATIVE** ➔ 25.0
- **HIGH_NEGATIVE** ➔ 0.0

---

## 5. Horizon Adjustments

The core metrics remain identical, but the **lookback windows** and **Macro context** adjust based on the selected horizon:
- **SHORT**: Technicals check the last 5 days. Macro focuses on immediate news and weekly economic data.
- **MID**: Technicals check the last 4 weeks. Macro focuses on quarterly earnings trends.
- **LONG**: Technicals check the last 6 months. Macro focuses on structural, multi-year economic cycles.
