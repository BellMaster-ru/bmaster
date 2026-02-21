import subprocess
from pathlib import Path

from service.paths import REPO_PATH


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


def check_backend_updates(repo_path: Path = REPO_PATH) -> bool:
    _git(repo_path, "fetch")
    try:
        counts = _git(repo_path, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    except subprocess.CalledProcessError:
        return False
    ahead, behind = [int(value) for value in counts.split()]
    return behind > 0
