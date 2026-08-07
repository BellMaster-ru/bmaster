import os
import shutil
import subprocess
from pathlib import Path

from service.paths import REPO_PATH


UV_CANDIDATES = ("/usr/bin/uv", "~/.local/bin/uv", "~/.cargo/bin/uv")


def _git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def update_backend(repo_path: Path = REPO_PATH) -> bool:
    before = _git(repo_path, "rev-parse", "HEAD")
    subprocess.run(["git", "pull"], cwd=repo_path, check=True)
    after = _git(repo_path, "rev-parse", "HEAD")
    return before != after


def find_uv() -> str | None:
    uv = shutil.which("uv")
    if uv:
        return uv
    for candidate in UV_CANDIDATES:
        path = Path(candidate).expanduser()
        if os.access(path, os.X_OK):
            return str(path)
    return None


def sync_dependencies(repo_path: Path = REPO_PATH) -> bool:
    """Installs dependencies added by an update (`uv sync`)"""
    uv = find_uv()
    if uv is None:
        raise RuntimeError("uv executable not found, cannot install dependencies")

    subprocess.run([uv, "sync"], cwd=repo_path, check=True)
    return True


def check_backend_updates(repo_path: Path = REPO_PATH) -> bool:
    _git(repo_path, "fetch")
    try:
        counts = _git(repo_path, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    except subprocess.CalledProcessError:
        return False
    ahead, behind = [int(value) for value in counts.split()]
    return behind > 0
