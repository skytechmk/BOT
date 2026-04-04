import sys
import os
sys.path.append(os.getcwd())
from trading_utilities import is_prime_trading_session, detect_market_regime, CircuitBreaker
import pandas as pd
import numpy as np

def test():
    print(f"Session Filter Active: {is_prime_trading_session()}")
    df = pd.DataFrame({'ADX': [30], 'Upper Band': [105], 'Lower Band': [95], 'SMA_20': [100]})
    print(f"Market Regime: {detect_market_regime(df)}")
    
    cb = CircuitBreaker("/tmp/test_cb.json")
    cb.update_pnl(-2.0)
    cb.update_pnl(-4.0)
    blocked, reason = cb.should_block_trade()
    print(f"Circuit Breaker Blocked: {blocked}, Reason: {reason}")

if __name__ == '__main__':
    test()
