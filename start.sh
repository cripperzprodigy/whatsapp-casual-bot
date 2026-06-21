#!/usr/bin/env bash
# start.sh - Launch script for Linux and macOS

set -e

MARKER_FILE=".bot_ready_state"

echo "=========================================="
echo "    WhatsApp Casual Bot - Setup & Run     "
echo "=========================================="
echo ""

# --- Helper: Check Ready State ---
check_ready_state() {
    if [ -f "$MARKER_FILE" ]; then
        local marker_content=$(cat "$MARKER_FILE")
        local saved_bin="${marker_content%%|*}"
        
        if [ -x "$saved_bin" ]; then
            local version=$("$saved_bin" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
            if [ "$version" == "3.12" ]; then
                echo "✅ Ready state detected. Python 3.12 verified at $saved_bin."
                export PYTHON_BIN="$saved_bin"
                export PATH="$HOME/.local/bin:$PATH"
                return 0
            fi
        fi
        echo "⚠️  Ready state marker invalid or binary broken. Proceeding to full installation..."
        rm -f "$MARKER_FILE"
    fi
    return 1
}

# --- Helper: OS Package Install ---
install_os_pkg() {
    PKG_NAME=$1
    if [ -x "$(command -v apt-get)" ]; then
        echo "⏳ Auto-installing OS package: $PKG_NAME"
        sudo apt-get update
        sudo apt-get install -y $PKG_NAME
    else
        echo "❌ Error: $PKG_NAME is not installed and apt-get is not available. Please install it manually."
        exit 1
    fi
}

# --- 1. Pre-Flight System Checks (Idempotent) ---
install_system_deps() {
    if [ -f "./install_deps.sh" ]; then
        echo "🔍 Running pre-flight dependency checks..."
        ./install_deps.sh
        if [ $? -ne 0 ]; then
            echo "❌ Pre-flight checks failed. Please resolve the missing dependencies manually."
            exit 1
        fi
    fi

    # Check Node.js/npm/ffmpeg
    if ! command -v node &> /dev/null || ! command -v npm &> /dev/null || ! command -v ffmpeg &> /dev/null; then
        install_os_pkg "nodejs npm ffmpeg"
    fi

    # Check Puppeteer dependencies
    if [ -x "$(command -v apt-get)" ]; then
        if ! dpkg -l | grep -q "libatk1.0-0"; then
            echo "⏳ Auto-installing Puppeteer (Headless Chrome) OS dependencies..."
            sudo apt-get update
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
        fi
    fi

    # Swap check for low memory
    if [ "$(uname)" = "Linux" ]; then
        total_mem=$(free -m | awk '/^Mem:/{print $2}')
        if [ "$total_mem" -lt 2000 ]; then
            if [ ! -f /swapfile ] && [ -z "$(swapon --show)" ]; then
                echo "⏳ Creating 2G swap file to prevent OOM..."
                if [ -x "$(command -v sudo)" ]; then
                    sudo fallocate -l 2G /swapfile
                    sudo chmod 600 /swapfile
                    sudo mkswap /swapfile
                    sudo swapon /swapfile
                    echo "✅ 2GB Swap file created successfully."
                fi
            fi
        fi
    fi
}

# --- 2. Python Binary Resolution ---
find_or_install_python() {
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
                sudo apt-get install -y build-essential libssl-dev zlib1g-dev \
                     libncurses-dev libreadline-dev libsqlite3-dev libbz2-dev \
                     liblzma-dev libgdbm-dev libdb-dev uuid-dev libffi-dev wget tar

                PYTHON_VERSION="3.12.9"
                PREFIX_DIR="$HOME/.local"
                export PYTHON_BIN="$PREFIX_DIR/bin/python3.12"

                if [ ! -x "$PYTHON_BIN" ]; then
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
                    
                    if [ ! -x "$PYTHON_BIN" ]; then
                        echo "❌ Critical Error: Python source compilation failed."
                        exit 1
                    fi
                fi
                echo "✅ Python 3.12 compiled and installed successfully!"
            fi
        fi
    fi
}

# --- 3. Verify Python ---
verify_python() {
    echo "⏳ Running functional tests on Python binary..."
    export PATH="$HOME/.local/bin:$PATH"
    hash -r
    
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
}

# --- 4. Setup Virtual Env & Pip ---
create_venv_and_deps() {
    # Check if .env exists
    if [ ! -f ".env" ]; then
        echo "⚠️  WARNING: .env file not found."
        echo "Please copy .env.example to .env and configure it before starting."
        sleep 3
    fi

    # Check and recreate venv if wrong version
    if [ -d "venv" ]; then
        CURRENT_VERSION=$(venv/bin/python --version 2>&1 | grep -oP '\d+\.\d+')
        if [ "$CURRENT_VERSION" != "3.12" ]; then
            echo "⚠️  Detected existing venv with Python $CURRENT_VERSION. Recreating with Python 3.12..."
            rm -rf venv
        fi
    fi

    if [ ! -f "venv/bin/activate" ]; then
        echo "⏳ Creating Python virtual environment..."
        "$PYTHON_BIN" -m venv venv
    fi

    source venv/bin/activate

    if [ "requirements.txt" -nt "$MARKER_FILE" ] || ! venv/bin/python -c "import fastapi" 2>/dev/null; then
        echo "⏳ Installing Python dependencies..."
        pip install -q --upgrade pip
        pip install -q --upgrade-strategy only-if-needed -r requirements.txt
        echo "✅ Python dependencies installed."
        touch "$MARKER_FILE"
    else
        echo "✅ Python dependencies already present."
    fi

    # Setup Node.js Microservice
    if [ ! -d "whatsapp-service/node_modules" ]; then
        echo "⏳ Setting up Node.js WhatsApp Gateway..."
        cd whatsapp-service
        npm install
        cd ..
    fi
}

# --- 5. Start Services ---
start_services() {
    echo "=========================================="
    echo "🚀 Starting Services..."
    echo "=========================================="

    # Write marker safely
    echo "$PYTHON_BIN|3.12" > "$MARKER_FILE"

    echo "-> Starting Node.js WhatsApp Gateway (background)..."
    cd whatsapp-service
    node index.js &
    NODE_PID=$!
    cd ..

    trap "echo '🛑 Stopping services...'; kill $NODE_PID; exit" INT TERM EXIT

    echo "-> Starting Python FastAPI server..."
    echo "-> Once started, visit http://localhost:8000/whatsapp/qr to link your device."
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
}

# --- Main Pipeline ---
main() {
    if check_ready_state; then
        create_venv_and_deps
        start_services
    else
        install_system_deps
        find_or_install_python
        verify_python
        create_venv_and_deps
        start_services
    fi
}

main
