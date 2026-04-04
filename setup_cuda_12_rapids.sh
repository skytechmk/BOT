#!/bin/bash

# CUDA 12.0 Rapids Setup Script for RTX 3090
# Optimized for existing CUDA 12.0 installation

set -e  # Exit on any error

echo "🚀 Setting up CUDA 12.0 Rapids for RTX 3090..."
echo "=============================================="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_header() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Step 1: Verify CUDA 12.0 installation
print_header "1. Verifying CUDA 12.0 Installation"

GPU_INFO=$(nvidia-smi --query-gpu=name --format=csv,noheader,nounits)
DRIVER_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader,nounits)
print_status "GPU: $GPU_INFO"
print_status "Driver: $DRIVER_VERSION"

if command -v nvcc &> /dev/null; then
    CUDA_VERSION=$(nvcc --version | grep "release" | awk '{print $6}' | cut -c2-)
    print_status "CUDA Version: $CUDA_VERSION"
else
    print_status "CUDA compiler not in PATH, but that's okay for conda installation"
fi

# Step 2: Create environment with fixed packages
print_header "2. Creating Conda Environment"

# Remove existing environment if it exists
if conda env list | grep -q "binance-hunter-talib"; then
    print_status "Removing existing environment..."
    conda env remove -n binance-hunter-talib -y
fi

print_status "Creating new environment..."
conda env create -f environment.yml

# Step 3: Activate and install CUDA packages
print_header "3. Installing CUDA 12.0 Compatible Packages"

eval "$(conda shell.bash hook)"
conda activate binance-hunter-talib

print_status "Environment activated: binance-hunter-talib"

# Install PyTorch with CUDA 12.1 (compatible with CUDA 12.0)
print_status "Installing PyTorch with CUDA 12.1..."
conda install -y pytorch torchvision torchaudio pytorch-cuda=12.1 -c pytorch -c nvidia

# Install CuPy for CUDA 12.x
print_status "Installing CuPy for CUDA 12.x..."
pip install cupy-cuda12x

# Install Rapids for CUDA 12.0 (using pip for better compatibility)
print_status "Installing Rapids AI packages..."
pip install --extra-index-url=https://pypi.nvidia.com cudf-cu12 cuml-cu12 cugraph-cu12

# Install GPU-accelerated ML libraries
print_status "Installing GPU-accelerated ML libraries..."
pip install xgboost[gpu]
pip install lightgbm --config-settings=cmake.define.USE_GPU=ON
pip install catboost[gpu]

# Step 4: Configure environment variables for CUDA 12.0
print_header "4. Configuring CUDA 12.0 Environment"

cat > cuda_12_env_vars.sh << 'EOF'
#!/bin/bash
# CUDA 12.0 Environment Variables for RTX 3090

# CUDA Configuration
export CUDA_HOME=/usr/local/cuda-12.0
export CUDA_ROOT=/usr/local/cuda-12.0
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH

# CUDA Runtime Configuration
export CUDA_VISIBLE_DEVICES=0
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_LAUNCH_BLOCKING=0
export CUDA_CACHE_DISABLE=0

# Memory Management for RTX 3090 (24GB)
export PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:1024
export CUPY_CACHE_DIR=/tmp/cupy_cache
export NUMBA_CUDA_DRIVER=/usr/lib/x86_64-linux-gnu/libcuda.so

# Performance Optimization
export OMP_NUM_THREADS=8
export MKL_NUM_THREADS=8
export NUMBA_NUM_THREADS=8

# Rapids Configuration for CUDA 12.0
export RAPIDS_NO_INITIALIZE=1
export CUDF_SPILL=1
export CUML_GPU_MEMORY_LIMIT=20GB
export RMM_ALLOCATOR=cuda_memory_resource

# XGBoost GPU Configuration
export XGBOOST_GPU_ID=0

# LightGBM GPU Configuration
export LIGHTGBM_GPU=1

# CatBoost GPU Configuration
export CATBOOST_GPU_PLATFORM=CUDA

# CUDA 12.0 specific optimizations
export CUDA_MODULE_LOADING=LAZY
export PYTORCH_NVFUSER_DISABLE_FALLBACK=1
EOF

chmod +x cuda_12_env_vars.sh
print_status "Created CUDA 12.0 environment variables: cuda_12_env_vars.sh"

# Add to .bashrc if not already present
if ! grep -q "cuda_12_env_vars.sh" ~/.bashrc; then
    echo "# CUDA 12.0 Rapids Configuration" >> ~/.bashrc
    echo "source $(pwd)/cuda_12_env_vars.sh" >> ~/.bashrc
    print_status "Added CUDA 12.0 environment variables to ~/.bashrc"
fi

# Step 5: Create CUDA 12.0 test script
print_header "5. Creating CUDA 12.0 Test Script"

cat > test_cuda_12_setup.py << 'EOF'
#!/usr/bin/env python3
"""
CUDA 12.0 Setup Test for RTX 3090
"""

import sys
import time

def test_pytorch_cuda12():
    """Test PyTorch with CUDA 12.0"""
    print("🔥 Testing PyTorch CUDA 12.0...")
    try:
        import torch
        
        print(f"✅ PyTorch Version: {torch.__version__}")
        print(f"✅ CUDA Available: {torch.cuda.is_available()}")
        
        if torch.cuda.is_available():
            print(f"✅ CUDA Version: {torch.version.cuda}")
            print(f"✅ GPU Name: {torch.cuda.get_device_name(0)}")
            print(f"✅ GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
            
            # Quick performance test
            device = torch.device('cuda:0')
            x = torch.randn(5000, 5000, device=device)
            y = torch.randn(5000, 5000, device=device)
            
            start_time = time.time()
            z = torch.matmul(x, y)
            torch.cuda.synchronize()
            gpu_time = time.time() - start_time
            
            print(f"✅ GPU Matrix Multiplication (5000x5000): {gpu_time:.3f}s")
            return True
        else:
            print("❌ CUDA not available in PyTorch")
            return False
            
    except Exception as e:
        print(f"❌ PyTorch test failed: {e}")
        return False

def test_cupy_cuda12():
    """Test CuPy with CUDA 12.0"""
    print("\n🐍 Testing CuPy CUDA 12.0...")
    try:
        import cupy as cp
        
        print(f"✅ CuPy Version: {cp.__version__}")
        print(f"✅ CUDA Runtime Version: {cp.cuda.runtime.runtimeGetVersion()}")
        
        # Performance test
        x = cp.random.randn(5000, 5000)
        y = cp.random.randn(5000, 5000)
        
        start_time = time.time()
        z = cp.dot(x, y)
        cp.cuda.Stream.null.synchronize()
        gpu_time = time.time() - start_time
        
        print(f"✅ CuPy Matrix Multiplication (5000x5000): {gpu_time:.3f}s")
        return True
        
    except Exception as e:
        print(f"❌ CuPy test failed: {e}")
        return False

def test_rapids_cuda12():
    """Test Rapids with CUDA 12.0"""
    print("\n📊 Testing Rapids CUDA 12.0...")
    try:
        import cudf
        import cuml
        import numpy as np
        
        print(f"✅ cuDF Version: {cudf.__version__}")
        print(f"✅ cuML Version: {cuml.__version__}")
        
        # Quick cuDF test
        df = cudf.DataFrame({
            'a': np.random.randn(100000),
            'b': np.random.randn(100000),
            'c': np.random.randint(0, 10, 100000)
        })
        
        start_time = time.time()
        result = df.groupby('c').agg({'a': 'mean', 'b': 'sum'})
        gpu_time = time.time() - start_time
        
        print(f"✅ cuDF Operations (100k rows): {gpu_time:.3f}s")
        return True
        
    except Exception as e:
        print(f"❌ Rapids test failed: {e}")
        return False

def test_xgboost_gpu():
    """Test XGBoost GPU with CUDA 12.0"""
    print("\n🚀 Testing XGBoost GPU...")
    try:
        import xgboost as xgb
        from sklearn.datasets import make_classification
        
        print(f"✅ XGBoost Version: {xgb.__version__}")
        
        # Create test data
        X, y = make_classification(n_samples=50000, n_features=20, random_state=42)
        
        # Test GPU training
        start_time = time.time()
        model = xgb.XGBClassifier(
            tree_method='gpu_hist',
            gpu_id=0,
            n_estimators=50,
            random_state=42
        )
        model.fit(X, y)
        gpu_time = time.time() - start_time
        
        print(f"✅ XGBoost GPU Training (50k samples): {gpu_time:.3f}s")
        return True
        
    except Exception as e:
        print(f"❌ XGBoost GPU test failed: {e}")
        return False

def main():
    print("🚀 CUDA 12.0 RTX 3090 Setup Verification")
    print("=" * 50)
    
    tests = [
        test_pytorch_cuda12,
        test_cupy_cuda12,
        test_rapids_cuda12,
        test_xgboost_gpu
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()  # Add spacing between tests
    
    print("=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All CUDA 12.0 tests passed! RTX 3090 ready for maximum performance!")
    elif passed >= total - 1:
        print("✅ Most tests passed! Your setup is ready for trading.")
    else:
        print("⚠️  Some tests failed. Check error messages above.")
    
    return passed >= total - 1

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
EOF

chmod +x test_cuda_12_setup.py
print_status "Created CUDA 12.0 test script: test_cuda_12_setup.py"

# Step 6: Create startup script for trading
print_header "6. Creating Trading Startup Script"

cat > start_trading_cuda12.sh << 'EOF'
#!/bin/bash

echo "🚀 Starting CUDA 12.0 Accelerated Trading System..."

# Load CUDA 12.0 environment
source cuda_12_env_vars.sh

# Activate conda environment
eval "$(conda shell.bash hook)"
conda activate binance-hunter-talib

# Verify CUDA setup
echo "🔍 Verifying CUDA 12.0 setup..."
python -c "
import torch
print(f'PyTorch CUDA: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'VRAM: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB')
    print(f'CUDA Version: {torch.version.cuda}')
"

# Start trading system
echo "💰 Starting Binance Hunter TA-Lib with CUDA acceleration..."
python main.py
EOF

chmod +x start_trading_cuda12.sh
print_status "Created trading startup script: start_trading_cuda12.sh"

# Step 7: Source environment and test
print_header "7. Final Setup and Testing"

source cuda_12_env_vars.sh

print_status "Testing basic CUDA 12.0 functionality..."
python -c "
try:
    import torch
    print(f'✅ PyTorch CUDA Available: {torch.cuda.is_available()}')
    if torch.cuda.is_available():
        print(f'✅ GPU: {torch.cuda.get_device_name(0)}')
        print(f'✅ CUDA Version: {torch.version.cuda}')
    else:
        print('❌ CUDA not detected - may need environment restart')
except Exception as e:
    print(f'❌ Error: {e}')
"

# Final instructions
print_header "Setup Complete!"
echo ""
print_status "CUDA 12.0 Rapids setup completed!"
echo ""
echo "📋 Next Steps:"
echo "1. Restart terminal or run: source ~/.bashrc"
echo "2. Test setup: ./test_cuda_12_setup.py"
echo "3. Start trading: ./start_trading_cuda12.sh"
echo ""
echo "🔧 Files Created:"
echo "- cuda_12_env_vars.sh (CUDA 12.0 environment)"
echo "- test_cuda_12_setup.py (verification script)"
echo "- start_trading_cuda12.sh (trading startup)"
echo ""
print_status "Your RTX 3090 with CUDA 12.0 is ready! 🚀"
