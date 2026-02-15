@echo off

echo [=] Installation...

echo [-] Checking if Python and pip are installed...
where python >nul 2>&1
if errorlevel 1 (
    echo Python not found
    exit /b 1
)
where pip >nul 2>&1
if errorlevel 1 (
    echo pip not found
    exit /b 1
)
echo [+] Python and pip are installed

echo [-] Updating pip...
pip install --upgrade pip
echo [+] Updated pip

echo [-] Installing uv...
pip install uv
echo [+] Installed uv

REM Create a virtual environment if it doesn't exist
if not exist "venv" (
    echo [-] Creating virtual environment...
    python -m venv venv
    echo [+] Virtual environment created
)

REM Activate virtual environment
echo [-] Activating virtual environment...
call venv\Scripts\activate.bat
echo [+] Virtual environment activated

REM Install dependencies
echo [-] Installing requirements...
uv sync
echo [+] Installed requirements

echo [-] Creating data directory and app data...
python setup.py
echo [+] Data directory and app data created

echo [=] Installation finished
echo ---------------------------------------------------------
echo INFO: Our project is using uv, please use uv instead of pip for convenient package management.
echo INFO: You can check docs at https://docs.astral.sh/uv/getting-started/ for more information.
echo INFO: You can now run the application using "uv run main.py"
