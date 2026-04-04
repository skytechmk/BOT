import os
import sys
import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler

LOG_FILE = "debug_log10.txt"
MAX_BYTES = 50 * 1024 * 1024  # 50 MB per file
BACKUP_COUNT = 5

# Configure root logger
logger = logging.getLogger("aladdin")
logger.setLevel(logging.DEBUG)

# Prevent duplicate handlers if module is reloaded
if not logger.handlers:
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # Rotating file handler
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

# Level mapping for backward compatibility
LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL
}

def log_message(message, level="INFO"):
    """Log a message with the specified level. Backward compatible with existing code."""
    log_level = LEVEL_MAP.get(level.upper(), logging.INFO)
    logger.log(log_level, message)

def clear_console():
    """Clear the console screen"""
    os.system('cls' if os.name == 'nt' else 'clear')
