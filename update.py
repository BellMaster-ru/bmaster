import io
import json
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests


REPO_PATH = Path(__file__).resolve().parent
STATIC_PATH = REPO_PATH / "static"
INSTALLED_META_FILE = STATIC_PATH / ".frontend_release.json"
GITHUB_RELEASE_ZIP_URL = "https://github.com/wumtdev/bmaster-lite/releases/latest/download/build.zip"
GITHUB_LATEST_API = "https://api.github.com/repos/wumtdev/bmaster-lite/releases/latest"


@dataclass(frozen=True)
class ReleaseInfo:
    tag_name: str
    id: int
    published_at: str


def _read_installed_release(meta_file: Path) -> Optional[ReleaseInfo]:
    if not meta_file.exists():
        return None
    try:
        data = json.loads(meta_file.read_text(encoding="utf-8"))
        return ReleaseInfo(
            tag_name=str(data.get("tag_name", "")),
            id=int(data.get("id", 0)),
            published_at=str(data.get("published_at", "")),
        )
    except Exception:
        return None


def _write_installed_release(meta_file: Path, info: ReleaseInfo) -> None:
    meta_file.write_text(
        json.dumps(
            {
                "tag_name": info.tag_name,
                "id": info.id,
                "published_at": info.published_at,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _fetch_latest_release(session: requests.Session) -> ReleaseInfo:
    response = session.get(
        GITHUB_LATEST_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "bmaster-updater",
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    tag_name = data.get("tag_name")
    release_id = data.get("id")
    published_at = data.get("published_at")
    if not tag_name or not release_id or not published_at:
        raise RuntimeError("Invalid GitHub release response")

    return ReleaseInfo(
        tag_name=str(tag_name),
        id=int(release_id),
        published_at=str(published_at),
    )


def _download_zip(session: requests.Session) -> bytes:
    response = session.get(
        GITHUB_RELEASE_ZIP_URL,
        headers={"User-Agent": "bmaster-updater"},
        timeout=60,
    )
    response.raise_for_status()
    return response.content


def update_backend(repo_path: Path = REPO_PATH) -> bool:
    before = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    subprocess.run(["git", "pull"], cwd=repo_path, check=True)

    after = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    return before != after


def update_frontend(static_path: Path = STATIC_PATH) -> bool:
    static_path.mkdir(parents=True, exist_ok=True)
    meta_file = static_path / INSTALLED_META_FILE.name
    installed = _read_installed_release(meta_file)

    with requests.Session() as session:
        latest = _fetch_latest_release(session)
        if installed and installed.id >= latest.id:
            return False
        zip_bytes = _download_zip(session)

    tmp_dir = Path(tempfile.mkdtemp(prefix="frontend_build_"))
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            archive.extractall(tmp_dir)

        entries = list(tmp_dir.iterdir())
        build_root = entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp_dir

        for item in static_path.iterdir():
            if item.name == meta_file.name:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        for item in build_root.iterdir():
            dest = static_path / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)

        _write_installed_release(meta_file, latest)
        return True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_update() -> tuple[bool, bool]:
    backend_updated = update_backend(REPO_PATH)
    frontend_updated = update_frontend(STATIC_PATH)
    return backend_updated, frontend_updated


def main() -> int:
    backend_updated, frontend_updated = run_update()
    print("Backend: updated" if backend_updated else "Backend: no updates")
    print("Frontend: updated" if frontend_updated else "Frontend: no updates")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Update failed: {exc}")
        raise SystemExit(1)
