#!/usr/bin/env bash
# start.sh - Launch script for Linux and macOS

set -e

echo "Starting WhatsApp Casual Bot setup..."

# Check if python3 is available
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed or not in PATH."
    exit 1
fi

# Check if Node.js is available
if ! command -v node &> /dev/null; then
    echo "Error: node is not installed or not in PATH."
    exit 1
fi

# Setup Node.js Microservice
echo "Setting up Node.js WhatsApp Gateway..."
cd whatsapp-service
npm install
node index.js &
NODE_PID=$!
cd ..

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install requirements
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Handle cleanup
trap "kill $NODE_PID; exit" INT TERM EXIT

# Run the application
echo "Starting FastAPI server..."
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
