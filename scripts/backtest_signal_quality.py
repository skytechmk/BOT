#!/usr/bin/env python3
"""
backtest_signal_quality.py — S5: Analyze features_json vs outcomes.

Usage:
    python3 scripts/backtest_signal_quality.py [--min-signals 50] [--days 30]

What it does:
    1. Reads all CLOSED signals from signal_registry.db that have features_json
    2. Labels each: WIN (TP1 hit, pnl > 0) vs LOSS (SL hit, pnl <= 0)
    3. Runs feature importance via sklearn LogisticRegression + permutation importance
    4. Prints ranked indicator weights + recommended confidence threshold
    5. Saves report to proposals/backtest_YYYY-MM-DD.md
"""

import sys
import os
import json
import sqlite3
import argparse
import time
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, 'signal_registry.db')


def load_labeled_signals(min_signals=50, days=90):
    """Load CLOSED signals with non-empty features_json."""
    cutoff = time.time() - days * 86400
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("""
        SELECT signal_id, pair, signal, confidence, pnl, features_json, timestamp
        FROM signals
        WHERE status = 'CLOSED'
          AND features_json IS NOT NULL
          AND features_json != '{}'
          AND features_json != 'null'
          AND timestamp >= ?
        ORDER BY timestamp DESC
    """, (cutoff,))
    rows = cur.fetchall()
    con.close()

    records = []
    for r in rows:
        try:
            features = json.loads(r['features_json'])
            if not features:
                continue
            label = 1 if r['pnl'] > 0 else 0   # 1 = WIN, 0 = LOSS
            records.append({
                'signal_id': r['signal_id'],
                'pair': r['pair'],
                'direction': r['signal'],
                'confidence': r['confidence'],
                'pnl': r['pnl'],
                'label': label,
                'features': features,
            })
        except Exception:
            continue

    print(f"Loaded {len(records)} labeled signals ({sum(r['label'] for r in records)} wins, "
          f"{len(records) - sum(r['label'] for r in records)} losses)")

    if len(records) < min_signals:
        print(f"⚠️  Only {len(records)} signals available (need {min_signals}). "
              f"Accumulate more data and re-run.")
        return []
    return records


def build_feature_matrix(records):
    """Convert records to a (X, y) matrix using the union of all feature keys."""
    import pandas as pd
    import numpy as np

    all_keys = set()
    for r in records:
        all_keys.update(r['features'].keys())

    # Keep only numeric features
    rows = []
    labels = []
    for r in records:
        row = {}
        for k in all_keys:
            v = r['features'].get(k)
            try:
                row[k] = float(v) if v is not None else float('nan')
            except (TypeError, ValueError):
                row[k] = float('nan')
        rows.append(row)
        labels.append(r['label'])

    df = pd.DataFrame(rows)

    # Drop columns with >50% missing
    threshold = 0.5
    df = df.loc[:, df.isna().mean() < threshold]

    # Fill remaining NaN with column median
    df = df.fillna(df.median(numeric_only=True))

    y = pd.Series(labels, name='label')
    return df, y


def run_analysis(records):
    """Feature importance via logistic regression + win-rate by confidence bucket."""
    import numpy as np
    import pandas as pd
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.inspection import permutation_importance
    from sklearn.model_selection import cross_val_score

    X, y = build_feature_matrix(records)
    if X.empty or len(y.unique()) < 2:
        print("Not enough class diversity (all wins or all losses). Need more data.")
        return None

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = LogisticRegression(max_iter=500, C=0.5)
    model.fit(X_scaled, y)

    cv_scores = cross_val_score(model, X_scaled, y, cv=5, scoring='accuracy')
    print(f"\n📊 Cross-val accuracy: {cv_scores.mean():.1%} ± {cv_scores.std():.1%}")

    # Feature importance
    perm = permutation_importance(model, X_scaled, y, n_repeats=20, random_state=42)
    importance_df = pd.DataFrame({
        'feature': X.columns,
        'importance': perm.importances_mean,
        'std': perm.importances_std,
    }).sort_values('importance', ascending=False)

    print("\n🔍 Top 20 most predictive indicators:")
    print(importance_df.head(20).to_string(index=False))

    # Win rate by confidence bucket
    conf_buckets = pd.DataFrame(records)[['confidence', 'label']]
    conf_buckets['bucket'] = pd.cut(
        conf_buckets['confidence'],
        bins=[0, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80, 1.01],
        labels=['<50%', '50-55%', '55-60%', '60-65%', '65-70%', '70-80%', '>80%']
    )
    win_rate = conf_buckets.groupby('bucket', observed=True)['label'].agg(['mean', 'count'])
    win_rate.columns = ['win_rate', 'count']
    print("\n📈 Win rate by confidence bucket:")
    print(win_rate.to_string())

    # Find optimal threshold
    best_thresh = 0.55
    best_win = 0.0
    for thresh in [0.50, 0.55, 0.60, 0.65, 0.70]:
        subset = conf_buckets[conf_buckets['confidence'] >= thresh]
        if len(subset) >= 10:
            wr = subset['label'].mean()
            if wr > best_win:
                best_win = wr
                best_thresh = thresh

    print(f"\n✅ Recommended confidence threshold: {best_thresh:.0%} "
          f"(win rate {best_win:.1%} on {len(conf_buckets[conf_buckets['confidence'] >= best_thresh])} signals)")

    return {
        'cv_accuracy': float(cv_scores.mean()),
        'importance': importance_df.head(20).to_dict('records'),
        'win_rate_by_bucket': win_rate.reset_index().to_dict('records'),
        'recommended_threshold': best_thresh,
        'recommended_win_rate': best_win,
    }


def save_report(results, records):
    """Save markdown report to proposals/."""
    if not results:
        return
    date_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    path = os.path.join(PROJECT_ROOT, 'proposals', f'backtest_{date_str}.md')

    n_win = sum(r['label'] for r in records)
    n_total = len(records)

    lines = [
        f"# Backtest Report — {date_str}",
        f"",
        f"**Signals analyzed**: {n_total} ({n_win} wins, {n_total - n_win} losses)",
        f"**Cross-val accuracy**: {results['cv_accuracy']:.1%}",
        f"**Recommended confidence threshold**: {results['recommended_threshold']:.0%} "
        f"(→ {results['recommended_win_rate']:.1%} win rate)",
        f"",
        f"## Win Rate by Confidence Bucket",
        f"",
        f"| Bucket | Win Rate | Count |",
        f"|--------|----------|-------|",
    ]
    for row in results['win_rate_by_bucket']:
        lines.append(f"| {row['bucket']} | {row['win_rate']:.1%} | {row['count']:.0f} |")

    lines += [
        f"",
        f"## Top 20 Predictive Indicators",
        f"",
        f"| Rank | Indicator | Importance | Std |",
        f"|------|-----------|------------|-----|",
    ]
    for i, row in enumerate(results['importance'], 1):
        lines.append(f"| {i} | {row['feature']} | {row['importance']:.4f} | {row['std']:.4f} |")

    lines += [
        f"",
        f"## Action Items",
        f"",
        f"- [ ] Update confidence threshold in `main.py` to `{results['recommended_threshold']:.0%}` if different from current",
        f"- [ ] Recalibrate weights in `calculate_detailed_confidence()` based on top indicators above",
        f"- [ ] Re-run this script after 2 more weeks of data to validate",
    ]

    with open(path, 'w') as f:
        f.write('\n'.join(lines))
    print(f"\n📝 Report saved: {path}")


def main():
    parser = argparse.ArgumentParser(description='Backtest signal quality analysis')
    parser.add_argument('--min-signals', type=int, default=50,
                        help='Minimum labeled signals required (default: 50)')
    parser.add_argument('--days', type=int, default=90,
                        help='Look back N days (default: 90)')
    args = parser.parse_args()

    print(f"🔎 Loading signals from last {args.days} days...")
    records = load_labeled_signals(min_signals=args.min_signals, days=args.days)
    if not records:
        sys.exit(0)

    try:
        results = run_analysis(records)
        save_report(results, records)
    except ImportError as e:
        print(f"Missing dependency: {e}")
        print("Install with: pip install scikit-learn pandas")
        sys.exit(1)


if __name__ == '__main__':
    main()
