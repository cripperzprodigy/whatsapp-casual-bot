#!/usr/bin/env bash
# start.sh - Launch script for Linux and macOS

set -e

echo "=========================================="
echo "    WhatsApp Casual Bot - Setup & Run     "
echo "=========================================="
echo ""

# OS-Level Dependency Checks
# Run Pre-Flight Dependency Checker
if [ -f "./install_deps.sh" ]; then
    echo "🔍 Running pre-flight dependency checks..."
    ./install_deps.sh
    if [ $? -ne 0 ]; then
        echo "❌ Pre-flight checks failed. Please resolve the missing dependencies manually."
        exit 1
    fi
else
    echo "⚠️  install_deps.sh not found, skipping pre-flight checks."
fi

# Dynamic Python 3.12 Resolution & Fallback Ladder
export PYTHON_BIN="python3.12"

if ! command -v $PYTHON_BIN &> /dev/null; then
    echo "⚠️  System python3.12 not found. Initializing Python 3.12 Fallback Ladder..."

    # Step 1: Attempt Standard APT Install
    echo "⏳ Step 1: Attempting standard APT installation..."
    if sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv python3.12-dev; then
        echo "✅ Installed python3.12 via APT."
    else
        echo "⚠️  APT failed. Proceeding to Step 2..."

        # Step 2: Attempt PPA Installation
        echo "⏳ Step 2: Attempting PPA installation (deadsnakes)..."
        if sudo apt-get install -y software-properties-common && \
           sudo add-apt-repository ppa:deadsnakes/ppa -y && \
           sudo apt-get update && \
           sudo apt-get install -y python3.12 python3.12-venv python3.12-dev; then
            echo "✅ Installed python3.12 via PPA."
        else
            echo "⚠️  PPA failed. Proceeding to Step 3..."

            # Step 3: Autonomous Source Compilation
            echo "⏳ Step 3: Compiling Python 3.12 from source..."
            echo "Checking prerequisites..."
            sudo apt-get install -y build-essential libssl-dev zlib1g-dev \
                 libncurses-dev libreadline-dev libsqlite3-dev libbz2-dev \
                 liblzma-dev libgdbm-dev libdb-dev uuid-dev libffi-dev wget tar

            PYTHON_VERSION="3.12.9"
            PREFIX_DIR="$HOME/.local"
            export PYTHON_BIN="$PREFIX_DIR/bin/python3.12"

            if [ -x "$PYTHON_BIN" ]; then
                echo "✅ Python 3.12 is already compiled at $PYTHON_BIN"
            else
                TEMP_DIR=$(mktemp -d)
                cd "$TEMP_DIR"

                echo "⏳ Downloading Python ${PYTHON_VERSION}..."
                wget -q --show-progress "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz"
                tar -xzf "Python-${PYTHON_VERSION}.tgz"
                cd "Python-${PYTHON_VERSION}"

                echo "⏳ Configuring build..."
                ./configure --enable-optimizations --with-ensurepip=install --prefix="$PREFIX_DIR" >/dev/null

                echo "⏳ Compiling Python (this may take 5-10 minutes)..."
                make -j $(nproc) >/dev/null

                echo "⏳ Installing Python to $PREFIX_DIR..."
                make install >/dev/null

                cd - >/dev/null
                rm -rf "$TEMP_DIR"

                if [ -x "$PYTHON_BIN" ]; then
                    echo "✅ Python 3.12 compiled and installed successfully!"
                    export PATH="$HOME/.local/bin:$PATH"
                else
                    echo "❌ Critical Error: Python source compilation failed."
                    exit 1
                fi
            fi
        fi
    fi
fi

# Verify Python Binary works (Functional Tests)
echo "⏳ Running functional tests on Python binary..."
if ! command -v "$PYTHON_BIN" &> /dev/null; then
    echo "❌ Error: Python binary not found at $PYTHON_BIN"
    exit 1
fi

VERSION=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
if [ "$VERSION" != "3.12" ]; then
    echo "❌ Error: Found Python $VERSION, but 3.12 is required."
    exit 1
fi

if ! "$PYTHON_BIN" -c "import sqlite3" &> /dev/null; then
    echo "❌ Error: Python 3.12 is missing sqlite3 support. SQLite headers may be missing."
    exit 1
fi

if ! "$PYTHON_BIN" -c "import venv" &> /dev/null; then
    echo "❌ Error: Python 3.12 is missing venv support. python3.12-venv may be missing."
    exit 1
fi

INSTALL_METHOD="APT/System"
if [[ "$PYTHON_BIN" == *".local"* ]]; then
    INSTALL_METHOD="Source"
fi
echo "✅ Python 3.12 verified and ready (Method: $INSTALL_METHOD)"


# Function to ask and install OS packages if on apt-based Linux
install_os_pkg() {
    PKG_NAME=$1
    if [ -x "$(command -v apt-get)" ]; then
        echo "⚠️  Missing OS package: $PKG_NAME"
        read -p "Would you like to install it now via sudo apt? (y/n) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            sudo apt-get update
            sudo apt-get install -y $PKG_NAME
        else
            echo "❌ Cannot proceed without $PKG_NAME."
            exit 1
        fi
    else
        echo "❌ Error: $PKG_NAME is not installed. Please install it manually."
        exit 1
    fi
}

install_puppeteer_deps() {
    if [ -x "$(command -v apt-get)" ]; then
        echo "⚠️  Checking for Puppeteer (Headless Chrome) OS dependencies..."
        # Check if a critical library like libatk1.0-0 is missing
        if ! dpkg -l | grep -q "libatk1.0-0"; then
            echo "⚠️  Puppeteer requires several OS libraries to run headless Chrome on Ubuntu/Debian."
            read -p "Would you like to install them now via sudo apt? (y/n) " -n 1 -r
            echo ""
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                sudo apt-get update
                
                # Check for libasound2 vs libasound2t64 (Ubuntu 24.04+ compatibility)
                LIBASOUND="libasound2"
                if apt-cache show libasound2t64 &> /dev/null; then
                    LIBASOUND="libasound2t64"
                fi

                sudo apt-get install -y \
                    ca-certificates fonts-liberation libappindicator3-1 $LIBASOUND \
                    libatk-bridge2.0-0 libatk1.0-0 libc6 libcairo2 libcups2 libdbus-1-3 \
                    libexpat1 libfontconfig1 libgbm1 libgcc1 libglib2.0-0 libgtk-3-0 \
                    libnspr4 libnss3 libpango-1.0-0 libpangocairo-1.0-0 libstdc++6 \
                    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 libxdamage1 \
                    libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 libxss1 libxtst6 \
                    lsb-release wget xdg-utils
            else
                echo "❌ Cannot proceed. The WhatsApp Web gateway will crash without these libraries."
                exit 1
            fi
        fi
    fi
}

# Check if Node.js/npm is available
if ! command -v node &> /dev/null || ! command -v npm &> /dev/null; then
    install_os_pkg "nodejs npm ffmpeg"
fi


# Swap check for low memory environments (like 1GB VMs)
if [ "$(uname)" = "Linux" ]; then
    total_mem=$(free -m | awk '/^Mem:/{print $2}')
    if [ "$total_mem" -lt 2000 ]; then
        if [ ! -f /swapfile ] && [ -z "$(swapon --show)" ]; then
            echo "⚠️  Low memory detected (< 2GB RAM) and no swap space found."
            echo "Creating 2G swap file to prevent OOM (Out Of Memory) crashes during pip install..."
            if [ -x "$(command -v sudo)" ]; then
                sudo fallocate -l 2G /swapfile
                sudo chmod 600 /swapfile
                sudo mkswap /swapfile
                sudo swapon /swapfile
                echo "✅ 2GB Swap file created successfully."
            else
                echo "❌ Cannot create swap file: 'sudo' not found or insufficient privileges."
            fi
        fi
    fi
fi


# Ensure Puppeteer dependencies are present
install_puppeteer_deps


# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️  WARNING: .env file not found."
    echo "Please copy .env.example to .env and configure it before starting."
    read -p "Press any key to continue anyway or Ctrl+C to exit..." -n 1 -r
    echo ""
fi


# 2. Validate existing venv Python version
if [ -d "venv" ]; then
    CURRENT_VERSION=$(venv/bin/python --version 2>&1 | grep -oP '\d+\.\d+')
    if [ "$CURRENT_VERSION" != "3.12" ]; then
        echo "⚠️  Detected existing venv with Python $CURRENT_VERSION. Recreating with Python 3.12..."
        rm -rf venv
    fi
fi

# Check if installation is needed
NEEDS_INSTALL=false

if [ ! -d "venv" ] || [ ! -d "whatsapp-service/node_modules" ]; then
    NEEDS_INSTALL=true
fi

if [ "$NEEDS_INSTALL" = true ]; then
    echo "⚠️  First-time setup or missing dependencies detected."
    read -p "Would you like to install the required dependencies now? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "⏳ Installing dependencies..."

        # Setup Node.js Microservice
        echo "-> Setting up Node.js WhatsApp Gateway..."
        cd whatsapp-service
        npm install
        cd ..

        # Create virtual environment
        echo "DEBUG: PYTHON_BIN is set to: $PYTHON_BIN"
        echo "-> Creating Python virtual environment..."
        $PYTHON_BIN -m venv venv

        # Activate virtual environment and install python dependencies
        echo "-> Installing Python dependencies..."
        source venv/bin/activate
        pip install --upgrade pip
        pip install -r requirements.txt
        echo "✅ Installation complete!"
    else
        echo "❌ Installation aborted. The bot cannot start without dependencies."
        exit 1
    fi
else
    echo "✅ Dependencies found. Preparing to start..."
    source venv/bin/activate
fi

echo "=========================================="
echo "🚀 Starting Services..."
echo "=========================================="

# Start Node.js Microservice in background
echo "-> Starting Node.js WhatsApp Gateway (background)..."
cd whatsapp-service
node index.js &
NODE_PID=$!
cd ..

# Handle cleanup
trap "echo '🛑 Stopping services...'; kill $NODE_PID; exit" INT TERM EXIT

# Run the application
echo "-> Starting Python FastAPI server..."
echo "-> Once started, visit http://localhost:8000/whatsapp/qr to link your device."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
