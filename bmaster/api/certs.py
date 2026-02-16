from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from bmaster.logs import main_logger
import bmaster.server

logger = main_logger.getChild('certs')
router = APIRouter(tags=['certs'])


def _get_cert_path() -> Path:
    if bmaster.server.config and bmaster.server.config.ssl:
        return Path(bmaster.server.config.ssl.cert_path)
    return Path('data/cert.pem')


@router.get('/download')
@router.get('/cert.cer', include_in_schema=False)
async def download_cert() -> FileResponse:
    cert_path = _get_cert_path()
    if not cert_path.exists() or not cert_path.is_file():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            'Certificate file not found'
        )

    return FileResponse(
        path=cert_path,
        filename='bmaster-cert.cer',
        media_type='application/x-x509-ca-cert'
    )
