/**
 * PineTS Sidecar — HTTP microservice to run Pine Script v5 on Binance data.
 *
 * POST /run
 *   Body: { script: string, symbol: string, interval: string, bars: number }
 *   Returns: { plots: object, signals: object, error?: string }
 *
 * POST /supertrend
 *   Body: { symbol: string, interval: string, period: number, multiplier: number }
 *   Returns: { direction: 1|-1, line: number, bars: array }
 *
 * GET /health
 *   Returns: { status: "ok", version: string }
 */

const express = require('express');
const app = express();
app.use(express.json({ limit: '2mb' }));

const PORT = process.env.PINE_PORT || 3141;

// ── Lazy-load PineTS (heavy import) ─────────────────────────────────────────
let PineTS, Provider;
async function getPineTS() {
  if (!PineTS) {
    ({ PineTS, Provider } = await import('pinets'));
  }
  return { PineTS, Provider };
}

// ── Health check ─────────────────────────────────────────────────────────────
app.get('/health', (req, res) => {
  res.json({ status: 'ok', version: '1.0.0', port: PORT });
});

// ── Run arbitrary Pine Script ─────────────────────────────────────────────────
app.post('/run', async (req, res) => {
  const { script, symbol = 'BTCUSDT', interval = '1h', bars = 200, candles } = req.body;
  if (!script) return res.status(400).json({ error: 'script is required' });

  try {
    const { PineTS, Provider } = await getPineTS();
    let pine;
    if (candles && Array.isArray(candles)) {
      pine = new PineTS(candles);
    } else {
      pine = new PineTS(Provider.Binance, symbol.replace('USDT', '') + 'USDT', interval, bars);
    }
    const { plots } = await pine.run(script);

    // Extract last values from each plot series
    const summary = {};
    for (const [name, series] of Object.entries(plots || {})) {
      const data = series?.data || [];
      summary[name] = data.length ? data[data.length - 1]?.value ?? null : null;
    }

    res.json({ plots, summary, symbol, interval });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── Supertrend shortcut ───────────────────────────────────────────────────────
app.post('/supertrend', async (req, res) => {
  const {
    symbol   = 'BTCUSDT',
    interval = '1h',
    period   = 10,
    multiplier = 3.0,
    bars     = 100,
  } = req.body;

  const script = `
//@version=5
indicator("Supertrend")
[st, dir] = ta.supertrend(${multiplier}, ${period})
plot(st, "ST")
plotchar(dir == 1, "Up", "", location.top, color.green)
plotchar(dir == -1, "Down", "", location.bottom, color.red)
`;

  try {
    const { PineTS, Provider } = await getPineTS();
    const sym = symbol.replace('USDT', '') + 'USDT';
    const pine = new PineTS(Provider.Binance, sym, interval, bars);
    const { plots } = await pine.run(script);

    const stData  = plots['ST']?.data   || [];
    const upData  = plots['Up']?.data   || [];
    const downData= plots['Down']?.data || [];

    const last      = stData.length - 1;
    const stVal     = stData[last]?.value ?? null;
    const isUp      = !!(upData[last]?.value);
    const direction = isUp ? 1 : -1;

    res.json({ direction, line: stVal, symbol, interval, period, multiplier });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ── RSI + MACD shortcut ───────────────────────────────────────────────────────
app.post('/indicators', async (req, res) => {
  const { symbol = 'BTCUSDT', interval = '1h', bars = 100 } = req.body;

  const script = `
//@version=5
indicator("Indicators")
plot(ta.rsi(close, 14), "RSI")
[m, s, h] = ta.macd(close, 12, 26, 9)
plot(m, "MACD")
plot(s, "Signal")
plot(h, "Hist")
plot(ta.ema(close, 21), "EMA21")
plot(ta.ema(close, 50), "EMA50")
`;

  try {
    const { PineTS, Provider } = await getPineTS();
    const sym = symbol.replace('USDT', '') + 'USDT';
    const pine = new PineTS(Provider.Binance, sym, interval, bars);
    const { plots } = await pine.run(script);

    const last = (name) => {
      const d = plots[name]?.data || [];
      return d.length ? (d[d.length - 1]?.value ?? null) : null;
    };

    res.json({
      symbol, interval,
      rsi:    last('RSI'),
      macd:   last('MACD'),
      signal: last('Signal'),
      hist:   last('Hist'),
      ema21:  last('EMA21'),
      ema50:  last('EMA50'),
    });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.listen(PORT, () => {
  console.log(`[pine-sidecar] listening on http://127.0.0.1:${PORT}`);
});
