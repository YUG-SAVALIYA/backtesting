import sys
sys.path.insert(0, 'src')
from rsi_supertrend_backtester.orders.dhan_client import _client
dhan = _client()

# Fetch LTP for SUNPHARMA and HINDALCO
# SUNPHARMA securityId: 3333
# HINDALCO securityId: 1363
# (Verify these if possible)

try:
    # Use quotes to get LTP
    resp = dhan.get_quote_data(security_id='3333', exchange_segment='NSE_EQ', instrument_type='EQUITY')
    print("SUNPHARMA Quote:", resp)
    
    resp_h = dhan.get_quote_data(security_id='1363', exchange_segment='NSE_EQ', instrument_type='EQUITY')
    print("HINDALCO Quote:", resp_h)
except Exception as e:
    print("Error getting quotes:", e)
