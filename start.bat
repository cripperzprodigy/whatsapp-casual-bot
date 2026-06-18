@echo off
setlocal
echo Starting WhatsApp Casual Bot setup...

:: Check if python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: python is not installed or not in PATH.
    pause
    exit /b 1
)

:: Check if Node is available
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: node is not installed or not in PATH.
    pause
    exit /b 1
)

:: Setup Node.js Microservice
echo Setting up Node.js WhatsApp Gateway...
cd whatsapp-service
call npm install
start /b cmd /c "node index.js"
cd ..

:: Create virtual environment if it doesn't exist
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

:: Install requirements
echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

:: Run the application
echo Starting FastAPI server...
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

endlocal
