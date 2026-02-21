from pathlib import Path


REPO_PATH = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_PATH / "data"
STATIC_PATH = REPO_PATH / "static"
DEFAULT_CONFIG_PATH = REPO_PATH / "defaults" / "config.yml"
SSL_KEY_PATH = DATA_PATH / "key.pem"
SSL_CERT_PATH = DATA_PATH / "cert.pem"
CONFIG_PATH = DATA_PATH / "config.yml"
SOUNDS_PATH = DATA_PATH / "sounds"
LOGS_PATH = DATA_PATH / "logs.log"
FRONTEND_META_FILE = STATIC_PATH / ".frontend_release.json"
FRONTEND_INDEX_FILE = STATIC_PATH / "index.html"

GITHUB_RELEASE_ZIP_URL = "https://github.com/wumtdev/bmaster-lite/releases/latest/download/build.zip"
GITHUB_LATEST_API = "https://api.github.com/repos/wumtdev/bmaster-lite/releases/latest"
SYSTEMD_SERVICE_NAME = "bmaster.service"
