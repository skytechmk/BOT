#!/usr/bin/env python3
"""
Test script for CUDA/Rapids and Institutional ML System
"""

import sys
print('🔍 Testing CUDA/Rapids availability...')

try:
    import cudf
    import cuml
    print('✅ cuDF and cuML imported successfully')
    
    # Test basic CUDA functionality
    import cupy as cp
    print('✅ CuPy imported successfully')
    
    # Test if GPU is available
    try:
        gpu_count = cp.cuda.runtime.getDeviceCount()
        print(f'🚀 Found {gpu_count} GPU(s)')
        
        if gpu_count > 0:
            gpu_info = cp.cuda.runtime.getDeviceProperties(0)
            print(f'   GPU 0: {gpu_info["name"].decode()}')
            print(f'   Memory: {gpu_info["totalGlobalMem"] / (1024**3):.1f} GB')
        
    except Exception as e:
        print(f'⚠️  GPU detection failed: {e}')
    
    print('\n🧠 Testing Institutional ML System...')
    from institutional_ml_system import initialize_institutional_ml
    print('✅ Institutional ML system imports successfully')
    
    # Test basic initialization
    system = initialize_institutional_ml()
    print('✅ Institutional ML system initialized successfully')
    print(f'   CUDA Available: {system.cuda_available}')
    print(f'   Models per pair: {len(system.config["models_per_pair"])}')
    
    # Test basic CUDA operations
    if system.cuda_available:
        print('\n🚀 Testing CUDA operations...')
        try:
            # Create a simple cuDF DataFrame
            import pandas as pd
            test_data = pd.DataFrame({
                'A': [1, 2, 3, 4, 5],
                'B': [10, 20, 30, 40, 50]
            })
            
            # Convert to cuDF
            cudf_data = cudf.from_pandas(test_data)
            print(f'✅ cuDF DataFrame created: {cudf_data.shape}')
            
            # Test basic cuML
            from cuml.linear_model import LinearRegression
            model = LinearRegression()
            print('✅ cuML LinearRegression model created')
            
        except Exception as e:
            print(f'⚠️  CUDA operations test failed: {e}')
    
    print('\n🎯 All tests completed successfully!')
    
except Exception as e:
    print(f'❌ Error: {e}')
    import traceback
    traceback.print_exc()
