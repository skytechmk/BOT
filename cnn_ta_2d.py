"""
cnn_ta_2d.py — 2D CNN-TA Model (indicator image approach).

Based on: Sezer & Ozbayoglu (2018) "Algorithmic Financial Trading with Deep
Convolutional Neural Networks: Time Series to Image Conversion Approach"
(Applied Soft Computing, vol. 70, pp. 525-538).

Architecture:
  - 15 technical indicators × 15-bar windows → 15×15 normalised image
  - 2× Conv2D → MaxPool → Dropout → FC → 3-class softmax (LONG/SHORT/NEUTRAL)
  - GPU-accelerated (RTX 3090)

Functions:
  build_indicator_image(df)  → np.ndarray (15, 15)
  predict_direction_2d(df)   → {'signal': 'LONG'|'SHORT'|'NEUTRAL', 'confidence': float, 'probs': dict}
  train_cnn_2d(pairs_data)   → saves model to ml_models/cnn_ta_2d.pt
"""

import os
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
from utils_logger import log_message

MODEL_PATH   = os.path.join(os.path.dirname(__file__), "ml_models", "cnn_ta_2d.pt")
DEVICE       = torch.device("cuda" if torch.cuda.is_available() else "cpu")
IMG_SIZE     = 15   # 15 indicators × 15 bars
N_CLASSES    = 3    # -1=SHORT(0), 0=NEUTRAL(1), 1=LONG(2)


# ── Indicator list (15 rows) ──────────────────────────────────────────────────

def _ema(s, span):
    return s.ewm(span=span, adjust=False).mean()

def _rma(s, period):
    return s.ewm(alpha=1.0/period, adjust=False).mean()

def build_indicator_image(df: pd.DataFrame) -> np.ndarray:
    """
    Convert recent 15 bars of OHLCV data into a 15×15 indicator image.
    Each row = one indicator normalised to [-1, 1] using sliding min-max.
    Each column = one time bar (oldest left, newest right).
    Returns float32 array of shape (15, 15).
    """
    if len(df) < IMG_SIZE + 50:
        return np.zeros((IMG_SIZE, IMG_SIZE), dtype=np.float32)

    try:
        w = df.tail(IMG_SIZE + 50).copy()
        c, h, l, v = w["close"], w["high"], w["low"], w["volume"]

        def norm_tail(s):
            t = s.tail(IMG_SIZE).values.astype(float)
            mn, mx = t.min(), t.max()
            if mx - mn < 1e-12:
                return np.zeros(IMG_SIZE, dtype=np.float32)
            return ((t - mn) / (mx - mn) * 2 - 1).astype(np.float32)

        # 15 indicators
        rows = [
            norm_tail(c),                                          # 0  close
            norm_tail(_ema(c, 9)),                                 # 1  EMA9
            norm_tail(_ema(c, 21)),                                # 2  EMA21
            norm_tail(_ema(c, 50)),                                # 3  EMA50
            norm_tail(c.rolling(20).mean()),                       # 4  SMA20
            norm_tail(c.rolling(20).std()),                        # 5  BB width
            norm_tail(                                             # 6  RSI14
                100 - 100 / (1 + _rma(c.diff().clip(lower=0), 14) /
                               _rma((-c.diff()).clip(lower=0), 14).replace(0, 1e-12))
            ),
            norm_tail(                                             # 7  MACD hist
                _ema(c, 12) - _ema(c, 26) - _ema(_ema(c, 12) - _ema(c, 26), 9)
            ),
            norm_tail(                                             # 8  ATR14
                _rma(pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1), 14)
            ),
            norm_tail(v),                                          # 9  volume
            norm_tail(v / v.rolling(20).mean()),                   # 10 rel_vol
            norm_tail(                                             # 11 Stoch %K
                100 * (c - l.rolling(14).min()) /
                (h.rolling(14).max() - l.rolling(14).min()).replace(0, 1e-12)
            ),
            norm_tail(                                             # 12 CCI
                (c - c.rolling(20).mean()) /
                (0.015 * c.rolling(20).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)).replace(0, 1e-12)
            ),
            norm_tail(                                             # 13 ROC10
                (c - c.shift(10)) / c.shift(10).replace(0, 1e-12) * 100
            ),
            norm_tail((h + l + c) / 3),                           # 14 typical price
        ]
        return np.array(rows, dtype=np.float32)   # (15, 15)
    except Exception as exc:
        log_message(f"[cnn_ta_2d] build_indicator_image error: {exc}")
        return np.zeros((IMG_SIZE, IMG_SIZE), dtype=np.float32)


# ── Model architecture ────────────────────────────────────────────────────────

class CNNTA2D(nn.Module):
    """
    LeNet-style 2D CNN operating on 15×15 indicator images.
    Channels: 1 (greyscale image).
    """
    def __init__(self, n_classes: int = 3):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 32, kernel_size=3, padding=1)
        self.conv2 = nn.Conv2d(32, 64, kernel_size=3, padding=1)
        self.pool  = nn.MaxPool2d(2, 2)          # 15→7
        self.drop  = nn.Dropout(0.4)
        self.fc1   = nn.Linear(64 * 7 * 7, 128)
        self.fc2   = nn.Linear(128, n_classes)

    def forward(self, x):
        x = F.relu(self.conv1(x))                # (B,32,15,15)
        x = F.relu(self.conv2(x))                # (B,64,15,15)
        x = self.pool(x)                         # (B,64,7,7)
        x = self.drop(x.flatten(1))             # (B,64*7*7)
        x = F.relu(self.fc1(x))
        x = self.drop(x)
        return self.fc2(x)                       # (B,3) logits


# ── Lazy model loader ─────────────────────────────────────────────────────────

_model: CNNTA2D | None = None

def _load_model() -> CNNTA2D | None:
    global _model
    if _model is not None:
        return _model
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        m = CNNTA2D(N_CLASSES).to(DEVICE)
        m.load_state_dict(torch.load(MODEL_PATH, map_location=DEVICE))
        m.eval()
        _model = m
        log_message(f"[cnn_ta_2d] Model loaded from {MODEL_PATH} on {DEVICE}")
        return _model
    except Exception as exc:
        log_message(f"[cnn_ta_2d] Model load error: {exc}")
        return None


# ── Inference ─────────────────────────────────────────────────────────────────

def predict_direction_2d(df: pd.DataFrame) -> dict:
    """
    Run 2D CNN-TA inference on a DataFrame.
    Returns:
        {'signal': 'LONG'|'SHORT'|'NEUTRAL', 'confidence': float, 'probs': dict}
    Falls back to NEUTRAL with 0.33 confidence if model not trained yet.
    """
    model = _load_model()
    if model is None:
        return {"signal": "NEUTRAL", "confidence": 0.33,
                "probs": {"LONG": 0.33, "SHORT": 0.33, "NEUTRAL": 0.34},
                "source": "cnn_ta_2d_untrained"}

    img = build_indicator_image(df)           # (15, 15)
    x   = torch.tensor(img, dtype=torch.float32).unsqueeze(0).unsqueeze(0).to(DEVICE)
    # shape: (1, 1, 15, 15)
    with torch.no_grad():
        logits = model(x)
        probs  = F.softmax(logits, dim=1).squeeze().cpu().numpy()

    # Label mapping: 0=SHORT, 1=NEUTRAL, 2=LONG
    label_map = {0: "SHORT", 1: "NEUTRAL", 2: "LONG"}
    pred      = int(probs.argmax())
    signal    = label_map[pred]
    conf      = float(probs[pred])

    return {
        "signal":     signal,
        "confidence": round(conf, 4),
        "probs": {
            "LONG":    round(float(probs[2]), 4),
            "NEUTRAL": round(float(probs[1]), 4),
            "SHORT":   round(float(probs[0]), 4),
        },
        "source": "cnn_ta_2d",
    }


# ── Training ──────────────────────────────────────────────────────────────────

def train_cnn_2d(pairs_data: dict, forward_bars: int = 24,
                 epochs: int = 30, batch_size: int = 256,
                 lr: float = 1e-3) -> None:
    """
    Train the 2D CNN-TA model.

    pairs_data: {pair_symbol: pd.DataFrame with OHLCV + atr_14 columns}
    Labels: 1=LONG if price rises ≥ 1.5×ATR within forward_bars,
           -1=SHORT if price falls ≥ 1.5×ATR, 0=NEUTRAL otherwise.
    """
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)

    images, labels = [], []

    for pair, df in pairs_data.items():
        if len(df) < IMG_SIZE + 50 + forward_bars:
            continue
        atr_col = "atr_14" if "atr_14" in df.columns else None

        for i in range(IMG_SIZE + 50, len(df) - forward_bars):
            sub_df  = df.iloc[:i]
            img     = build_indicator_image(sub_df)
            if img.sum() == 0:
                continue

            price  = float(df["close"].iloc[i])
            future = df["close"].iloc[i + 1: i + 1 + forward_bars].values
            atr    = float(df[atr_col].iloc[i]) if atr_col else price * 0.02
            tp     = 1.5 * atr
            sl     = 1.5 * atr

            fut_max = future.max() - price
            fut_min = price - future.min()

            if fut_max >= tp:
                label = 2   # LONG
            elif fut_min >= sl:
                label = 0   # SHORT
            else:
                label = 1   # NEUTRAL

            images.append(img)
            labels.append(label)

    if not images:
        log_message("[cnn_ta_2d] No training data generated — skipping")
        return

    X = torch.tensor(np.array(images), dtype=torch.float32).unsqueeze(1)  # (N,1,15,15)
    y = torch.tensor(labels, dtype=torch.long)

    dataset    = TensorDataset(X, y)
    loader     = DataLoader(dataset, batch_size=batch_size, shuffle=True,
                            pin_memory=DEVICE.type == "cuda")

    model      = CNNTA2D(N_CLASSES).to(DEVICE)
    optimiser  = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler  = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=epochs)

    # Class weights for imbalance
    counts     = np.bincount(labels, minlength=3).astype(float)
    weights    = torch.tensor(1.0 / (counts + 1), dtype=torch.float32).to(DEVICE)
    criterion  = nn.CrossEntropyLoss(weight=weights)

    log_message(f"[cnn_ta_2d] Training on {len(labels)} samples ({X.shape}) | device={DEVICE}")

    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        correct    = 0
        for xb, yb in loader:
            xb, yb = xb.to(DEVICE), yb.to(DEVICE)
            optimiser.zero_grad()
            out  = model(xb)
            loss = criterion(out, yb)
            loss.backward()
            optimiser.step()
            total_loss += loss.item() * len(xb)
            correct    += (out.argmax(1) == yb).sum().item()
        scheduler.step()
        if epoch % 5 == 0 or epoch == 1:
            acc = correct / len(labels) * 100
            log_message(f"[cnn_ta_2d] Epoch {epoch:3d}/{epochs} | loss={total_loss/len(labels):.4f} | acc={acc:.1f}%")

    torch.save(model.state_dict(), MODEL_PATH)
    log_message(f"[cnn_ta_2d] Model saved → {MODEL_PATH}")
    global _model
    _model = model.eval()
