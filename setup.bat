@echo off
SETLOCAL EnableDelayedExpansion

echo ====================================================
echo      FIFAIndex Player Scraper Setup Script
echo ====================================================
echo.

:: 1. Check Python installation
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in your system PATH.
    echo Please install Python (3.8 or higher) from https://www.python.org/
    pause
    exit /b 1
)

:: 2. Create Virtual Environment
if not exist .venv (
    echo [INFO] Creating virtual environment (.venv)...
    python -m venv .venv
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [INFO] Virtual environment (.venv) already exists.
)

:: 3. Activate Virtual Environment
echo [INFO] Activating virtual environment...
call .venv\Scripts\activate.bat
if !errorlevel! neq 0 (
    echo [ERROR] Failed to activate virtual environment.
    pause
    exit /b 1
)

:: 4. Upgrade pip and install requirements
echo [INFO] Upgrading pip...
python -m pip install --upgrade pip

echo [INFO] Installing required dependencies...
pip install -r requirements.txt
if !errorlevel! neq 0 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

:: 5. Install Playwright browser
echo [INFO] Installing Playwright Chromium browser...
playwright install chromium
if !errorlevel! neq 0 (
    echo [ERROR] Failed to install Playwright browser.
    pause
    exit /b 1
)

echo.
echo ====================================================
echo  Setup Completed Successfully!
echo ====================================================
echo  To run the scraper:
echo  1. Run '.venv\Scripts\activate.bat' to activate environment.
echo  2. Run 'python -m scraper.main' to start scraping.
echo ====================================================
echo.
pause
