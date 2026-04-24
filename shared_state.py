import os
import torch
from datetime import datetime, timezone
from binance.client import Client
from dotenv import load_dotenv
from utils_logger import log_message
from constants import *

# Advanced Strategic Utilities
from trading_utilities import (
    CircuitBreaker, PairCooldownManager, AutoBlacklist, 
    DynamicConfidenceThreshold, 
    PortfolioCorrelationManager, 
    RegimePositionSizer, 
    check_gpu_availability
)
from macro_risk_engine import MacroRiskEngine
from openrouter_intelligence import OpenRouterIntelligence

# Global instances that need to be shared
load_dotenv()

# Rust Core integration (separate module to avoid circular imports)
from rust_integration import RUST_CORE_AVAILABLE, RUST_CORE_VERSION

API_KEY = os.getenv('BINANCE_API_KEY')
API_SECRET = os.getenv('BINANCE_API_SECRET')
client = Client(API_KEY, API_SECRET, requests_params={"timeout": 30})

# Proxy pool + connection pool (Webshare rotating proxy when PROXY_ENABLED=true)
from proxy_config import configure_session as _configure_session
_configure_session(client.session, pool_connections=30, pool_maxsize=30)

GPU_INFO = check_gpu_availability()
device = torch.device('cuda' if GPU_INFO['available'] else 'cpu')

CIRCUIT_BREAKER = CircuitBreaker()
PAIR_COOLDOWN = PairCooldownManager(cooldown_hours=2)
AUTO_BLACKLIST = AutoBlacklist(max_consecutive_losses=2, blacklist_hours=24)
DYNAMIC_THRESHOLD = DynamicConfidenceThreshold(max_daily_signals=90)
MACRO_RISK_ENGINE = MacroRiskEngine()
OPENROUTER_INTEL = OpenRouterIntelligence() # Updated instance name
DEEPSEEK_INTEL = OPENROUTER_INTEL # Legacy alias for compatibility
OPENROUTER_AVAILABLE = OPENROUTER_INTEL.api_key is not None

PORTFOLIO_MANAGER = PortfolioCorrelationManager(max_correlated_exposure=0.3)
REGIME_SIZER = RegimePositionSizer()

# AI & Institutional Intelligence (Modular Loading)
try:
    from smart_money_analyzer import SmartMoneyAnalyzer
    SMART_MONEY_ANALYZER = SmartMoneyAnalyzer()
    SMART_MONEY_AVAILABLE = True
except ImportError:
    SMART_MONEY_ANALYZER = None
    SMART_MONEY_AVAILABLE = False
except Exception as e:
    log_message(f"Error loading SmartMoneyAnalyzer: {e}")
    SMART_MONEY_ANALYZER = None
    SMART_MONEY_AVAILABLE = False

try:
    from institutional_ml_system import initialize_institutional_ml, get_institutional_prediction
    INSTITUTIONAL_ML_AVAILABLE = True
except ImportError:
    INSTITUTIONAL_ML_AVAILABLE = False
except Exception as e:
    log_message(f"Error loading InstitutionalML: {e}")
    INSTITUTIONAL_ML_AVAILABLE = False

# Global Signal Trackers
from signal_registry_db import SignalRegistryDB, SignalRegistryProxy

try:
    _db = SignalRegistryDB()
    SIGNAL_REGISTRY = SignalRegistryProxy(_db)
except Exception as e:
    import logging
    logging.getLogger("aladdin").error(f"Error starting SQLite Registry: {e}")
    SIGNAL_REGISTRY = {}
CORNIX_SIGNALS = {}
PERFORMANCE_HISTORY = {}
OPEN_SIGNALS_TRACKER = {}
ACTIVE_TRADES_MONITOR = {}
LEARNING_INSIGHTS = {}
SIGNAL_CACHE = {}
DAILY_SIGNAL_COUNTER = {'count': 0, 'date': datetime.now(timezone.utc).date()}

# High-Level Availability Flags (Consolidated)
try:
    from ollama_analysis import analyze_top_pairs_with_ollama
    OLLAMA_AVAILABLE = True
except ImportError: OLLAMA_AVAILABLE = False

try:
    from multi_timeframe_ml_system import get_multi_timeframe_prediction
    MULTI_TF_ML_AVAILABLE = True
except ImportError: MULTI_TF_ML_AVAILABLE = False

# RealTimeSignalMonitor disabled — caused Telegram floods on restart.
# Signal closures handled by _reconcile_sent_signals in performance_tracker.
try:
    from enhanced_websocket_monitor import RealTimeSignalMonitor
except ImportError:
    RealTimeSignalMonitor = None
WEBSOCKET_MONITOR_AVAILABLE = False

ENHANCED_CACHE_AVAILABLE = False # Default unless specified


# AUTO-AUDIT TRIGGER
try:
    from ai_audit_interface import quick_security_scan
    print("🔍 AUDIT TOOLS AVAILABLE IN shared_state")
except:
    pass
