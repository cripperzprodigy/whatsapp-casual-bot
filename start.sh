#!/usr/bin/env bash
# start.sh - Launch script for Linux and macOS

set -e

echo "=========================================="
echo "    WhatsApp Casual Bot - Setup & Run     "
echo "=========================================="
echo ""

# OS-Level Dependency Checks
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: python3 is not installed or not in PATH. Please install Python 3."
    exit 1
fi

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

# Check if Node.js/npm is available
if ! command -v node &> /dev/null || ! command -v npm &> /dev/null; then
    install_os_pkg "nodejs npm"
fi

# Check if python3-venv is available (often missing on clean Ubuntu)
if ! python3 -c "import venv" &> /dev/null; then
    install_os_pkg "python3-venv"
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
        echo "-> Creating Python virtual environment..."
        python3 -m venv venv

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
