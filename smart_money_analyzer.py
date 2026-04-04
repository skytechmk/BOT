#!/usr/bin/env python3
"""
Enhanced Smart Money Concept Trading System
Institutional-grade implementation with advanced ML capabilities
"""

import pandas as pd
import numpy as np
import talib
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Tuple, Optional
import warnings
import time
import json
import os
from scipy import stats
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import DBSCAN
from sklearn.ensemble import IsolationForest
import xgboost as xgb

warnings.filterwarnings('ignore')

class SmartMoneyAnalyzer:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.min_volume_24h = 50_000_000  # 50M USDT minimum volume for top pairs
        self.institutional_patterns = {}
        self.market_regime_model = None
        self.anomaly_detector = IsolationForest(contamination=0.1, random_state=42)
        self.scaler = StandardScaler()
        self.historical_analysis = {}
        self.load_institutional_patterns()
        
    def load_institutional_patterns(self):
        """Load historical institutional trading patterns"""
        try:
            if os.path.exists('institutional_patterns.json'):
                with open('institutional_patterns.json', 'r') as f:
                    self.institutional_patterns = json.load(f)
            else:
                self.institutional_patterns = {
                    'accumulation_patterns': [],
                    'distribution_patterns': [],
                    'manipulation_signatures': [],
                    'institutional_footprints': []
                }
        except Exception as e:
            self.logger.error(f"Error loading institutional patterns: {e}")
            self.institutional_patterns = {}
    
    def save_institutional_patterns(self):
        """Save institutional patterns for future analysis"""
        try:
            with open('institutional_patterns.json', 'w') as f:
                json.dump(self.institutional_patterns, f, indent=2)
        except Exception as e:
            self.logger.error(f"Error saving institutional patterns: {e}")
        
    def analyze_market_structure(self, df: pd.DataFrame, pair: str = None) -> Dict:
        """Enhanced market structure analysis with institutional-grade intelligence"""
        try:
            # Core smart money structure analysis
            structure = {
                'trend': self._identify_trend(df),
                'order_blocks': self._detect_order_blocks(df),
                'liquidity_zones': self._detect_liquidity_zones(df),
                'fair_value_gaps': self._detect_fair_value_gaps(df),
                'break_of_structure': self._detect_bos(df),
                'change_of_character': self._detect_choch(df),
                'inducement': self._detect_inducement(df),
                'premium_discount': self._calculate_premium_discount(df),
                
                # Enhanced institutional analysis
                'institutional_footprint': self._detect_institutional_footprint(df),
                'market_regime': self._identify_market_regime(df),
                'volume_profile_analysis': self._advanced_volume_profile(df),
                'wyckoff_phases': self._detect_wyckoff_phases(df),
                'accumulation_distribution': self._analyze_accumulation_distribution(df),
                'smart_money_divergence': self._detect_smart_money_divergence(df),
                'institutional_levels': self._identify_institutional_levels(df),
                'market_manipulation': self._detect_market_manipulation(df),
                'algorithmic_trading_patterns': self._detect_algo_patterns(df),
                'dark_pool_activity': self._estimate_dark_pool_activity(df)
            }
            
            # Generate comprehensive signal
            structure['signal'] = self._generate_comprehensive_signal(structure, df)
            structure['confidence'] = self._calculate_institutional_confidence(structure)
            
            # Store analysis for learning
            if pair:
                self._store_analysis_for_learning(pair, structure, df)
            
            return structure
            
        except Exception as e:
            self.logger.error(f"Error analyzing market structure: {e}")
            return {}
    
    def _identify_trend(self, df: pd.DataFrame) -> str:
        """Identify overall market trend using smart money concepts"""
        try:
            # Use multiple timeframe analysis for trend identification
            if len(df) < 50:
                return 'UNKNOWN'
            
            # Higher highs and higher lows for uptrend
            highs = df['high'].rolling(10).max()
            lows = df['low'].rolling(10).min()
            
            recent_highs = highs.tail(20)
            recent_lows = lows.tail(20)
            
            # Check for higher highs and higher lows
            hh_count = sum(1 for i in range(1, len(recent_highs)) 
                          if recent_highs.iloc[i] > recent_highs.iloc[i-1])
            hl_count = sum(1 for i in range(1, len(recent_lows)) 
                          if recent_lows.iloc[i] > recent_lows.iloc[i-1])
            
            # Check for lower highs and lower lows
            lh_count = sum(1 for i in range(1, len(recent_highs)) 
                          if recent_highs.iloc[i] < recent_highs.iloc[i-1])
            ll_count = sum(1 for i in range(1, len(recent_lows)) 
                          if recent_lows.iloc[i] < recent_lows.iloc[i-1])
            
            if hh_count > lh_count and hl_count > ll_count:
                return 'BULLISH'
            elif lh_count > hh_count and ll_count > hl_count:
                return 'BEARISH'
            else:
                return 'RANGING'
                
        except Exception as e:
            self.logger.error(f"Error identifying trend: {e}")
            return 'UNKNOWN'
    
    def _detect_order_blocks(self, df: pd.DataFrame) -> List[Dict]:
        """Detect bullish and bearish order blocks"""
        try:
            order_blocks = []
            
            if len(df) < 20:
                return order_blocks
            
            # Look for strong moves followed by retracements
            for i in range(10, len(df) - 5):
                current_candle = df.iloc[i]
                
                # Bullish Order Block Detection
                # Look for strong bullish candle followed by upward movement
                if self._is_strong_bullish_candle(current_candle):
                    # Check if price moved significantly higher after this candle
                    future_high = df['high'].iloc[i+1:i+6].max()
                    if future_high > current_candle['high'] * 1.005:  # 0.5% move
                        
                        # Check if price later returned to this zone
                        return_zone = False
                        for j in range(i+6, min(i+50, len(df))):
                            if (df['low'].iloc[j] <= current_candle['high'] and 
                                df['low'].iloc[j] >= current_candle['low']):
                                return_zone = True
                                break
                        
                        if return_zone:
                            order_blocks.append({
                                'type': 'BULLISH_OB',
                                'index': i,
                                'timestamp': df.index[i],
                                'high': current_candle['high'],
                                'low': current_candle['low'],
                                'open': current_candle['open'],
                                'close': current_candle['close'],
                                'strength': self._calculate_ob_strength(df, i, 'bullish'),
                                'tested': return_zone,
                                'valid': True
                            })
                
                # Bearish Order Block Detection
                if self._is_strong_bearish_candle(current_candle):
                    # Check if price moved significantly lower after this candle
                    future_low = df['low'].iloc[i+1:i+6].min()
                    if future_low < current_candle['low'] * 0.995:  # 0.5% move
                        
                        # Check if price later returned to this zone
                        return_zone = False
                        for j in range(i+6, min(i+50, len(df))):
                            if (df['high'].iloc[j] >= current_candle['low'] and 
                                df['high'].iloc[j] <= current_candle['high']):
                                return_zone = True
                                break
                        
                        if return_zone:
                            order_blocks.append({
                                'type': 'BEARISH_OB',
                                'index': i,
                                'timestamp': df.index[i],
                                'high': current_candle['high'],
                                'low': current_candle['low'],
                                'open': current_candle['open'],
                                'close': current_candle['close'],
                                'strength': self._calculate_ob_strength(df, i, 'bearish'),
                                'tested': return_zone,
                                'valid': True
                            })
            
            # Sort by strength and return top order blocks
            order_blocks.sort(key=lambda x: x['strength'], reverse=True)
            return order_blocks[:10]  # Return top 10 order blocks
            
        except Exception as e:
            self.logger.error(f"Error detecting order blocks: {e}")
            return []
    
    def _is_strong_bullish_candle(self, candle) -> bool:
        """Check if candle is a strong bullish candle"""
        try:
            body_size = abs(candle['close'] - candle['open'])
            candle_range = candle['high'] - candle['low']
            
            # Bullish candle with strong body
            is_bullish = candle['close'] > candle['open']
            strong_body = body_size > (candle_range * 0.6)  # Body is 60% of range
            good_size = candle_range > (candle['close'] * 0.002)  # At least 0.2% range
            
            return is_bullish and strong_body and good_size
            
        except Exception:
            return False
    
    def _is_strong_bearish_candle(self, candle) -> bool:
        """Check if candle is a strong bearish candle"""
        try:
            body_size = abs(candle['close'] - candle['open'])
            candle_range = candle['high'] - candle['low']
            
            # Bearish candle with strong body
            is_bearish = candle['close'] < candle['open']
            strong_body = body_size > (candle_range * 0.6)  # Body is 60% of range
            good_size = candle_range > (candle['close'] * 0.002)  # At least 0.2% range
            
            return is_bearish and strong_body and good_size
            
        except Exception:
            return False
    
    def _calculate_ob_strength(self, df: pd.DataFrame, index: int, ob_type: str) -> float:
        """Calculate order block strength"""
        try:
            candle = df.iloc[index]
            
            # Base strength from candle characteristics
            body_size = abs(candle['close'] - candle['open'])
            candle_range = candle['high'] - candle['low']
            body_ratio = body_size / candle_range if candle_range > 0 else 0
            
            # Volume strength (if available)
            volume_strength = 1.0
            if 'volume' in df.columns and len(df) > index + 10:
                avg_volume = df['volume'].iloc[max(0, index-10):index+10].mean()
                if avg_volume > 0:
                    volume_strength = min(candle['volume'] / avg_volume, 3.0)
            
            # Price movement after order block
            movement_strength = 1.0
            if len(df) > index + 5:
                if ob_type == 'bullish':
                    future_high = df['high'].iloc[index+1:index+6].max()
                    movement_strength = (future_high - candle['close']) / candle['close']
                else:
                    future_low = df['low'].iloc[index+1:index+6].min()
                    movement_strength = (candle['close'] - future_low) / candle['close']
            
            # Combine factors
            strength = (body_ratio * 0.4 + 
                       min(volume_strength / 2, 0.3) * 0.3 + 
                       min(movement_strength * 100, 0.3) * 0.3)
            
            return min(strength, 1.0)
            
        except Exception:
            return 0.5
    
    def _detect_liquidity_zones(self, df: pd.DataFrame) -> List[Dict]:
        """Detect liquidity zones (equal highs/lows)"""
        try:
            liquidity_zones = []
            
            if len(df) < 20:
                return liquidity_zones
            
            # Find swing highs and lows
            swing_highs = self._find_swing_points(df, 'high')
            swing_lows = self._find_swing_points(df, 'low')
            
            # Group equal highs
            equal_highs = self._group_equal_levels(swing_highs, df, 'high')
            for level_group in equal_highs:
                if len(level_group) >= 2:  # At least 2 equal highs
                    liquidity_zones.append({
                        'type': 'SELL_SIDE_LIQUIDITY',
                        'level': level_group[0]['price'],
                        'touches': len(level_group),
                        'first_touch': level_group[0]['timestamp'],
                        'last_touch': level_group[-1]['timestamp'],
                        'strength': len(level_group) * 0.2,
                        'zone_range': [level_group[0]['price'] * 0.999, 
                                     level_group[0]['price'] * 1.001]
                    })
            
            # Group equal lows
            equal_lows = self._group_equal_levels(swing_lows, df, 'low')
            for level_group in equal_lows:
                if len(level_group) >= 2:  # At least 2 equal lows
                    liquidity_zones.append({
                        'type': 'BUY_SIDE_LIQUIDITY',
                        'level': level_group[0]['price'],
                        'touches': len(level_group),
                        'first_touch': level_group[0]['timestamp'],
                        'last_touch': level_group[-1]['timestamp'],
                        'strength': len(level_group) * 0.2,
                        'zone_range': [level_group[0]['price'] * 0.999, 
                                     level_group[0]['price'] * 1.001]
                    })
            
            # Sort by strength
            liquidity_zones.sort(key=lambda x: x['strength'], reverse=True)
            return liquidity_zones[:10]
            
        except Exception as e:
            self.logger.error(f"Error detecting liquidity zones: {e}")
            return []
    
    def _find_swing_points(self, df: pd.DataFrame, price_type: str) -> List[Dict]:
        """Find swing highs or lows"""
        try:
            swing_points = []
            lookback = 5
            
            for i in range(lookback, len(df) - lookback):
                current_price = df[price_type].iloc[i]
                
                if price_type == 'high':
                    # Check if it's a swing high
                    is_swing = all(current_price >= df[price_type].iloc[j] 
                                 for j in range(i-lookback, i+lookback+1) if j != i)
                else:
                    # Check if it's a swing low
                    is_swing = all(current_price <= df[price_type].iloc[j] 
                                 for j in range(i-lookback, i+lookback+1) if j != i)
                
                if is_swing:
                    swing_points.append({
                        'index': i,
                        'timestamp': df.index[i],
                        'price': current_price
                    })
            
            return swing_points
            
        except Exception:
            return []
    
    def _group_equal_levels(self, swing_points: List[Dict], df: pd.DataFrame, 
                           price_type: str) -> List[List[Dict]]:
        """Group swing points that are at equal levels"""
        try:
            if not swing_points:
                return []
            
            groups = []
            tolerance = 0.002  # 0.2% tolerance for equal levels
            
            for point in swing_points:
                added_to_group = False
                
                for group in groups:
                    group_level = group[0]['price']
                    if abs(point['price'] - group_level) / group_level <= tolerance:
                        group.append(point)
                        added_to_group = True
                        break
                
                if not added_to_group:
                    groups.append([point])
            
            # Filter groups with at least 2 points
            return [group for group in groups if len(group) >= 2]
            
        except Exception:
            return []
    
    def _detect_fair_value_gaps(self, df: pd.DataFrame) -> List[Dict]:
        """Detect Fair Value Gaps (FVG)"""
        try:
            fvgs = []
            
            if len(df) < 3:
                return fvgs
            
            for i in range(1, len(df) - 1):
                candle1 = df.iloc[i-1]  # Previous candle
                candle2 = df.iloc[i]    # Current candle
                candle3 = df.iloc[i+1]  # Next candle
                
                # Bullish FVG: Gap between candle1 high and candle3 low
                if candle1['high'] < candle3['low']:
                    # Verify it's a true gap (candle2 doesn't fill it completely)
                    if candle2['low'] > candle1['high'] or candle2['high'] < candle3['low']:
                        gap_size = candle3['low'] - candle1['high']
                        if gap_size > 0:
                            fvgs.append({
                                'type': 'BULLISH_FVG',
                                'index': i,
                                'timestamp': df.index[i],
                                'top': candle3['low'],
                                'bottom': candle1['high'],
                                'size': gap_size,
                                'size_pct': (gap_size / candle1['high']) * 100,
                                'filled': False,
                                'fill_percentage': 0.0,
                                'strength': self._calculate_fvg_strength(df, i, gap_size)
                            })
                
                # Bearish FVG: Gap between candle1 low and candle3 high
                elif candle1['low'] > candle3['high']:
                    # Verify it's a true gap (candle2 doesn't fill it completely)
                    if candle2['high'] < candle1['low'] or candle2['low'] > candle3['high']:
                        gap_size = candle1['low'] - candle3['high']
                        if gap_size > 0:
                            fvgs.append({
                                'type': 'BEARISH_FVG',
                                'index': i,
                                'timestamp': df.index[i],
                                'top': candle1['low'],
                                'bottom': candle3['high'],
                                'size': gap_size,
                                'size_pct': (gap_size / candle3['high']) * 100,
                                'filled': False,
                                'fill_percentage': 0.0,
                                'strength': self._calculate_fvg_strength(df, i, gap_size)
                            })
            
            # Check which FVGs have been filled
            current_price = df['close'].iloc[-1]
            for fvg in fvgs:
                if fvg['type'] == 'BULLISH_FVG':
                    if current_price <= fvg['top']:
                        fill_pct = max(0, (fvg['top'] - current_price) / (fvg['top'] - fvg['bottom']))
                        fvg['fill_percentage'] = min(fill_pct * 100, 100)
                        fvg['filled'] = fill_pct >= 0.5  # 50% fill threshold
                else:  # BEARISH_FVG
                    if current_price >= fvg['bottom']:
                        fill_pct = max(0, (current_price - fvg['bottom']) / (fvg['top'] - fvg['bottom']))
                        fvg['fill_percentage'] = min(fill_pct * 100, 100)
                        fvg['filled'] = fill_pct >= 0.5  # 50% fill threshold
            
            # Sort by strength and recency
            fvgs.sort(key=lambda x: (x['strength'], -x['index']), reverse=True)
            return fvgs[:20]  # Return top 20 FVGs
            
        except Exception as e:
            self.logger.error(f"Error detecting FVGs: {e}")
            return []
    
    def _calculate_fvg_strength(self, df: pd.DataFrame, index: int, gap_size: float) -> float:
        """Calculate FVG strength based on various factors"""
        try:
            # Base strength from gap size
            current_price = df['close'].iloc[index]
            size_strength = min((gap_size / current_price) * 1000, 1.0)  # Normalize gap size
            
            # Volume strength
            volume_strength = 1.0
            if 'volume' in df.columns and len(df) > index + 5:
                avg_volume = df['volume'].iloc[max(0, index-5):index+5].mean()
                if avg_volume > 0:
                    current_volume = df['volume'].iloc[index]
                    volume_strength = min(current_volume / avg_volume, 2.0) / 2.0
            
            # Momentum strength (how fast price moved through the gap)
            momentum_strength = 0.5
            if len(df) > index + 2:
                price_change = abs(df['close'].iloc[index+1] - df['close'].iloc[index-1])
                momentum_strength = min((price_change / current_price) * 100, 1.0)
            
            # Combine factors
            strength = (size_strength * 0.4 + volume_strength * 0.3 + momentum_strength * 0.3)
            return min(strength, 1.0)
            
        except Exception:
            return 0.5
    
    def _detect_bos(self, df: pd.DataFrame) -> List[Dict]:
        """Detect Break of Structure (BOS)"""
        try:
            bos_signals = []
            
            if len(df) < 20:
                return bos_signals
            
            # Find recent swing highs and lows
            swing_highs = self._find_swing_points(df, 'high')
            swing_lows = self._find_swing_points(df, 'low')
            
            # Look for breaks of recent swing levels
            recent_highs = [sh for sh in swing_highs if sh['index'] >= len(df) - 50]
            recent_lows = [sl for sl in swing_lows if sl['index'] >= len(df) - 50]
            
            current_price = df['close'].iloc[-1]
            
            # Check for bullish BOS (break above recent swing high)
            for swing_high in recent_highs:
                if current_price > swing_high['price']:
                    bos_signals.append({
                        'type': 'BULLISH_BOS',
                        'level': swing_high['price'],
                        'timestamp': df.index[-1],
                        'swing_timestamp': swing_high['timestamp'],
                        'strength': self._calculate_bos_strength(df, swing_high, 'bullish')
                    })
            
            # Check for bearish BOS (break below recent swing low)
            for swing_low in recent_lows:
                if current_price < swing_low['price']:
                    bos_signals.append({
                        'type': 'BEARISH_BOS',
                        'level': swing_low['price'],
                        'timestamp': df.index[-1],
                        'swing_timestamp': swing_low['timestamp'],
                        'strength': self._calculate_bos_strength(df, swing_low, 'bearish')
                    })
            
            # Sort by strength
            bos_signals.sort(key=lambda x: x['strength'], reverse=True)
            return bos_signals[:5]
            
        except Exception as e:
            self.logger.error(f"Error detecting BOS: {e}")
            return []
    
    def _calculate_bos_strength(self, df: pd.DataFrame, swing_point: Dict, bos_type: str) -> float:
        """Calculate Break of Structure strength"""
        try:
            current_price = df['close'].iloc[-1]
            swing_price = swing_point['price']
            
            # Distance from swing level
            distance = abs(current_price - swing_price) / swing_price
            distance_strength = min(distance * 100, 1.0)
            
            # Time factor (more recent swings are stronger)
            time_diff = len(df) - 1 - swing_point['index']
            time_strength = max(0, 1 - (time_diff / 50))  # Decay over 50 periods
            
            # Volume confirmation
            volume_strength = 0.5
            if 'volume' in df.columns:
                recent_volume = df['volume'].iloc[-5:].mean()
                avg_volume = df['volume'].iloc[-20:].mean()
                if avg_volume > 0:
                    volume_strength = min(recent_volume / avg_volume, 2.0) / 2.0
            
            # Combine factors
            strength = (distance_strength * 0.4 + time_strength * 0.3 + volume_strength * 0.3)
            return min(strength, 1.0)
            
        except Exception:
            return 0.5
    
    def _detect_choch(self, df: pd.DataFrame) -> List[Dict]:
        """Detect Change of Character (CHoCH)"""
        try:
            choch_signals = []
            
            if len(df) < 30:
                return choch_signals
            
            # Analyze trend changes using swing points
            swing_highs = self._find_swing_points(df, 'high')
            swing_lows = self._find_swing_points(df, 'low')
            
            # Look for trend reversals
            recent_swings = sorted(
                [(sh['index'], sh['price'], 'high') for sh in swing_highs[-10:]] +
                [(sl['index'], sl['price'], 'low') for sl in swing_lows[-10:]],
                key=lambda x: x[0]
            )
            
            if len(recent_swings) >= 4:
                # Check for change from uptrend to downtrend
                for i in range(2, len(recent_swings)):
                    if (recent_swings[i-2][2] == 'high' and recent_swings[i][2] == 'high' and
                        recent_swings[i-1][2] == 'low' and
                        recent_swings[i][1] < recent_swings[i-2][1] and  # Lower high
                        recent_swings[i-1][1] < recent_swings[i-3][1] if i >= 3 else True):  # Lower low
                        
                        choch_signals.append({
                            'type': 'BEARISH_CHOCH',
                            'timestamp': df.index[recent_swings[i][0]],
                            'level': recent_swings[i][1],
                            'strength': 0.7
                        })
                
                # Check for change from downtrend to uptrend
                for i in range(2, len(recent_swings)):
                    if (recent_swings[i-2][2] == 'low' and recent_swings[i][2] == 'low' and
                        recent_swings[i-1][2] == 'high' and
                        recent_swings[i][1] > recent_swings[i-2][1] and  # Higher low
                        recent_swings[i-1][1] > recent_swings[i-3][1] if i >= 3 else True):  # Higher high
                        
                        choch_signals.append({
                            'type': 'BULLISH_CHOCH',
                            'timestamp': df.index[recent_swings[i][0]],
                            'level': recent_swings[i][1],
                            'strength': 0.7
                        })
            
            return choch_signals[-3:]  # Return most recent CHoCH signals
            
        except Exception as e:
            self.logger.error(f"Error detecting CHoCH: {e}")
            return []
    
    def _detect_inducement(self, df: pd.DataFrame) -> List[Dict]:
        """Detect inducement (liquidity grabs)"""
        try:
            inducements = []
            
            if len(df) < 10:
                return inducements
            
            # Look for quick moves that grab liquidity and reverse
            for i in range(5, len(df) - 2):
                current_candle = df.iloc[i]
                
                # Check for bullish inducement (fake breakout above resistance)
                recent_high = df['high'].iloc[i-5:i].max()
                if (current_candle['high'] > recent_high and
                    current_candle['close'] < current_candle['open'] and  # Bearish close
                    df['close'].iloc[i+1] < current_candle['low']):  # Follow-through down
                    
                    inducements.append({
                        'type': 'BEARISH_INDUCEMENT',
                        'index': i,
                        'timestamp': df.index[i],
                        'level': current_candle['high'],
                        'strength': 0.6
                    })
                
                # Check for bearish inducement (fake breakdown below support)
                recent_low = df['low'].iloc[i-5:i].min()
                if (current_candle['low'] < recent_low and
                    current_candle['close'] > current_candle['open'] and  # Bullish close
                    df['close'].iloc[i+1] > current_candle['high']):  # Follow-through up
                    
                    inducements.append({
                        'type': 'BULLISH_INDUCEMENT',
                        'index': i,
                        'timestamp': df.index[i],
                        'level': current_candle['low'],
                        'strength': 0.6
                    })
            
            return inducements[-5:]  # Return most recent inducements
            
        except Exception as e:
            self.logger.error(f"Error detecting inducement: {e}")
            return []
    
    def _calculate_premium_discount(self, df: pd.DataFrame) -> Dict:
        """Calculate if price is in premium or discount relative to range"""
        try:
            if len(df) < 20:
                return {'zone': 'UNKNOWN', 'percentage': 50}
            
            # Use recent range (last 20 periods)
            recent_high = df['high'].iloc[-20:].max()
            recent_low = df['low'].iloc[-20:].min()
            current_price = df['close'].iloc[-1]
            
            if recent_high == recent_low:
                return {'zone': 'UNKNOWN', 'percentage': 50}
            
            # Calculate position in range
            range_position = (current_price - recent_low) / (recent_high - recent_low)
            percentage = range_position * 100
            
            # Determine zone
            if percentage >= 70:
                zone = 'PREMIUM'
            elif percentage <= 30:
                zone = 'DISCOUNT'
            else:
                zone = 'EQUILIBRIUM'
            
            return {
                'zone': zone,
                'percentage': percentage,
                'range_high': recent_high,
                'range_low': recent_low,
                'current_price': current_price
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating premium/discount: {e}")
            return {'zone': 'UNKNOWN', 'percentage': 50}
    
    def generate_smart_money_signal(self, df_4h: pd.DataFrame, df_15m: pd.DataFrame, 
                                   current_price: float) -> Dict:
        """Generate trading signal based on smart money concepts"""
        try:
            # Analyze 4H structure for bias
            structure_4h = self.analyze_market_structure(df_4h)
            
            # Analyze 15M for entry
            structure_15m = self.analyze_market_structure(df_15m)
            
            # Calculate advanced indicators
            signals = self._calculate_advanced_signals(df_15m)
            
            # Determine bias from 4H
            bias = self._determine_bias(structure_4h, df_4h)
            
            # Find entry on 15M
            entry_signal = self._find_entry_signal(structure_15m, signals, bias, current_price)
            
            return {
                'bias': bias,
                'entry_signal': entry_signal,
                'structure_4h': structure_4h,
                'structure_15m': structure_15m,
                'advanced_signals': signals,
                'confidence': self._calculate_signal_confidence(bias, entry_signal, signals)
            }
            
        except Exception as e:
            self.logger.error(f"Error generating smart money signal: {e}")
            return {}
    
    def _calculate_advanced_signals(self, df: pd.DataFrame) -> Dict:
        """Calculate advanced trading signals"""
        try:
            signals = {}
            
            # RSI + ADX combination
            signals['rsi_adx'] = self._calculate_rsi_adx_signal(df)
            
            # EMA 10/80 crossover
            signals['ema_crossover'] = self._calculate_ema_crossover(df)
            
            # OBV trend filter
            signals['obv_trend'] = self._calculate_obv_trend(df)
            
            return signals
            
        except Exception as e:
            self.logger.error(f"Error calculating advanced signals: {e}")
            return {}
    
    def _calculate_rsi_adx_signal(self, df: pd.DataFrame) -> Dict:
        """Calculate RSI + ADX combined signal"""
        try:
            if len(df) < 30:
                return {'signal': 'NEUTRAL', 'strength': 0}
            
            # Calculate RSI
            rsi = talib.RSI(df['close'].values, timeperiod=14)
            current_rsi = rsi[-1] if not np.isnan(rsi[-1]) else 50
            
            # Calculate ADX
            adx = talib.ADX(df['high'].values, df['low'].values, df['close'].values, timeperiod=14)
            current_adx = adx[-1] if not np.isnan(adx[-1]) else 20
            
            # Calculate +DI and -DI
            plus_di = talib.PLUS_DI(df['high'].values, df['low'].values, df['close'].values, timeperiod=14)
            minus_di = talib.MINUS_DI(df['high'].values, df['low'].values, df['close'].values, timeperiod=14)
            
            current_plus_di = plus_di[-1] if not np.isnan(plus_di[-1]) else 20
            current_minus_di = minus_di[-1] if not np.isnan(minus_di[-1]) else 20
            
            # Signal logic
            signal = 'NEUTRAL'
            strength = 0
            
            # Strong trend confirmation (ADX > 25)
            if current_adx > 25:
                # Bullish: RSI oversold + +DI > -DI
                if current_rsi < 35 and current_plus_di > current_minus_di:
                    signal = 'BULLISH'
                    strength = min((35 - current_rsi) / 35 + (current_adx - 25) / 50, 1.0)
                
                # Bearish: RSI overbought + -DI > +DI
                elif current_rsi > 65 and current_minus_di > current_plus_di:
                    signal = 'BEARISH'
                    strength = min((current_rsi - 65) / 35 + (current_adx - 25) / 50, 1.0)
            
            return {
                'signal': signal,
                'strength': strength,
                'rsi': current_rsi,
                'adx': current_adx,
                'plus_di': current_plus_di,
                'minus_di': current_minus_di
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating RSI+ADX signal: {e}")
            return {'signal': 'NEUTRAL', 'strength': 0}
    
    def _calculate_ema_crossover(self, df: pd.DataFrame) -> Dict:
        """Calculate EMA 10/80 crossover signal"""
        try:
            if len(df) < 100:
                return {'signal': 'NEUTRAL', 'strength': 0}
            
            # Calculate EMAs
            ema10 = talib.EMA(df['close'].values, timeperiod=10)
            ema80 = talib.EMA(df['close'].values, timeperiod=80)
            
            if len(ema10) < 2 or len(ema80) < 2:
                return {'signal': 'NEUTRAL', 'strength': 0}
            
            # Current and previous values
            current_ema10 = ema10[-1]
            current_ema80 = ema80[-1]
            prev_ema10 = ema10[-2]
            prev_ema80 = ema80[-2]
            
            signal = 'NEUTRAL'
            strength = 0
            
            # Bullish crossover: EMA10 crosses above EMA80
            if prev_ema10 <= prev_ema80 and current_ema10 > current_ema80:
                signal = 'BULLISH'
                strength = min((current_ema10 - current_ema80) / current_ema80 * 100, 1.0)
            
            # Bearish crossover: EMA10 crosses below EMA80
            elif prev_ema10 >= prev_ema80 and current_ema10 < current_ema80:
                signal = 'BEARISH'
                strength = min((current_ema80 - current_ema10) / current_ema80 * 100, 1.0)
            
            # Trend continuation
            elif current_ema10 > current_ema80:
                signal = 'BULLISH_CONTINUATION'
                strength = min((current_ema10 - current_ema80) / current_ema80 * 50, 0.5)
            
            elif current_ema10 < current_ema80:
                signal = 'BEARISH_CONTINUATION'
                strength = min((current_ema80 - current_ema10) / current_ema80 * 50, 0.5)
            
            return {
                'signal': signal,
                'strength': strength,
                'ema10': current_ema10,
                'ema80': current_ema80,
                'crossover': signal in ['BULLISH', 'BEARISH']
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating EMA crossover: {e}")
            return {'signal': 'NEUTRAL', 'strength': 0}
    
    def _calculate_obv_trend(self, df: pd.DataFrame) -> Dict:
        """Calculate OBV trend filter"""
        try:
            if len(df) < 20 or 'volume' not in df.columns:
                return {'signal': 'NEUTRAL', 'strength': 0}
            
            # Calculate OBV
            obv = talib.OBV(df['close'].values, df['volume'].values)
            
            if len(obv) < 10:
                return {'signal': 'NEUTRAL', 'strength': 0}
            
            # Calculate OBV trend using linear regression
            recent_obv = obv[-10:]
            x = np.arange(len(recent_obv))
            
            # Linear regression to determine trend
            slope = np.polyfit(x, recent_obv, 1)[0]
            
            # Normalize slope
            obv_range = np.max(recent_obv) - np.min(recent_obv)
            if obv_range > 0:
                normalized_slope = slope / obv_range * 10
            else:
                normalized_slope = 0
            
            signal = 'NEUTRAL'
            strength = 0
            
            # Determine signal based on slope
            if normalized_slope > 0.1:
                signal = 'BULLISH'
                strength = min(normalized_slope, 1.0)
            elif normalized_slope < -0.1:
                signal = 'BEARISH'
                strength = min(abs(normalized_slope), 1.0)
            
            return {
                'signal': signal,
                'strength': strength,
                'obv': obv[-1],
                'slope': normalized_slope,
                'trend': 'RISING' if normalized_slope > 0 else 'FALLING' if normalized_slope < 0 else 'FLAT'
            }
            
        except Exception as e:
            self.logger.error(f"Error calculating OBV trend: {e}")
            return {'signal': 'NEUTRAL', 'strength': 0}
    
    def _determine_bias(self, structure_4h: Dict, df_4h: pd.DataFrame) -> Dict:
        """Determine market bias from 4H structure"""
        try:
            bias = {
                'direction': 'NEUTRAL',
                'strength': 0.5,
                'confidence': 0.5,
                'reasons': []
            }
            
            # Trend analysis
            trend = structure_4h.get('trend', 'UNKNOWN')
            if trend == 'BULLISH':
                bias['direction'] = 'BULLISH'
                bias['strength'] += 0.2
                bias['reasons'].append('4H uptrend')
            elif trend == 'BEARISH':
                bias['direction'] = 'BEARISH'
                bias['strength'] += 0.2
                bias['reasons'].append('4H downtrend')
            
            # Order blocks analysis
            order_blocks = structure_4h.get('order_blocks', [])
            if order_blocks:
                bullish_obs = [ob for ob in order_blocks if ob['type'] == 'BULLISH_OB']
                bearish_obs = [ob for ob in order_blocks if ob['type'] == 'BEARISH_OB']
                
                if len(bullish_obs) > len(bearish_obs):
                    if bias['direction'] == 'BULLISH':
                        bias['strength'] += 0.1
                    bias['reasons'].append('More bullish order blocks')
                elif len(bearish_obs) > len(bullish_obs):
                    if bias['direction'] == 'BEARISH':
                        bias['strength'] += 0.1
                    bias['reasons'].append('More bearish order blocks')
            
            # Break of structure analysis
            bos_signals = structure_4h.get('break_of_structure', [])
            if bos_signals:
                latest_bos = bos_signals[0]  # Strongest BOS
                if latest_bos['type'] == 'BULLISH_BOS':
                    bias['direction'] = 'BULLISH'
                    bias['strength'] += 0.15
                    bias['reasons'].append('Recent bullish BOS')
                elif latest_bos['type'] == 'BEARISH_BOS':
                    bias['direction'] = 'BEARISH'
                    bias['strength'] += 0.15
                    bias['reasons'].append('Recent bearish BOS')
            
            # Premium/Discount analysis
            premium_discount = structure_4h.get('premium_discount', {})
            zone = premium_discount.get('zone', 'UNKNOWN')
            if zone == 'DISCOUNT' and bias['direction'] == 'BULLISH':
                bias['strength'] += 0.1
                bias['reasons'].append('Price in discount zone')
            elif zone == 'PREMIUM' and bias['direction'] == 'BEARISH':
                bias['strength'] += 0.1
                bias['reasons'].append('Price in premium zone')
            
            # Normalize strength and calculate confidence
            bias['strength'] = min(bias['strength'], 1.0)
            bias['confidence'] = min(len(bias['reasons']) * 0.2, 1.0)
            
            return bias
            
        except Exception as e:
            self.logger.error(f"Error determining bias: {e}")
            return {'direction': 'NEUTRAL', 'strength': 0.5, 'confidence': 0.5, 'reasons': []}
    
    def _find_entry_signal(self, structure_15m: Dict, signals: Dict, bias: Dict, current_price: float) -> Dict:
        """Find entry signal on 15M timeframe"""
        try:
            entry = {
                'signal': 'NO_SIGNAL',
                'entry_price': current_price,
                'stop_loss': None,
                'take_profit': None,
                'risk_reward': 0,
                'reasons': []
            }
            
            bias_direction = bias.get('direction', 'NEUTRAL')
            if bias_direction == 'NEUTRAL':
                return entry
            
            # Check for confluence of signals
            confluence_score = 0
            
            # Advanced signals confluence
            rsi_adx = signals.get('rsi_adx', {})
            ema_crossover = signals.get('ema_crossover', {})
            obv_trend = signals.get('obv_trend', {})
            
            if bias_direction == 'BULLISH':
                # Look for bullish entry signals
                if rsi_adx.get('signal') == 'BULLISH':
                    confluence_score += rsi_adx.get('strength', 0) * 0.3
                    entry['reasons'].append('RSI+ADX bullish')
                
                if ema_crossover.get('signal') in ['BULLISH', 'BULLISH_CONTINUATION']:
                    confluence_score += ema_crossover.get('strength', 0) * 0.3
                    entry['reasons'].append('EMA bullish')
                
                if obv_trend.get('signal') == 'BULLISH':
                    confluence_score += obv_trend.get('strength', 0) * 0.2
                    entry['reasons'].append('OBV rising')
                
                # Check for order block support
                order_blocks = structure_15m.get('order_blocks', [])
                bullish_obs = [ob for ob in order_blocks if ob['type'] == 'BULLISH_OB' and ob['tested']]
                if bullish_obs:
                    nearest_ob = min(bullish_obs, key=lambda x: abs(current_price - x['low']))
                    if abs(current_price - nearest_ob['low']) / current_price < 0.01:  # Within 1%
                        confluence_score += 0.2
                        entry['reasons'].append('Near bullish order block')
                        entry['stop_loss'] = nearest_ob['low'] * 0.998
                
            elif bias_direction == 'BEARISH':
                # Look for bearish entry signals
                if rsi_adx.get('signal') == 'BEARISH':
                    confluence_score += rsi_adx.get('strength', 0) * 0.3
                    entry['reasons'].append('RSI+ADX bearish')
                
                if ema_crossover.get('signal') in ['BEARISH', 'BEARISH_CONTINUATION']:
                    confluence_score += ema_crossover.get('strength', 0) * 0.3
                    entry['reasons'].append('EMA bearish')
                
                if obv_trend.get('signal') == 'BEARISH':
                    confluence_score += obv_trend.get('strength', 0) * 0.2
                    entry['reasons'].append('OBV falling')
                
                # Check for order block resistance
                order_blocks = structure_15m.get('order_blocks', [])
                bearish_obs = [ob for ob in order_blocks if ob['type'] == 'BEARISH_OB' and ob['tested']]
                if bearish_obs:
                    nearest_ob = min(bearish_obs, key=lambda x: abs(current_price - x['high']))
                    if abs(current_price - nearest_ob['high']) / current_price < 0.01:  # Within 1%
                        confluence_score += 0.2
                        entry['reasons'].append('Near bearish order block')
                        entry['stop_loss'] = nearest_ob['high'] * 1.002
            
            # Generate signal if confluence is strong enough
            if confluence_score >= 0.6:
                entry['signal'] = bias_direction
                
                # Set stop loss if not already set
                if not entry['stop_loss']:
                    if bias_direction == 'BULLISH':
                        entry['stop_loss'] = current_price * 0.99  # 1% stop
                    else:
                        entry['stop_loss'] = current_price * 1.01  # 1% stop
                
                # Set take profit (2:1 risk reward)
                risk = abs(current_price - entry['stop_loss'])
                if bias_direction == 'BULLISH':
                    entry['take_profit'] = current_price + (risk * 2)
                else:
                    entry['take_profit'] = current_price - (risk * 2)
                
                entry['risk_reward'] = 2.0
            
            return entry
            
        except Exception as e:
            self.logger.error(f"Error finding entry signal: {e}")
            return {'signal': 'NO_SIGNAL', 'entry_price': current_price, 'reasons': []}
    
    def _calculate_signal_confidence(self, bias: Dict, entry_signal: Dict, signals: Dict) -> float:
        """Calculate overall signal confidence"""
        try:
            if entry_signal.get('signal') == 'NO_SIGNAL':
                return 0.0
            
            # Base confidence from bias
            confidence = bias.get('confidence', 0.5) * 0.4
            
            # Add confluence factors
            confluence_factors = len(entry_signal.get('reasons', []))
            confidence += min(confluence_factors * 0.15, 0.6)
            
            return min(confidence, 1.0)
            
        except Exception:
            return 0.5
    
    def _calculate_volume_trend(self, df: pd.DataFrame) -> float:
        """Calculate volume trend using linear regression"""
        try:
            if len(df) < 5 or 'volume' not in df.columns:
                return 0.0
            
            volumes = df['volume'].values
            x = np.arange(len(volumes))
            
            # Linear regression
            slope, intercept, r_value, p_value, std_err = stats.linregress(x, volumes)
            
            # Normalize slope by average volume
            avg_volume = np.mean(volumes)
            if avg_volume > 0:
                normalized_slope = slope / avg_volume * len(volumes)
                return min(max(normalized_slope, -1.0), 1.0)
            
            return 0.0
            
        except Exception:
            return 0.0
    
    def _calculate_smart_money_flow(self, df: pd.DataFrame) -> str:
        """Calculate smart money flow direction"""
        try:
            if len(df) < 20 or 'volume' not in df.columns:
                return 'NEUTRAL'
            
            # Calculate Money Flow Index components
            typical_price = (df['high'] + df['low'] + df['close']) / 3
            money_flow = typical_price * df['volume']
            
            # Positive and negative money flow
            positive_flow = []
            negative_flow = []
            
            for i in range(1, len(typical_price)):
                if typical_price.iloc[i] > typical_price.iloc[i-1]:
                    positive_flow.append(money_flow.iloc[i])
                    negative_flow.append(0)
                elif typical_price.iloc[i] < typical_price.iloc[i-1]:
                    negative_flow.append(money_flow.iloc[i])
                    positive_flow.append(0)
                else:
                    positive_flow.append(0)
                    negative_flow.append(0)
            
            # Calculate recent flow (last 10 periods)
            recent_positive = sum(positive_flow[-10:])
            recent_negative = sum(negative_flow[-10:])
            
            if recent_positive > recent_negative * 1.2:
                return 'BULLISH'
            elif recent_negative > recent_positive * 1.2:
                return 'BEARISH'
            else:
                return 'NEUTRAL'
                
        except Exception:
            return 'NEUTRAL'
    
    def _calculate_regime_features(self, df: pd.DataFrame) -> List[float]:
        """Calculate features for market regime identification"""
        try:
            features = []
            
            if len(df) < 50:
                return features
            
            # Volatility features
            returns = df['close'].pct_change().dropna()
            volatility_20 = returns.rolling(20).std().iloc[-1]
            volatility_5 = returns.rolling(5).std().iloc[-1]
            features.extend([volatility_20, volatility_5, volatility_5/volatility_20 if volatility_20 > 0 else 1])
            
            # Trend features
            sma_20 = df['close'].rolling(20).mean().iloc[-1]
            sma_50 = df['close'].rolling(50).mean().iloc[-1] if len(df) >= 50 else sma_20
            current_price = df['close'].iloc[-1]
            
            trend_20 = (current_price - sma_20) / sma_20
            trend_50 = (current_price - sma_50) / sma_50
            ma_slope = (sma_20 - sma_50) / sma_50 if sma_50 > 0 else 0
            
            features.extend([trend_20, trend_50, ma_slope])
            
            # Volume features
            if 'volume' in df.columns:
                vol_ratio = df['volume'].iloc[-1] / df['volume'].rolling(20).mean().iloc[-1]
                vol_trend = self._calculate_volume_trend(df.tail(10))
                features.extend([vol_ratio, vol_trend])
            else:
                features.extend([1.0, 0.0])
            
            # Range features
            high_20 = df['high'].rolling(20).max().iloc[-1]
            low_20 = df['low'].rolling(20).min().iloc[-1]
            range_position = (current_price - low_20) / (high_20 - low_20) if high_20 > low_20 else 0.5
            features.append(range_position)
            
            return features
            
        except Exception:
            return []
    
    def _detect_wyckoff_phases(self, df: pd.DataFrame) -> Dict:
        """Detect Wyckoff accumulation/distribution phases"""
        try:
            if len(df) < 100:
                return {'phase': 'UNKNOWN', 'confidence': 0}
            
            # Calculate key metrics for Wyckoff analysis
            volume_ma = df['volume'].rolling(20).mean()
            price_range = df['high'] - df['low']
            volume_spread_analysis = df['volume'] / price_range
            
            # Recent price action analysis
            recent_df = df.tail(50)
            price_volatility = recent_df['close'].std() / recent_df['close'].mean()
            volume_increase = recent_df['volume'].tail(10).mean() / recent_df['volume'].head(10).mean()
            
            # Phase identification logic
            if price_volatility < 0.02 and volume_increase > 1.3:
                # Low volatility with increasing volume suggests accumulation
                phase = 'ACCUMULATION'
                confidence = min(volume_increase - 1, 1.0)
            elif price_volatility < 0.02 and volume_increase < 0.7:
                # Low volatility with decreasing volume suggests distribution
                phase = 'DISTRIBUTION'
                confidence = min(1 - volume_increase, 1.0)
            elif price_volatility > 0.05:
                # High volatility suggests markup/markdown
                recent_trend = (recent_df['close'].iloc[-1] - recent_df['close'].iloc[0]) / recent_df['close'].iloc[0]
                if recent_trend > 0.1:
                    phase = 'MARKUP'
                    confidence = min(recent_trend * 5, 1.0)
                elif recent_trend < -0.1:
                    phase = 'MARKDOWN'
                    confidence = min(abs(recent_trend) * 5, 1.0)
                else:
                    phase = 'TRANSITION'
                    confidence = 0.5
            else:
                phase = 'UNKNOWN'
                confidence = 0
            
            return {
                'phase': phase,
                'confidence': confidence,
                'volume_increase': volume_increase,
                'price_volatility': price_volatility
            }
            
        except Exception as e:
            self.logger.error(f"Error detecting Wyckoff phases: {e}")
            return {'phase': 'UNKNOWN', 'confidence': 0}
    
    def _analyze_accumulation_distribution(self, df: pd.DataFrame) -> Dict:
        """Analyze accumulation/distribution using advanced volume analysis"""
        try:
            if len(df) < 20 or 'volume' not in df.columns:
                return {'signal': 'NEUTRAL', 'strength': 0}
            
            # Calculate Accumulation/Distribution Line
            ad_line = talib.AD(df['high'].values, df['low'].values, df['close'].values, df['volume'].values)
            
            # Calculate trend of A/D line
            recent_ad = ad_line[-10:]
            x = np.arange(len(recent_ad))
            slope, _, r_value, _, _ = stats.linregress(x, recent_ad)
            
            # Normalize slope
            ad_range = np.max(recent_ad) - np.min(recent_ad)
            if ad_range > 0:
                normalized_slope = slope / ad_range * 10
            else:
                normalized_slope = 0
            
            # Determine signal
            if normalized_slope > 0.1:
                signal = 'ACCUMULATION'
                strength = min(normalized_slope, 1.0)
            elif normalized_slope < -0.1:
                signal = 'DISTRIBUTION'
                strength = min(abs(normalized_slope), 1.0)
            else:
                signal = 'NEUTRAL'
                strength = 0
            
            # Volume confirmation
            volume_trend = self._calculate_volume_trend(df.tail(10))
            if signal == 'ACCUMULATION' and volume_trend > 0:
                strength *= 1.2
            elif signal == 'DISTRIBUTION' and volume_trend > 0:
                strength *= 1.2
            
            return {
                'signal': signal,
                'strength': min(strength, 1.0),
                'ad_line': ad_line[-1],
                'slope': normalized_slope,
                'volume_confirmation': volume_trend > 0
            }
            
        except Exception as e:
            self.logger.error(f"Error analyzing accumulation/distribution: {e}")
            return {'signal': 'NEUTRAL', 'strength': 0}
    
    def _detect_smart_money_divergence(self, df: pd.DataFrame) -> Dict:
        """Detect smart money divergence patterns"""
        try:
            if len(df) < 50:
                return {'divergence': 'NONE', 'strength': 0}
            
            # Calculate price and volume trends
            price_trend = (df['close'].iloc[-1] - df['close'].iloc[-20]) / df['close'].iloc[-20]
            volume_trend = self._calculate_volume_trend(df.tail(20))
            
            # Calculate OBV trend
            obv = talib.OBV(df['close'].values, df['volume'].values)
            obv_trend = (obv[-1] - obv[-20]) / abs(obv[-20]) if obv[-20] != 0 else 0
            
            # Detect divergences
            divergence = 'NONE'
            strength = 0
            
            # Bullish divergence: Price down, volume/OBV up
            if price_trend < -0.02 and (volume_trend > 0.1 or obv_trend > 0.1):
                divergence = 'BULLISH'
                strength = min(abs(price_trend) + max(volume_trend, obv_trend), 1.0)
            
            # Bearish divergence: Price up, volume/OBV down
            elif price_trend > 0.02 and (volume_trend < -0.1 or obv_trend < -0.1):
                divergence = 'BEARISH'
                strength = min(price_trend + abs(min(volume_trend, obv_trend)), 1.0)
            
            return {
                'divergence': divergence,
                'strength': strength,
                'price_trend': price_trend,
                'volume_trend': volume_trend,
                'obv_trend': obv_trend
            }
            
        except Exception as e:
            self.logger.error(f"Error detecting smart money divergence: {e}")
            return {'divergence': 'NONE', 'strength': 0}
    
    def _identify_institutional_levels(self, df: pd.DataFrame) -> Dict:
        """Identify key institutional support/resistance levels"""
        try:
            if len(df) < 100:
                return {'support_levels': [], 'resistance_levels': []}
            
            # Find significant price levels using volume
            price_volume_map = {}
            
            # Group prices by volume
            for _, row in df.iterrows():
                price_bucket = round(row['close'], 4)
                if price_bucket not in price_volume_map:
                    price_volume_map[price_bucket] = 0
                price_volume_map[price_bucket] += row['volume']
            
            # Find high volume levels
            sorted_levels = sorted(price_volume_map.items(), key=lambda x: x[1], reverse=True)
            high_volume_levels = [level[0] for level in sorted_levels[:20]]
            
            current_price = df['close'].iloc[-1]
            
            # Separate into support and resistance
            support_levels = [level for level in high_volume_levels if level < current_price]
            resistance_levels = [level for level in high_volume_levels if level > current_price]
            
            # Sort by proximity to current price
            support_levels.sort(reverse=True)  # Closest support first
            resistance_levels.sort()  # Closest resistance first
            
            return {
                'support_levels': support_levels[:5],
                'resistance_levels': resistance_levels[:5],
                'current_price': current_price
            }
            
        except Exception as e:
            self.logger.error(f"Error identifying institutional levels: {e}")
            return {'support_levels': [], 'resistance_levels': []}
    
    def _detect_market_manipulation(self, df: pd.DataFrame) -> Dict:
        """Detect potential market manipulation patterns"""
        try:
            if len(df) < 20:
                return {'manipulation_detected': False, 'patterns': []}
            
            manipulation_patterns = []
            
            # Look for stop hunting patterns
            for i in range(10, len(df) - 2):
                current = df.iloc[i]
                
                # Detect stop hunt above resistance
                recent_high = df['high'].iloc[i-10:i].max()
                if (current['high'] > recent_high and
                    current['close'] < current['open'] and
                    abs(current['close'] - current['open']) > abs(current['high'] - current['low']) * 0.3):
                    
                    manipulation_patterns.append({
                        'type': 'STOP_HUNT_ABOVE',
                        'timestamp': df.index[i],
                        'level': current['high'],
                        'strength': 0.7
                    })
                
                # Detect stop hunt below support
                recent_low = df['low'].iloc[i-10:i].min()
                if (current['low'] < recent_low and
                    current['close'] > current['open'] and
                    abs(current['close'] - current['open']) > abs(current['high'] - current['low']) * 0.3):
                    
                    manipulation_patterns.append({
                        'type': 'STOP_HUNT_BELOW',
                        'timestamp': df.index[i],
                        'level': current['low'],
                        'strength': 0.7
                    })
            
            # Detect volume anomalies (potential wash trading)
            if 'volume' in df.columns:
                volume_zscore = (df['volume'] - df['volume'].rolling(20).mean()) / df['volume'].rolling(20).std()
                
                for i in range(len(volume_zscore)):
                    if volume_zscore.iloc[i] > 3:  # 3 sigma volume spike
                        price_impact = abs(df['close'].iloc[i] - df['open'].iloc[i]) / df['open'].iloc[i]
                        if price_impact < 0.002:  # Less than 0.2% price impact
                            manipulation_patterns.append({
                                'type': 'VOLUME_ANOMALY',
                                'timestamp': df.index[i],
                                'volume_zscore': volume_zscore.iloc[i],
                                'price_impact': price_impact,
                                'strength': 0.6
                            })
            
            return {
                'manipulation_detected': len(manipulation_patterns) > 0,
                'patterns': manipulation_patterns[-5:],  # Last 5 patterns
                'pattern_count': len(manipulation_patterns)
            }
            
        except Exception as e:
            self.logger.error(f"Error detecting market manipulation: {e}")
            return {'manipulation_detected': False, 'patterns': []}
    
    def _detect_algo_patterns(self, df: pd.DataFrame) -> Dict:
        """Detect algorithmic trading patterns"""
        try:
            if len(df) < 50:
                return {'algo_activity': 'LOW', 'patterns': []}
            
            algo_patterns = []
            
            # Detect regular volume spikes (algo execution)
            if 'volume' in df.columns:
                volume_ma = df['volume'].rolling(20).mean()
                volume_spikes = df['volume'] > volume_ma * 2
                
                # Count regular intervals
                spike_intervals = []
                last_spike = None
                
                for i, is_spike in enumerate(volume_spikes):
                    if is_spike and last_spike is not None:
                        interval = i - last_spike
                        spike_intervals.append(interval)
                    if is_spike:
                        last_spike = i
                
                # Check for regular patterns
                if len(spike_intervals) > 5:
                    interval_std = np.std(spike_intervals)
                    interval_mean = np.mean(spike_intervals)
                    
                    if interval_std < interval_mean * 0.3:  # Low variance = regular pattern
                        algo_patterns.append({
                            'type': 'REGULAR_EXECUTION',
                            'interval': interval_mean,
                            'regularity': 1 - (interval_std / interval_mean),
                            'strength': 0.8
                        })
            
            # Detect price clustering (algo price levels)
            price_decimals = df['close'].apply(lambda x: len(str(x).split('.')[-1]) if '.' in str(x) else 0)
            round_number_ratio = sum(price_decimals <= 2) / len(price_decimals)
            
            if round_number_ratio > 0.3:
                algo_patterns.append({
                    'type': 'PRICE_CLUSTERING',
                    'round_ratio': round_number_ratio,
                    'strength': round_number_ratio
                })
            
            # Determine overall algo activity level
            if len(algo_patterns) >= 2:
                activity = 'HIGH'
            elif len(algo_patterns) == 1:
                activity = 'MEDIUM'
            else:
                activity = 'LOW'
            
            return {
                'algo_activity': activity,
                'patterns': algo_patterns,
                'confidence': min(len(algo_patterns) * 0.4, 1.0)
            }
            
        except Exception as e:
            self.logger.error(f"Error detecting algo patterns: {e}")
            return {'algo_activity': 'LOW', 'patterns': []}
    
    def _estimate_dark_pool_activity(self, df: pd.DataFrame) -> Dict:
        """Estimate dark pool trading activity"""
        try:
            if len(df) < 50 or 'volume' not in df.columns:
                return {'dark_pool_activity': 'LOW', 'indicators': []}
            
            indicators = []
            
            # Large volume with minimal price impact
            volume_ma = df['volume'].rolling(20).mean()
            price_impact = abs(df['close'] - df['open']) / df['open']
            
            large_volume_low_impact = 0
            for i in range(len(df)):
                if (df['volume'].iloc[i] > volume_ma.iloc[i] * 1.5 and
                    price_impact.iloc[i] < 0.005):  # Large volume, <0.5% impact
                    large_volume_low_impact += 1
            
            if large_volume_low_impact > len(df) * 0.1:  # More than 10% of periods
                indicators.append({
                    'type': 'LARGE_VOLUME_LOW_IMPACT',
                    'frequency': large_volume_low_impact / len(df),
                    'strength': min(large_volume_low_impact / len(df) * 5, 1.0)
                })
            
            # Volume-price divergence
            volume_trend = self._calculate_volume_trend(df.tail(20))
            price_trend = (df['close'].iloc[-1] - df['close'].iloc[-20]) / df['close'].iloc[-20]
            
            if abs(volume_trend) > 0.2 and abs(price_trend) < 0.05:
                indicators.append({
                    'type': 'VOLUME_PRICE_DIVERGENCE',
                    'volume_trend': volume_trend,
                    'price_trend': price_trend,
                    'strength': min(abs(volume_trend) - abs(price_trend), 1.0)
                })
            
            # Determine activity level
            if len(indicators) >= 2:
                activity = 'HIGH'
            elif len(indicators) == 1:
                activity = 'MEDIUM'
            else:
                activity = 'LOW'
            
            return {
                'dark_pool_activity': activity,
                'indicators': indicators,
                'confidence': min(len(indicators) * 0.5, 1.0)
            }
            
        except Exception as e:
            self.logger.error(f"Error estimating dark pool activity: {e}")
            return {'dark_pool_activity': 'LOW', 'indicators': []}
    
    def _generate_comprehensive_signal(self, structure: Dict, df: pd.DataFrame) -> str:
        """Generate comprehensive trading signal from all analysis"""
        try:
            bullish_factors = 0
            bearish_factors = 0
            
            # Trend analysis
            trend = structure.get('trend', 'UNKNOWN')
            if trend == 'BULLISH':
                bullish_factors += 2
            elif trend == 'BEARISH':
                bearish_factors += 2
            
            # Order blocks
            order_blocks = structure.get('order_blocks', [])
            bullish_obs = [ob for ob in order_blocks if ob['type'] == 'BULLISH_OB']
            bearish_obs = [ob for ob in order_blocks if ob['type'] == 'BEARISH_OB']
            
            if len(bullish_obs) > len(bearish_obs):
                bullish_factors += 1
            elif len(bearish_obs) > len(bullish_obs):
                bearish_factors += 1
            
            # Break of structure
            bos_signals = structure.get('break_of_structure', [])
            if bos_signals:
                latest_bos = bos_signals[0]
                if latest_bos['type'] == 'BULLISH_BOS':
                    bullish_factors += 2
                elif latest_bos['type'] == 'BEARISH_BOS':
                    bearish_factors += 2
            
            # Premium/Discount
            premium_discount = structure.get('premium_discount', {})
            zone = premium_discount.get('zone', 'UNKNOWN')
            if zone == 'DISCOUNT':
                bullish_factors += 1
            elif zone == 'PREMIUM':
                bearish_factors += 1
            
            # Institutional analysis
            institutional_footprint = structure.get('institutional_footprint', {})
            smart_money_flow = institutional_footprint.get('smart_money_flow', 'NEUTRAL')
            
            if smart_money_flow == 'BULLISH':
                bullish_factors += 1
            elif smart_money_flow == 'BEARISH':
                bearish_factors += 1
            
            # Wyckoff analysis
            wyckoff = structure.get('wyckoff_phases', {})
            phase = wyckoff.get('phase', 'UNKNOWN')
            
            if phase in ['ACCUMULATION', 'MARKUP']:
                bullish_factors += 1
            elif phase in ['DISTRIBUTION', 'MARKDOWN']:
                bearish_factors += 1
            
            # Generate final signal
            if bullish_factors >= bearish_factors + 2:
                return 'Long'
            elif bearish_factors >= bullish_factors + 2:
                return 'Short'
            else:
                return 'Neutral'
                
        except Exception as e:
            self.logger.error(f"Error generating comprehensive signal: {e}")
            return 'Neutral'
    
    def _calculate_institutional_confidence(self, structure: Dict) -> float:
        """Calculate confidence based on institutional analysis"""
        try:
            confidence_factors = []
            
            # Trend strength
            trend = structure.get('trend', 'UNKNOWN')
            if trend in ['BULLISH', 'BEARISH']:
                confidence_factors.append(0.2)
            
            # Order block quality
            order_blocks = structure.get('order_blocks', [])
            if order_blocks:
                avg_strength = np.mean([ob['strength'] for ob in order_blocks[:3]])
                confidence_factors.append(avg_strength * 0.15)
            
            # Institutional footprint
            footprint = structure.get('institutional_footprint', {})
            if footprint.get('large_block_trades'):
                confidence_factors.append(0.1)
            if footprint.get('stealth_accumulation'):
                confidence_factors.append(0.1)
            
            # Market regime clarity
            regime = structure.get('market_regime', {})
            regime_confidence = regime.get('confidence', 0)
            confidence_factors.append(regime_confidence * 0.15)
            
            # Wyckoff phase confidence
            wyckoff = structure.get('wyckoff_phases', {})
            wyckoff_confidence = wyckoff.get('confidence', 0)
            confidence_factors.append(wyckoff_confidence * 0.1)
            
            # Smart money divergence
            divergence = structure.get('smart_money_divergence', {})
            if divergence.get('divergence') != 'NONE':
                confidence_factors.append(divergence.get('strength', 0) * 0.1)
            
            return min(sum(confidence_factors), 1.0)
            
        except Exception as e:
            self.logger.error(f"Error calculating institutional confidence: {e}")
            return 0.5
    
    def _store_analysis_for_learning(self, pair: str, structure: Dict, df: pd.DataFrame):
        """Store analysis results for machine learning"""
        try:
            current_time = time.time()
            
            analysis_data = {
                'timestamp': current_time,
                'pair': pair,
                'signal': structure.get('signal', 'Neutral'),
                'confidence': structure.get('confidence', 0.5),
                'current_price': df['close'].iloc[-1],
                'structure_summary': {
                    'trend': structure.get('trend'),
                    'order_blocks_count': len(structure.get('order_blocks', [])),
                    'bos_signals': len(structure.get('break_of_structure', [])),
                    'premium_discount': structure.get('premium_discount', {}).get('zone'),
                    'wyckoff_phase': structure.get('wyckoff_phases', {}).get('phase'),
                    'market_regime': structure.get('market_regime', {}).get('regime')
                }
            }
            
            # Store in historical analysis
            if pair not in self.historical_analysis:
                self.historical_analysis[pair] = []
            
            self.historical_analysis[pair].append(analysis_data)
            
            # Keep only last 100 analyses per pair
            if len(self.historical_analysis[pair]) > 100:
                self.historical_analysis[pair] = self.historical_analysis[pair][-100:]
            
            # Update institutional patterns
            self._update_institutional_patterns(analysis_data)
            
        except Exception as e:
            self.logger.error(f"Error storing analysis for learning: {e}")
    
    def _update_institutional_patterns(self, analysis_data: Dict):
        """Update institutional pattern database"""
        try:
            signal = analysis_data['signal']
            confidence = analysis_data['confidence']
            
            if confidence > 0.7:  # High confidence signals only
                pattern_data = {
                    'timestamp': analysis_data['timestamp'],
                    'signal': signal,
                    'confidence': confidence,
                    'structure': analysis_data['structure_summary']
                }
                
                if signal == 'Long':
                    self.institutional_patterns['accumulation_patterns'].append(pattern_data)
                elif signal == 'Short':
                    self.institutional_patterns['distribution_patterns'].append(pattern_data)
                
                # Keep only last 50 patterns per type
                for pattern_type in self.institutional_patterns:
                    if len(self.institutional_patterns[pattern_type]) > 50:
                        self.institutional_patterns[pattern_type] = self.institutional_patterns[pattern_type][-50:]
                
                # Save patterns periodically
                if len(self.institutional_patterns['accumulation_patterns']) % 10 == 0:
                    self.save_institutional_patterns()
                    
        except Exception as e:
            self.logger.error(f"Error updating institutional patterns: {e}")
    
    def _detect_institutional_footprint(self, df: pd.DataFrame) -> Dict:
        """Detect institutional trading footprints using advanced volume analysis"""
        try:
            footprint = {
                'large_block_trades': [],
                'iceberg_orders': [],
                'stealth_accumulation': False,
                'institutional_absorption': [],
                'smart_money_flow': 'NEUTRAL'
            }
            
            if len(df) < 50 or 'volume' not in df.columns:
                return footprint
            
            # Calculate volume statistics
            volume_mean = df['volume'].rolling(20).mean()
            volume_std = df['volume'].rolling(20).std()
            volume_zscore = (df['volume'] - volume_mean) / volume_std
            
            # Detect large block trades (volume spikes with minimal price impact)
            for i in range(20, len(df)):
                if volume_zscore.iloc[i] > 2.5:  # 2.5 sigma volume spike
                    price_impact = abs(df['close'].iloc[i] - df['open'].iloc[i]) / df['open'].iloc[i]
                    
                    if price_impact < 0.005:  # Less than 0.5% price impact
                        footprint['large_block_trades'].append({
                            'index': i,
                            'timestamp': df.index[i],
                            'volume': df['volume'].iloc[i],
                            'volume_zscore': volume_zscore.iloc[i],
                            'price_impact': price_impact,
                            'absorption_quality': 'HIGH' if price_impact < 0.002 else 'MEDIUM'
                        })
            
            # Detect stealth accumulation (gradual volume increase with price stability)
            recent_volume_trend = self._calculate_volume_trend(df.tail(20))
            recent_price_volatility = df['close'].tail(20).std() / df['close'].tail(20).mean()
            
            if recent_volume_trend > 0.1 and recent_price_volatility < 0.02:
                footprint['stealth_accumulation'] = True
            
            # Analyze smart money flow direction
            money_flow = self._calculate_smart_money_flow(df)
            footprint['smart_money_flow'] = money_flow
            
            return footprint
            
        except Exception as e:
            self.logger.error(f"Error detecting institutional footprint: {e}")
            return {}
    
    def _identify_market_regime(self, df: pd.DataFrame) -> Dict:
        """Identify current market regime using ML-based analysis"""
        try:
            if len(df) < 100:
                return {'regime': 'UNKNOWN', 'confidence': 0}
            
            # Calculate regime features
            features = self._calculate_regime_features(df)
            
            # Use clustering to identify regime
            if len(features) > 0:
                # Simple regime classification based on volatility and trend
                volatility = df['close'].rolling(20).std().iloc[-1] / df['close'].iloc[-1]
                trend_strength = abs(df['close'].iloc[-1] - df['close'].iloc[-20]) / df['close'].iloc[-20]
                volume_trend = self._calculate_volume_trend(df.tail(20))
                
                if volatility > 0.03 and volume_trend > 0.2:
                    regime = 'HIGH_VOLATILITY_TRENDING'
                    confidence = 0.8
                elif volatility < 0.015 and trend_strength < 0.02:
                    regime = 'LOW_VOLATILITY_RANGING'
                    confidence = 0.7
                elif trend_strength > 0.05:
                    regime = 'STRONG_TRENDING'
                    confidence = 0.75
                else:
                    regime = 'TRANSITIONAL'
                    confidence = 0.5
                
                return {
                    'regime': regime,
                    'confidence': confidence,
                    'volatility': volatility,
                    'trend_strength': trend_strength,
                    'volume_trend': volume_trend
                }
            
            return {'regime': 'UNKNOWN', 'confidence': 0}
            
        except Exception as e:
            self.logger.error(f"Error identifying market regime: {e}")
            return {'regime': 'UNKNOWN', 'confidence': 0}
    
    def _advanced_volume_profile(self, df: pd.DataFrame) -> Dict:
        """Advanced volume profile analysis with institutional insights"""
        try:
            if len(df) < 50:
                return {}
            
            # Calculate VWAP and volume-weighted levels
            vwap = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()
            
            # Identify high-volume nodes (institutional interest levels)
            price_bins = 50
            price_min = df['low'].min()
            price_max = df['high'].max()
            bin_size = (price_max - price_min) / price_bins
            
            volume_profile = {}
            for i in range(price_bins):
                bin_low = price_min + i * bin_size
                bin_high = bin_low + bin_size
                bin_volume = 0
                
                for _, row in df.iterrows():
                    if bin_low <= row['close'] <= bin_high:
                        bin_volume += row['volume']
                
                volume_profile[bin_low + bin_size/2] = bin_volume
            
            # Find Point of Control (POC) and Value Area
            poc_price = max(volume_profile, key=volume_profile.get)
            total_volume = sum(volume_profile.values())
            
            # Calculate Value Area (70% of volume)
            sorted_levels = sorted(volume_profile.items(), key=lambda x: x[1], reverse=True)
            cumulative_volume = 0
            value_area_prices = []
            
            for price, volume in sorted_levels:
                cumulative_volume += volume
                value_area_prices.append(price)
                if cumulative_volume >= total_volume * 0.7:
                    break
            
            vah = max(value_area_prices) if value_area_prices else poc_price
            val = min(value_area_prices) if value_area_prices else poc_price
            
            # Identify institutional absorption levels
            absorption_levels = []
            for price, volume in sorted_levels[:10]:  # Top 10 volume levels
                if volume > total_volume * 0.05:  # More than 5% of total volume
                    absorption_levels.append({
                        'price': price,
                        'volume': volume,
                        'volume_percentage': (volume / total_volume) * 100
                    })
            
            return {
                'poc': poc_price,
                'vah': vah,
                'val': val,
                'vwap': vwap.iloc[-1],
                'absorption_levels': absorption_levels,
                'volume_distribution': 'NORMAL' if len(absorption_levels) <= 3 else 'FRAGMENTED'
            }
            
        except Exception as e:
            self.logger.error(f"Error in advanced volume profile: {e}")
            return {}
