@echo off
REM Multi-Exchange Trading Bot Launcher
REM Batch script for Windows

REM Change directory to the folder where this script lives so all relative paths work
cd /d "%~dp0"

echo.
echo =====================================
echo    Multi-Exchange Trading Bot
echo =====================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    echo Please install Python 3.7+ from https://python.org
    pause
    exit /b 1
)

REM Check if required packages are installed
echo Checking dependencies...
python -c "import pandas, robin_stocks, schwab" >nul 2>&1

if errorlevel 1 (
    echo.
    echo Required Python packages are missing.
    choice /M "Would you like to install them now" >nul
    if errorlevel 2 (
        echo Skipping installation at user request. Exiting.
        pause
        exit /b 1
    )
    echo Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo Installation failed. Please install the packages manually and re-run this script.
        pause
        exit /b 1
    )
)

REM ---------------------------------------------------------
REM If arguments are supplied, run the bot with them
REM ---------------------------------------------------------
if not "%~1"=="" (
    python trading_bot.py %*
    goto :eof
)

REM ---------------------------------------------------------
REM No arguments: open an interactive shell in this folder
REM ---------------------------------------------------------
echo.
echo Project folder is now active: %CD%
echo -------------------------------------------------------
echo Type commands such as:
echo    python trading_bot.py sample_trades.csv --dry-run
echo -------------------------------------------------------
echo.
cmd /k 