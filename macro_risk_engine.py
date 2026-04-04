
import requests
import time
from datetime import datetime
import json
import os

class MacroRiskEngine:
    """
    Institutional-grade Macro & Liquidity Risk Engine.
    Tracks global market sentiment, liquidity flows, and systemic risks.
    """
    def __init__(self, log_path="performance_logs/macro_risk.json"):
        self.log_path = log_path
        self.last_update = 0
        self.cache_duration = 3600  # 1 hour cache for macro data
        self.state = {
            'fear_greed': 50,
            'fear_greed_sentiment': 'Neutral',
            'global_funding_rate': 0.01,
            'liquidity_risk': 'Low',
            'market_regime': 'Stable',
            'risk_score': 0.5,  # 0 (Safe) to 1 (Extreme Risk)
            'last_updated': None
        }
        self.load_state()

    def load_state(self):
        if os.path.exists(self.log_path):
            try:
                with open(self.log_path, 'r') as f:
                    self.state = json.load(f)
                    self.last_update = self.state.get('timestamp', 0)
            except Exception:
                pass

    def save_state(self):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        self.state['timestamp'] = time.time()
        self.state['last_updated'] = datetime.now().isoformat()
        with open(self.log_path, 'w') as f:
            json.dump(self.state, f, indent=2)

    def get_fear_greed_index(self):
        """Fetch Bitcoin Fear & Greed Index from alternative.me API"""
        try:
            response = requests.get("https://api.alternative.me/fng/", timeout=10)
            data = response.json()
            if 'data' in data and len(data['data']) > 0:
                val = int(data['data'][0]['value'])
                sentiment = data['data'][0]['value_classification']
                return val, sentiment
        except Exception:
            pass
        return 50, "Neutral"

    def get_global_funding_sentiment(self, client):
        """Calculate average funding rate across top 50 pairs to gauge market heat"""
        try:
            bellwethers = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']
            rates = []
            for symbol in bellwethers:
                f = client.futures_funding_rate(symbol=symbol, limit=1)
                if f:
                    rates.append(float(f[0]['fundingRate']))
            
            avg_rate = sum(rates) / len(rates) if rates else 0.01
            return avg_rate
        except Exception:
            return 0.01

    def update_risk_metrics(self, binance_client=None):
        """Update all macro metrics and calculate unified risk score"""
        now = time.time()
        if now - self.last_update < self.cache_duration and self.state['last_updated']:
            return self.state

        # 1. Fear & Greed
        fng_val, fng_sent = self.get_fear_greed_index()
        self.state['fear_greed'] = fng_val
        self.state['fear_greed_sentiment'] = fng_sent

        # 2. Funding Sentiment
        if binance_client:
            avg_funding = self.get_global_funding_sentiment(binance_client)
            self.state['global_funding_rate'] = avg_funding
        
        # 3. Calculate Risk Score (0 = Good to Trade, 1 = Dangerous)
        fng_risk = 0
        if fng_val < 20 or fng_val > 80: fng_risk = 0.5
        elif fng_val < 25 or fng_val > 75: fng_risk = 0.4
        elif fng_val < 40 or fng_val > 60: fng_risk = 0.2

        # Funding risk: High positive rates = overcrowded longs. High negative = short squeeze risk.
        funding_risk = 0
        if abs(self.state['global_funding_rate']) > 0.03: funding_risk = 0.5
        elif abs(self.state['global_funding_rate']) > 0.01: funding_risk = 0.2

        self.state['risk_score'] = min(1.0, fng_risk + funding_risk)
        
        # Define Regime — MUST match RegimePositionSizer expected values
        if self.state['risk_score'] > 0.8:
            self.state['market_regime'] = 'SYSTEMIC_PANIC'
        elif self.state['risk_score'] > 0.6:
            self.state['market_regime'] = 'HIGH_RISK'
        elif self.state['risk_score'] > 0.4:
            self.state['market_regime'] = 'VOLATILE_CAUTION'
        elif fng_val > 60 and self.state['risk_score'] < 0.2:
            self.state['market_regime'] = 'BULLISH_TREND'
        else:
            self.state['market_regime'] = 'STABLE'

        self.save_state()
        return self.state

    def should_allow_trading(self):
        """Institutional gate: blocks all trading if macro risk is too high"""
        if self.state['market_regime'] == 'SYSTEMIC_PANIC':
            return False, "Systemic Macro Risk too high (Panic-level Sentiment/Funding)"
        return True, ""

    def get_summary_report(self):
        return (
            f"🌍 **MACRO RISK REPORT**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎭 Sentiment: {self.state['fear_greed']} ({self.state['fear_greed_sentiment']})\n"
            f"💸 Avg Funding: {self.state['global_funding_rate']:.4f}%\n"
            f"🛡️ Risk Score: {self.state['risk_score']:.2f}/1.00\n"
            f"🚦 Status: **{self.state['market_regime']}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━"
        )
