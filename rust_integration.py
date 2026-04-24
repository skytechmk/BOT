"""
Rust Core Integration Module
Handles availability checks and version compatibility for the Aladdin Rust Core
"""

import os
from utils_logger import log_message

# Rust Core availability check with version compatibility
RUST_CORE_AVAILABLE = False
RUST_CORE_VERSION = None
EXPECTED_RUST_VERSION = "0.2.0"  # Keep in sync with Cargo.toml

try:
    import aladdin_core
    # Check version compatibility
    rust_version = aladdin_core.get_rust_version()
    if rust_version == EXPECTED_RUST_VERSION:
        RUST_CORE_AVAILABLE = True
        RUST_CORE_VERSION = rust_version
        log_message(f"✅ Aladdin Rust Core v{rust_version} loaded successfully")
    else:
        log_message(f"⚠️ Rust Core version mismatch: got {rust_version}, expected {EXPECTED_RUST_VERSION}")
        log_message("Please rebuild Rust core with: ./build_rust.sh")
except ImportError:
    log_message("⚠️ Aladdin Rust Core not available - falling back to Python implementations")
except Exception as e:
    log_message(f"⚠️ Error checking Rust Core version: {e}")
