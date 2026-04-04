#!/usr/bin/env python3
"""
Test script to verify conda environment setup for Binance Hunter TA-Lib
"""

import sys
import importlib

def test_import(module_name, package_name=None):
    """Test if a module can be imported"""
    try:
        importlib.import_module(module_name)
        print(f"✅ {package_name or module_name}")
        return True
    except ImportError as e:
        print(f"❌ {package_name or module_name}: {e}")
        return False

def main():
    print("🧪 Testing Binance Hunter TA-Lib Conda Environment")
    print("=" * 50)
    
    # Core dependencies
    print("\n📦 Core Dependencies:")
    core_tests = [
        ("pandas", "pandas"),
        ("numpy", "numpy"),
        ("scipy", "scipy"),
        ("sklearn", "scikit-learn"),
        ("xgboost", "xgboost"),
        ("joblib", "joblib"),
    ]
    
    core_passed = sum(test_import(module, package) for module, package in core_tests)
    
    # Trading dependencies
    print("\n💰 Trading Dependencies:")
    trading_tests = [
        ("binance", "python-binance"),
        ("ccxt", "ccxt"),
    ]
    
    trading_passed = sum(test_import(module, package) for module, package in trading_tests)
    
    # Technical Analysis
    print("\n📈 Technical Analysis:")
    ta_tests = [
        ("talib", "TA-Lib"),
    ]
    
    ta_passed = sum(test_import(module, package) for module, package in ta_tests)
    
    # Machine Learning
    print("\n🤖 Machine Learning:")
    ml_tests = [
        ("torch", "pytorch"),
        ("transformers", "transformers"),
        ("lightgbm", "lightgbm"),
        ("catboost", "catboost"),
    ]
    
    ml_passed = sum(test_import(module, package) for module, package in ml_tests)
    
    # Communication
    print("\n📱 Communication:")
    comm_tests = [
        ("telegram", "python-telegram-bot"),
        ("requests", "requests"),
        ("aiohttp", "aiohttp"),
    ]
    
    comm_passed = sum(test_import(module, package) for module, package in comm_tests)
    
    # Optional dependencies
    print("\n🔧 Optional Dependencies:")
    optional_tests = [
        ("arch", "arch"),
        ("rich", "rich"),
        ("tqdm", "tqdm"),
        ("dotenv", "python-dotenv"),
    ]
    
    optional_passed = sum(test_import(module, package) for module, package in optional_tests)
    
    # Summary
    total_tests = len(core_tests) + len(trading_tests) + len(ta_tests) + len(ml_tests) + len(comm_tests) + len(optional_tests)
    total_passed = core_passed + trading_passed + ta_passed + ml_passed + comm_passed + optional_passed
    
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {total_passed}/{total_tests} packages imported successfully")
    
    if total_passed == total_tests:
        print("🎉 All dependencies are working correctly!")
        print("✅ Your conda environment is ready for trading!")
        return 0
    elif core_passed == len(core_tests) and trading_passed == len(trading_tests) and ta_passed == len(ta_tests):
        print("⚠️  Core trading functionality is working, but some optional packages failed.")
        print("✅ You can still run the trading system!")
        return 0
    else:
        print("❌ Critical dependencies are missing. Please check your installation.")
        print("\n🔧 Troubleshooting:")
        print("1. Make sure you activated the conda environment:")
        print("   conda activate binance-hunter-talib")
        print("2. Try reinstalling the environment:")
        print("   conda env remove -n binance-hunter-talib")
        print("   conda env create -f environment.yml")
        print("3. For TA-Lib issues, try:")
        print("   conda install -c conda-forge ta-lib")
        return 1

if __name__ == "__main__":
    sys.exit(main())
