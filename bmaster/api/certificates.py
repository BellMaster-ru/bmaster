from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
from cryptography import x509
from cryptography.hazmat.backends import default_backend

from bmaster.api.auth import require_permissions
from bmaster import certificates
from bmaster.api import api


router = APIRouter(tags=['certificates'])


class CertificateInfo(BaseModel):
    exists: bool
    valid: bool
    issued_date: str | None = None
    expiry_date: str | None = None
    common_name: str | None = None
    path: str | None = None


def _get_cert_info() -> CertificateInfo:
    if not certificates.CERT_PATH.exists():
        return CertificateInfo(exists=False, valid=False)

    try:
        with open(certificates.CERT_PATH, 'rb') as f:
            cert_data = f.read()
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())

        is_valid = datetime.utcnow() < cert.not_valid_after
        common_name = cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)
        cn = common_name[0].value if common_name else None

        return CertificateInfo(
            exists=True,
            valid=is_valid,
            issued_date=cert.not_valid_before.isoformat(),
            expiry_date=cert.not_valid_after.isoformat(),
            common_name=cn,
            path=str(certificates.CERT_PATH)
        )
    except Exception as e:
        return CertificateInfo(exists=False, valid=False)


@router.get('/info')
async def get_certificate_info() -> CertificateInfo:
    return _get_cert_info()


@router.get('/download')
async def download_certificate() -> FileResponse:
    if not certificates.CERT_PATH.exists():
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            'Certificate not found. Please generate it first.'
        )

    return FileResponse(
        path=certificates.CERT_PATH,
        filename='bmaster-audio-cert.pem',
        media_type='application/x-pem-file'
    )


@router.post('/regenerate', dependencies=[
    Depends(require_permissions('bmaster.certificates.manage'))
])
async def regenerate_certificate() -> CertificateInfo:
    from bmaster import logs
    logger = logs.main_logger.getChild('certificates')
    
    logger.info("Regenerating certificate by user request...")
    await certificates.generate_or_load_certificate(force_regenerate=True)
    
    info = _get_cert_info()
    if info.valid:
        logger.info("Certificate regenerated successfully")
    else:
        logger.warning("Certificate regenerated but may not be valid")
    
    return info