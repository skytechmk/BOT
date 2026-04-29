"""
profiler_engine.py — Conditional pyinstrument integration for the HFT engine.

Architecture:
  • Env-gated: PROFILE_ENGINE=True is the ONLY way profiling activates.
  • Zero overhead: when the env var is absent/false, every function returns
    immediately and the profiler is never instantiated.
  • Two entry points:
      1. ProfilingContextManager — wraps the main async event loop.
      2. ProfileMiddleware        — ASGI middleware for FastAPI endpoints.

Usage:
  # main.py
  from profiler_engine import ProfilingContextManager
  async with ProfilingContextManager() as prof:
      ...  # main loop body

  # dashboard/app.py  (insert before other middleware)
  from profiler_engine import ProfileMiddleware
  app.add_middleware(ProfileMiddleware, profile_dir=Path("logs/profiles"))
"""
from __future__ import annotations

import os
import time
import uuid
import asyncio
from pathlib import Path
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ── Conditional import: pyinstrument is only loaded when profiling is on ──
_ENABLED = os.getenv("PROFILE_ENGINE", "").lower() in ("1", "true", "yes", "on")

_profiler_cls = None
if _ENABLED:
    try:
        from pyinstrument import Profiler
        _profiler_cls = Profiler
    except ImportError:
        pass


def is_enabled() -> bool:
    """Public gate — callers can short-circuit their own hot-path checks."""
    return _ENABLED and _profiler_cls is not None


# ═══════════════════════════════════════════════════════════════════════
#  1. ASYNC EVENT-LOOP PROFILING CONTEXT MANAGER
# ═══════════════════════════════════════════════════════════════════════

class ProfilingContextManager:
    """
    Wraps a section of the async event loop for a controlled profiling window.

    Parameters:
        duration_sec:  max seconds to profile (None = use iteration cap only)
        max_iterations: max loop iterations to profile (None = use duration only)
        output_dir:    directory for the exported HTML report
        filename:      output filename (default: profile_output.html)

    Profile starts on first __aenter__ and auto-stops + exports when EITHER
    duration_sec elapses OR max_iterations is reached, whichever comes first.

    When PROFILE_ENGINE is not set, all methods are no-ops with near-zero cost.
    """

    def __init__(
        self,
        duration_sec: float = 60.0,
        max_iterations: Optional[int] = 1000,
        output_dir: str = "logs/profiles",
        filename: str = "profile_output.html",
    ) -> None:
        self._profiler: object | None = None
        self._duration_sec = duration_sec
        self._max_iterations = max_iterations
        self._iteration_count = 0
        self._start_time: float = 0.0
        self._output_path = Path(output_dir) / filename
        self._stopped = False

    async def __aenter__(self) -> "ProfilingContextManager":
        if not is_enabled():
            return self
        if self._profiler_cls is None:
            return self
        self._profiler = _profiler_cls(async_mode="enabled")
        self._profiler.start()
        self._start_time = time.monotonic()
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        if not is_enabled() or self._profiler is None or self._stopped:
            return False
        await self._stop_and_export()
        return False

    async def tick(self) -> bool:
        """
        Call once per loop iteration. Returns True if the profiling window
        has expired and the profiler has been stopped. Returns False to
        continue profiling.

        When disabled, returns False instantly with zero overhead.
        """
        if not is_enabled() or self._profiler is None or self._stopped:
            return False

        self._iteration_count += 1
        duration_expired = (
            self._duration_sec is not None
            and (time.monotonic() - self._start_time) >= self._duration_sec
        )
        iterations_expired = (
            self._max_iterations is not None
            and self._iteration_count >= self._max_iterations
        )

        if duration_expired or iterations_expired:
            await self._stop_and_export()
            return True
        return False

    async def _stop_and_export(self) -> None:
        if self._profiler is None or self._stopped:
            return
        self._stopped = True
        self._profiler.stop()
        html = self._profiler.output_html()
        self._output_path.write_text(html, encoding="utf-8")
        # Non-blocking log — avoids I/O blocking the event loop
        try:
            print(
                f"[profiler] Profile saved → {self._output_path} "
                f"({self._iteration_count} iterations, "
                f"{time.monotonic() - self._start_time:.1f}s)",
                flush=True,
            )
        except Exception:
            pass
        self._profiler = None


# ═══════════════════════════════════════════════════════════════════════
#  2. FASTAPI ASGI MIDDLEWARE — Header-gated per-request profiling
# ═══════════════════════════════════════════════════════════════════════

class ProfileMiddleware(BaseHTTPMiddleware):
    """
    ASGI middleware that profiles a single request when the header
    ``X-Profile: true`` is present.

    The output HTML is saved to:
        <profile_dir>/<correlation_id>.html

    When PROFILE_ENGINE is not set, the middleware delegates to the
    next handler immediately with near-zero overhead.
    """

    def __init__(self, app, profile_dir: str = "logs/profiles") -> None:
        super().__init__(app)
        self._profile_dir = Path(profile_dir)
        self._profile_dir.mkdir(parents=True, exist_ok=True)

    async def dispatch(self, request: Request, call_next) -> Response:
        if not is_enabled():
            return await call_next(request)

        header_val = request.headers.get("x-profile", "").lower()
        if header_val not in ("1", "true", "yes", "on"):
            return await call_next(request)

        if _profiler_cls is None:
            return await call_next(request)

        # Derive correlation_id from the request context; fall back to UUID.
        try:
            corr = request.headers.get("x-correlation-id") or str(
                getattr(request.state, "correlation_id", None) or uuid.uuid4().hex[:12]
            )
        except Exception:
            corr = f"unknown-{int(time.time())}"

        profiler = _profiler_cls(async_mode="enabled")
        profiler.start()
        try:
            response = await call_next(request)
        finally:
            profiler.stop()

        output_path = self._profile_dir / f"{corr}.html"
        output_path.write_text(profiler.output_html(), encoding="utf-8")
        response.headers["X-Profile-Report"] = str(output_path)
        return response
