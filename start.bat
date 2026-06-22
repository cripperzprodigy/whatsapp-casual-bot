@echo off
setlocal
echo ==========================================
echo     WhatsApp Casual Bot - Setup ^& Run
echo ==========================================
echo.

:: Check if python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Error: python is not installed or not in PATH.
    pause
    exit /b 1
)

:: Check if Node is available
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [X] Error: node is not installed or not in PATH.
    pause
    exit /b 1
)


:: Check if .env exists
if not exist ".env" (
    echo [!] WARNING: .env file not found.
    echo Please copy .env.example to .env and configure it before starting.
    pause
)

:: Check if installation is needed
set NEEDS_INSTALL=false
if not exist "venv\" set NEEDS_INSTALL=true
if not exist "whatsapp-service\node_modules\" set NEEDS_INSTALL=true

if "%NEEDS_INSTALL%"=="true" (
    echo [!] First-time setup or missing dependencies detected.
    set /p "REPLY=Would you like to install the required dependencies now? (y/n) "
    if /I not "%REPLY%"=="y" (
        echo [X] Installation aborted. The bot cannot start without dependencies.
        pause
        exit /b 1
    )
    
    echo [~] Installing dependencies...

    echo -^> Setting up Node.js WhatsApp Gateway...
    cd whatsapp-service
    call npm install
    cd ..

    echo -^> Creating Python virtual environment...
    python -m venv venv

    echo -^> Installing Python dependencies...
    call venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    echo [OK] Installation complete!
) else (
    echo [OK] Dependencies found. Preparing to start...
    call venv\Scripts\activate.bat
)

echo ==========================================
echo [^>] Starting Services...
echo ==========================================

:: Start Node.js Microservice
echo -^> Starting Node.js WhatsApp Gateway (background)...
cd whatsapp-service
start /b cmd /c "node index.js"
cd ..

:: Run the application
echo -^> Starting Python FastAPI server...
echo -^> Once started, visit http://localhost:8000/whatsapp/qr to link your device.
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

endlocal
