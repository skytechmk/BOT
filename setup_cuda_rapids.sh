#!/bin/bash

# CUDA Rapids Setup Script for RTX 3090
# This script will configure CUDA and Rapids for maximum performance

set -e  # Exit on any error

echo "🚀 Setting up CUDA Rapids for RTX 3090..."
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

# Check if running as root for some operations
check_sudo() {
    if [ "$EUID" -eq 0 ]; then
        print_warning "Running as root. Some operations may not work correctly."
    fi
}

# Step 1: Check system requirements
print_header "1. Checking System Requirements"

# Check for NVIDIA GPU
if ! command -v nvidia-smi &> /dev/null; then
    print_error "nvidia-smi not found. Please install NVIDIA drivers first."
    exit 1
fi

# Check GPU model
GPU_INFO=$(nvidia-smi --query-gpu=name --format=csv,noheader,nounits)
print_status "Detected GPU: $GPU_INFO"

if [[ ! "$GPU_INFO" == *"RTX 3090"* ]]; then
    print_warning "GPU is not RTX 3090. This script is optimized for RTX 3090."
fi

# Check CUDA version
if command -v nvcc &> /dev/null; then
    CUDA_VERSION=$(nvcc --version | grep "release" | awk '{print $6}' | cut -c2-)
    print_status "CUDA Version: $CUDA_VERSION"
else
    print_warning "CUDA compiler (nvcc) not found."
fi

# Check driver version
DRIVER_VERSION=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader,nounits)
print_status "Driver Version: $DRIVER_VERSION"

# Step 2: Check conda environment
print_header "2. Checking Conda Environment"

if ! command -v conda &> /dev/null; then
    print_error "Conda not found. Please install Anaconda or Miniconda first."
    exit 1
fi

# Check if environment exists
if conda env list | grep -q "binance-hunter-talib"; then
    print_status "Environment 'binance-hunter-talib' found."
else
    print_warning "Environment 'binance-hunter-talib' not found. Creating it..."
    conda env create -f environment.yml
fi

# Step 3: Activate environment and install CUDA packages
print_header "3. Installing CUDA and Rapids Packages"

# Activate environment
eval "$(conda shell.bash hook)"
conda activate binance-hunter-talib

print_status "Activated environment: $(conda info --envs | grep '*' | awk '{print $1}')"

# Install CUDA toolkit and libraries
print_status "Installing CUDA toolkit..."
conda install -y -c nvidia -c conda-forge \
    cuda-toolkit=11.8 \
    cuda-libraries=11.8 \
    cuda-libraries-dev=11.8 \
    cuda-nvcc=11.8 \
    cuda-runtime=11.8

# Install Rapids
print_status "Installing Rapids AI packages..."
conda install -y -c rapidsai -c nvidia -c conda-forge \
    cudf=23.12 \
    cuml=23.12 \
    cugraph=23.12 \
    cuspatial=23.12 \
    cupy=12.3.0 \
    rmm=23.12

# Install additional GPU-accelerated packages
print_status "Installing additional GPU packages..."
conda install -y -c conda-forge \
    numba \
    dask-cuda \
    ucx-py \
    ucx-proc=*=gpu

# Install PyTorch with CUDA support
print_status "Installing PyTorch with CUDA 11.8..."
conda install -y pytorch torchvision torchaudio pytorch-cuda=11.8 -c pytorch -c nvidia

# Install XGBoost with GPU support
print_status "Installing XGBoost with GPU support..."
pip install xgboost[gpu]

# Install LightGBM with GPU support
print_status "Installing LightGBM with GPU support..."
pip install lightgbm --config-settings=cmake.define.USE_GPU=ON

# Install CatBoost with GPU support
print_status "Installing CatBoost with GPU support..."
pip install catboost[gpu]

# Step 4: Configure environment variables
print_header "4. Configuring Environment Variables"

# Create CUDA environment configuration
cat > cuda_env_vars.sh << 'EOF'
#!/bin/bash
# CUDA Environment Variables for RTX 3090

# CUDA Configuration
export CUDA_HOME=/usr/local/cuda
export CUDA_ROOT=/usr/local/cuda
export PATH=$CUDA_HOME/bin:$PATH
export LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH

# CUDA Runtime Configuration
export CUDA_VISIBLE_DEVICES=0
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_LAUNCH_BLOCKING=0
export CUDA_CACHE_DISABLE=0

# Memory Management
export PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512
export CUPY_CACHE_DIR=/tmp/cupy_cache
export NUMBA_CUDA_DRIVER=/usr/lib/x86_64-linux-gnu/libcuda.so

# Performance Optimization
export OMP_NUM_THREADS=8
export MKL_NUM_THREADS=8
export NUMBA_NUM_THREADS=8

# Rapids Configuration
export RAPIDS_NO_INITIALIZE=1
export CUDF_SPILL=1
export CUML_GPU_MEMORY_LIMIT=20GB

# XGBoost GPU Configuration
export XGBOOST_GPU_ID=0

# LightGBM GPU Configuration
export LIGHTGBM_GPU=1

# CatBoost GPU Configuration
export CATBOOST_GPU_PLATFORM=CUDA
EOF

chmod +x cuda_env_vars.sh
print_status "Created CUDA environment variables script: cuda_env_vars.sh"

# Add to .bashrc if not already present
if ! grep -q "cuda_env_vars.sh" ~/.bashrc; then
    echo "# CUDA Rapids Configuration" >> ~/.bashrc
    echo "source $(pwd)/cuda_env_vars.sh" >> ~/.bashrc
    print_status "Added CUDA environment variables to ~/.bashrc"
fi

# Step 5: Create GPU monitoring script
print_header "5. Creating GPU Monitoring Tools"

cat > monitor_gpu_detailed.py << 'EOF'
#!/usr/bin/env python3
"""
Detailed GPU monitoring for RTX 3090 CUDA Rapids setup
"""

import time
import subprocess
import json
from datetime import datetime

def get_gpu_info():
    """Get detailed GPU information"""
    try:
        result = subprocess.run([
            'nvidia-smi', 
            '--query-gpu=name,temperature.gpu,utilization.gpu,utilization.memory,memory.used,memory.total,power.draw,clocks.gr,clocks.mem',
            '--format=csv,noheader,nounits'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            values = result.stdout.strip().split(', ')
            return {
                'name': values[0],
                'temperature': int(values[1]),
                'gpu_util': int(values[2]),
                'mem_util': int(values[3]),
                'mem_used': int(values[4]),
                'mem_total': int(values[5]),
                'power_draw': float(values[6]),
                'gpu_clock': int(values[7]),
                'mem_clock': int(values[8])
            }
    except Exception as e:
        print(f"Error getting GPU info: {e}")
    return None

def test_cuda_libraries():
    """Test CUDA library availability"""
    results = {}
    
    # Test PyTorch CUDA
    try:
        import torch
        results['pytorch'] = {
            'available': torch.cuda.is_available(),
            'version': torch.version.cuda,
            'device_count': torch.cuda.device_count(),
            'device_name': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
        }
    except ImportError:
        results['pytorch'] = {'available': False, 'error': 'Not installed'}
    
    # Test CuPy
    try:
        import cupy as cp
        results['cupy'] = {
            'available': True,
            'version': cp.__version__,
            'cuda_version': cp.cuda.runtime.runtimeGetVersion()
        }
    except ImportError:
        results['cupy'] = {'available': False, 'error': 'Not installed'}
    
    # Test Rapids cuDF
    try:
        import cudf
        results['cudf'] = {
            'available': True,
            'version': cudf.__version__
        }
    except ImportError:
        results['cudf'] = {'available': False, 'error': 'Not installed'}
    
    # Test Rapids cuML
    try:
        import cuml
        results['cuml'] = {
            'available': True,
            'version': cuml.__version__
        }
    except ImportError:
        results['cuml'] = {'available': False, 'error': 'Not installed'}
    
    # Test XGBoost GPU
    try:
        import xgboost as xgb
        results['xgboost'] = {
            'available': True,
            'version': xgb.__version__,
            'gpu_support': 'gpu_hist' in xgb.XGBClassifier()._get_type()
        }
    except ImportError:
        results['xgboost'] = {'available': False, 'error': 'Not installed'}
    
    return results

def main():
    print("🔥 RTX 3090 CUDA Rapids Monitoring")
    print("=" * 50)
    
    # Test CUDA libraries
    print("\n📚 CUDA Library Status:")
    cuda_results = test_cuda_libraries()
    for lib, info in cuda_results.items():
        status = "✅" if info.get('available', False) else "❌"
        print(f"{status} {lib.upper()}: {info}")
    
    print("\n🔄 Real-time GPU Monitoring (Press Ctrl+C to stop)")
    print("-" * 50)
    
    try:
        while True:
            gpu_info = get_gpu_info()
            if gpu_info:
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"\r[{timestamp}] "
                      f"Temp: {gpu_info['temperature']}°C | "
                      f"GPU: {gpu_info['gpu_util']}% | "
                      f"VRAM: {gpu_info['mem_used']}/{gpu_info['mem_total']}MB ({gpu_info['mem_util']}%) | "
                      f"Power: {gpu_info['power_draw']}W | "
                      f"Clocks: {gpu_info['gpu_clock']}/{gpu_info['mem_clock']}MHz", 
                      end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 Monitoring stopped.")

if __name__ == "__main__":
    main()
EOF

chmod +x monitor_gpu_detailed.py
print_status "Created detailed GPU monitoring script: monitor_gpu_detailed.py"

# Step 6: Create CUDA test script
print_header "6. Creating CUDA Test Script"

cat > test_cuda_rapids_complete.py << 'EOF'
#!/usr/bin/env python3
"""
Comprehensive CUDA Rapids test for RTX 3090
"""

import time
import numpy as np
import pandas as pd

def test_pytorch_cuda():
    """Test PyTorch CUDA functionality"""
    print("🔥 Testing PyTorch CUDA...")
    try:
        import torch
        
        if not torch.cuda.is_available():
            print("❌ CUDA not available in PyTorch")
            return False
        
        device = torch.device('cuda:0')
        print(f"✅ CUDA Device: {torch.cuda.get_device_name(0)}")
        print(f"✅ CUDA Version: {torch.version.cuda}")
        print(f"✅ GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
        
        # Performance test
        size = 10000
        start_time = time.time()
        
        a = torch.randn(size, size, device=device)
        b = torch.randn(size, size, device=device)
        c = torch.matmul(a, b)
        torch.cuda.synchronize()
        
        gpu_time = time.time() - start_time
        print(f"✅ GPU Matrix Multiplication ({size}x{size}): {gpu_time:.3f}s")
        
        return True
        
    except Exception as e:
        print(f"❌ PyTorch CUDA test failed: {e}")
        return False

def test_cupy():
    """Test CuPy functionality"""
    print("\n🐍 Testing CuPy...")
    try:
        import cupy as cp
        
        print(f"✅ CuPy Version: {cp.__version__}")
        print(f"✅ CUDA Runtime Version: {cp.cuda.runtime.runtimeGetVersion()}")
        
        # Performance test
        size = 10000
        start_time = time.time()
        
        a = cp.random.randn(size, size)
        b = cp.random.randn(size, size)
        c = cp.dot(a, b)
        cp.cuda.Stream.null.synchronize()
        
        gpu_time = time.time() - start_time
        print(f"✅ CuPy Matrix Multiplication ({size}x{size}): {gpu_time:.3f}s")
        
        return True
        
    except Exception as e:
        print(f"❌ CuPy test failed: {e}")
        return False

def test_cudf():
    """Test cuDF functionality"""
    print("\n📊 Testing cuDF...")
    try:
        import cudf
        
        print(f"✅ cuDF Version: {cudf.__version__}")
        
        # Create test DataFrame
        size = 1000000
        start_time = time.time()
        
        df = cudf.DataFrame({
            'a': np.random.randn(size),
            'b': np.random.randn(size),
            'c': np.random.randint(0, 100, size)
        })
        
        # Perform operations
        result = df.groupby('c').agg({'a': 'mean', 'b': 'sum'})
        
        gpu_time = time.time() - start_time
        print(f"✅ cuDF DataFrame Operations ({size} rows): {gpu_time:.3f}s")
        
        return True
        
    except Exception as e:
        print(f"❌ cuDF test failed: {e}")
        return False

def test_cuml():
    """Test cuML functionality"""
    print("\n🤖 Testing cuML...")
    try:
        import cuml
        from cuml.ensemble import RandomForestClassifier
        from cuml.datasets import make_classification
        
        print(f"✅ cuML Version: {cuml.__version__}")
        
        # Create test dataset
        start_time = time.time()
        
        X, y = make_classification(n_samples=100000, n_features=20, n_classes=2, random_state=42)
        
        # Train model
        model = RandomForestClassifier(n_estimators=100, random_state=42)
        model.fit(X, y)
        
        # Make predictions
        predictions = model.predict(X)
        
        gpu_time = time.time() - start_time
        print(f"✅ cuML Random Forest (100k samples, 20 features): {gpu_time:.3f}s")
        
        return True
        
    except Exception as e:
        print(f"❌ cuML test failed: {e}")
        return False

def test_xgboost_gpu():
    """Test XGBoost GPU functionality"""
    print("\n🚀 Testing XGBoost GPU...")
    try:
        import xgboost as xgb
        from sklearn.datasets import make_classification
        
        print(f"✅ XGBoost Version: {xgb.__version__}")
        
        # Create test dataset
        X, y = make_classification(n_samples=100000, n_features=20, n_classes=2, random_state=42)
        
        # Train with GPU
        start_time = time.time()
        
        model = xgb.XGBClassifier(
            tree_method='gpu_hist',
            gpu_id=0,
            n_estimators=100,
            random_state=42
        )
        model.fit(X, y)
        
        gpu_time = time.time() - start_time
        print(f"✅ XGBoost GPU Training (100k samples, 20 features): {gpu_time:.3f}s")
        
        return True
        
    except Exception as e:
        print(f"❌ XGBoost GPU test failed: {e}")
        return False

def test_lightgbm_gpu():
    """Test LightGBM GPU functionality"""
    print("\n💡 Testing LightGBM GPU...")
    try:
        import lightgbm as lgb
        from sklearn.datasets import make_classification
        
        print(f"✅ LightGBM Version: {lgb.__version__}")
        
        # Create test dataset
        X, y = make_classification(n_samples=100000, n_features=20, n_classes=2, random_state=42)
        
        # Train with GPU
        start_time = time.time()
        
        train_data = lgb.Dataset(X, label=y)
        params = {
            'objective': 'binary',
            'device': 'gpu',
            'gpu_platform_id': 0,
            'gpu_device_id': 0,
            'num_leaves': 31,
            'learning_rate': 0.1,
            'verbose': -1
        }
        
        model = lgb.train(params, train_data, num_boost_round=100)
        
        gpu_time = time.time() - start_time
        print(f"✅ LightGBM GPU Training (100k samples, 20 features): {gpu_time:.3f}s")
        
        return True
        
    except Exception as e:
        print(f"❌ LightGBM GPU test failed: {e}")
        return False

def main():
    print("🚀 RTX 3090 CUDA Rapids Comprehensive Test")
    print("=" * 50)
    
    tests = [
        test_pytorch_cuda,
        test_cupy,
        test_cudf,
        test_cuml,
        test_xgboost_gpu,
        test_lightgbm_gpu
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
    
    print(f"\n📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All CUDA Rapids tests passed! Your RTX 3090 is ready for maximum performance!")
    else:
        print("⚠️  Some tests failed. Check the error messages above for troubleshooting.")
    
    return passed == total

if __name__ == "__main__":
    main()
EOF

chmod +x test_cuda_rapids_complete.py
print_status "Created comprehensive CUDA test script: test_cuda_rapids_complete.py"

# Step 7: Create performance benchmark script
print_header "7. Creating Performance Benchmark"

cat > benchmark_rtx3090.py << 'EOF'
#!/usr/bin/env python3
"""
RTX 3090 Performance Benchmark for Trading ML
"""

import time
import numpy as np
import pandas as pd

def benchmark_cpu_vs_gpu():
    """Benchmark CPU vs GPU performance"""
    print("⚡ CPU vs GPU Performance Benchmark")
    print("=" * 40)
    
    # Test data size
    n_samples = 100000
    n_features = 50
    
    # Generate test data
    print(f"📊 Generating test data: {n_samples} samples, {n_features} features")
    X = np.random.randn(n_samples, n_features)
    y = np.random.randint(0, 2, n_samples)
    
    results = {}
    
    # XGBoost CPU vs GPU
    print("\n🚀 XGBoost Benchmark:")
    try:
        import xgboost as xgb
        
        # CPU training
        start_time = time.time()
        model_cpu = xgb.XGBClassifier(tree_method='hist', n_estimators=100, random_state=42)
        model_cpu.fit(X, y)
        cpu_time = time.time() - start_time
        
        # GPU training
        start_time = time.time()
        model_gpu = xgb.XGBClassifier(tree_method='gpu_hist', gpu_id=0, n_estimators=100, random_state=42)
        model_gpu.fit(X, y)
        gpu_time = time.time() - start_time
        
        speedup = cpu_time / gpu_time
        results['xgboost'] = {'cpu': cpu_time, 'gpu': gpu_time, 'speedup': speedup}
        
        print(f"  CPU Time: {cpu_time:.2f}s")
        print(f"  GPU Time: {gpu_time:.2f}s")
        print(f"  Speedup: {speedup:.2f}x")
        
    except Exception as e:
        print(f"  ❌ XGBoost benchmark failed: {e}")
    
    # PyTorch CPU vs GPU
    print("\n🔥 PyTorch Benchmark:")
    try:
        import torch
        import torch.nn as nn
        
        # Convert data to tensors
        X_tensor = torch.FloatTensor(X)
        y_tensor = torch.LongTensor(y)
        
        # Simple neural network
        class SimpleNN(nn.Module):
            def __init__(self, input_size):
                super().__init__()
                self.layers = nn.Sequential(
                    nn.Linear(input_size, 128),
                    nn.ReLU(),
                    nn.Linear(128, 64),
                    nn.ReLU(),
                    nn.Linear(64, 2)
                )
            
            def forward(self, x):
                return self.layers(x)
        
        # CPU training
        model_cpu = SimpleNN(n_features)
        optimizer_cpu = torch.optim.Adam(model_cpu.parameters())
        criterion = nn.CrossEntropyLoss()
        
        start_time = time.time()
        for epoch in range(10):
            optimizer_cpu.zero_grad()
            outputs = model_cpu(X_tensor)
            loss = criterion(outputs, y_tensor)
            loss.backward()
            optimizer_cpu.step()
        cpu_time = time.time() - start_time
        
        # GPU training
        if torch.cuda.is_available():
            device = torch.device('cuda:0')
            model_gpu = SimpleNN(n_features).to(device)
            optimizer_gpu = torch.optim.Adam(model_gpu.parameters())
            X_gpu = X_tensor.to(device)
            y_gpu = y_tensor.to(device)
            
            start_time = time.time()
            for epoch in range(10):
                optimizer_gpu.zero_grad()
                outputs = model_gpu(X_gpu)
                loss = criterion(outputs, y_gpu)
                loss.backward()
                optimizer_gpu.step()
            torch.cuda.synchronize()
            gpu_time = time.time() - start_time
            
            speedup = cpu_time / gpu_time
            results['pytorch'] = {'cpu': cpu_time, 'gpu': gpu_time, 'speedup': speedup}
            
            print(f"  CPU Time: {cpu_time:.2f}s")
            print(f"  GPU Time: {gpu_time:.2f}s")
            print(f"  Speedup: {speedup:.2f}x")
        else:
            print("  ❌ CUDA not available for PyTorch")
            
    except Exception as e:
        print(f"  ❌ PyTorch benchmark failed: {e}")
    
    # Summary
    print("\n📈 Performance Summary:")
    print("-" * 30)
    total_speedup = 0
    count = 0
    
    for framework, times in results.items():
        print(f"{framework.upper()}: {times['speedup']:.2f}x speedup")
        total_speedup += times['speedup']
        count += 1
    
    if count > 0:
        avg_speedup = total_speedup / count
        print(f"\nAverage GPU Speedup: {avg_speedup:.2f}x")
        
        if avg_speedup > 5:
            print("🎉 Excellent GPU performance!")
        elif avg_speedup > 2:
            print("✅ Good GPU performance!")
        else:
            print("⚠️  GPU performance could be improved.")
    
    return results

if __name__ == "__main__":
    benchmark_cpu_vs_gpu()
EOF

chmod +x benchmark_rtx3090.py
print_status "Created performance benchmark script: benchmark_rtx3090.py"

# Step 8: Final verification
print_header "8. Final Verification"

# Source environment variables
source cuda_env_vars.sh

# Test basic CUDA functionality
print_status "Testing basic CUDA functionality..."
python -c "
import torch
print(f'CUDA Available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU Name: {torch.cuda.get_device_name(0)}')
    print(f'GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB')
else:
    print('❌ CUDA not detected')
"

# Step 9: Create startup script
print_header "9. Creating Startup Script"

cat > start_trading_with_cuda.sh << 'EOF'
#!/bin/bash

# Startup script for CUDA-accelerated trading system

echo "🚀 Starting CUDA-accelerated Binance Hunter TA-Lib..."

# Load CUDA environment
source cuda_env_vars.sh

# Activate conda environment
eval "$(conda shell.bash hook)"
conda activate binance-hunter-talib

# Check CUDA status
echo "🔍 Checking CUDA status..."
python -c "
import torch
print(f'CUDA Available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB')
"

# Start GPU monitoring in background
echo "📊 Starting GPU monitoring..."
python monitor_gpu_detailed.py &
MONITOR_PID=$!

# Start trading system
echo "💰 Starting trading system..."
python main.py

# Cleanup
kill $MONITOR_PID 2>/dev/null
echo "👋 Trading system stopped."
EOF

chmod +x start_trading_with_cuda.sh
print_status "Created startup script: start_trading_with_cuda.sh"

# Final instructions
print_header "Setup Complete!"
echo ""
print_status "CUDA Rapids setup completed successfully!"
echo ""
echo "📋 Next Steps:"
echo "1. Restart your terminal or run: source ~/.bashrc"
echo "2. Test CUDA functionality: ./test_cuda_rapids_complete.py"
echo "3. Run performance benchmark: ./benchmark_rtx3090.py"
echo "4. Monitor GPU usage: ./monitor_gpu_detailed.py"
echo "5. Start trading with CUDA: ./start_trading_with_cuda.sh"
echo ""
echo "🔧 Configuration Files Created:"
echo "- cuda_env_vars.sh (environment variables)"
echo "- test_cuda_rapids_complete.py (comprehensive testing)"
echo "- monitor_gpu_detailed.py (GPU monitoring)"
echo "- benchmark_rtx3090.py (performance testing)"
echo "- start_trading_with_cuda.sh (startup script)"
echo ""
print_status "Your RTX 3090 is now configured for maximum CUDA Rapids performance! 🚀"
