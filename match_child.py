import sys
sys.path.insert(0, 'src')
from rsi_supertrend_backtester.orders.dhan_client import _client
from rsi_supertrend_backtester.orders import trade_store

dhan = _client()
res = dhan.get_order_list()
orders = res.get('data', [])

active_trades = trade_store.load_active_trades()

for trade in active_trades:
    company = trade['company']
    target = trade['target_price']
    sl = trade['stoploss_price']
    print(f"\nChecking active trade: {company} (Target: {target}, SL: {sl})")
    
    for o in orders:
        if o.get('tradingSymbol') == company and o.get('transactionType') == 'SELL':
            print(f"  Found SELL order: Status={o.get('orderStatus')} Price={o.get('price')} Trigger={o.get('triggerPrice')} ID={o.get('orderId')}")
