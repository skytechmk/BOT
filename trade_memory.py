"""
trade_memory.py — ChromaDB-powered semantic trade memory.

Stores past signal contexts as vector embeddings. When a new signal fires,
retrieves the N most similar historical trades and their outcomes.
The retrieved context is injected into OpenRouter AI prompts to make the AI
pattern-aware (e.g. "last 3 similar BTC setups → 2 winners 1 loser").

Architecture:
  - Embedding: sentence-transformers all-MiniLM-L6-v2 (local, no API cost)
  - Vector DB: ChromaDB (persistent, on-disk at performance_logs/trade_memory/)
  - Fallback: JSON flat-file if ChromaDB unavailable
"""

import os
import json
import time
import hashlib
from typing import Optional
from utils_logger import log_message

_DB_PATH   = os.path.join(os.path.dirname(__file__), "performance_logs", "trade_memory")
_COLL_NAME = "aladdin_signals"
_FALLBACK  = os.path.join(os.path.dirname(__file__), "performance_logs", "trade_memory_fallback.json")

_chroma_client  = None
_collection     = None
_embedder       = None
_CHROMA_OK      = False


def _init():
    global _chroma_client, _collection, _embedder, _CHROMA_OK
    if _CHROMA_OK:
        return True
    try:
        import chromadb
        from chromadb.config import Settings
        os.makedirs(_DB_PATH, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=_DB_PATH)
        _collection    = _chroma_client.get_or_create_collection(
            name=_COLL_NAME,
            metadata={"hnsw:space": "cosine"}
        )

        # Local embedding model — no API calls
        try:
            from sentence_transformers import SentenceTransformer
            _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError:
            _embedder = None   # will use hash-based fallback embedding

        _CHROMA_OK = True
        log_message(f"[trade_memory] ChromaDB ready ({_collection.count()} memories)")
        return True
    except Exception as exc:
        log_message(f"[trade_memory] ChromaDB init failed, using JSON fallback: {exc}")
        return False


def _embed(text: str) -> list:
    """Embed text to vector. Falls back to deterministic pseudo-vector if no model."""
    if _embedder is not None:
        return _embedder.encode(text).tolist()
    # Deterministic 64-dim pseudo-embedding from hash (poor quality but functional)
    h = hashlib.sha256(text.encode()).digest()
    return [(b / 255.0 * 2 - 1) for b in h] + [0.0] * 32   # pad to 96 dims


def _context_string(pair: str, signal: str, regime: str, rsi: float,
                    tsi: float, atr_pct: float, sqi: int,
                    ce_dir: str, extra: dict = None) -> str:
    """Build a canonical text description of a market context for embedding."""
    base = (
        f"{pair} {signal} | regime={regime} | RSI={rsi:.1f} | TSI={tsi:.2f} | "
        f"ATR%={atr_pct:.2f} | SQI={sqi} | CE={ce_dir}"
    )
    if extra:
        extras = " | ".join(f"{k}={v}" for k, v in extra.items() if isinstance(v, (int, float, str, bool)))
        base += f" | {extras[:200]}"
    return base


# ── Public API ────────────────────────────────────────────────────────────────

def store_signal(signal_id: str, pair: str, signal: str, regime: str,
                 rsi: float, tsi: float, atr_pct: float, sqi: int,
                 ce_dir: str, entry: float, targets: list, stop: float,
                 extra: dict = None) -> None:
    """Persist a new signal to trade memory."""
    ctx = _context_string(pair, signal, regime, rsi, tsi, atr_pct, sqi, ce_dir, extra)
    metadata = {
        "signal_id": signal_id[:36],
        "pair":      pair,
        "signal":    signal,
        "regime":    regime,
        "rsi":       round(rsi, 2),
        "tsi":       round(tsi, 2),
        "atr_pct":   round(atr_pct, 3),
        "sqi":       sqi,
        "ce_dir":    ce_dir,
        "entry":     entry,
        "targets":   json.dumps(targets),
        "stop":      stop,
        "timestamp": time.time(),
        "outcome":   "PENDING",
        "pnl_pct":   0.0,
    }

    if _init() and _CHROMA_OK:
        try:
            _collection.upsert(
                ids=[signal_id[:36]],
                embeddings=[_embed(ctx)],
                documents=[ctx],
                metadatas=[metadata]
            )
            return
        except Exception as exc:
            log_message(f"[trade_memory] store error: {exc}")

    # JSON fallback
    try:
        os.makedirs(os.path.dirname(_FALLBACK), exist_ok=True)
        data = {}
        if os.path.exists(_FALLBACK):
            with open(_FALLBACK) as f:
                data = json.load(f)
        data[signal_id[:36]] = {**metadata, "context": ctx}
        with open(_FALLBACK, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def update_outcome(signal_id: str, outcome: str, pnl_pct: float) -> None:
    """Update a stored signal's outcome (WIN/LOSS/BREAK_EVEN) and PnL."""
    sid = signal_id[:36]
    if _init() and _CHROMA_OK:
        try:
            existing = _collection.get(ids=[sid])
            if existing["ids"]:
                meta = existing["metadatas"][0]
                meta["outcome"] = outcome
                meta["pnl_pct"] = round(pnl_pct, 3)
                _collection.update(ids=[sid], metadatas=[meta])
                return
        except Exception as exc:
            log_message(f"[trade_memory] update_outcome error: {exc}")

    # JSON fallback
    try:
        if os.path.exists(_FALLBACK):
            with open(_FALLBACK) as f:
                data = json.load(f)
            if sid in data:
                data[sid]["outcome"] = outcome
                data[sid]["pnl_pct"] = round(pnl_pct, 3)
                with open(_FALLBACK, "w") as f:
                    json.dump(data, f, indent=2)
    except Exception:
        pass


def retrieve_similar(pair: str, signal: str, regime: str, rsi: float,
                     tsi: float, atr_pct: float, sqi: int,
                     ce_dir: str, n_results: int = 5,
                     exclude_pending: bool = True) -> list:
    """
    Retrieve N most similar past trades by semantic similarity.
    Returns list of dicts with keys: pair, signal, outcome, pnl_pct, sqi, regime, similarity.
    """
    ctx = _context_string(pair, signal, regime, rsi, tsi, atr_pct, sqi, ce_dir)

    if _init() and _CHROMA_OK:
        try:
            count = _collection.count()
            if count == 0:
                return []
            k = min(n_results + 5, count)
            results = _collection.query(
                query_embeddings=[_embed(ctx)],
                n_results=k,
                include=["metadatas", "distances"]
            )
            out = []
            for meta, dist in zip(results["metadatas"][0], results["distances"][0]):
                if exclude_pending and meta.get("outcome") == "PENDING":
                    continue
                out.append({
                    "pair":       meta.get("pair"),
                    "signal":     meta.get("signal"),
                    "regime":     meta.get("regime"),
                    "sqi":        meta.get("sqi"),
                    "outcome":    meta.get("outcome"),
                    "pnl_pct":    meta.get("pnl_pct", 0.0),
                    "rsi":        meta.get("rsi"),
                    "tsi":        meta.get("tsi"),
                    "similarity": round(1 - dist, 3),
                })
                if len(out) >= n_results:
                    break
            return out
        except Exception as exc:
            log_message(f"[trade_memory] retrieve error: {exc}")

    # JSON fallback — return recent signals for same pair/direction
    try:
        if os.path.exists(_FALLBACK):
            with open(_FALLBACK) as f:
                data = json.load(f)
            matches = [
                v for v in data.values()
                if v.get("pair") == pair and v.get("signal") == signal
                and (not exclude_pending or v.get("outcome") != "PENDING")
            ]
            matches.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            return [{"pair": m.get("pair"), "signal": m.get("signal"),
                     "regime": m.get("regime"), "sqi": m.get("sqi"),
                     "outcome": m.get("outcome"), "pnl_pct": m.get("pnl_pct", 0.0),
                     "rsi": m.get("rsi"), "tsi": m.get("tsi"),
                     "similarity": 0.5} for m in matches[:n_results]]
    except Exception:
        pass
    return []


def format_memory_context(similar: list) -> str:
    """
    Format retrieved memories into a compact AI-readable summary block.
    Example output:
      "Similar past trades: BTCUSDT LONG (trending) SQI=98 → WIN +3.2% | ..."
    """
    if not similar:
        return "No similar historical trades found."
    lines = []
    for s in similar:
        outcome_str = f"{s['outcome']} {s['pnl_pct']:+.1f}%" if s["outcome"] != "PENDING" else "PENDING"
        lines.append(
            f"{s['pair']} {s['signal']} [{s['regime']}] SQI={s['sqi']} "
            f"RSI={s['rsi']:.0f} → {outcome_str} (sim={s['similarity']:.2f})"
        )
    wins    = sum(1 for s in similar if s["outcome"] == "WIN")
    losses  = sum(1 for s in similar if s["outcome"] == "LOSS")
    avg_pnl = sum(s["pnl_pct"] for s in similar if s["outcome"] != "PENDING")
    n_fin   = wins + losses
    summary = f"[{wins}W/{losses}L, avg_pnl={avg_pnl/max(n_fin,1):+.1f}%]" if n_fin else "[no closed trades]"
    return f"Similar past trades {summary}:\n" + "\n".join(f"  • {l}" for l in lines)
