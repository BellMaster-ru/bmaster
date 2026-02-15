import subprocess
from pathlib import Path

import requests

from update import (
    REPO_PATH,
    STATIC_PATH,
    _fetch_latest_release,
    _read_installed_release,
)


def _git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def check_backend_updates(repo_path: Path = REPO_PATH) -> bool:
    _git(repo_path, "fetch")
    try:
        counts = _git(repo_path, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    except subprocess.CalledProcessError:
        return False

    ahead, behind = [int(value) for value in counts.split()]
    return behind > 0


def check_frontend_updates(static_path: Path = STATIC_PATH) -> bool:
    installed = _read_installed_release(static_path / ".frontend_release.json")
    if installed is None:
        return True

    with requests.Session() as session:
        latest = _fetch_latest_release(session)
    return latest.id > installed.id


def run_check() -> tuple[bool, bool]:
    backend_has_updates = check_backend_updates(REPO_PATH)
    frontend_has_updates = check_frontend_updates(STATIC_PATH)
    return backend_has_updates, frontend_has_updates


def main() -> int:
    backend_has_updates, frontend_has_updates = run_check()

    if backend_has_updates:
        print("Backend: update available")
    if frontend_has_updates:
        print("Frontend: update available")
    if not backend_has_updates and not frontend_has_updates:
        print("Updates: none")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Check failed: {exc}")
        raise SystemExit(1)
