#!/usr/bin/env python3
"""
GPU Usage Test Script
Tests if PyTorch can detect and use your GPU
"""

import sys
import time

def test_gpu_availability():
    """Test GPU availability and usage"""
    print("🔍 Testing GPU Availability...")
    print("=" * 50)
    
    try:
        import torch
        print(f"✅ PyTorch version: {torch.__version__}")
        
        # Check CUDA availability
        cuda_available = torch.cuda.is_available()
        print(f"🚀 CUDA Available: {cuda_available}")
        
        if cuda_available:
            device_count = torch.cuda.device_count()
            print(f"📊 GPU Device Count: {device_count}")
            
            for i in range(device_count):
                device_name = torch.cuda.get_device_name(i)
                memory_total = torch.cuda.get_device_properties(i).total_memory / 1024**3
                print(f"🎯 GPU {i}: {device_name}")
                print(f"💾 Total Memory: {memory_total:.2f} GB")
                
                # Test GPU usage
                print(f"\n🧪 Testing GPU {i} usage...")
                device = torch.device(f'cuda:{i}')
                
                # Create test tensors
                print("   Creating test tensors...")
                x = torch.randn(1000, 1000, device=device)
                y = torch.randn(1000, 1000, device=device)
                
                # Perform computation
                print("   Performing matrix multiplication...")
                start_time = time.time()
                z = torch.matmul(x, y)
                torch.cuda.synchronize()  # Wait for GPU to finish
                end_time = time.time()
                
                print(f"   ✅ Computation completed in {end_time - start_time:.4f} seconds")
                
                # Check memory usage
                memory_allocated = torch.cuda.memory_allocated(i) / 1024**3
                memory_cached = torch.cuda.memory_reserved(i) / 1024**3
                print(f"   📊 Memory Allocated: {memory_allocated:.2f} GB")
                print(f"   💾 Memory Cached: {memory_cached:.2f} GB")
                
                # Clear memory
                del x, y, z
                torch.cuda.empty_cache()
                print("   🧹 GPU memory cleared")
                
        else:
            print("❌ CUDA not available. Possible reasons:")
            print("   - NVIDIA GPU not detected")
            print("   - CUDA drivers not installed")
            print("   - PyTorch not compiled with CUDA support")
            
            # Test CPU performance for comparison
            print("\n🖥️ Testing CPU performance...")
            device = torch.device('cpu')
            x = torch.randn(1000, 1000, device=device)
            y = torch.randn(1000, 1000, device=device)
            
            start_time = time.time()
            z = torch.matmul(x, y)
            end_time = time.time()
            
            print(f"   CPU computation time: {end_time - start_time:.4f} seconds")
            
    except ImportError:
        print("❌ PyTorch not installed!")
        print("   Install PyTorch with: pip install torch")
        return False
    except Exception as e:
        print(f"❌ Error during GPU test: {e}")
        return False
    
    return cuda_available

def test_transformers_gpu():
    """Test if transformers can use GPU"""
    print("\n" + "=" * 50)
    print("🤖 Testing Transformers GPU Usage...")
    
    try:
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification
        
        if not torch.cuda.is_available():
            print("⚠️ CUDA not available, skipping transformers GPU test")
            return False
        
        device = torch.device('cuda')
        print(f"🎯 Using device: {device}")
        
        # Load a small model for testing
        model_name = "distilbert-base-uncased"
        print(f"📥 Loading model: {model_name}")
        
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=2)
        
        # Move model to GPU
        print("🚀 Moving model to GPU...")
        model.to(device)
        
        # Test inference
        print("🧪 Testing inference...")
        test_text = "The market is showing bullish signals with strong volume."
        inputs = tokenizer(test_text, return_tensors="pt", padding=True, truncation=True)
        
        # Move inputs to GPU
        inputs = {k: v.to(device) for k, v in inputs.items()}
        
        # Perform inference
        start_time = time.time()
        with torch.no_grad():
            outputs = model(**inputs)
        torch.cuda.synchronize()
        end_time = time.time()
        
        print(f"✅ GPU inference completed in {end_time - start_time:.4f} seconds")
        print(f"📊 Output shape: {outputs.logits.shape}")
        
        # Check GPU memory usage
        memory_allocated = torch.cuda.memory_allocated() / 1024**3
        print(f"💾 GPU Memory Used: {memory_allocated:.2f} GB")
        
        # Clean up
        del model, inputs, outputs
        torch.cuda.empty_cache()
        print("🧹 GPU memory cleared")
        
        return True
        
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        return False
    except Exception as e:
        print(f"❌ Error during transformers GPU test: {e}")
        return False

def main():
    """Main test function"""
    print("🚀 GPU Usage Test for Binance Hunter Bot")
    print("=" * 60)
    
    # Test basic GPU availability
    gpu_available = test_gpu_availability()
    
    # Test transformers GPU usage
    if gpu_available:
        transformers_gpu = test_transformers_gpu()
    else:
        transformers_gpu = False
    
    # Summary
    print("\n" + "=" * 60)
    print("📋 TEST SUMMARY")
    print("=" * 60)
    print(f"🚀 GPU Available: {'✅ YES' if gpu_available else '❌ NO'}")
    print(f"🤖 Transformers GPU: {'✅ YES' if transformers_gpu else '❌ NO'}")
    
    if gpu_available and transformers_gpu:
        print("\n🎉 SUCCESS: Your GPU is working correctly!")
        print("   The Binance Hunter Bot will use GPU acceleration.")
    elif gpu_available:
        print("\n⚠️ PARTIAL: GPU detected but transformers test failed.")
        print("   Check transformers installation.")
    else:
        print("\n❌ FAILED: No GPU detected or CUDA not available.")
        print("   The bot will run on CPU (slower performance).")
    
    print("\n💡 Tips:")
    print("   - Make sure NVIDIA drivers are installed")
    print("   - Install CUDA toolkit if not present")
    print("   - Install PyTorch with CUDA support:")
    print("     pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118")

if __name__ == "__main__":
    main()
