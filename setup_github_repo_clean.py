#!/usr/bin/env python3
"""
GitHub Repository Setup - Add code to remote repository
"""

import os
import subprocess
import sys
from datetime import datetime

def setup_git_repository():
    """Setup git repository and add all code"""
    
    print("🚀 GITHUB REPOSITORY SETUP")
    print("=" * 50)
    
    # Repository info
    repo_url = "https://github.com/skytechmk/BOT"
    
    print(f"📋 Repository: {repo_url}")
    print("🔑 Using token: ghp_**** (configured in git remote)")
    print()
    
    try:
        # Check if we're in a git repo
        result = subprocess.run(["git", "status"], capture_output=True, text=True, cwd="/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA")
        
        if "not a git repository" in result.stderr:
            print("🔧 Initializing git repository...")
            
            # Initialize git
            subprocess.run(["git", "init"], cwd="/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA", check=True)
            
            # Add remote (without token - will need to authenticate)
            subprocess.run(["git", "remote", "add", "origin", repo_url], 
                         cwd="/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA", check=True)
            
            print("✅ Git repository initialized!")
        else:
            print("✅ Git repository already exists")
            
            # Check if remote exists
            remote_result = subprocess.run(["git", "remote", "-v"], 
                                         capture_output=True, text=True, 
                                         cwd="/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA")
            
            if repo_url not in remote_result.stdout:
                print("🔧 Adding remote repository...")
                subprocess.run(["git", "remote", "add", "origin", repo_url], 
                             cwd="/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA", check=True)
                print("✅ Remote repository added!")
        
        print("\n📁 Adding all files to git...")
        
        # Add all files
        subprocess.run(["git", "add", "."], cwd="/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA", check=True)
        
        # Create commit
        commit_message = f"Add AI trading bot with internet search and member communication\n\nFeatures:\n- AI member tagging and communication\n- Internet search capabilities\n- Real Ops member discovery\n- Trading signal analysis\n- Technical indicators\n- Multi-timeframe analysis\n\nTimestamp: {datetime.now()}"
        
        subprocess.run(["git", "commit", "-m", commit_message], 
                     cwd="/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA", check=True)
        
        print("✅ Files committed!")
        
        print("\n🚀 Pushing to GitHub...")
        
        # Push to repository
        subprocess.run(["git", "push", "-u", "origin", "master"], 
                     cwd="/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA", check=True)
        
        print("✅ Successfully pushed to GitHub!")
        print(f"🌐 Repository: {repo_url}")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Git command failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def create_gitignore():
    """Create .gitignore file"""
    
    gitignore_content = """
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Environment
.env
.venv
env/
venv/
ENV/
env.bak/
venv.bak/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Logs
*.log
debug_log*.txt
bot_output.log

# Models and Data
*.joblib
*.pkl
*.h5
*.model

# Cache
cache/
*.cache

# Temporary files
tmp/
temp/
*.tmp
*.temp

# Config files with sensitive data
config.json
secrets.json
emergency_token_config.json

# Rust build artifacts
target/
Cargo.lock

# CUDA files
*.run
*.deb

# Audit files
AUDIT_*.txt
audit_report_*.md

# Large files
*.sh
Miniforge3-Linux-x86_64.sh
cuda_12.2.0_535.54.03_linux.run
"""
    
    gitignore_path = "/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/.gitignore"
    
    with open(gitignore_path, 'w') as f:
        f.write(gitignore_content.strip())
    
    print(f"✅ Created .gitignore at {gitignore_path}")

def create_readme():
    """Create README.md file"""
    
    readme_content = """# AI Trading Bot - ANUNNAKI_OPS

## 🚀 Features

### 🤖 AI Capabilities
- **Internet Search**: Real-time web search for trading information
- **Member Communication**: Tag and communicate with Ops team members
- **Technical Analysis**: Advanced chart analysis and indicators
- **Market Data**: Real-time market data and news integration

### 📊 Trading Features
- **Multi-Timeframe Analysis**: Support for various timeframes
- **Technical Indicators**: RSI, MA, Volume, and custom indicators
- **Signal Generation**: AI-powered trading signals
- **Risk Management**: Built-in risk assessment

### 🌐 Communication
- **Telegram Integration**: Full Telegram bot functionality
- **Ops Channel Management**: Real member discovery and tagging
- **Two-way Communication**: Interactive conversations with team members
- **Internet-Enhanced Responses**: AI can search web for accurate information

## 🛠️ Installation

### Prerequisites
- Python 3.8+
- CUDA support (for GPU acceleration)
- Telegram Bot Token

### Setup
```bash
# Clone repository
git clone https://github.com/skytechmk/BOT
cd BOT

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your tokens and settings

# Run the bot
python main.py
```

## 📋 Configuration

### Environment Variables
- `TELEGRAM_TOKEN`: Your Telegram bot token
- `OPENROUTER_API_KEY`: API key for AI models
- `CHAT_ID`: Ops channel ID

### Key Files
- `main.py`: Main bot entry point
- `ai_mcp_bridge.py`: AI tool integration
- `ai_internet_search.py`: Internet search capabilities
- `telegram_chat_interface.py`: Telegram integration

## 🎯 Usage

### Basic Commands
- `/start`: Start the bot
- `/help`: Show available commands
- `/analyze [symbol]`: Analyze trading symbol
- `/news`: Get latest trading news
- `/search [query]`: Search internet for information

### AI Features
- **Member Tagging**: AI can tag Ops team members for discussions
- **Internet Search**: Ask AI to search for current market information
- **Technical Analysis**: Get detailed chart analysis
- **Risk Assessment**: AI-powered risk analysis

## 🔧 Technical Details

### Architecture
- **AI Core**: Advanced AI with internet search capabilities
- **Telegram Interface**: Full Telegram bot functionality
- **Trading Engine**: Real-time trading analysis
- **Member Management**: Ops team communication system

### Performance
- **GPU Accelerated**: CUDA support for faster processing
- **Real-time Data**: Live market data integration
- **Scalable**: Designed for high-frequency trading
- **Secure**: Built-in security and audit features

## 📊 Supported Exchanges
- Binance
- Multiple other exchanges (configurable)

## 🤝 Contributing

1. Fork the repository
2. Create feature branch
3. Commit changes
4. Push to branch
5. Create Pull Request

## 📄 License

This project is licensed under the MIT License

## 🆘 Support

For support and questions:
- Create an issue in the repository
- Contact the development team

---

**⚡ Powered by Advanced AI with Internet Search Capabilities**
**🔒 Secure and Audited Trading System**
**🌐 Real-time Market Intelligence**
"""
    
    readme_path = "/home/MAIN_BOT_BETA/MAIN_BOT_OFFICIAL_BETA/README.md"
    
    with open(readme_path, 'w') as f:
        f.write(readme_content.strip())
    
    print(f"✅ Created README.md at {readme_path}")

if __name__ == "__main__":
    print("🚀 GITHUB REPOSITORY SETUP")
    print("=" * 50)
    
    # Create .gitignore and README
    create_gitignore()
    create_readme()
    
    # Setup git repository
    success = setup_git_repository()
    
    if success:
        print("\n🎉 SUCCESS!")
        print("✅ Code added to GitHub repository")
        print("🌐 Repository: https://github.com/skytechmk/BOT")
        print("📋 All files committed and pushed")
    else:
        print("\n❌ Setup failed")
        print("🔧 Please check the error messages above")
        print("💡 You may need to manually push the code")
