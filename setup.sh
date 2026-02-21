#!/bin/bash
set -euo pipefail

echo "[=] Installation..."

# ---------- helpers ---------
is_root() {
  [ "${EUID:-$(id -u)}" -eq 0 ]
}

run_as_root() {
  if is_root; then
    "$@"
  else
    sudo "$@"
  fi
}

need_apt() {
  command -v apt-get >/dev/null 2>&1
}

apt_install_once() {
  local pkgs=("$@")
  run_as_root apt-get update
  run_as_root apt-get install -y "${pkgs[@]}"
}

# ---------- ensure OS deps (Debian-like) ----------
if need_apt; then
  echo "[-] Ensuring base packages (curl, ca-certificates, portaudio)..."
  apt_install_once curl ca-certificates portaudio19-dev libffi-dev build-essential ffmpeg pulseaudio python3 python3-pip python3-venv
  echo "[+] Base packages are installed"
else
  echo "[!] apt-get not found. This script expects Debian/Ubuntu-like systems."
  exit 1
fi

# ---------- ensure python + pip ----------
echo "[-] Checking if Python 3 is installed..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "[!] Python3 is still missing after package install."
  exit 1
fi
echo "[+] Python 3 is installed"

echo "[-] Checking if pip is installed..."
if ! command -v pip3 >/dev/null 2>&1; then
  echo "[!] pip is still missing after package install."
  exit 1
fi
echo "[+] pip is installed"

# ---------- install uv (official script) ----------
echo "[-] Installing uv via official script..."
curl -LsSf https://astral.sh/uv/install.sh | sh
echo "[+] uv installed"

# ---------- resolve uv path ----------
UV_BIN="/usr/bin/uv"
if [ ! -x "$UV_BIN" ]; then
  if [ -x "$HOME/.local/bin/uv" ]; then
    UV_BIN="$HOME/.local/bin/uv"
  else
    echo "[!] uv not found at /usr/bin/uv or ~/.local/bin/uv"
    echo "    Try re-opening your shell or add uv to PATH, then re-run."
    exit 1
  fi
fi

echo "[+] Using uv at: $UV_BIN"

# ---------- create venv if missing ----------
if [ ! -d ".venv" ]; then
  echo "[-] Creating virtual environment (.venv)..."
  "$UV_BIN" venv .venv
  echo "[+] Virtual environment created"
fi

# ---------- install dependencies ----------
echo "[-] Installing dependencies (uv sync)..."
"$UV_BIN" sync
echo "[+] Installed requirements"

# ---------- setup ----------
echo "[-] Creating data directory and app data..."
"$UV_BIN" run -m service bootstrap
echo "[+] Setup completed"

# ---------- systemd service ----------
if ! command -v systemctl >/dev/null 2>&1; then
  echo "[!] systemctl not found. This installer requires systemd."
  exit 1
fi

REPO_DIR="$(pwd -P)"
SERVICE_NAME="bmaster.service"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"
SERVICE_USER="${SUDO_USER:-${USER:-}}"
if [ -z "$SERVICE_USER" ]; then
  SERVICE_USER="$(id -un)"
fi

PYTHON_BIN="${REPO_DIR}/.venv/bin/python"
MAIN_PY="${REPO_DIR}/main.py"
if [ ! -x "$PYTHON_BIN" ]; then
  echo "[!] Python executable not found in .venv: $PYTHON_BIN"
  exit 1
fi

echo "[-] Creating systemd unit at ${SERVICE_FILE}..."
TMP_UNIT="$(mktemp)"
cat > "$TMP_UNIT" <<EOF
[Unit]
Description=bmaster service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${REPO_DIR}
ExecStart=${UV_BIN} ${MAIN_PY}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

run_as_root install -m 644 "$TMP_UNIT" "$SERVICE_FILE"
rm -f "$TMP_UNIT"

echo "[-] Reloading systemd daemon..."
run_as_root systemctl daemon-reload
echo "[+] systemd daemon reloaded"

echo "[-] Enabling ${SERVICE_NAME}..."
run_as_root systemctl enable "$SERVICE_NAME"
echo "[+] ${SERVICE_NAME} enabled"

echo "[=] Installation finished"
echo
echo "#############################################################"
echo "#  IMPORTANT: REBOOT REQUIRED                              #"
echo "#                                                           #"
echo "#  Please reboot your system now to ensure all             #"
echo "#  installed libraries and services work correctly.        #"
echo "#                                                           #"
echo "#  Command: sudo reboot                                    #"
echo "#############################################################"
echo
echo "INFO: Project uses uv. Prefer uv instead of pip for dependency management."
echo "INFO: Docs: https://docs.astral.sh/uv/getting-started/"
echo "INFO: Next step: sudo systemctl start ${SERVICE_NAME}"
echo "INFO: Check status: sudo systemctl status ${SERVICE_NAME}"
