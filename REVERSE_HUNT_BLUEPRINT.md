# REVERSE HUNT + Chandelier Exit — Bot Implementation Blueprint

## 1. Overview

Two-stage signal confirmation system based on PineScript indicators, running exclusively on **1h timeframe**.

**Stage 1 — REVERSE HUNT (TSI Watch)**: TSI enters extreme zones → activates tracking  
**Stage 2 — Chandelier Exit (Confirmation)**: CE flips direction → confirms entry  

No USDT.D secondary ticker — only the primary pair ticker is used.

---

## 2. Signal Flow

```
┌──────────────────────────────────────────────────────────────┐
│                    SIGNAL GENERATION FLOW                      │
│                                                                │
│  1h OHLCV Data                                                │
│       │                                                        │
│       ├──→ TSI Calculation (long=25, short=13, scale=50)      │
│       │         │                                              │
│       │         ├── TSI enters Level 1 (±1.5) ──→ WATCH MODE │
│       │         ├── TSI enters Level 2 (±2.0) ──→ WATCH MODE │
│       │         │                                              │
│       │         └── TSI exits zone (crosses back) ──→ READY  │
│       │                                                        │
│       ├──→ LinReg Oscillator (len=20, norm=100)               │
│       │         │                                              │
│       │         ├── Zero cross up/down                        │
│       │         └── Reversion signals (◇)                     │
│       │                                                        │
│       └──→ Chandelier Exit (Line + Cloud layers)              │
│                 │                                              │
│                 ├── Line: ATR=25, Look=27, Mult=1.4           │
│                 ├── Cloud: ATR=14, Look=28, Mult=3.2          │
│                 │                                              │
│                 └── Buy/Sell flip ──→ CONFIRMATION            │
│                                                                │
│  READY + CONFIRMATION = OPEN POSITION                         │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Component Breakdown

### 3.1 TSI (True Strength Index)

**Purpose**: Detect overbought/oversold extremes to arm the watch system.

**Formula**:
```
price_change = close - close[1]
double_smoothed = EMA(EMA(price_change, long=25), short=13)
double_smoothed_abs = EMA(EMA(|price_change|, long=25), short=13)
TSI = 100 × (double_smoothed / double_smoothed_abs)
scaled_TSI = TSI / scale_divisor(50)
```

**Zones**:
| Zone | Level | Meaning |
|------|-------|---------|
| Overbought L1 | TSI > +1.5 | Bearish watch armed |
| Overbought L2 | TSI > +2.0 | Extreme bearish watch armed |
| Oversold L1 | TSI < -1.5 | Bullish watch armed |
| Oversold L2 | TSI < -2.0 | Extreme bullish watch armed |

**Exit Signals** (Triangles in PineScript):
| Event | Condition | Implication |
|-------|-----------|-------------|
| Exit Top L1 | TSI crosses under +1.5 | Bearish reversal starting |
| Exit Top L2 | TSI crosses under +2.0 | Extreme bearish reversal |
| Exit Bot L1 | TSI crosses over -1.5 | Bullish reversal starting |
| Exit Bot L2 | TSI crosses over -2.0 | Extreme bullish reversal |

**State Machine**:
```
IDLE ──[TSI enters zone]──→ WATCHING
WATCHING ──[TSI exits zone]──→ READY_FOR_CONFIRM
READY_FOR_CONFIRM ──[CE confirms]──→ SIGNAL_GENERATED
READY_FOR_CONFIRM ──[timeout/invalidation]──→ IDLE
```

### 3.2 Linear Regression Oscillator

**Purpose**: Additional trend context and zero-cross signals.

**Formula**:
```
slope = linreg_slope(close, length=20)
raw = slope × bar_index + intercept
normalized = (raw - SMA(raw, 100)) / StdDev(raw, 100)
```

**Signals**:
- **Zero cross up**: Normalized crosses above 0 → bullish shift
- **Zero cross down**: Normalized crosses below 0 → bearish shift
- **Reversion up (◇)**: LinReg reverses while below lower level → bottom forming
- **Reversion down (◇)**: LinReg reverses while above upper level → top forming

### 3.3 Divergence Engine

**Purpose**: Detect hidden strength/weakness after TSI exits extreme zones.

**Logic**:
1. After bearish exit triangle → set anchor at current high
2. If price makes NEW high but TSI stays below Level 1 → bearish divergence dot
3. After bullish exit triangle → set anchor at current low  
4. If price makes NEW low but TSI stays above Level 1 → bullish divergence dot
5. Cooldown: minimum 14 bars after triangle before dots are valid

### 3.4 Chandelier Exit Hybrid (Confirmation Layer)

**Purpose**: Confirm entry direction after TSI signals readiness.

**Two independent ATR trailing stop layers**:

#### Line Layer (Signal — faster)
| Parameter | Value (from screenshot) |
|-----------|----------------------|
| Long Source | Low |
| Short Source | High |
| ATR Length | 25 |
| ATR Smoothing | RMA |
| Lookback Period | 27 |
| ATR Multiplier | 1.4 |
| Wait for Close | Yes (no repaint) |

#### Cloud Layer (Trend — slower)
| Parameter | Value (from screenshot) |
|-----------|----------------------|
| Source | Close |
| ATR Length | 14 |
| ATR Smoothing | RMA |
| Lookback Period | 28 |
| ATR Multiplier | 3.2 |
| Wait for Close | Yes (no repaint) |

**State Machine**:
```
long_stop = lowest(low, lookback) - ATR × mult
short_stop = highest(high, lookback) + ATR × mult

Ratcheting:
  if close[1] > long_stop[1]:  long_stop = max(long_stop, long_stop[1])
  if close[1] < short_stop[1]: short_stop = min(short_stop, short_stop[1])

Direction flip:
  if close > short_stop[1]: direction = LONG
  if close < long_stop[1]:  direction = SHORT

buy_signal  = direction changes to LONG
sell_signal = direction changes to SHORT
```

**Confirmation Rules**:
- CE **Buy Triangle** confirms a bullish TSI exit → LONG
- CE **Sell Triangle** confirms a bearish TSI exit → SHORT
- CE Cloud direction adds conviction (same direction = stronger signal)

---

## 4. Combined Signal Logic

### Entry Conditions

**LONG Entry**:
```
1. TSI was in oversold zone (< -1.5 or < -2.0)           [WATCH]
2. TSI crossed back above -1.5 (exit triangle fired)       [READY]
3. Chandelier Exit Line flips to LONG (buy triangle)       [CONFIRMED]
4. (Bonus) CE Cloud direction == LONG                      [HIGH CONVICTION]
5. (Bonus) LinReg zero cross up or reversion up            [EXTRA CONFLUENCE]
```

**SHORT Entry**:
```
1. TSI was in overbought zone (> +1.5 or > +2.0)          [WATCH]
2. TSI crossed back below +1.5 (exit triangle fired)       [READY]
3. Chandelier Exit Line flips to SHORT (sell triangle)     [CONFIRMED]
4. (Bonus) CE Cloud direction == SHORT                     [HIGH CONVICTION]
5. (Bonus) LinReg zero cross down or reversion down        [EXTRA CONFLUENCE]
```

### Conviction Scoring

| Component | Points | Condition |
|-----------|--------|-----------|
| TSI L1 exit | +1 | TSI exits ±1.5 zone |
| TSI L2 exit | +2 | TSI exits ±2.0 zone (stronger) |
| CE Line flip | +2 | Chandelier Exit direction change (required) |
| CE Cloud agreement | +1 | Cloud layer same direction |
| LinReg zero cross | +1 | LinReg crosses zero same direction |
| LinReg reversion | +1 | LinReg reversal diamond same direction |
| Divergence dot | +1 | Bullish/bearish divergence detected |
| **Max possible** | **9** | |
| **Min for signal** | **3** | TSI L1 exit (1) + CE Line flip (2) |

### Timeouts & Invalidation

- TSI READY state expires after **12 bars** (12 hours on 1h) without CE confirmation
- If TSI re-enters the zone before CE confirms → reset to WATCHING
- If CE flips opposite direction → cancel and return to IDLE

---

## 5. Implementation Plan

### New File: `reverse_hunt.py`

```python
# Core classes and functions:

class TSICalculator:
    """Calculates TSI with configurable long/short periods and scaling."""
    def calculate(self, df: pd.DataFrame) -> pd.Series  # Returns scaled TSI
    def get_zone(self, tsi_value: float) -> str          # 'OB_L2', 'OB_L1', 'NEUTRAL', 'OS_L1', 'OS_L2'
    def detect_exits(self, df: pd.DataFrame) -> dict     # Exit triangle signals

class LinRegOscillator:
    """Normalized linear regression oscillator."""
    def calculate(self, df: pd.DataFrame) -> pd.Series
    def detect_signals(self, df: pd.DataFrame) -> dict   # Zero crosses, reversions

class DivergenceEngine:
    """Single-anchor divergence detection with cooldown."""
    def update(self, bar_data, tsi_value) -> str|None     # 'bullish', 'bearish', or None

class ChandelierExit:
    """Dual-layer Chandelier Exit (Line + Cloud)."""
    def calculate_line(self, df: pd.DataFrame) -> dict    # {long_stop, short_stop, direction}
    def calculate_cloud(self, df: pd.DataFrame) -> dict   # {long_stop, short_stop, direction}
    def detect_signals(self, df: pd.DataFrame) -> dict    # Buy/sell triangles

class ReverseHuntSignaler:
    """Orchestrates TSI watch + CE confirmation pipeline."""
    def process_pair(self, pair: str, df_1h: pd.DataFrame) -> dict|None
    # Returns: {signal, conviction, tsi_zone, ce_direction, components}
```

### Integration with `main.py`

```python
# In process_pair(), BEFORE the existing signal generation:
from reverse_hunt import ReverseHuntSignaler

rh = ReverseHuntSignaler()
rh_result = rh.process_pair(pair, df_1h)

if rh_result:
    # Use as additional confluence for existing signal pipeline
    # OR as standalone signal source
    ...
```

### Parameters (Hardcoded from PineScript defaults + screenshot)

```python
# TSI
TSI_LONG = 25
TSI_SHORT = 13
TSI_SCALE = 50.0
TSI_INVERT = True       # As per PineScript default

# Levels
LEVEL_1 = 1.5
LEVEL_2 = 2.0

# LinReg
LINREG_LEN = 20
LINREG_NORM = 100
LINREG_SMOOTH = 1
LINREG_INVERT = True

# Chandelier Exit — Line Layer (from screenshot)
CE_LINE_ATR_LEN = 25
CE_LINE_LOOKBACK = 27
CE_LINE_MULT = 1.4
CE_LINE_SMOOTH = 'RMA'

# Chandelier Exit — Cloud Layer (from screenshot)
CE_CLOUD_ATR_LEN = 14
CE_CLOUD_LOOKBACK = 28
CE_CLOUD_MULT = 3.2
CE_CLOUD_SMOOTH = 'RMA'

# Divergence
DIV_COOLDOWN_BARS = 14

# Signal
READY_TIMEOUT_BARS = 12   # 12h on 1h TF
```

---

## 6. Data Requirements

- **Timeframe**: 1h exclusively
- **Minimum bars needed**: 200 (warmup for LinReg norm=100 + EMA warmup)
- **OHLCV columns**: open, high, low, close, volume
- **Source**: Existing `data_fetcher.py` (already fetches 1h data)

---

## 7. State Persistence

Each pair maintains its own state between scan cycles:

```python
pair_state = {
    'pair': 'BTCUSDT',
    'watch_mode': 0,          # 0=idle, 1=bullish_watch, -1=bearish_watch
    'tsi_zone_entered': None, # 'OS_L1', 'OS_L2', 'OB_L1', 'OB_L2'
    'ready_since_bar': None,  # Bar index when TSI exited zone
    'anchor_high': None,      # For divergence tracking
    'anchor_low': None,
    'anchor_bar': None,
    'last_ce_direction': 0,   # 1=long, -1=short
}
```

State is kept in-memory (dict) — resets on bot restart. No persistence needed since 1h TF recalculates full history each cycle.

---

## 8. File Structure

```
reverse_hunt.py          # All-in-one: TSI, LinReg, Divergence, CE, Signaler
                         # ~400-500 lines
```

Single file — no separate module directory needed. All calculations are pure NumPy/Pandas.

---

## 9. Signal Output Format

```python
{
    'signal': 'LONG',              # or 'SHORT'
    'conviction': 5,               # 3-9 scale
    'conviction_pct': 0.71,        # conviction / 7 normalized
    'components': {
        'tsi_zone': 'OS_L2',      # Which zone TSI was in
        'tsi_exit': True,          # TSI has exited the zone
        'ce_line_flip': True,      # CE Line layer flipped (required)
        'ce_cloud_agree': True,    # CE Cloud agrees
        'linreg_zero_cross': True, # LinReg zero cross
        'linreg_reversion': False, # LinReg diamond
        'divergence': False,       # Divergence dot
    },
    'levels': {
        'ce_line_stop': 83450.0,   # Chandelier Exit stop level
        'ce_cloud_stop': 82100.0,  # Cloud layer stop
    },
    'timeframe': '1h',
}
```

---

## 10. Risk Notes

- **No USDT.D**: Original PineScript uses USDT.D as secondary — removed per request
- **Single timeframe**: 1h only — no MTF confusion
- **Wait for close**: Both CE layers use `wait=True` (no repaint), matching screenshot settings
- **TSI inversion**: Default `invert=True` from PineScript — inverts TSI so overbought = price overbought (not indicator overbought)
- **Confirmation required**: CE flip is mandatory — TSI alone never triggers a trade
- **Timeout**: READY state has 12-bar expiry to prevent stale signals
