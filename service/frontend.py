import io
import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

from service.paths import (
    FRONTEND_INDEX_FILE,
    FRONTEND_META_FILE,
    GITHUB_LATEST_API,
    GITHUB_RELEASE_ZIP_URL,
    STATIC_PATH,
)


@dataclass(frozen=True)
class ReleaseInfo:
    tag_name: str
    id: int
    published_at: str


def _read_installed_release(meta_file: Path = FRONTEND_META_FILE) -> Optional[ReleaseInfo]:
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


def _write_installed_release(info: ReleaseInfo, meta_file: Path = FRONTEND_META_FILE) -> None:
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
            "User-Agent": "bmaster-maintenance",
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
        headers={"User-Agent": "bmaster-maintenance"},
        timeout=60,
    )
    response.raise_for_status()
    return response.content


def _replace_static_files(static_path: Path, zip_bytes: bytes, meta_file_name: str) -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="frontend_build_"))
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            archive.extractall(tmp_dir)

        entries = list(tmp_dir.iterdir())
        build_root = entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp_dir

        for item in static_path.iterdir():
            if item.name == meta_file_name:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

        for item in build_root.iterdir():
            destination = static_path / item.name
            if item.is_dir():
                shutil.copytree(item, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(item, destination)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def sync_frontend(static_path: Path = STATIC_PATH, force: bool = False) -> bool:
    static_path.mkdir(parents=True, exist_ok=True)
    meta_file = static_path / FRONTEND_META_FILE.name
    index_file = static_path / FRONTEND_INDEX_FILE.name
    installed = _read_installed_release(meta_file)

    with requests.Session() as session:
        latest = _fetch_latest_release(session)
        should_download = (
            force
            or installed is None
            or installed.id < latest.id
            or not index_file.exists()
        )
        if not should_download:
            return False

        zip_bytes = _download_zip(session)

    _replace_static_files(static_path, zip_bytes, meta_file.name)
    _write_installed_release(latest, meta_file)
    return True


def check_frontend_updates(static_path: Path = STATIC_PATH) -> bool:
    installed = _read_installed_release(static_path / FRONTEND_META_FILE.name)
    if installed is None:
        return True

    with requests.Session() as session:
        latest = _fetch_latest_release(session)
    return latest.id > installed.id
