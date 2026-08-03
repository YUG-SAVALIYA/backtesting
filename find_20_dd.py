import json
from find_best_filters import evaluate_combination

def run():
    data = json.load(open(r'output\backtest_2026-07-31_22-16-17_2102stocks.json', 'r', encoding='utf-8'))
    signals = data.get('signals', [])
    
    best_combos = []
    
    for rsiL_min in [60, 65, 70]:
        for rsiH_min in [60, 65]:
            for adx in [20, 25, 26]:
                for mcap in [5000, 8000, 10000]:
                    for mhlf in [3.0, 4.0]:
                        for clf in [0.0, 1.0]:
                            args = (rsiL_min, 80, rsiH_min, 85, adx, 3, 10, mcap, mhlf, clf, signals)
                            c, avg, dd, pnl, _ = evaluate_combination(args)
                            if c >= 30:
                                best_combos.append((c, avg, dd, pnl, args))
                                    
    best_combos.sort(key=lambda x: x[2])
    print("BEST COMBOS (MIN 30 TRADES, LOWEST DD):")
    for b in best_combos[:5]:
        c, avg, dd, pnl, args = b
        print(f"Trades: {c}, DD: {dd:.2f}%, PNL: {pnl:,.2f}")
        print(f"RSI L {args[0]}-{args[1]}, H {args[2]}-{args[3]}")
        print(f"ADX >= {args[4]}, Range 3-10, Mcap >= {args[7]}, MHLF >= {args[8]}, CLF >= {args[9]}")
        print("-" * 30)

if __name__ == '__main__':
    run()
