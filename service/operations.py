import secrets

from service.backend import check_backend_updates, update_backend
from service.certs import setup_cert
from service.frontend import check_frontend_updates, sync_frontend
from service.paths import (
    CONFIG_PATH,
    DATA_PATH,
    DEFAULT_CONFIG_PATH,
    FRONTEND_META_FILE,
    GITHUB_LATEST_API,
    LOGS_PATH,
    REPO_PATH,
    SOUNDS_PATH,
    SSL_CERT_PATH,
    SSL_KEY_PATH,
    STATIC_PATH,
    SYSTEMD_SERVICE_NAME,
)


def bootstrap(update_cert: bool = False) -> int:
    print(f"[-] Checking for directory: {DATA_PATH}...")
    DATA_PATH.mkdir(parents=True, exist_ok=True)
    print(f"[+] Directory '{DATA_PATH}' checked/created.")

    SOUNDS_PATH.mkdir(parents=True, exist_ok=True)
    print(f"[+] Directory '{SOUNDS_PATH}' checked/created.")

    if not CONFIG_PATH.exists() and DEFAULT_CONFIG_PATH.exists():
        config_text = DEFAULT_CONFIG_PATH.read_text(encoding="utf-8").replace(
            "$auth.jwt.secret_key",
            secrets.token_hex(32),
        )
        CONFIG_PATH.write_text(config_text, encoding="utf-8")
        print("[+] Config file 'config.yml' created.")

    if not LOGS_PATH.exists():
        LOGS_PATH.touch()
        print("[+] Log file 'logs.log' created.")

    if update_cert:
        print("[-] Updating self-signed certificate...")
    else:
        print("[-] Generating self-signed certificate...")

    cert_generated = setup_cert(
        SSL_KEY_PATH,
        SSL_CERT_PATH,
        regenerate=update_cert,
    )
    if cert_generated and update_cert:
        print("[+] Certificate updated")
    elif cert_generated:
        print("[+] Generated self-signed certificate")
    print("[+] Data directory and app data created")

    print(f"[-] Checking for directory: {STATIC_PATH}...")
    STATIC_PATH.mkdir(parents=True, exist_ok=True)
    print(f"[+] Directory '{STATIC_PATH}' checked/created.")

    print(f"[-] Fetching frontend release metadata from {GITHUB_LATEST_API}...")
    try:
        frontend_updated = sync_frontend(STATIC_PATH, force=False)
    except Exception as exc:
        print(f"[!] Failed to download or extract frontend: {exc}")
    else:
        if frontend_updated:
            print(f"[+] Frontend build extracted to '{STATIC_PATH}'.")
            print(f"[+] Frontend release metadata saved to '{FRONTEND_META_FILE}'.")
        else:
            print("[+] Frontend is already up to date.")

    if update_cert and cert_generated:
        print("[!] Certificate has been updated. Download it again and add it to trusted on all clients.")

    return 0


def run_update() -> tuple[bool, bool]:
    backend_updated = update_backend(REPO_PATH)
    frontend_updated = sync_frontend(STATIC_PATH, force=False)
    return backend_updated, frontend_updated


def run_check() -> tuple[bool, bool]:
    backend_has_updates = check_backend_updates(REPO_PATH)
    frontend_has_updates = check_frontend_updates(STATIC_PATH)
    return backend_has_updates, frontend_has_updates


def print_check_result() -> None:
    backend_has_updates, frontend_has_updates = run_check()
    if backend_has_updates:
        print("Backend: update available")
    if frontend_has_updates:
        print("Frontend: update available")
    if not backend_has_updates and not frontend_has_updates:
        print("Updates: none")


def print_update_result() -> None:
    backend_updated, frontend_updated = run_update()
    print("Backend: updated" if backend_updated else "Backend: no updates")
    print("Frontend: updated" if frontend_updated else "Frontend: no updates")
    if backend_updated:
        print(f"[!] Restart service to apply backend changes: sudo systemctl restart {SYSTEMD_SERVICE_NAME}")
