# Предлог: Критични Поправки — Feature Persistence, BTC Trend Filter, Lekeliranje

**Датум**: 2026-04-07  
**Приоритет**: КРИТИЧНО  
**Автор**: S.P.E.C.T.R.E.  
**Поврзано**: 2026-04-07_fix-feature-persistence.md, 2026-04-07_risk-parameter-tightening.md

---

## executive Zliv

Три кри brake се cause наsustained guerril失:

1. **Feature persistence broken** — `features_json` е празно бидејќи филтерот одбива numpy float → неможеме да анализа или подобриме моделот
2. **Нема BTC trend filter** — SHORT сигнали се generate во bullish BTC regime → systemic directional losses
3. **Ексцесивно lekebinna на moderate confidence** — 20–44× на 56–69% confidence → амплифицирани загуби

Сите три мораат да се применат веднаш.

---

## Проблем 1: Feature Persistence Broken (РООТ CAUSE IDENTIFIED)

**Локација**: `main.py:468-472` (feature snapshot capture)

**Тековна код**:
```python
# Capture features for learning
feature_snapshot = df.iloc[-1].to_dict()
# Remove massive strings/objects to keep registry clean
feature_snapshot = {k: v for k, v in feature_snapshot.items() if isinstance(v, (int, float, bool, str)) and len(str(v)) < 100}
```

**Баг**: `isinstance(v, (int, float, bool, str))` враќа `False` за `numpy.float64`, `numpy.int64`, итн. Сите технички индикатори од pandas/numpy (ATR, MACD, RSI, Senkou spans, etc.) се numpy scalar типи. Се филтрираат, оставајќи `features_json` празно.

**Поправка**:
```python
import numpy as np  # додади на врв на main.py

# Capture features for learning
feature_snapshot = df.iloc[-1].to_dict()
def is_keepable(v):
    if isinstance(v, (int, float, bool, str)):
        return len(str(v)) < 100
    if isinstance(v, (np.integer, np.floating)):
        return True  # numpy numerics се секогаш компактни
    return False

feature_snapshot = {k: v for k, v in feature_snapshot.items() if is_keepable(v)}
```

**Ефект**: Откако ќе се поправи, `features_json` ќе содржи full technical context (RSI, MACD, ADX, BB, Ichimoku, VWAP, etc.) за секој signal, enabling сите downstream analysis.

---

## Проблем 2: Missing BTC Trend Filter

**Проблем**: Сите 24 последни SHORT сигнали беа генерирани без да се провери BTC's higher‑timeframe trend. Ако BTC е bullish, alts ќе се подигнуваат и stop‑out.

**Предложена имплементација** — Додади во `signal_generator.py` пред да се прифати SHORT:

```python
def get_btc_regime(timeframe='1h'):
    """
    Земi BTCUSDT 1h data и определи trend regime.
    Враќа: 'bullish', 'bearish', 'neutral'
    """
    try:
        df_btc = fetch_ohlcv('BTCUSDT', timeframe, limit=100)  # implement this helper
        if df_btc is None or len(df_btc) < 50:
            return 'neutral'
        
        latest = df_btc.iloc[-1]
        sma20 = df_btc['close'].rolling(20).mean().iloc[-1]
        sma50 = df_btc['close'].rolling(50).mean().iloc[-1]
        price = latest['close']
        
        if price > sma20 and sma20 > sma50:
            return 'bullish'
        elif price < sma20 and sma20 < sma50:
            return 'bearish'
        else:
            return 'neutral'
    except Exception as e:
        log_message(f"BTC regime check failed: {e}")
        return 'neutral'

# В calculate_base_signal(df, pair=None), откако ќе се пресмета base_signal но пред да се врати:
if pair is not None and pair != 'BTCUSDT':
    btc_regime = get_btc_regime('1h')
    if base_signal == 'SHORT' and btc_regime == 'bullish':
        log_message(f"Rejecting SHORT on {pair}: BTC regime bullish")
        return 'NEUTRAL'
    elif base_signal == 'LONG' and btc_regime == 'bearish':
        log_message(f"Rejecting LONG on {pair}: BTC regime bearish")
        return 'NEUTRAL'
```

**Поправо alternativa (пола лесно)**: Провери само price vs SMA20; прескокни SMA50 ако data е sparse.

**Caching**: Cache BTC regime за 5 минути за да се избегнат екцесивни повици.

---

## Проблем 3: Dynamic Leverage Scaling

**Тековно lekebinna** (од open signals): 20–44× на 56–69% confidence. Тереторатски.

**Предложен Lekebinna Schedule** (implement во `trading_utilities.py` or каде што се доделува leverage):

```python
def assign_leverage(confidence: float, signal_type: str, pair: str = None) -> int:
    """
    Confidence е 0.0–1.0.
    Враќа max дозволено lekebinna.
    """
    # Base tiers
    if confidence >= 0.70:
        base_lev = 20
    elif confidence >= 0.60:
        base_lev = 10
    elif confidence >= 0.50:
        base_lev = 5
    else:
        return 1  # spot only

    # Дополнително намали за SHORTs во bullish BTC regime (ако BTC filter не блокира)
    # if signal_type == 'SHORT' and get_btc_regime('1h') == 'bullish':
    #     base_lev = max(2, base_lev // 2)

    # Pair‑specific caps за ултра‑volatile-micro‑caps
    high_risk_pairs = {'PUMPUSDT', 'XANUSDT', 'COSUSDT', 'LEVERUSDT', 'TROYUSDT', '1000SATSUSDT'}
    if pair in high_risk_pairs:
        base_lev = min(base_lev, 5)

    return base_lev
```

**Wire‑up**: Повикај `assign_leverage()` во `main.py` откако ќе се пресмета `adj_confidence`, пред да се испрати сигнал.

---

## Implementation Checklist

### Фаза 1: Feature Persistence Fix
- [ ] Импортирај `numpy as np` на врв на `main.py`
- [ ] Замени филтерот за `feature_snapshot` со онај што прифаќа `np.integer` и `np.floating`
- [ ] Тест: Генерирај 1 signal, прашај DB, осигурај дека `features_json` содржи keys како 'ATR', 'RSI_14', 'MACD Histogram'
- [ ] Верувај со: `SELECT features_json FROM signals LIMIT 1;`

### Фаза 2: BTC Trend Filter
- [ ] Имплементирај `fetch_ohlcv(pair, timeframe, limit)` helper (или користи постоечки Binance client)
- [ ] Имплементирај `get_btc_regime(timeframe)` како погоре
- [ ] Интегрирај во `signal_generator.py` (или `main.py` откако `final_signal` ќе се определи, пред `register_signal`)
- [ ] Додај caching (запази последен regime и timestamp во module global, refresh ако > 5 min old)
- [ ] Логирај секое odbrane со причината

### Фаза 3: Leverage Scaling
- [ ] Додај `assign_leverage(confidence, signal_type, pair)` функция во `trading_utilities.py`
- [ ] Замени тековното lekebinna доделување во `main.py` со повик на оваа функция
- [ ] осигурај дека `high_risk_pairs` листата ги покрива нај‑volatile token‑ите (базирано на ATR% > 5%)
- [ ] Опционо: намали lekebinna ако ADX < 25 (weak trend)

### Тестирање и Валидација
1. **Feature Test**:
   ```python
   db = SignalRegistryDB()
   sig = db.get_all()
   sample = list(sig.values())[0]
   assert 'ATR' in json.loads(sample['features_json'])
   ```
2. **BTC Filter Test**: Mock BTC downtrend → осигурај дека SHORT signals сеуште пролаз; mock BTC uptrend → осигурај дека SHORT‑ите се odbrani.
3. **Leverage Test**: Логирај lekebinna доделувања за 10 сигнали, верифирај дека одговараат confidence тиров.

---

## Ризици и Митигација

| Ризик | Влијание | Митигација |
|------|--------|------------|
| BTC regime check додава latency | Побавно generiranje signals | Cache BTC data за 5 min; користи async fetch |
| Filter прекрасно стрикт, пропушдa добри trades | Намален број на signals | Прифатливо trade‑off; monitor win rate подобрување |
| Lekebinna reduction cuts PnL | Помали gaining на winner‑ите | Подобро risk‑adjusted returns; преживе dispatching |
| Feature filter change break other logic | Неочекувани errors | Тест на staging first; чувај стари филтри како fallback |

---

## Rollback

Сите промени се локализирани:
- Feature filter: врати на оригиналниот `isinstance(v, (int, float, bool, str))`
- BTC filter: закоментирај го одблокирањето
- Leverage: врати на hard‑coded мапа

Чувај оригиналниот код во comments за брз rollback.

---

## Success Metrics (По 7 Days)

- **Feature persistence**: 100% од signals имаат non‑empty `features_json`
- **BTC filter rejections**: ~30% од SHORT‑и одбиени во bullish regime (верифирај log)
- **Leverage distribution**: ≤5× за <60% confidence; max 20× за ≥70%
- **Performance**: Win rate >55%, avg win > avg loss, net PnL положително

---

## За漂 MI

Овие поправки го адресираат **непосредните root causes** на последните загуби:
- Празни features → слепа анализа
- Нема BTC filter → SHORT‑и против macro trend
- Pre‑lekebinna → амплифицирано krvarenje

Apply во ред: Feature fix прв (enable се), потоа BTC filter, потоа lekebinna scaling. Мониторирај logs за rejections и feature population. Очекувај почетен signal count пад; quality ќеraste.
