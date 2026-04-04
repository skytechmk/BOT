#!/bin/bash

# Conda Setup Script for Binance Hunter TA-Lib Trading System
# This script helps set up the conda environment for the trading system

set -e  # Exit on any error

echo "🚀 Binance Hunter TA-Lib Conda Setup"
echo "====================================="

# Check if conda is installed
if ! command -v conda &> /dev/null; then
    echo "❌ Conda is not installed or not in PATH"
    echo "Please install Anaconda or Miniconda first:"
    echo "  - Anaconda: https://www.anaconda.com/products/distribution"
    echo "  - Miniconda: https://docs.conda.io/en/latest/miniconda.html"
    exit 1
fi

echo "✅ Conda found: $(conda --version)"

# Function to create environment
create_environment() {
    local env_file=$1
    local env_name=$2
    
    echo "📦 Creating conda environment from $env_file..."
    
    # Remove existing environment if it exists
    if conda env list | grep -q "^$env_name "; then
        echo "⚠️  Environment '$env_name' already exists. Removing..."
        conda env remove -n "$env_name" -y
    fi
    
    # Create new environment
    conda env create -f "$env_file"
    
    echo "✅ Environment '$env_name' created successfully!"
    echo ""
    echo "To activate the environment, run:"
    echo "  conda activate $env_name"
    echo ""
}

# Check for CUDA availability
check_cuda() {
    if command -v nvidia-smi &> /dev/null; then
        echo "🎮 NVIDIA GPU detected:"
        nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits
        return 0
    else
        echo "💻 No NVIDIA GPU detected (CPU-only mode)"
        return 1
    fi
}

# Main menu
echo "Please choose your installation type:"
echo "1) Full installation (all features)"
echo "2) Minimal installation (essential packages only)"
echo "3) CUDA installation (for NVIDIA GPU users)"
echo "4) Custom installation (choose your own environment file)"
echo ""

read -p "Enter your choice (1-4): " choice

case $choice in
    1)
        echo "🔧 Full installation selected"
        create_environment "environment.yml" "binance-hunter-talib"
        ;;
    2)
        echo "⚡ Minimal installation selected"
        create_environment "environment-minimal.yml" "binance-hunter-minimal"
        ;;
    3)
        echo "🚀 CUDA installation selected"
        if check_cuda; then
            create_environment "environment-cuda.yml" "binance-hunter-cuda"
        else
            echo "⚠️  No CUDA GPU detected. Consider using option 1 or 2 instead."
            read -p "Continue with CUDA installation anyway? (y/N): " confirm
            if [[ $confirm =~ ^[Yy]$ ]]; then
                create_environment "environment-cuda.yml" "binance-hunter-cuda"
            else
                echo "Installation cancelled."
                exit 1
            fi
        fi
        ;;
    4)
        echo "📁 Custom installation selected"
        read -p "Enter path to your environment.yml file: " custom_file
        if [[ -f "$custom_file" ]]; then
            # Extract environment name from file
            env_name=$(grep "^name:" "$custom_file" | cut -d' ' -f2)
            create_environment "$custom_file" "$env_name"
        else
            echo "❌ File not found: $custom_file"
            exit 1
        fi
        ;;
    *)
        echo "❌ Invalid choice. Please run the script again."
        exit 1
        ;;
esac

echo "🎉 Setup completed successfully!"
echo ""
echo "Next steps:"
echo "1. Activate your environment:"
echo "   conda activate [environment-name]"
echo ""
echo "2. Install TA-Lib (if needed):"
echo "   # On Linux/macOS:"
echo "   conda install -c conda-forge ta-lib"
echo "   # Or compile from source if conda version doesn't work"
echo ""
echo "3. Set up your .env file with API credentials"
echo ""
echo "4. Run the trading system:"
echo "   python binance_hunter_talib.py"
echo ""
echo "For troubleshooting, see INSTALLATION-CONDA.md"
