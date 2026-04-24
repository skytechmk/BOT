import os
from datetime import datetime, timezone

# API Configuration
TOP_PAIRS_COUNT = 1000  # No effective cap — fetch all available USDT perp pairs
RATE_LIMIT = 1200
REQUESTS_PER_SECOND = RATE_LIMIT / 60

# File Paths
LOG_FILE = "debug_log10.txt"
SIGNAL_REGISTRY_FILE = "signal_registry.json"
CORNIX_SIGNALS_FILE = "cornix_signals.json"
SIGNAL_PERFORMANCE_FILE = "signal_performance.json"
OPEN_SIGNALS_FILE = "open_signals.json"
TRADE_MONITOR_FILE = "trade_monitor.json"
LEARNING_INSIGHTS_FILE = "learning_insights.json"
SIGNAL_CACHE_FILE = "signal_cache.json"

# Permanent manual blacklist — pairs that must never generate signals
MANUAL_BLACKLIST = {
    'MATICUSDT',   # Deprecated — rebranded to POL; confuses users with Polygon
}

# Limits & Thresholds
MAX_DAILY_SIGNALS = 150
MAX_OPEN_SIGNALS = 20
SIGNAL_CHECK_INTERVAL = 60
SIGNAL_CACHE_TTL = 3600  # 1 hour

# Monitoring Configuration
REALTIME_MONITOR_INTERVAL = 5
ENTRY_ZONE_SCAN_INTERVAL = 30
MARKET_SCAN_INTERVAL = 300
PRIMARY_TIMEFRAME = '4h'
INTERMEDIATE_TIMEFRAME = '1h'
ENTRY_TIMEFRAMES = ['15m', '5m']
MONITORING_TIMEFRAME = '1m'

# ML & AI Config
TRANSFORMER_MODEL_NAME = "distilbert-base-uncased"
OLLAMA_ANALYSIS_INTERVAL = 21600  # 6 hours
RETRAIN_INTERVAL = 86400  # 24 hours
