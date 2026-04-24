import os
import sys
import logging
import warnings
from datetime import datetime
from logging.handlers import RotatingFileHandler

# Suppress urllib3 connection pool warnings — non-critical noise during parallel pair scanning
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message="Connection pool is full")

LOG_FILE = "debug_log10.txt"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
BACKUP_COUNT = 5

# Configure root logger
logger = logging.getLogger("aladdin")
logger.setLevel(logging.DEBUG)

# Level mapping for backward compatibility
LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL
}

# Apply environment variable log level to console handler
env_log_level = os.environ.get("ALADDIN_LOG_LEVEL", "INFO").upper()
if not logger.handlers:
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(LEVEL_MAP.get(env_log_level, logging.INFO))
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # Rotating file handler (always DEBUG)
    file_handler = RotatingFileHandler(
        LOG_FILE, 
        maxBytes=MAX_BYTES, 
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

def log_message(message, level="INFO"):
    """Log a message with the specified level. Backward compatible with existing code."""
    log_level = LEVEL_MAP.get(level.upper(), logging.INFO)
    logger.log(log_level, message)

def clear_console():
    """Clear the console screen"""
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Aladdin Logger initialized (Console: {env_log_level}, File: DEBUG)")
