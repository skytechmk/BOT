#!/usr/bin/env python3
"""
Stop-Loss Failure Analysis & Hypothesis Testing

Analyzes closed signals to identify which technical features distinguish
winners from losers. Tests 7 hypotheses from proposal:
  H1: Trend Alignment (SMA20 vs SMA50)
  H2: Cloud Position (price vs senkou spans)
  H3: MACD Histogram strength
  H4: Volume confirmation
  H5: ADX strength
  H6: RSI extremes
  H7: ATR-based stop proximity

Usage:
  python scripts/stop_loss_failure_analysis.py [--min-signals N] [--output-dir DIR]

Requirements:
  pip install pandas numpy scipy matplotlib seaborn scikit-learn
"""

import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import chi2_contingency, ttest_ind
import matplotlib.pyplot as plt

# Optional visualization libraries
try:
    import seaborn as sns
    SEABORN_AVAILABLE = True
except ImportError:
    SEABORN_AVAILABLE = False
    print("Warning: seaborn not available. Using matplotlib defaults.")

# Try to import sklearn for decision tree analysis
try:
    from sklearn.tree import DecisionTreeClassifier, plot_tree
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, classification_report
    from sklearn.linear_model import LogisticRegression
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("Warning: scikit-learn not available. Decision tree analysis will be skipped.")

# Configuration
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'signal_registry.db')
DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'analysis_output')

# Hypothesis thresholds (can be tuned based on findings)
THRESHOLDS = {
    'volume_spike': 1.20,      # Volume > 120% of 20-period average
    'adx_strong': 25.0,        # ADX > 25 for strong trend
    'rsi_overbought': 70.0,    # RSI > 70 for SHORT
    'rsi_oversold': 30.0,      # RSI < 30 for LONG
    'atr_stop_min': 1.0,       # Stop loss at least 1x ATR
    'atr_stop_optimal': 1.5,   # Stop loss at least 1.5x ATR
}


def load_signals_with_features(db_path: str, min_signals: int = 20) -> pd.DataFrame:
    """
    Load closed signals with non-null features_json from database.
    
    Returns DataFrame with signal data and parsed features.
    """
    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Query for closed signals with non-empty features
    query = """
        SELECT 
            signal_id,
            pair,
            signal,
            price as entry_price,
            confidence,
            stop_loss,
            leverage,
            features_json,
            pnl,
            timestamp,
            closed_timestamp,
            status
        FROM signals 
        WHERE status = 'CLOSED' 
            AND pnl IS NOT NULL 
            AND features_json IS NOT NULL 
            AND features_json != '{}' 
            AND features_json != ''
        ORDER BY timestamp DESC
    """
    
    cursor = conn.execute(query)
    rows = cursor.fetchall()
    conn.close()
    
    if len(rows) < min_signals:
        print(f"Warning: Only {len(rows)} closed signals with features found.")
        print(f"  Minimum recommended for statistical analysis: {min_signals}")
        print(f"  Analysis will proceed but results may not be statistically significant.")
    
    # Parse features and build DataFrame
    records = []
    for row in rows:
        record = dict(row)
        
        # Parse features JSON
        try:
            features = json.loads(record['features_json'])
            record.update(features)  # Flatten features into record
        except (json.JSONDecodeError, TypeError) as e:
            print(f"Warning: Could not parse features for signal {record['signal_id']}: {e}")
            continue
        
        # Calculate derived metrics
        record = calculate_derived_metrics(record)
        records.append(record)
    
    df = pd.DataFrame(records)
    
    if len(df) == 0:
        print("Error: No valid signals with features found.")
        sys.exit(1)
    
    print(f"\nLoaded {len(df)} closed signals with features:")
    print(f"  Winners (PnL > 0): {len(df[df['pnl'] > 0])}")
    print(f"  Losers (PnL <= 0): {len(df[df['pnl'] <= 0])}")
    print(f"  Average PnL: {df['pnl'].mean():.2f}%")
    print(f"  SHORT signals: {len(df[df['signal'] == 'SHORT'])}")
    print(f"  LONG signals: {len(df[df['signal'] == 'LONG'])}")
    
    return df


def calculate_derived_metrics(record: Dict) -> Dict:
    """
    Calculate derived metrics for hypothesis testing.
    
    Metrics:
    - trend_aligned: SMA20 < SMA50 for SHORT, SMA20 > SMA50 for LONG
    - cloud_below: close < senkou_span_a AND close < senkou_span_b
    - macd_strength: absolute value of MACD histogram
    - volume_spike: volume / 20-period average
    - adx_strong: ADX > 25
    - rsi_extreme: RSI > 70 for SHORT, RSI < 30 for LONG
    - stop_atr_ratio: (stop - entry) / ATR
    """
    signal = record.get('signal', '').upper()
    
    # H1: Trend Alignment
    sma20 = record.get('SMA_20') or record.get('sma_20')
    sma50 = record.get('SMA_50') or record.get('sma_50')
    price = record.get('price') or record.get('entry_price') or record.get('close')
    
    if sma20 is not None and sma50 is not None:
        if signal == 'SHORT':
            record['trend_aligned'] = sma20 < sma50  # Bearish trend
        elif signal == 'LONG':
            record['trend_aligned'] = sma20 > sma50  # Bullish trend
        else:
            record['trend_aligned'] = None
    else:
        record['trend_aligned'] = None
    
    # H2: Cloud Position
    senkou_a = record.get('Ichimoku_SenkouA') or record.get('senkou_span_a')
    senkou_b = record.get('Ichimoku_SenkouB') or record.get('senkou_span_b')
    
    if price is not None and senkou_a is not None and senkou_b is not None:
        record['cloud_below'] = price < senkou_a and price < senkou_b
        record['cloud_above'] = price > senkou_a and price > senkou_b
        record['cloud_inside'] = not record['cloud_below'] and not record['cloud_above']
    else:
        record['cloud_below'] = None
        record['cloud_above'] = None
        record['cloud_inside'] = None
    
    # H3: MACD Histogram strength
    macd_hist = record.get('MACD_histogram') or record.get('MACD_Histogram')
    if macd_hist is not None:
        record['macd_strength'] = abs(macd_hist)
        record['macd_sign'] = 'bullish' if macd_hist > 0 else 'bearish' if macd_hist < 0 else 'neutral'
    else:
        record['macd_strength'] = None
        record['macd_sign'] = None
    
    # H4: Volume confirmation
    volume = record.get('Volume') or record.get('volume')
    volume_ma = record.get('Volume_MA') or record.get('volume_ma')
    
    if volume is not None and volume_ma is not None and volume_ma > 0:
        record['volume_spike'] = volume / volume_ma
    else:
        record['volume_spike'] = None
    
    # H5: ADX Strength
    adx = record.get('ADX')
    if adx is not None:
        record['adx_strong'] = adx > THRESHOLDS['adx_strong']
        record['adx_value'] = adx
    else:
        record['adx_strong'] = None
        record['adx_value'] = None
    
    # H6: RSI Extremes
    rsi = record.get('RSI_14')
    if rsi is not None:
        if signal == 'SHORT':
            record['rsi_extreme'] = rsi > THRESHOLDS['rsi_overbought']
            record['rsi_extreme_value'] = max(0, rsi - THRESHOLDS['rsi_overbought'])
        elif signal == 'LONG':
            record['rsi_extreme'] = rsi < THRESHOLDS['rsi_oversold']
            record['rsi_extreme_value'] = max(0, THRESHOLDS['rsi_oversold'] - rsi)
        else:
            record['rsi_extreme'] = None
            record['rsi_extreme_value'] = None
    else:
        record['rsi_extreme'] = None
        record['rsi_extreme_value'] = None
    
    # H7: ATR-Based Stop Proximity
    atr = record.get('ATR')
    entry = record.get('entry_price') or record.get('price')
    stop = record.get('stop_loss')
    
    if atr is not None and atr > 0 and entry is not None and stop is not None:
        stop_distance = abs(stop - entry)
        record['stop_atr_ratio'] = stop_distance / atr
        record['stop_tight'] = record['stop_atr_ratio'] < THRESHOLDS['atr_stop_min']
        record['stop_optimal'] = record['stop_atr_ratio'] >= THRESHOLDS['atr_stop_optimal']
    else:
        record['stop_atr_ratio'] = None
        record['stop_tight'] = None
        record['stop_optimal'] = None
    
    # Classification
    record['is_winner'] = record.get('pnl', 0) > 0
    record['is_loser'] = record.get('pnl', 0) <= 0
    
    return record


def cohens_d(group1: np.ndarray, group2: np.ndarray) -> float:
    """
    Calculate Cohen's d effect size.
    
    Interpretation:
    - Small: 0.2
    - Medium: 0.5
    - Large: 0.8
    """
    n1, n2 = len(group1), len(group2)
    pooled_std = np.sqrt(((n1 - 1) * np.var(group1, ddof=1) + (n2 - 1) * np.var(group2, ddof=1)) / (n1 + n2 - 2))
    
    if pooled_std == 0:
        return 0.0
    
    return (np.mean(group1) - np.mean(group2)) / pooled_std


def chi_square_test(df: pd.DataFrame, feature: str, min_samples: int = 10) -> Optional[Dict]:
    """
    Perform chi-square test for binary feature vs winner/loser outcome.
    """
    # Filter out None values
    valid_df = df[df[feature].notna()]
    
    if len(valid_df) < min_samples:
        return None
    
    # Create contingency table
    contingency = pd.crosstab(valid_df[feature], valid_df['is_winner'])
    
    if contingency.shape != (2, 2):
        return None
    
    # Chi-square test
    chi2, p_value, dof, expected = chi2_contingency(contingency)
    
    # Calculate effect size (Cramér's V)
    n = contingency.sum().sum()
    cramers_v = np.sqrt(chi2 / (n * (min(contingency.shape) - 1)))
    
    # Win rates by feature
    feature_true_winrate = valid_df[valid_df[feature] == True]['is_winner'].mean()
    feature_false_winrate = valid_df[valid_df[feature] == False]['is_winner'].mean()
    
    return {
        'feature': feature,
        'test': 'chi_square',
        'chi2': chi2,
        'p_value': p_value,
        'cramers_v': cramers_v,
        'significant': p_value < 0.05,
        'n_samples': len(valid_df),
        'winrate_feature_true': feature_true_winrate,
        'winrate_feature_false': feature_false_winrate,
        'contingency_table': contingency.to_dict()
    }


def t_test_analysis(df: pd.DataFrame, feature: str, min_samples: int = 10) -> Optional[Dict]:
    """
    Perform t-test for continuous feature between winners and losers.
    """
    winners = df[df['is_winner'] == True][feature].dropna()
    losers = df[df['is_winner'] == False][feature].dropna()
    
    if len(winners) < min_samples or len(losers) < min_samples:
        return None
    
    # T-test
    t_stat, p_value = ttest_ind(winners, losers)
    
    # Effect size
    effect_size = cohens_d(winners.values, losers.values)
    
    return {
        'feature': feature,
        'test': 't_test',
        't_statistic': t_stat,
        'p_value': p_value,
        'significant': p_value < 0.05,
        'effect_size': effect_size,
        'effect_magnitude': 'large' if abs(effect_size) >= 0.8 else 'medium' if abs(effect_size) >= 0.5 else 'small',
        'winners_mean': winners.mean(),
        'losers_mean': losers.mean(),
        'winners_std': winners.std(),
        'losers_std': losers.std(),
        'n_winners': len(winners),
        'n_losers': len(losers)
    }


def run_all_hypothesis_tests(df: pd.DataFrame) -> Dict[str, List[Dict]]:
    """
    Run all hypothesis tests and return results.
    """
    results = {
        'binary': [],
        'continuous': []
    }
    
    print("\n" + "="*60)
    print("HYPOTHESIS TESTING RESULTS")
    print("="*60)
    
    # Binary features (Chi-square)
    binary_features = [
        ('trend_aligned', 'H1: Trend Alignment (SMA20 vs SMA50)'),
        ('cloud_below', 'H2: Cloud Position (price below cloud)'),
        ('adx_strong', 'H5: ADX Strength (> 25)'),
        ('rsi_extreme', 'H6: RSI Extremes (SHORT>70, LONG<30)'),
        ('stop_tight', 'H7: Tight Stop (< 1x ATR)'),
        ('stop_optimal', 'H7: Optimal Stop (> 1.5x ATR)'),
    ]
    
    print("\n--- Binary Features (Chi-Square Tests) ---")
    for feature, description in binary_features:
        result = chi_square_test(df, feature)
        if result:
            results['binary'].append(result)
            sig_marker = "***" if result['significant'] else ""
            print(f"\n{description} {sig_marker}")
            print(f"  Feature: {feature}")
            print(f"  p-value: {result['p_value']:.4f}")
            print(f"  Cramér's V: {result['cramers_v']:.3f}")
            print(f"  Win rate (feature=True): {result['winrate_feature_true']:.1%}")
            print(f"  Win rate (feature=False): {result['winrate_feature_false']:.1%}")
            print(f"  Sample size: {result['n_samples']}")
        else:
            print(f"\n{description}: Insufficient data")
    
    # Continuous features (T-tests)
    continuous_features = [
        ('macd_strength', 'H3: MACD Histogram Strength'),
        ('volume_spike', 'H4: Volume Spike Ratio'),
        ('adx_value', 'H5: ADX Value'),
        ('stop_atr_ratio', 'H7: Stop Distance (ATR ratio)'),
        ('rsi_extreme_value', 'H6: RSI Extreme Value'),
    ]
    
    print("\n--- Continuous Features (T-Tests) ---")
    for feature, description in continuous_features:
        result = t_test_analysis(df, feature)
        if result:
            results['continuous'].append(result)
            sig_marker = "***" if result['significant'] else ""
            print(f"\n{description} {sig_marker}")
            print(f"  Feature: {feature}")
            print(f"  p-value: {result['p_value']:.4f}")
            print(f"  Effect size (Cohen's d): {result['effect_size']:.3f} ({result['effect_magnitude']})")
            print(f"  Winners mean: {result['winners_mean']:.4f} ± {result['winners_std']:.4f}")
            print(f"  Losers mean: {result['losers_mean']:.4f} ± {result['losers_std']:.4f}")
        else:
            print(f"\n{description}: Insufficient data")
    
    return results


def find_optimal_thresholds(df: pd.DataFrame, output_dir: str) -> Dict[str, Any]:
    """
    Find optimal thresholds for continuous features to maximize separation.
    """
    print("\n" + "="*60)
    print("OPTIMAL THRESHOLD ANALYSIS")
    print("="*60)
    
    thresholds = {}
    
    features_to_optimize = [
        'volume_spike',
        'adx_value',
        'stop_atr_ratio',
        'macd_strength',
    ]
    
    for feature in features_to_optimize:
        if feature not in df.columns or df[feature].isna().all():
            continue
        
        valid_data = df[df[feature].notna()]
        if len(valid_data) < 20:
            continue
        
        # Try different thresholds and find one that maximizes accuracy
        values = valid_data[feature].values
        min_val, max_val = np.percentile(values, [10, 90])
        
        best_threshold = None
        best_accuracy = 0.5
        
        for threshold in np.linspace(min_val, max_val, 50):
            predicted = valid_data[feature] >= threshold
            accuracy = (predicted == valid_data['is_winner']).mean()
            
            # Also check the inverse
            accuracy_inv = ((~predicted) == valid_data['is_winner']).mean()
            
            if accuracy > best_accuracy:
                best_accuracy = accuracy
                best_threshold = (threshold, '>=')
            
            if accuracy_inv > best_accuracy:
                best_accuracy = accuracy_inv
                best_threshold = (threshold, '<')
        
        if best_threshold:
            thresholds[feature] = {
                'threshold': round(best_threshold[0], 4),
                'operator': best_threshold[1],
                'accuracy': round(best_accuracy, 3)
            }
            print(f"\n{feature}:")
            print(f"  Optimal threshold: {thresholds[feature]['threshold']}")
            print(f"  Operator: {thresholds[feature]['operator']}")
            print(f"  Accuracy: {thresholds[feature]['accuracy']:.1%}")
    
    return thresholds


def decision_tree_analysis(df: pd.DataFrame, output_dir: str) -> Optional[Dict]:
    """
    Build a decision tree to visualize feature importance.
    """
    if not SKLEARN_AVAILABLE:
        print("\nDecision tree analysis skipped (scikit-learn not available)")
        return None
    
    print("\n" + "="*60)
    print("DECISION TREE ANALYSIS")
    print("="*60)
    
    # Select features for modeling
    feature_cols = [
        'trend_aligned', 'cloud_below', 'adx_strong', 'rsi_extreme',
        'stop_tight', 'stop_optimal', 'volume_spike', 'macd_strength',
        'stop_atr_ratio', 'adx_value'
    ]
    
    # Filter to columns that exist and have data
    available_cols = [c for c in feature_cols if c in df.columns and df[c].notna().sum() > 10]
    
    if len(available_cols) < 2:
        print("Insufficient features for decision tree analysis")
        return None
    
    # Prepare data
    model_df = df[available_cols + ['is_winner']].dropna()
    
    if len(model_df) < 20:
        print(f"Insufficient samples for decision tree: {len(model_df)}")
        return None
    
    X = model_df[available_cols]
    y = model_df['is_winner']
    
    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)
    
    # Train decision tree
    dt = DecisionTreeClassifier(max_depth=4, min_samples_leaf=5, random_state=42)
    dt.fit(X_train, y_train)
    
    # Predictions
    y_pred = dt.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    
    print(f"\nDecision Tree Accuracy: {accuracy:.1%}")
    print(f"Training samples: {len(X_train)}, Test samples: {len(X_test)}")
    
    # Feature importance
    importance = pd.DataFrame({
        'feature': available_cols,
        'importance': dt.feature_importances_
    }).sort_values('importance', ascending=False)
    
    print("\nFeature Importance:")
    for _, row in importance.head(5).iterrows():
        print(f"  {row['feature']}: {row['importance']:.3f}")
    
    # Plot tree
    try:
        fig, ax = plt.subplots(figsize=(20, 12))
        plot_tree(dt, feature_names=available_cols, class_names=['Loser', 'Winner'],
                  filled=True, rounded=True, ax=ax, fontsize=10)
        plt.title('Decision Tree: Winner vs Loser Classification')
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, 'decision_tree.png'), dpi=150, bbox_inches='tight')
        plt.close()
        print(f"\nDecision tree plot saved to: {output_dir}/decision_tree.png")
    except Exception as e:
        print(f"Could not plot decision tree: {e}")
    
    return {
        'accuracy': accuracy,
        'feature_importance': importance.to_dict('records'),
        'n_features': len(available_cols),
        'n_samples': len(model_df)
    }


def logistic_regression_summary(df: pd.DataFrame) -> Optional[Dict]:
    """
    Build a logistic regression using top 2 features.
    """
    if not SKLEARN_AVAILABLE:
        return None
    
    print("\n" + "="*60)
    print("LOGISTIC REGRESSION (Top 2 Features)")
    print("="*60)
    
    # Find top 2 features by t-test effect size
    continuous_results = []
    for feature in ['volume_spike', 'adx_value', 'stop_atr_ratio', 'macd_strength']:
        result = t_test_analysis(df, feature)
        if result and result['significant']:
            continuous_results.append((feature, abs(result['effect_size'])))
    
    continuous_results.sort(key=lambda x: x[1], reverse=True)
    top_2 = [f[0] for f in continuous_results[:2]]
    
    if len(top_2) < 2:
        print("Insufficient significant features for logistic regression")
        return None
    
    print(f"\nUsing top 2 features: {top_2}")
    
    # Prepare data
    model_df = df[top_2 + ['is_winner']].dropna()
    
    if len(model_df) < 20:
        print(f"Insufficient samples: {len(model_df)}")
        return None
    
    X = model_df[top_2]
    y = model_df['is_winner']
    
    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)
    
    # Train logistic regression
    lr = LogisticRegression(random_state=42)
    lr.fit(X_train, y_train)
    
    # Predictions
    y_pred = lr.predict(X_test)
    accuracy = accuracy_score(y_test, y_pred)
    
    print(f"\nLogistic Regression Accuracy: {accuracy:.1%}")
    print(f"Coefficients: {dict(zip(top_2, lr.coef_[0]))}")
    
    return {
        'accuracy': accuracy,
        'features_used': top_2,
        'coefficients': dict(zip(top_2, lr.coef_[0]))
    }


def create_visualizations(df: pd.DataFrame, output_dir: str):
    """
    Create visualization plots for analysis.
    """
    print("\n" + "="*60)
    print("GENERATING VISUALIZATIONS")
    print("="*60)
    
    if SEABORN_AVAILABLE:
        sns.set_style("whitegrid")
    else:
        plt.style.use('default')
    
    # 1. PnL Distribution
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    
    # PnL histogram
    ax = axes[0, 0]
    winners = df[df['pnl'] > 0]['pnl']
    losers = df[df['pnl'] <= 0]['pnl']
    ax.hist(winners, bins=20, alpha=0.7, label=f'Winners (n={len(winners)})', color='green')
    ax.hist(losers, bins=20, alpha=0.7, label=f'Losers (n={len(losers)})', color='red')
    ax.axvline(x=0, color='black', linestyle='--', alpha=0.5)
    ax.set_xlabel('PnL (%)')
    ax.set_ylabel('Frequency')
    ax.set_title('PnL Distribution: Winners vs Losers')
    ax.legend()
    
    # Signal direction bias
    ax = axes[0, 1]
    direction_counts = df['signal'].value_counts()
    colors = ['red' if d == 'SHORT' else 'green' for d in direction_counts.index]
    ax.bar(direction_counts.index, direction_counts.values, color=colors, alpha=0.7)
    ax.set_ylabel('Count')
    ax.set_title('Signal Direction Distribution')
    
    # Win rate by signal direction
    ax = axes[1, 0]
    winrate_by_dir = df.groupby('signal')['is_winner'].mean()
    colors = ['red' if d == 'SHORT' else 'green' for d in winrate_by_dir.index]
    ax.bar(winrate_by_dir.index, winrate_by_dir.values, color=colors, alpha=0.7)
    ax.set_ylabel('Win Rate')
    ax.set_title('Win Rate by Signal Direction')
    ax.set_ylim(0, 1)
    for i, v in enumerate(winrate_by_dir.values):
        ax.text(i, v + 0.02, f'{v:.1%}', ha='center')
    
    # Confidence vs PnL scatter
    ax = axes[1, 1]
    if 'confidence' in df.columns:
        winners_df = df[df['is_winner']]
        losers_df = df[df['is_loser']]
        ax.scatter(winners_df['confidence'], winners_df['pnl'], alpha=0.6, color='green', label='Winners')
        ax.scatter(losers_df['confidence'], losers_df['pnl'], alpha=0.6, color='red', label='Losers')
        ax.set_xlabel('Confidence')
        ax.set_ylabel('PnL (%)')
        ax.set_title('Confidence vs PnL')
        ax.legend()
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'overview_analysis.png'), dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: overview_analysis.png")
    
    # 2. Feature Comparison Boxplots
    features_to_plot = [
        ('volume_spike', 'Volume Spike Ratio'),
        ('adx_value', 'ADX Value'),
        ('stop_atr_ratio', 'Stop Distance (ATR)'),
        ('macd_strength', 'MACD Strength'),
    ]
    
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    axes = axes.flatten()
    
    for idx, (feature, title) in enumerate(features_to_plot):
        ax = axes[idx]
        
        if feature not in df.columns or df[feature].isna().all():
            ax.text(0.5, 0.5, f'No data for {feature}', ha='center', va='center')
            ax.set_title(title)
            continue
        
        winners = df[df['is_winner']][feature].dropna()
        losers = df[df['is_loser']][feature].dropna()
        
        if len(winners) > 0 and len(losers) > 0:
            bp = ax.boxplot([winners, losers], labels=['Winners', 'Losers'],
                            patch_artist=True, showmeans=True)
            bp['boxes'][0].set_facecolor('green')
            bp['boxes'][1].set_facecolor('red')
            
            # Add means
            ax.text(1, winners.mean(), f'μ={winners.mean():.2f}', ha='left', va='bottom')
            ax.text(2, losers.mean(), f'μ={losers.mean():.2f}', ha='left', va='bottom')
        
        ax.set_title(title)
        ax.set_ylabel('Value')
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'feature_boxplots.png'), dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Saved: feature_boxplots.png")
    
    # 3. Binary Features Win Rates
    binary_features = ['trend_aligned', 'cloud_below', 'adx_strong', 'rsi_extreme']
    available_binary = [f for f in binary_features if f in df.columns and df[f].notna().sum() > 10]
    
    if available_binary:
        fig, ax = plt.subplots(figsize=(12, 6))
        
        winrates = []
        labels = []
        colors_list = []
        
        for feature in available_binary:
            true_wr = df[df[feature] == True]['is_winner'].mean()
            false_wr = df[df[feature] == False]['is_winner'].mean()
            
            winrates.extend([true_wr, false_wr])
            labels.extend([f'{feature}=True', f'{feature}=False'])
            colors_list.extend(['darkgreen', 'darkred'])
        
        x = np.arange(len(winrates))
        bars = ax.bar(x, winrates, color=colors_list, alpha=0.7)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=45, ha='right')
        ax.set_ylabel('Win Rate')
        ax.set_title('Win Rate by Binary Feature')
        ax.axhline(y=0.5, color='black', linestyle='--', alpha=0.5, label='50% baseline')
        ax.set_ylim(0, 1)
        
        # Add value labels
        for bar, val in zip(bars, winrates):
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.02,
                    f'{val:.1%}', ha='center', va='bottom', fontsize=8)
        
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, 'binary_feature_winrates.png'), dpi=150, bbox_inches='tight')
        plt.close()
        print(f"  Saved: binary_feature_winrates.png")


def generate_report(df: pd.DataFrame, results: Dict, thresholds: Dict, 
                   dt_results: Optional[Dict], lr_results: Optional[Dict],
                   output_dir: str):
    """
    Generate a comprehensive markdown report.
    """
    report_path = os.path.join(output_dir, 'stop_loss_analysis_report.md')
    
    with open(report_path, 'w') as f:
        f.write("# Stop-Loss Failure Analysis Report\n\n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        # Executive Summary
        f.write("## Executive Summary\n\n")
        f.write(f"- **Total Signals Analyzed:** {len(df)}\n")
        f.write(f"- **Winners:** {len(df[df['is_winner']])} ({len(df[df['is_winner']])/len(df):.1%})\n")
        f.write(f"- **Losers:** {len(df[df['is_loser']])} ({len(df[df['is_loser']])/len(df):.1%})\n")
        f.write(f"- **Average PnL:** {df['pnl'].mean():.2f}%\n")
        f.write(f"- **SHORT signals:** {len(df[df['signal'] == 'SHORT'])} ({len(df[df['signal'] == 'SHORT'])/len(df):.1%})\n")
        f.write(f"- **LONG signals:** {len(df[df['signal'] == 'LONG'])} ({len(df[df['signal'] == 'LONG'])/len(df):.1%})\n\n")
        
        # Short bias warning
        short_pct = len(df[df['signal'] == 'SHORT']) / len(df)
        if short_pct > 0.6:
            f.write(f"⚠️ **WARNING:** {short_pct:.1%} of signals are SHORT. "
                   f"This may indicate counter-trend shorting in bullish/neutral market.\n\n")
        
        # Hypothesis Test Results
        f.write("## Hypothesis Testing Results\n\n")
        
        # Binary features
        f.write("### Binary Features (Chi-Square Tests)\n\n")
        f.write("| Hypothesis | Feature | p-value | Significant | Win Rate (True) | Win Rate (False) |\n")
        f.write("|------------|---------|---------|-------------|-----------------|------------------|\n")
        
        for result in results['binary']:
            sig = "✅" if result['significant'] else "❌"
            f.write(f"| {result['feature']} | {result['feature']} | "
                   f"{result['p_value']:.4f} | {sig} | "
                   f"{result['winrate_feature_true']:.1%} | "
                   f"{result['winrate_feature_false']:.1%} |\n")
        
        f.write("\n### Continuous Features (T-Tests)\n\n")
        f.write("| Hypothesis | Feature | p-value | Significant | Effect Size | Winners Mean | Losers Mean |\n")
        f.write("|------------|---------|---------|-------------|-------------|--------------|-------------|\n")
        
        for result in results['continuous']:
            sig = "✅" if result['significant'] else "❌"
            f.write(f"| {result['feature']} | {result['feature']} | "
                   f"{result['p_value']:.4f} | {sig} | "
                   f"{result['effect_size']:.3f} ({result['effect_magnitude']}) | "
                   f"{result['winners_mean']:.4f} | {result['losers_mean']:.4f} |\n")
        
        # Optimal Thresholds
        f.write("\n## Recommended Thresholds\n\n")
        f.write("| Feature | Optimal Threshold | Operator | Accuracy |\n")
        f.write("|---------|-------------------|----------|----------|\n")
        
        for feature, data in thresholds.items():
            f.write(f"| {feature} | {data['threshold']} | {data['operator']} | {data['accuracy']:.1%} |\n")
        
        # Decision Tree Results
        if dt_results:
            f.write(f"\n## Decision Tree Analysis\n\n")
            f.write(f"- **Accuracy:** {dt_results['accuracy']:.1%}\n")
            f.write(f"- **Features Used:** {dt_results['n_features']}\n")
            f.write(f"- **Samples:** {dt_results['n_samples']}\n\n")
            f.write("### Feature Importance\n\n")
            f.write("| Feature | Importance |\n")
            f.write("|---------|------------|\n")
            for feat in dt_results['feature_importance'][:5]:
                f.write(f"| {feat['feature']} | {feat['importance']:.3f} |\n")
        
        # Logistic Regression
        if lr_results:
            f.write(f"\n## Logistic Regression (Top 2 Features)\n\n")
            f.write(f"- **Accuracy:** {lr_results['accuracy']:.1%}\n")
            f.write(f"- **Features:** {', '.join(lr_results['features_used'])}\n\n")
        
        # Recommendations
        f.write("\n## Recommendations\n\n")
        
        # Find significant features
        sig_binary = [r for r in results['binary'] if r['significant']]
        sig_continuous = [r for r in results['continuous'] if r['significant']]
        
        if sig_binary or sig_continuous:
            f.write("### Statistically Significant Findings\n\n")
            
            for r in sig_binary:
                better = "True" if r['winrate_feature_true'] > r['winrate_feature_false'] else "False"
                f.write(f"- **{r['feature']}**: Signals with {r['feature']}=True have "
                       f"{r['winrate_feature_true']:.1%} win rate vs "
                       f"{r['winrate_feature_false']:.1%} when False. "
                       f"Prefer signals where {r['feature']}={better}.\n")
            
            for r in sig_continuous:
                direction = "higher" if r['winners_mean'] > r['losers_mean'] else "lower"
                f.write(f"- **{r['feature']}**: Winners have {direction} values "
                       f"({r['winners_mean']:.4f} vs {r['losers_mean']:.4f}). "
                       f"Filter for {direction} {r['feature']}.\n")
        else:
            f.write("No statistically significant features found at p < 0.05. "
                   "Consider collecting more data or adjusting thresholds.\n")
        
        # Filter recommendations
        f.write("\n### Proposed Signal Filters\n\n")
        
        filters = []
        for r in sig_binary:
            if r['winrate_feature_true'] > r['winrate_feature_false'] + 0.1:
                filters.append(f"- Require `{r['feature']} == True` (improves win rate by "
                             f"{(r['winrate_feature_true'] - r['winrate_feature_false']):.1%})")
        
        for feature, data in thresholds.items():
            if data['accuracy'] > 0.6:
                filters.append(f"- Require `{feature} {data['operator']} {data['threshold']}` "
                             f"(accuracy: {data['accuracy']:.1%})")
        
        if filters:
            f.write("Based on the analysis, implement these pre-signal filters:\n\n")
            for filt in filters:
                f.write(filt + "\n")
        else:
            f.write("No strong filter candidates identified yet. Collect more data.\n")
        
        f.write("\n---\n\n")
        f.write("*Report generated by stop_loss_failure_analysis.py*\n")
    
    print(f"\nReport saved to: {report_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Analyze stop-loss failures and test hypotheses about signal quality.'
    )
    parser.add_argument('--min-signals', type=int, default=20,
                       help='Minimum signals required for analysis (default: 20)')
    parser.add_argument('--output-dir', type=str, default=DEFAULT_OUTPUT_DIR,
                       help=f'Output directory for results (default: {DEFAULT_OUTPUT_DIR})')
    parser.add_argument('--db-path', type=str, default=DB_PATH,
                       help=f'Path to signal_registry.db (default: {DB_PATH})')
    args = parser.parse_args()
    
    # Create output directory
    os.makedirs(args.output_dir, exist_ok=True)
    
    print("="*60)
    print("STOP-LOSS FAILURE ANALYSIS")
    print("="*60)
    print(f"Database: {args.db_path}")
    print(f"Output directory: {args.output_dir}")
    print(f"Minimum signals: {args.min_signals}")
    
    # Load data
    df = load_signals_with_features(args.db_path, args.min_signals)
    
    # Run hypothesis tests
    results = run_all_hypothesis_tests(df)
    
    # Find optimal thresholds
    thresholds = find_optimal_thresholds(df, args.output_dir)
    
    # Decision tree analysis
    dt_results = decision_tree_analysis(df, args.output_dir)
    
    # Logistic regression with top 2 features
    lr_results = logistic_regression_summary(df)
    
    # Create visualizations
    create_visualizations(df, args.output_dir)
    
    # Generate report
    generate_report(df, results, thresholds, dt_results, lr_results, args.output_dir)
    
    print("\n" + "="*60)
    print("ANALYSIS COMPLETE")
    print("="*60)
    print(f"Output files in: {args.output_dir}")
    print("\nNext steps:")
    print("1. Review the markdown report for findings")
    print("2. Check the generated plots for visual patterns")
    print("3. Implement recommended filters in signal_generator.py")
    print("4. Re-run analysis after collecting more signals")


if __name__ == '__main__':
    main()
