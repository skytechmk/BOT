"""
utils_logger.py — Loguru-based structured logging for multi-worker Uvicorn.
═══════════════════════════════════════════════════════════════════════════

Drop-in replacement for the legacy stdlib logger.  Existing call-sites
(`from utils_logger import log_message`, `logger.info(...)`, `clear_console()`)
continue to work without modification.

Key capabilities added:
  • Process ID in every line          — traces logs to a specific Uvicorn worker
  • Correlation ID via contextvars    — ties every log within an HTTP request
  • enqueue=True on file sink         — non-blocking disk writes (async-safe)
  • Colorized console / clean file    — readable stdout, greppable files
  • Background task IDs               — set_context("CVD-TICK") for loop tracing
"""

import os
import sys
import contextvars
import logging
import warnings

from loguru import logger as _loguru_logger

# ── Suppress noisy third-party loggers ────────────────────────────────────
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("websockets").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message="Connection pool is full")

# ── Context variable: correlation ID ──────────────────────────────────────
# HTTP middleware sets a per-request UUID; background loops set a static tag.
# Default "SYSTEM" means the log was emitted outside any request context.
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="SYSTEM"
)

# ── Configuration ─────────────────────────────────────────────────────────
LOG_FILE     = "debug_log10.txt"
MAX_BYTES    = 10 * 1024 * 1024   # 10 MB per file  (loguru: rotation)
BACKUP_COUNT = 5                   # loguru: retention

env_log_level = os.environ.get("ALADDIN_LOG_LEVEL", "INFO").upper()

# ── Format strings ────────────────────────────────────────────────────────
# Console: colorized, human-friendly
_CONSOLE_FMT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<cyan>PID:{process}</cyan> | "
    "<yellow>[{extra[correlation_id]}]</yellow> | "
    "<level>{level: <8}</level> | "
    "{message}"
)

# File: no ANSI codes, machine-parseable
_FILE_FMT = (
    "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
    "PID:{process} | "
    "[{extra[correlation_id]}] | "
    "{level: <8} | "
    "{message}"
)


# ── Patcher: inject correlation_id into every record ──────────────────────
def _patch_record(record):
    """Called by loguru before each log line is formatted.
    Reads the current correlation_id from the context variable and injects
    it into record["extra"] so the format string can reference it."""
    record["extra"]["correlation_id"] = correlation_id_var.get()


# ── Configure loguru sinks ────────────────────────────────────────────────
# Remove the default stderr sink that loguru ships with.
_loguru_logger.remove()

# 1) Console sink — colorized, respects ALADDIN_LOG_LEVEL
_loguru_logger.add(
    sys.stdout,
    format=_CONSOLE_FMT,
    level=env_log_level,
    colorize=True,
    backtrace=True,
    diagnose=False,       # No variable introspection in prod (security)
    enqueue=False,        # stdout is fast enough synchronously
)

# 2) Rotating file sink — always DEBUG, non-blocking (enqueue=True)
_loguru_logger.add(
    LOG_FILE,
    format=_FILE_FMT,
    level="DEBUG",
    rotation=f"{MAX_BYTES // (1024 * 1024)} MB",
    retention=BACKUP_COUNT,
    compression="gz",     # Old rotated logs are compressed automatically
    encoding="utf-8",
    enqueue=True,         # ← crucial: queues writes so async loops don't block
    colorize=False,       # No ANSI in files
    backtrace=True,
    diagnose=False,
)

# Apply the patcher globally so every sink gets the correlation_id.
_loguru_logger = _loguru_logger.patch(_patch_record)


# ── Intercept stdlib logging → loguru ─────────────────────────────────────
# Libraries that use `logging.getLogger(__name__).info(...)` (uvicorn,
# binance, httpx, etc.) will have their output captured and reformatted
# through loguru's pipeline, gaining PID + correlation ID for free.
class _InterceptHandler(logging.Handler):
    """Redirect stdlib logging records into loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        # Get corresponding loguru level
        try:
            level = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Find the caller frame that actually issued the log call
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


# Wire up the intercept handler on the root logger so ALL stdlib loggers
# route through loguru.
logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)


# ══════════════════════════════════════════════════════════════════════════
#  PUBLIC API — backward-compatible with every existing call-site
# ══════════════════════════════════════════════════════════════════════════

# The `logger` object that callers import.  This IS loguru's logger with
# our patches applied, so `logger.info(...)`, `logger.error(...)`, etc.
# work identically to the old stdlib logger.
logger = _loguru_logger

# Level mapping kept for log_message() backward compatibility
LEVEL_MAP = {
    "DEBUG":    "DEBUG",
    "INFO":     "INFO",
    "WARNING":  "WARNING",
    "ERROR":    "ERROR",
    "CRITICAL": "CRITICAL",
}


def log_message(message: str, level: str = "INFO") -> None:
    """Log a message with the specified level.

    100 % backward-compatible with every existing call-site::

        from utils_logger import log_message
        log_message("pair scanned", level="DEBUG")
        log_message("signal fired")                  # defaults to INFO
    """
    lvl = LEVEL_MAP.get(level.upper(), "INFO")
    # opt(depth=1) ensures loguru reports the CALLER's file/line, not this
    # wrapper's file/line.
    _loguru_logger.opt(depth=1).log(lvl, message)


def clear_console() -> None:
    """Clear the console screen."""
    os.system("cls" if os.name == "nt" else "clear")
    print(
        f"Aladdin Logger initialized — loguru "
        f"(Console: {env_log_level}, File: DEBUG, PID: {os.getpid()})"
    )


def set_context(correlation_id: str) -> None:
    """Set the correlation ID for the current execution context.

    Use in background loops to tag all logs emitted during that iteration::

        from utils_logger import set_context
        set_context("CVD-TICK")        # all subsequent logs show [CVD-TICK]
        set_context("PREDATOR-LOOP")
    """
    correlation_id_var.set(correlation_id)


def get_context() -> str:
    """Return the current correlation ID (or 'SYSTEM' if unset)."""
    return correlation_id_var.get()
