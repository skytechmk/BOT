"""
qpso_optimizer.py — Quantum Particle Swarm Optimization for strategy parameters.

Based on: QTradeX's QPSO optimizer concept. Quantum PSO uses wave-function collapse
to escape local optima better than classic PSO, without momentum memory.

Optimises the following Aladdin parameters against win-rate on historical signals:
  - ce_atr_multiplier:   ATR multiplier for Chandelier Exit (2.0 – 4.0)
  - ce_period:           CE ATR lookback (8 – 26)
  - sqi_gate:            Minimum SQI to emit a signal (50 – 80)
  - tsi_threshold:       TSI level for zone triggers (10 – 35)
  - laguerre_gamma:      Laguerre RSI smoothing factor (0.3 – 0.8)

Usage:
    from qpso_optimizer import QPSOOptimizer
    opt = QPSOOptimizer(signals_history)
    best_params = opt.run(iterations=50, n_particles=30)
    print(best_params)

Run via weekly cron / Telegram /optimize command.
"""

import os
import json
import time
import random
import math
import numpy as np
from typing import Callable, Optional
from utils_logger import log_message

_RESULTS_PATH = os.path.join(os.path.dirname(__file__), "performance_logs", "qpso_results.json")


# ── Parameter space definition ────────────────────────────────────────────────

PARAM_BOUNDS: dict[str, tuple] = {
    "ce_atr_multiplier": (2.0,  4.0),
    "ce_period":         (8,    26),
    "sqi_gate":          (50,   82),
    "tsi_threshold":     (10.0, 35.0),
    "laguerre_gamma":    (0.3,  0.8),
}


def _clamp(val, lo, hi):
    return max(lo, min(hi, val))


def _random_particle() -> dict:
    return {
        k: random.uniform(lo, hi)
        for k, (lo, hi) in PARAM_BOUNDS.items()
    }


# ── Quantum PSO core ──────────────────────────────────────────────────────────

class QPSOOptimizer:
    """
    Quantum PSO (QPSO) — no velocity vectors, particles collapse toward
    attractor points sampled stochastically. Better global exploration.

    Reference: Sun et al. (2004) "A Global Search Strategy of Quantum-behaved
    Particle Swarm Optimization"
    """

    def __init__(self, signals_history: list, fitness_fn: Optional[Callable] = None):
        """
        signals_history: list of dicts from signal_registry with outcome, pnl_pct, features.
        fitness_fn: optional custom fitness(params, signals) → float.
        """
        self.signals   = signals_history
        self.fitness_fn = fitness_fn or self._default_fitness
        self.best_params: dict = {}
        self.best_score: float = -999.0
        self.history: list = []

    def _default_fitness(self, params: dict, signals: list) -> float:
        """
        Default fitness: simulate which signals would have been KEPT under these
        params and score by expectancy = win_rate * avg_win - loss_rate * avg_loss.

        Signals are filtered by:
          - sqi_gate: signals with sqi < gate are excluded
          - tsi_threshold: signals where |tsi| < threshold are excluded
        """
        gate       = params["sqi_gate"]
        tsi_thresh = params["tsi_threshold"]

        filtered = [
            s for s in signals
            if s.get("sqi_score", 0) >= gate
            and abs(s.get("tsi", 0)) >= tsi_thresh
            and s.get("outcome") in ("WIN", "LOSS", "BREAK_EVEN")
        ]

        if len(filtered) < 5:
            return -50.0   # not enough data

        wins   = [s["pnl_pct"] for s in filtered if s.get("outcome") == "WIN"]
        losses = [abs(s["pnl_pct"]) for s in filtered if s.get("outcome") == "LOSS"]

        if not wins and not losses:
            return -50.0

        win_rate = len(wins) / len(filtered)
        avg_win  = np.mean(wins)  if wins  else 0.0
        avg_loss = np.mean(losses) if losses else 0.0
        expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss

        # Bonus for higher signal count (diversity)
        count_bonus = math.log1p(len(filtered)) * 0.5
        return expectancy + count_bonus

    def run(self, iterations: int = 50, n_particles: int = 30,
            beta: float = 0.75, verbose: bool = True) -> dict:
        """
        Run QPSO.

        beta: contraction-expansion coefficient (0.5–1.0). Higher = more exploration.
              Linearly annealed from beta to beta*0.5 over iterations.
        """
        particles = [_random_particle() for _ in range(n_particles)]
        p_best    = [dict(p) for p in particles]
        p_scores  = [self.fitness_fn(p, self.signals) for p in particles]
        g_best    = dict(p_best[np.argmax(p_scores)])
        g_score   = max(p_scores)

        log_message(f"[qpso] Starting {iterations} iters × {n_particles} particles | initial best={g_score:.3f}")

        for it in range(1, iterations + 1):
            # Anneal beta
            b = beta - (beta - beta * 0.5) * (it / iterations)

            # Mean best position (mBest)
            mbest = {
                k: np.mean([pb[k] for pb in p_best])
                for k in PARAM_BOUNDS
            }

            for idx, particle in enumerate(particles):
                new_particle = {}
                for k, (lo, hi) in PARAM_BOUNDS.items():
                    phi = random.random()
                    # Local attractor: interpolation between personal best and global best
                    attractor = phi * p_best[idx][k] + (1 - phi) * g_best[k]

                    # Quantum delta — sampled from exponential distribution
                    u = random.random() + 1e-12
                    delta = b * abs(mbest[k] - particle[k]) * math.log(1 / u)
                    sign  = 1 if random.random() > 0.5 else -1

                    new_val = _clamp(attractor + sign * delta, lo, hi)
                    new_particle[k] = new_val

                particles[idx] = new_particle
                score = self.fitness_fn(new_particle, self.signals)

                if score > p_scores[idx]:
                    p_best[idx]  = dict(new_particle)
                    p_scores[idx] = score

                if score > g_score:
                    g_best  = dict(new_particle)
                    g_score = score

            if verbose and (it % 10 == 0 or it == 1):
                log_message(f"[qpso] Iter {it:3d}/{iterations} | best_score={g_score:.4f} | "
                            f"params={{{', '.join(f'{k}={v:.2f}' for k,v in g_best.items())}}}")
            self.history.append({"iter": it, "score": g_score, "params": dict(g_best)})

        self.best_params = g_best
        self.best_score  = g_score
        self._save_results()
        log_message(f"[qpso] ✅ Optimisation complete | score={g_score:.4f}")
        log_message(f"[qpso] Best params: {g_best}")
        return dict(g_best)

    def _save_results(self):
        try:
            os.makedirs(os.path.dirname(_RESULTS_PATH), exist_ok=True)
            with open(_RESULTS_PATH, "w") as f:
                json.dump({
                    "timestamp":   time.time(),
                    "best_score":  self.best_score,
                    "best_params": self.best_params,
                    "history":     self.history[-20:],  # keep last 20 checkpoints
                }, f, indent=2)
        except Exception:
            pass


def load_best_params() -> Optional[dict]:
    """Load the most recently optimised parameters from disk."""
    try:
        if not os.path.exists(_RESULTS_PATH):
            return None
        with open(_RESULTS_PATH) as f:
            data = json.load(f)
        age_h = (time.time() - data.get("timestamp", 0)) / 3600
        if age_h > 168:   # > 1 week old → stale
            log_message(f"[qpso] Stored params are {age_h:.0f}h old — consider re-optimising")
        return data.get("best_params")
    except Exception:
        return None


async def run_weekly_optimisation(signal_registry) -> dict:
    """
    Async wrapper. Pulls closed signals from SIGNAL_REGISTRY, runs QPSO,
    logs results, and returns best_params dict.
    """
    import asyncio
    try:
        closed = [
            s for s in signal_registry.values()
            if s.get("status") == "CLOSED"
            and s.get("outcome") in ("WIN", "LOSS", "BREAK_EVEN")
        ]
        if len(closed) < 10:
            log_message(f"[qpso] Only {len(closed)} closed signals — skipping optimisation (need ≥10)")
            return {}

        log_message(f"[qpso] Running QPSO on {len(closed)} closed signals")
        opt = QPSOOptimizer(closed)
        best = await asyncio.to_thread(opt.run, 40, 25, verbose=True)
        return best
    except Exception as exc:
        log_message(f"[qpso] Weekly optimisation error: {exc}")
        return {}
