@echo off
title BTC Trading Bot
color 0A

echo ========================================
echo   BTC TRADING BOT - TELEGRAM
echo ========================================
echo.

cd /d "%~dp0"

echo [1/3] Checking Python...
python --version
if errorlevel 1 (
    echo ERROR: Python not found!
    echo Download from: https://www.python.org/downloads/
    pause
    exit
)

echo.
echo [2/3] Installing dependencies...
python -m pip install python-telegram-bot==20.7 aiosqlite python-dotenv requests websocket-client --quiet

echo.
echo [3/3] Starting bot...
echo.
echo ========================================
echo   Bot is RUNNING!
echo   Open Telegram and send /start
echo   Press Ctrl+C to stop
echo ========================================
echo.

python main.py

echo.
echo Bot stopped.
pause
