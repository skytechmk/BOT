#!/bin/bash

# Aladdin Rust Core Build Script
# Automates building the Rust extension with maturin

set -e  # Exit on any error

echo "🔧 Building Aladdin Rust Core..."

# Check if we're in the right directory
if [ ! -f "aladdin_core/Cargo.toml" ]; then
    echo "❌ Error: aladdin_core/Cargo.toml not found. Run from project root."
    exit 1
fi

# Check if maturin is installed
if ! command -v maturin &> /dev/null; then
    echo "📦 Installing maturin..."
    pip install maturin
fi

# Check Rust toolchain
if ! command -v rustc &> /dev/null; then
    echo "❌ Error: Rust toolchain not found. Install Rust first:"
    echo "   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    exit 1
fi

# Clean previous builds
echo "🧹 Cleaning previous builds..."
cd aladdin_core
cargo clean

# Build in development mode (faster, for development)
if [ "$1" = "--dev" ] || [ "$1" = "-d" ]; then
    echo "🚀 Building in development mode..."
    maturin develop --release
    cp target/release/libaladdin_core.so ../aladdin_core.so
    echo "✅ Development build complete! (.so copied to project root)"
else
    # Build in release mode (optimized)
    echo "🚀 Building in release mode..."
    maturin build --release
    echo "✅ Release build complete!"
    
    # Install the built wheel
    echo "📦 Installing wheel..."
    pip install target/wheels/aladdin_core*.whl --force-reinstall
fi

# Verify the build
echo "🔍 Verifying build..."
cd ..
python3 -c "
try:
    import aladdin_core
    print('✅ aladdin_core imported successfully!')
    print(f'📊 Version info: {getattr(aladdin_core, \"__version__\", \"unknown\")}')
except ImportError as e:
    print(f'❌ Import failed: {e}')
    exit(1)
"

echo "🎉 Aladdin Rust Core build completed successfully!"
