
import numpy as np
import pandas as pd
from datetime import datetime, time, timedelta, timezone
import json
import os

# Aladdin Rust Core Integration (availability check in rust_integration.py)
from rust_integration import RUST_CORE_AVAILABLE
import time as time_module
import uuid
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from utils_logger import log_message, log_message as log_msg

def is_prime_trading_session():
    """Check if current time is within high-volatility session overlaps"""
    now = datetime.now().time()
    london_start, london_end = time(8, 0), time(16, 0)
    ny_start, ny_end = time(13, 0), time(21, 0)
    tokyo_start, tokyo_end = time(0, 0), time(8, 0)
    
    in_london = london_start <= now <= london_end
    in_ny = ny_start <= now <= ny_end
    in_tokyo = tokyo_start <= now <= tokyo_end
    return in_london or in_ny or (in_tokyo and now >= time(2,0))

def get_order_book_imbalance(client, symbol):
    """Calculate the bid/ask volume imbalance ratio"""
    try:
        depth = client.futures_order_book(symbol=symbol, limit=20)
        bids, asks = depth.get('bids', []), depth.get('asks', [])
        bid_vol = sum(float(b[1]) for b in bids)
        ask_vol = sum(float(a[1]) for a in asks)
        if ask_vol == 0: return 2.0
        return bid_vol / ask_vol
    except Exception:
        return 1.0

def calculate_pearson_correlation(client, symbol1, symbol2='BTCUSDT', timeframe='1h', limit=25):
    """Calculate the 24h Pearson correlation using percentage RETURNS (not raw prices)"""
    try:
        k1 = client.futures_klines(symbol=symbol1, interval=timeframe, limit=limit)
        k2 = client.futures_klines(symbol=symbol2, interval=timeframe, limit=limit)
        
        # Use pct_change on close prices to get returns correlation
        c1 = pd.Series([float(k[4]) for k in k1]).pct_change().dropna()
        c2 = pd.Series([float(k[4]) for k in k2]).pct_change().dropna()
        
        if len(c1) < 10 or len(c2) < 10: return 0.7
        
        correlation = c1.corr(c2)
        return correlation if not pd.isna(correlation) else 0.7
    except Exception:
        return 0.7

def check_btc_correlation(client, signal_type, symbol=None):
    """Check if BTC is moving in the same direction and calculate strength"""
    try:
        btc_klines = client.futures_klines(symbol='BTCUSDT', interval='15m', limit=5)
        closes = [float(k[4]) for k in btc_klines]
        btc_trend = 'LONG' if closes[-1] > closes[0] else 'SHORT'
        
        direction_match = btc_trend == signal_type.upper()
        
        correlation_strength = 0.7
        if symbol:
            correlation_strength = calculate_pearson_correlation(client, symbol)
            
        return direction_match, correlation_strength
    except Exception:
        return True, 0.7

def detect_market_regime(df):
    """Detect if market is trending or ranging using ADX and BB Width"""
    if len(df) < 30: return "UNKNOWN"
    latest_adx = df['ADX'].iloc[-1] if 'ADX' in df.columns else 20
    if 'Upper Band' in df.columns and 'Lower Band' in df.columns and 'SMA_20' in df.columns:
        sma20 = df['SMA_20'].iloc[-1]
        bb_width = (df['Upper Band'].iloc[-1] - df['Lower Band'].iloc[-1]) / sma20 if sma20 > 0 else 0.05
    else:
        bb_width = 0.05
    if latest_adx > 25: return "TRENDING"
    elif bb_width < 0.02: return "RANGING_NARROW"
    else: return "RANGING"


class CircuitBreaker:
    """Manages trading pauses during extreme drawdowns"""
    def __init__(self, log_path="performance_logs/circuit_breaker.json"):
        self.log_path = log_path
        self.load_state()
        
    def load_state(self):
        try:
            if os.path.exists(self.log_path):
                with open(self.log_path, 'r') as f:
                    self.state = json.load(f)
            else:
                self.state = {'daily_pnl': 0, 'consecutive_losses': 0, 'last_reset': datetime.now().date().isoformat()}
        except Exception:
            self.state = {'daily_pnl': 0, 'consecutive_losses': 0, 'last_reset': datetime.now().date().isoformat()}

    def save_state(self):
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, 'w') as f:
                json.dump(self.state, f)
        except Exception:
            pass

    def check_reset(self):
        today = datetime.now().date().isoformat()
        if self.state['last_reset'] != today:
            self.state['daily_pnl'] = 0
            self.state['consecutive_losses'] = 0
            self.state['last_reset'] = today
            self.save_state()

    def update_pnl(self, pnl):
        self.check_reset()
        self.state['daily_pnl'] += pnl
        if pnl < 0:
            self.state['consecutive_losses'] += 1
        else:
            self.state['consecutive_losses'] = 0
        self.save_state()

    def should_block_trade(self, max_drawdown=-5.0, max_consecutive_losses=3):
        self.check_reset()
        if self.state['daily_pnl'] <= max_drawdown:
            return True, f"Daily drawdown hit ({self.state['daily_pnl']:.2f}%)"
        if self.state['consecutive_losses'] >= max_consecutive_losses:
            return True, f"Max consecutive losses hit ({self.state['consecutive_losses']})"
        return False, ""


def get_symbol_win_rate(symbol, logs_path="performance_logs/cornix_signals.json"):
    """Calculate historical win rate for a specific symbol"""
    try:
        if not os.path.exists(logs_path): return 0.5
        with open(logs_path, 'r') as f:
            signals = json.load(f)
        pair_signals = [s for s in signals.values() if s.get('pair') == symbol]
        if not pair_signals: return 0.5
        wins = sum(1 for s in pair_signals if s.get('status') == 'SUCCESS')
        return wins / len(pair_signals)
    except Exception:
        return 0.5


# ========== PHASE 5: SIGNAL QUALITY ENHANCEMENTS ==========

class PairCooldownManager:
    """Enforces minimum cooldown between signals for the same pair"""
    def __init__(self, cooldown_hours=2):
        self.cooldown_seconds = cooldown_hours * 3600
        self.last_signal_time = {}
    
    def can_send_signal(self, pair):
        now = time_module.time()
        last_time = self.last_signal_time.get(pair, 0)
        elapsed = now - last_time
        if elapsed < self.cooldown_seconds:
            remaining_min = (self.cooldown_seconds - elapsed) / 60
            return False, f"Cooldown active ({remaining_min:.0f}min remaining)"
        return True, ""
    
    def record_signal(self, pair):
        self.last_signal_time[pair] = time_module.time()


class AutoBlacklist:
    """Temporarily blacklists pairs with consecutive losses"""
    def __init__(self, max_consecutive_losses=3, blacklist_hours=24,
                 log_path="performance_logs/pair_blacklist.json"):
        self.max_losses = max_consecutive_losses
        self.blacklist_duration = blacklist_hours * 3600
        self.log_path = log_path
        self.consecutive_losses = {}
        self.blacklisted_until = {}
        self.load_state()
    
    def load_state(self):
        try:
            if os.path.exists(self.log_path):
                with open(self.log_path, 'r') as f:
                    data = json.load(f)
                    self.consecutive_losses = data.get('consecutive_losses', {})
                    self.blacklisted_until = data.get('blacklisted_until', {})
        except Exception:
            pass
    
    def save_state(self):
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, 'w') as f:
                json.dump({
                    'consecutive_losses': self.consecutive_losses,
                    'blacklisted_until': self.blacklisted_until
                }, f)
        except Exception:
            pass
    
    def is_blacklisted(self, pair):
        until = self.blacklisted_until.get(pair, 0)
        if time_module.time() < until:
            remaining_h = (until - time_module.time()) / 3600
            return True, f"Blacklisted for {remaining_h:.1f}h ({self.consecutive_losses.get(pair, 0)} consecutive losses)"
        elif until > 0:
            del self.blacklisted_until[pair]
            self.consecutive_losses[pair] = 0
            self.save_state()
        return False, ""
    
    def record_outcome(self, pair, is_win):
        if is_win:
            self.consecutive_losses[pair] = 0
        else:
            self.consecutive_losses[pair] = self.consecutive_losses.get(pair, 0) + 1
            if self.consecutive_losses[pair] >= self.max_losses:
                self.blacklisted_until[pair] = time_module.time() + self.blacklist_duration
        self.save_state()


class DynamicConfidenceThreshold:
    """Raises minimum confidence as daily signal count approaches cap"""
    def __init__(self, max_daily_signals=90):
        self.max_signals = max_daily_signals
        self.tiers = [
            (0.67, 0.55),   # Signals 1-60: 55% min
            (0.89, 0.70),   # Signals 61-80: 70% min
            (1.00, 0.85),   # Signals 81-90: 85% min
        ]
    
    def get_min_confidence(self, current_count):
        fraction = current_count / self.max_signals
        for tier_frac, min_conf in self.tiers:
            if fraction < tier_frac:
                return min_conf
        return self.tiers[-1][1]
    
    def should_send(self, current_count, signal_confidence):
        min_conf = self.get_min_confidence(current_count)
        if signal_confidence < min_conf:
            return False, f"Confidence {signal_confidence:.1%} below dynamic threshold {min_conf:.1%} (#{current_count+1})"
        return True, f"Passed threshold {min_conf:.1%}"


def check_multi_tf_confirmation(df_15m, df_1h, df_4h, signal_direction):
    """Check if at least 2/3 timeframes agree on signal direction (EMA10 vs EMA50)"""
    agreements = 0
    details = []
    
    for df, tf_name in [(df_15m, '15m'), (df_1h, '1h'), (df_4h, '4h')]:
        if df is None or df.empty or len(df) < 50:
            details.append(f"{tf_name}: SKIP")
            continue
        try:
            ema10 = df['EMA_10'].iloc[-1] if 'EMA_10' in df.columns else df['close'].ewm(span=10).mean().iloc[-1]
            ema50 = df['EMA_50'].iloc[-1] if 'EMA_50' in df.columns else df['close'].ewm(span=50).mean().iloc[-1]
            tf_trend = 'LONG' if ema10 > ema50 else 'SHORT'
            
            is_match = tf_trend.upper() in signal_direction.upper() or signal_direction.upper() in tf_trend.upper()
            if is_match:
                agreements += 1
                details.append(f"{tf_name}: ✅")
            else:
                details.append(f"{tf_name}: ❌")
        except Exception:
            details.append(f"{tf_name}: SKIP")
    
    confirmed = agreements >= 2
    return confirmed, agreements, " | ".join(details)


class SignalPrioritizer:
    """Collects pending signals and ranks them by confidence before sending"""
    def __init__(self, max_per_batch=10):
        self.max_per_batch = max_per_batch
        self.pending_signals = []
    
    def add_pending(self, signal_data):
        self.pending_signals.append(signal_data)
    
    def get_top_signals(self, max_signals=None):
        limit = max_signals or self.max_per_batch
        sorted_signals = sorted(self.pending_signals, key=lambda s: s.get('confidence', 0), reverse=True)
        top = sorted_signals[:limit]
        skipped = sorted_signals[limit:]
        self.pending_signals = []
        return top, skipped
    
    def has_pending(self):
        return len(self.pending_signals) > 0
    
    def clear(self):
        self.pending_signals = []


# ========== ALADDIN PHASE 6: MATHEMATICAL PRECISION ==========

class MonteCarloSimulator:
    """
    Runs 10,000+ simulations per signal to calculate Probability of Success (PoS) 
    and Expected Value (EV) using the high-performance Aladdin Rust Core.
    """
    def __init__(self, simulations=10000):
        self.simulations = simulations

    def simulate_signal(self, entry, sl, tps, atr_pct, drift=0.0):
        """
        Simulate potential price paths with optional directional drift.
        tps: list of (price, weight) tuples e.g. [(price1, 0.4), (price2, 0.25)...]
        atr_pct: ATR as a percentage of price (volatility proxy)
        drift: Directional bias (positive for Bullish, negative for Bearish)
        """
        if RUST_CORE_AVAILABLE:
            try:
                # Use High-Performance Rust Core (Informed Brownian Motion)
                pos, ev, drawdown = aladdin_core.simulate_monte_carlo(
                    float(entry),
                    float(sl),
                    [(float(p), float(w)) for p, w in tps],
                    float(atr_pct),
                    self.simulations,
                    50, # Time steps
                    float(drift) # Passing ML directional bias to Rust
                )
                return {'pos': pos, 'ev': ev, 'max_drawdown': drawdown, 'source': 'RUST_ACCEL'}
            except Exception as e:
                # Fallback to Python if Rust core errors
                from utils_logger import log_message
                log_message(f"⚠️ Aladdin Rust Core Error: {e}. Falling back to Python engine.")

        # Legacy Python Implementation (Single-threaded)
        success_count = 0
        total_pnl = 0
        step_vol = atr_pct / np.sqrt(50) # Assuming 50 steps
        period_drift = float(drift) / 50.0 # Pro-rate drift across steps
        sim_count = min(self.simulations, 1000)  # Cap at 1000 for Python performance
        
        for _ in range(sim_count): 
            current_sim_price = entry
            hit_sl = False
            hit_tps = [False] * len(tps)
            sim_pnl = 0
            
            for _ in range(50):
                # Standard Brownian Motion + Drift
                change = np.random.normal(period_drift, step_vol)
                current_sim_price *= (1 + change)
                
                is_long = tps[0][0] > entry
                if (is_long and current_sim_price <= sl) or (not is_long and current_sim_price >= sl):
                    pnl = (sl - entry) / entry
                    if not is_long:
                        pnl = -pnl
                    sim_pnl = pnl
                    hit_sl = True
                    break
                
                for i, (tp_price, weight) in enumerate(tps):
                    if not hit_tps[i]:
                        if (is_long and current_sim_price >= tp_price) or (not is_long and current_sim_price <= tp_price):
                            hit_tps[i] = True
                            pnl = (tp_price - entry) / entry
                            if not is_long:
                                pnl = -pnl
                            sim_pnl += pnl * weight
                
                if all(hit_tps):
                    break
            
            # FIX 3.4: Align with Rust - success = TP1 hit (not any TP)
            if hit_tps[0] and not hit_sl:
                success_count += 1
            
            if not hit_sl:
                current_pnl = 0
                for i, (tp_price, weight) in enumerate(tps):
                    if hit_tps[i]:
                        pnl = (tp_price - entry) / entry
                        if not is_long:
                            pnl = -pnl
                        current_pnl += pnl * weight
                    else:
                        pnl = (current_sim_price - entry) / entry
                        if not is_long:
                            pnl = -pnl
                        current_pnl += pnl * weight
                sim_pnl = current_pnl
            
            total_pnl += sim_pnl

        pos = success_count / sim_count
        ev = total_pnl / sim_count
        
        # Return EV as raw ratio (same unit as Rust core): 1.0 = breakeven
        # Gate in main.py checks ev < 1.0 to reject
        ev_normalized = 1.0 + ev  # Convert PnL fraction to ratio (0% PnL = 1.0)
        
        return {
            'pos': pos,
            'ev': ev_normalized,
            'max_drawdown': 0.0,
            'source': 'PYTHON_LEGACY',
            'rating': 'HIGH' if ev_normalized > 1.012 else ('MED' if ev_normalized > 1.005 else 'LOW')
        }


class PortfolioCorrelationManager:
    """
    Prevents over-exposure to correlated assets (e.g., all altcoins moving with BTC).
    """
    def __init__(self, max_correlated_exposure=0.3):
        self.max_exposure = max_correlated_exposure
        self.active_weights = {} # {pair: weight}

    def get_correlation_risk(self, pair, active_signals, btc_correlation=0.0):
        """
        Calculates if adding a new pair exceeds the allowed correlated exposure.
        btc_correlation: Correlation of the new pair to BTC.
        """
        # If correlation to BTC is high (>0.7), count it toward the "Market Cluster"
        if btc_correlation > 0.7:
            current_correlated_count = sum(1 for p in active_signals if p != pair)
            if current_correlated_count >= 3: # Max 3 highly correlated signals at once
                return True, f"High Correlation Risk: {current_correlated_count} active BTC-correlated trades"
        
        return False, ""


class RegimePositionSizer:
    """
    Institutional Position Sizing using RL-inspired feedback.
    Scales trade size based on market regime and recent performance.
    """
    def __init__(self, log_path="performance_logs/position_sizer.json"):
        self.log_path = log_path
        self.multiplier = 1.0
        self.recent_outcomes = [] # List of booleans (True=Win)
        self.load_state()

    def load_state(self):
        try:
            if os.path.exists(self.log_path):
                with open(self.log_path, 'r') as f:
                    data = json.load(f)
                    self.multiplier = data.get('multiplier', 1.0)
                    self.recent_outcomes = data.get('recent_outcomes', [])
        except Exception:
            pass

    def save_state(self):
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, 'w') as f:
                json.dump({
                    'multiplier': self.multiplier,
                    'recent_outcomes': self.recent_outcomes
                }, f)
        except Exception:
            pass

    def record_outcome(self, is_win):
        """PROPOSAL 6: EMA-based Win-Streak Position Sizing."""
        self.recent_outcomes.append(1.0 if is_win else 0.0)
        if len(self.recent_outcomes) > 20:
            self.recent_outcomes.pop(0)
        
        # Calculate EMA of outcomes (more recent trades weighted higher)
        if len(self.recent_outcomes) >= 3:
            alpha = 2.0 / (len(self.recent_outcomes) + 1)
            ema = self.recent_outcomes[0]
            for val in self.recent_outcomes[1:]:
                ema = alpha * val + (1 - alpha) * ema
            # Map EMA (0.0–1.0) → multiplier (0.5–1.5)
            # 50% winrate = 1.0x, 80% = 1.3x, 20% = 0.7x
            self.multiplier = 0.5 + ema * 1.0
        else:
            # Fallback to simple step logic for first few trades
            if is_win:
                self.multiplier *= 1.05
            else:
                self.multiplier *= 0.90
            
        # Hard caps for safety
        self.multiplier = max(0.3, min(1.5, self.multiplier))
        self.save_state()

    def calculate_multiplier(self, macro_risk_data, ai_sentiment=None):
        """
        Combines performance multiplier, market regime, and AI institutional score.
        """
        regime = macro_risk_data.get('market_regime', 'STABLE')
        regime_mod = 1.0
        
        if regime == 'BULLISH_TREND':
            regime_mod = 1.2
        elif regime == 'VOLATILE_CAUTION':
            regime_mod = 0.5
        elif regime == 'SYSTEMIC_PANIC':
            regime_mod = 0.05
        elif regime == 'HIGH_RISK':
            regime_mod = 0.2
            
        # Add AI Institutional Sentiment Factor (0.0 to 1.0)
        ai_mod = 1.0
        if ai_sentiment and isinstance(ai_sentiment, dict):
            score = ai_sentiment.get('institutional_score', 0.5)
            # Scale ai_mod: 0.5 (very bearish) to 1.5 (very bullish institutional sweep)
            ai_mod = 0.5 + (score * 1.0)
            
        final_multiplier = self.multiplier * regime_mod * ai_mod
        return max(0.0, min(1.5, final_multiplier))


class BlackSwanStressTester:
    """
    Institutional-grade Stress Tester for Black Swan events.
    Simulates various catastrophic scenarios and calculates Value at Risk (VaR).
    """
    @staticmethod
    def run_stress_test(active_signals, scenario="FLASH_CRASH"):
        """
        Runs a specific stress scenario on the current portfolio.
        Returns potential drawdown and severity.
        """
        scenarios = {
            "FLASH_CRASH": {"btc_move": -0.20, "alt_beta": 1.5, "desc": "20% BTC Flash Crash"},
            "SYSTEMIC_PANIC": {"btc_move": -0.40, "alt_beta": 2.0, "desc": "40% Systemic Panic"},
            "LIQUIDITY_CRISIS": {"btc_move": -0.15, "alt_beta": 3.0, "desc": "Market-wide Liquidity Squeeze"},
            "STABLE_DEPEG": {"btc_move": -0.05, "alt_beta": 0.5, "desc": "Stablecoin De-pegging Event"}
        }
        
        config = scenarios.get(scenario, scenarios["FLASH_CRASH"])
        btc_move = config["btc_move"]
        alt_beta = config["alt_beta"]
        
        total_risk_exposure = 0
        potential_loss = 0
        
        for pair, data in active_signals.items():
            entry = data.get('entry_price', 0)
            leverage = data.get('leverage', 1)
            signal_type = "LONG" if "LONG" in str(data.get('signal_type', 'LONG')).upper() else "SHORT"
            
            # Beta-adjusted expected move
            expected_move = btc_move * (1.0 if "BTC" in pair else alt_beta)
            
            # Potential PnL change
            if signal_type == "LONG":
                pnl_impact = expected_move * leverage  # Negative in crash
            else:
                # Shorts benefit from crash but suffer chaotic slippage/gap risk
                pnl_impact = -(abs(expected_move) * 0.2 * leverage)  # MUST be negative to count
            
            if pnl_impact < 0:
                potential_loss += abs(pnl_impact)
                
        return {
            'scenario': scenario,
            'description': config["desc"],
            'potential_drawdown_risk': potential_loss, # Fraction of total portfolio if size=100%
            'severity': 'CRITICAL' if potential_loss > 0.4 else ('HIGH' if potential_loss > 0.2 else 'LOW'),
            'timestamp': datetime.now().isoformat()
        }

    @staticmethod
    def calculate_var(active_signals, confidence_level=0.95):
        """
        Simplified Value at Risk (VaR) calculation.
        Estimates the maximum loss over 24h at the given confidence level.
        """
        # In a real system, this would use a 30-day historical volatility matrix
        # For now, we use a 'Regime-Based Volatility' approximation
        volatilities = {
            'BTCUSDT': 0.04, 'ETHUSDT': 0.05, 'ALTS': 0.08
        }
        
        total_var = 0
        for pair, data in active_signals.items():
            base_vol = volatilities.get(pair, volatilities['ALTS'])
            leverage = data.get('leverage', 1)
            # 95% confidence = 1.65 standard deviations
            z_score = 1.65 if confidence_level == 0.95 else 2.33
            position_var = base_vol * z_score * leverage
            total_var += position_var
            
        return total_var / max(1, len(active_signals))


def check_gpu_availability():
    """Check and log GPU availability"""
    try:
        # Check CUDA availability
        cuda_available = torch.cuda.is_available()
        device_count = torch.cuda.device_count() if cuda_available else 0
        
        if cuda_available:
            current_device = torch.cuda.current_device()
            device_name = torch.cuda.get_device_name(current_device)
            memory_allocated = torch.cuda.memory_allocated(current_device) / 1024**3  # GB
            memory_total = torch.cuda.get_device_properties(current_device).total_memory / 1024**3  # GB
            
            gpu_info = {
                'available': True,
                'device_count': device_count,
                'current_device': current_device,
                'device_name': device_name,
                'memory_allocated': memory_allocated,
                'memory_total': memory_total,
                'utilization': (memory_allocated / memory_total) * 100
            }
            
            log_message(f"🚀 GPU DETECTED: {device_name}")
            log_message(f"📊 GPU Memory: {memory_allocated:.2f}GB / {memory_total:.2f}GB ({gpu_info['utilization']:.1f}% used)")
            
        else:
            gpu_info = {
                'available': False,
                'device_count': 0,
                'reason': 'CUDA not available'
            }
            log_message("⚠️ GPU NOT AVAILABLE: CUDA not detected")
            
        return gpu_info
        
    except Exception as e:
        log_message(f"⚠️ GPU CHECK ERROR: {e}")
        return {'available': False, 'reason': str(e)}

import talib

def generate_market_summary(df):
    """Generate enhanced text summary of market conditions for transformer"""
    try:
        last_row = df.iloc[-1]
        
        # Basic price and trend information
        rsi_value = talib.RSI(df['close'].values)[-1] if len(df) > 14 else 50
        
        # Safe comparison for MACD trend - fix Series ambiguity
        macd_hist_val = last_row['MACD Histogram']
        if pd.isna(macd_hist_val):
            macd_trend = 'neutral'
        else:
            macd_trend = 'bullish' if float(macd_hist_val) > 0 else 'bearish'
        
        # Safe comparison for VWAP - fix Series ambiguity
        close_val = float(last_row['close'])
        vwap_val = float(last_row['VWAP'])
        price_vs_vwap = 'above' if close_val > vwap_val else 'below'
        
        # Bollinger Bands position - fix Series ambiguity
        close_price = float(last_row['close'])
        upper_band = float(last_row['Upper Band'])
        lower_band = float(last_row['Lower Band'])
        
        if close_price > upper_band:
            bb_position = 'above upper band'
        elif close_price < lower_band:
            bb_position = 'below lower band'
        else:
            bb_position = 'in middle range'
        
        # Advanced indicators if available - fix Series ambiguity
        additional_context = ""
        if 'ADX' in df.columns and not pd.isna(last_row['ADX']):
            adx_val = float(last_row['ADX'])
            trend_strength = "strong" if adx_val > 25 else "weak"
            additional_context += f" The trend strength is {trend_strength} with ADX at {adx_val:.1f}."
        
        if 'MFI' in df.columns and not pd.isna(last_row['MFI']):
            mfi_val = float(last_row['MFI'])
            mfi_condition = "overbought" if mfi_val > 80 else "oversold" if mfi_val < 20 else "neutral"
            additional_context += f" Money flow is {mfi_condition} at {mfi_val:.1f}."
        
        # Pattern information - fix Series ambiguity
        pattern_info = ""
        if 'Pattern' in df.columns:
            pattern_val = str(last_row['Pattern'])
            pattern_type_val = str(last_row['Pattern_Type'])
            if pattern_val != 'None':
                pattern_info = f" A {pattern_val} pattern is detected with {pattern_type_val.lower()} implications."
        
        # Volume context - fix Series ambiguity
        volume_context = ""
        if len(df) > 20:
            avg_volume = df['volume'].rolling(20).mean().iloc[-1]
            current_volume = float(last_row['volume'])
            if pd.notna(avg_volume) and avg_volume > 0 and pd.notna(current_volume) and current_volume > 0:
                volume_ratio = current_volume / avg_volume
                if volume_ratio > 1.5:
                    volume_context = " Trading volume is significantly above average."
                elif volume_ratio < 0.5:
                    volume_context = " Trading volume is below average."
        
        summary = (
            f"The current price is {last_row['close']:.6f}. "
            f"RSI is at {rsi_value:.1f}. "
            f"MACD is {macd_trend}. "
            f"Price is {price_vs_vwap} VWAP. "
            f"Bollinger Bands show price is {bb_position}."
            f"{additional_context}"
            f"{pattern_info}"
            f"{volume_context}"
        )
        
        return summary
        
    except Exception as e:
        log_message(f"Error generating market summary: {e}")
        return "Market analysis unavailable due to data processing error."
