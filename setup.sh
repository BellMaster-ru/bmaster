#!/bin/bash

echo "[=] Installation..."

echo "[-]" "Checking if Python 3 and pip are installed..."
command -v python3 >/dev/null 2>&1 || { echo "Python3 не найден"; exit 1; }
command -v pip >/dev/null 2>&1     || { echo "pip не найден"; exit 1; }
echo "[+] Python 3 and pip are installed"

echo "[-] Updating pip..."
pip install --upgrade pip
echo "[+] Updated pip"

echo "[-] Installing uv"
pip install uv
echo "[+] Installed uv"

# Create a virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "[-] Creating virtual environment..."
    uv venv .venv
    echo "[+] Virtual environment created"
fi

# Activate virtual environment
echo "[-] Activating virtual environment..."
source .venv/bin/activate
echo "[+] Virtual environment activated"

# Install dependencies

echo "[-] Installing requirements..."
uv sync
echo "[+] Installed requirements"

echo "[-] Creating data directory and app data..."
python3 setup.py
# There script will create the necessary directories and files and print messages

echo "[=] Installation finished"
echo "---------------------------------------------------------"
echo "INFO: Our project is using uv, please use uv instead of pip for convenient package management."
echo "INFO: You can check docs at https://docs.astral.sh/uv/getting-started/ for more information."
echo "INFO: You can now run the application using `uv run main.py`"
