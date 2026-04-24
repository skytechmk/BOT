"""
cnn_model.py — 1D Convolutional Neural Network for OHLCV chart pattern recognition.

Architecture inspired by "Deep Convolution Stock Technical Analysis" (philipxjm),
ported to modern PyTorch and adapted for crypto 1h futures data.

Input:  [batch, window, 5]  — (open, high, low, close, volume), window=128 bars
Output: [batch, 2]          — (bullish_prob, bearish_prob)

Integrates with the existing signal pipeline as an additional confidence signal.
The model is GPU-accelerated on the RTX 3090 automatically.
"""

import os
import time
import logging
import numpy as np
from pathlib import Path

log = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent / "ml_models" / "cnn_ohlcv.pt"
WINDOW = 128   # bars of history per sample
FEATURES = 5   # open, high, low, close, volume

# ── Architecture ──────────────────────────────────────────────────────────────

def _build_model():
    import torch.nn as nn
    class CNNPatternModel(nn.Module):
        def __init__(self, window: int = WINDOW, n_features: int = FEATURES):
            super().__init__()
            self.conv_stack = nn.Sequential(
                # Block 1: broad patterns
                nn.Conv1d(n_features, 64, kernel_size=9, stride=1, padding=4),
                nn.BatchNorm1d(64),
                nn.GELU(),
                nn.MaxPool1d(kernel_size=2),          # → [64, W/2]

                # Block 2: intermediate patterns
                nn.Conv1d(64, 128, kernel_size=5, stride=1, padding=2),
                nn.BatchNorm1d(128),
                nn.GELU(),
                nn.MaxPool1d(kernel_size=2),          # → [128, W/4]

                # Block 3: fine-grained patterns
                nn.Conv1d(128, 256, kernel_size=3, stride=1, padding=1),
                nn.BatchNorm1d(256),
                nn.GELU(),
                nn.MaxPool1d(kernel_size=2),          # → [256, W/8]

                # Block 4: deep abstraction
                nn.Conv1d(256, 512, kernel_size=3, stride=1, padding=1),
                nn.BatchNorm1d(512),
                nn.GELU(),
                nn.AdaptiveAvgPool1d(4),              # → [512, 4]
            )
            self.classifier = nn.Sequential(
                nn.Flatten(),                         # → [512 * 4 = 2048]
                nn.Linear(512 * 4, 256),
                nn.GELU(),
                nn.Dropout(0.3),
                nn.Linear(256, 64),
                nn.GELU(),
                nn.Linear(64, 2),
                nn.Softmax(dim=1),                    # (bullish, bearish)
            )

        def forward(self, x):
            # x: [batch, window, features] → permute → [batch, features, window]
            x = x.permute(0, 2, 1)
            x = self.conv_stack(x)
            return self.classifier(x)

    return CNNPatternModel()


# ── Singleton loader ──────────────────────────────────────────────────────────
_model = None
_device = None

def _get_model():
    global _model, _device
    if _model is not None:
        return _model, _device
    try:
        import torch
        _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _model = _build_model().to(_device)
        if MODEL_PATH.exists():
            _model.load_state_dict(torch.load(MODEL_PATH, map_location=_device))
            _model.eval()
            log.info(f"[CNN] Loaded model from {MODEL_PATH} on {_device}")
        else:
            _model.eval()
            log.warning(f"[CNN] No saved model at {MODEL_PATH} — using random weights. Run train_cnn() first.")
    except Exception as exc:
        log.error(f"[CNN] Init failed: {exc}")
        _model = None
    return _model, _device


# ── Inference ─────────────────────────────────────────────────────────────────

def predict_direction(df, window: int = WINDOW) -> dict:
    """
    Given a DataFrame with columns [open, high, low, close, volume],
    returns {'bullish': float, 'bearish': float, 'signal': 'LONG'|'SHORT'|'NEUTRAL'}.

    Uses the last `window` bars. Returns neutral if model not loaded or data insufficient.
    """
    if len(df) < window:
        return {"bullish": 0.5, "bearish": 0.5, "signal": "NEUTRAL", "confidence": 0.0}

    model, device = _get_model()
    if model is None:
        return {"bullish": 0.5, "bearish": 0.5, "signal": "NEUTRAL", "confidence": 0.0}

    try:
        import torch
        cols = ["open", "high", "low", "close", "volume"]
        arr = df[cols].iloc[-window:].values.astype(np.float32)

        # Normalise each feature independently (min-max per window)
        for i in range(arr.shape[1]):
            col_min, col_max = arr[:, i].min(), arr[:, i].max()
            rng = col_max - col_min
            if rng > 1e-8:
                arr[:, i] = (arr[:, i] - col_min) / rng
            else:
                arr[:, i] = 0.5

        x = torch.tensor(arr).unsqueeze(0).to(device)   # [1, 128, 5]
        with torch.no_grad():
            probs = model(x).cpu().numpy()[0]             # [bull, bear]

        bullish, bearish = float(probs[0]), float(probs[1])
        confidence = abs(bullish - bearish)

        if bullish > bearish and bullish > 0.55:
            signal = "LONG"
        elif bearish > bullish and bearish > 0.55:
            signal = "SHORT"
        else:
            signal = "NEUTRAL"

        return {"bullish": bullish, "bearish": bearish,
                "signal": signal, "confidence": round(confidence, 4)}

    except Exception as exc:
        log.warning(f"[CNN] Inference error: {exc}")
        return {"bullish": 0.5, "bearish": 0.5, "signal": "NEUTRAL", "confidence": 0.0}


# ── Training ───────────────────────────────────────────────────────────────────

def train_cnn(pairs_data: dict, epochs: int = 30, lr: float = 1e-3):
    """
    Train the CNN on historical OHLCV data.

    pairs_data: {pair: DataFrame with [open, high, low, close, volume]}
    Labels:     1-bar-forward return → bullish if next close > current, else bearish.

    Call this from a training script; saves to MODEL_PATH.
    """
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import TensorDataset, DataLoader

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        log.info(f"[CNN] Training on {device}")

        X_list, y_list = [], []
        cols = ["open", "high", "low", "close", "volume"]

        for pair, df in pairs_data.items():
            if len(df) < WINDOW + 1:
                continue
            arr = df[cols].values.astype(np.float32)
            closes = df["close"].values

            for i in range(WINDOW, len(df) - 1):
                window_arr = arr[i - WINDOW:i].copy()
                # Normalise
                for c in range(window_arr.shape[1]):
                    mn, mx = window_arr[:, c].min(), window_arr[:, c].max()
                    rng = mx - mn
                    if rng > 1e-8:
                        window_arr[:, c] = (window_arr[:, c] - mn) / rng
                    else:
                        window_arr[:, c] = 0.5
                label = 1 if closes[i + 1] > closes[i] else 0   # 1=bull, 0=bear
                X_list.append(window_arr)
                y_list.append(label)

        if not X_list:
            log.error("[CNN] No training samples")
            return

        X = torch.tensor(np.array(X_list))   # [N, 128, 5]
        y = torch.tensor(np.array(y_list), dtype=torch.long)
        log.info(f"[CNN] {len(X)} samples | bull={y.sum().item()} bear={(y==0).sum().item()}")

        ds = TensorDataset(X, y)
        dl = DataLoader(ds, batch_size=256, shuffle=True, num_workers=4, pin_memory=True)

        model = _build_model().to(device)
        optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
        criterion = nn.CrossEntropyLoss()

        for epoch in range(1, epochs + 1):
            model.train()
            total_loss = correct = total = 0
            for xb, yb in dl:
                xb, yb = xb.to(device), yb.to(device)
                optimizer.zero_grad()
                out = model(xb)
                loss = criterion(out, yb)
                loss.backward()
                optimizer.step()
                total_loss += loss.item() * len(xb)
                correct += (out.argmax(1) == yb).sum().item()
                total += len(xb)
            scheduler.step()
            acc = correct / total * 100
            log.info(f"[CNN] Epoch {epoch:3d}/{epochs}  loss={total_loss/total:.4f}  acc={acc:.1f}%")

        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        torch.save(model.state_dict(), MODEL_PATH)
        log.info(f"[CNN] Saved to {MODEL_PATH}")

        # Update singleton
        global _model, _device
        _model = model.eval()
        _device = device

    except Exception as exc:
        log.error(f"[CNN] Training failed: {exc}")
        raise
