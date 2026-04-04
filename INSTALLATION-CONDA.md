# Conda Installation Guide for Binance Hunter TA-Lib Trading System

This guide provides comprehensive instructions for setting up the Binance Hunter TA-Lib trading system using conda environments on Linux systems.

## Prerequisites

### 1. Install Conda (if not already installed)

#### Option A: Miniconda (Recommended - Lightweight)
```bash
# Download Miniconda installer
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh

# Make installer executable
chmod +x Miniconda3-latest-Linux-x86_64.sh

# Run installer
./Miniconda3-latest-Linux-x86_64.sh

# Follow the prompts and restart your terminal
# Initialize conda
conda init bash
source ~/.bashrc
```

#### Option B: Anaconda (Full Distribution)
```bash
# Download Anaconda installer
wget https://repo.anaconda.com/archive/Anaconda3-2023.09-Linux-x86_64.sh

# Make installer executable
chmod +x Anaconda3-2023.09-Linux-x86_64.sh

# Run installer
./Anaconda3-2023.09-Linux-x86_64.sh

# Follow the prompts and restart your terminal
source ~/.bashrc
```

### 2. Verify Conda Installation
```bash
conda --version
conda info
```

## Quick Setup (Automated)

### 1. Make Setup Script Executable
```bash
chmod +x conda-setup.sh
```

### 2. Run Setup Script
```bash
./conda-setup.sh
```

The script will guide you through:
- Environment type selection (Full/Minimal/CUDA)
- Automatic environment creation
- Dependency installation

## Manual Setup

### Option 1: Full Installation (Recommended)
```bash
# Create environment from file
conda env create -f environment.yml

# Activate environment
conda activate binance-hunter-talib

# Verify installation
python -c "import pandas, numpy, sklearn, xgboost; print('Core packages installed successfully')"
```

### Option 2: Minimal Installation
```bash
# Create minimal environment
conda env create -f environment-minimal.yml

# Activate environment
conda activate binance-hunter-minimal

# Verify installation
python -c "import pandas, numpy, sklearn; print('Minimal packages installed successfully')"
```

### Option 3: CUDA Installation (For NVIDIA GPU Users)
```bash
# Check CUDA availability
nvidia-smi

# Create CUDA environment
conda env create -f environment-cuda.yml

# Activate environment
conda activate binance-hunter-cuda

# Verify CUDA installation
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

## TA-Lib Installation

TA-Lib requires special attention as it's a C library with Python bindings.

### Method 1: Conda Installation (Recommended)
```bash
# Activate your environment first
conda activate binance-hunter-talib

# Install TA-Lib from conda-forge
conda install -c conda-forge ta-lib

# Verify installation
python -c "import talib; print('TA-Lib installed successfully')"
```

### Method 2: Compile from Source (If conda version fails)
```bash
# Install build dependencies
sudo apt-get update
sudo apt-get install build-essential

# Download and compile TA-Lib
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib/
./configure --prefix=/usr
make
sudo make install

# Install Python wrapper
pip install TA-Lib

# Verify installation
python -c "import talib; print('TA-Lib compiled and installed successfully')"
```

## Environment Configuration

### 1. Create .env File
```bash
# Copy template
cp .env.example .env

# Edit with your credentials
nano .env
```

Add your API credentials:
```bash
# Binance API Credentials
BINANCE_API_KEY=your_binance_api_key_here
BINANCE_SECRET_KEY=your_binance_secret_key_here

# Telegram Bot Configuration
TELEGRAM_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
```

### 2. Set Permissions
```bash
# Secure your .env file
chmod 600 .env

# Make Python scripts executable
chmod +x binance_hunter_talib.py
```

## Running the System

### 1. Activate Environment
```bash
conda activate binance-hunter-talib
```

### 2. Test Installation
```bash
# Run dependency test
python -c "
import pandas as pd
import numpy as np
import talib
import xgboost as xgb
import torch
from binance.client import Client
print('✅ All core dependencies imported successfully')
"
```

### 3. Start Trading System
```bash
# Run the main trading system
python binance_hunter_talib.py
```

## Environment Management

### List Environments
```bash
conda env list
```

### Activate/Deactivate Environment
```bash
# Activate
conda activate binance-hunter-talib

# Deactivate
conda deactivate
```

### Update Environment
```bash
# Update from environment file
conda env update -f environment.yml

# Update specific package
conda update pandas numpy scikit-learn
```

### Remove Environment
```bash
conda env remove -n binance-hunter-talib
```

## Troubleshooting

### Common Issues and Solutions

#### 1. TA-Lib Installation Fails
```bash
# Try conda-forge channel
conda install -c conda-forge ta-lib

# If still fails, compile from source (see Method 2 above)
```

#### 2. CUDA Not Detected
```bash
# Check NVIDIA driver
nvidia-smi

# Reinstall CUDA toolkit
conda install cudatoolkit=11.8

# Verify PyTorch CUDA
python -c "import torch; print(torch.cuda.is_available())"
```

#### 3. Package Conflicts
```bash
# Create fresh environment
conda env remove -n binance-hunter-talib
conda env create -f environment.yml

# Or use mamba for faster solving
conda install mamba
mamba env create -f environment.yml
```

#### 4. Permission Errors
```bash
# Fix conda permissions
sudo chown -R $USER:$USER ~/miniconda3/
# or
sudo chown -R $USER:$USER ~/anaconda3/
```

#### 5. Environment Activation Issues
```bash
# Reinitialize conda
conda init bash
source ~/.bashrc

# Or manually activate
source ~/miniconda3/bin/activate binance-hunter-talib
```

### Performance Optimization

#### 1. Use Mamba for Faster Package Management
```bash
# Install mamba
conda install mamba

# Use mamba instead of conda
mamba env create -f environment.yml
mamba install package_name
```

#### 2. Enable Conda-Libmamba Solver
```bash
# Enable faster solver
conda install -n base conda-libmamba-solver
conda config --set solver libmamba
```

#### 3. Configure Conda Channels
```bash
# Set channel priority
conda config --set channel_priority strict

# Add useful channels
conda config --add channels conda-forge
conda config --add channels pytorch
conda config --add channels nvidia
```

## System Requirements

### Minimum Requirements
- **CPU**: 2+ cores
- **RAM**: 4GB minimum, 8GB recommended
- **Storage**: 5GB free space
- **OS**: Ubuntu 18.04+ or equivalent Linux distribution

### Recommended Requirements
- **CPU**: 4+ cores
- **RAM**: 16GB
- **Storage**: 20GB free space (for data and models)
- **GPU**: NVIDIA GPU with 4GB+ VRAM (optional, for CUDA acceleration)

## Security Considerations

### 1. API Key Security
```bash
# Secure .env file
chmod 600 .env

# Never commit .env to version control
echo ".env" >> .gitignore
```

### 2. Environment Isolation
```bash
# Always use conda environments
conda activate binance-hunter-talib

# Never install packages in base environment
```

### 3. Regular Updates
```bash
# Update conda itself
conda update conda

# Update environment packages
conda env update -f environment.yml
```

## Support and Resources

### Documentation
- [Conda Documentation](https://docs.conda.io/)
- [TA-Lib Documentation](https://ta-lib.org/)
- [Binance API Documentation](https://binance-docs.github.io/apidocs/)

### Community
- [Conda Community](https://community.anaconda.cloud/)
- [PyTorch Community](https://pytorch.org/community/)

### Troubleshooting Resources
- [Conda Troubleshooting](https://docs.conda.io/projects/conda/en/latest/user-guide/troubleshooting.html)
- [TA-Lib Installation Issues](https://github.com/mrjbq7/ta-lib#troubleshooting)

## Next Steps

After successful installation:

1. **Configure API Keys**: Set up your Binance and Telegram credentials
2. **Test System**: Run initial tests to verify functionality
3. **Customize Settings**: Adjust trading parameters as needed
4. **Monitor Performance**: Set up logging and monitoring
5. **Backup Configuration**: Save your working environment configuration

For additional help, refer to the main project documentation or create an issue in the project repository.
