import asyncio
import platform
import re
import subprocess

from fastapi import APIRouter, Depends, Form, HTTPException, status
from pydantic import BaseModel, Field, ValidationError, field_validator

from bmaster.api.auth import require_permissions
from bmaster import configs


router = APIRouter(tags=['settings'])


class VolumeSetRequest(BaseModel):
    volume: int = Field(..., ge=0, le=100)


class VolumeResponse(BaseModel):
    ok: bool
    volume: int


class UpdateResponse(BaseModel):
    ok: bool
    status: str
    backend_updated: bool = False
    frontend_updated: bool = False
    detail: str | None = None


class CheckUpdatesResponse(BaseModel):
    ok: bool
    status: str
    has_updates: bool
    backend_has_updates: bool = False
    frontend_has_updates: bool = False
    detail: str | None = None


# class NetworkSettingsPayload(BaseModel):
#     ip: str
#     mask: str
#     gateway: str
#     dns: str

#     @field_validator('ip', 'gateway', 'dns')
#     @classmethod
#     def validate_ip(cls, v: str) -> str:
#         pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
#         if not re.match(pattern, v):
#             raise ValueError(f'Невалидный IP: {v}')
#         parts = v.split('.')
#         if not all(0 <= int(p) <= 255 for p in parts):
#             raise ValueError(f'IP октеты должны быть 0-255: {v}')
#         return v

#     @field_validator('mask')
#     @classmethod
#     def validate_mask(cls, v: str) -> str:
#         valid_masks = {
#             '255.255.255.0', '255.255.0.0', '255.0.0.0',
#             '255.255.255.128', '255.255.255.192', '255.255.255.224',
#             '255.255.255.240', '255.255.255.252',
#         }
#         if v not in valid_masks:
#             raise ValueError(f'Невалидная маска: {v}')
#         return v

@router.post('/reboot', dependencies=[Depends(require_permissions('bmaster.settings.reboot'))])
async def reboot() -> bool:
    try:
        system = platform.system()

        if system == "Linux":
            subprocess.Popen(["sh", "-c", "sleep 5 && reboot"])

        elif system == "Windows":
            subprocess.Popen(["shutdown", "/r", "/t", "5"])

        else:
            return False

        return True

    except Exception:
        return False

def set_system_volume(percent: int) -> bool:
    system = platform.system()

    try:
        if system == "Linux":
            subprocess.run(
                ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True

        elif system == "Windows":
            # TODO: Make changing volume on Windows
            return False

        return False

    except Exception:
        return False


def get_system_volume() -> int | None:
    system = platform.system()
    try:
        if system == "Linux":
            result = subprocess.run(
                ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                capture_output=True,
                text=True,
                check=True
            )

            match = re.search(r"(\d+)%", result.stdout)
            if not match:
                return None

            return int(match.group(1))

        elif system == "Windows":
            # TODO: Make getting volume on Windows
            return None

    except Exception:
        return None


@router.put(
    "/volume",
    response_model=VolumeResponse,
    dependencies=[Depends(require_permissions("bmaster.settings.volume"))]
)
async def set_volume(req: VolumeSetRequest) -> VolumeResponse:
    ok = set_system_volume(req.volume)
    if not ok:
        raise HTTPException(status_code=500)
    return VolumeResponse(ok=True, volume=req.volume)


@router.get("/volume", response_model=VolumeResponse, dependencies=[Depends(require_permissions("bmaster.settings.volume"))])
async def get_volume() -> VolumeResponse:
    res = get_system_volume()
    if res is None:
        raise HTTPException(status_code=500)
    return VolumeResponse(ok=True, volume=res)


def _run_update_sync() -> tuple[bool, bool]:
    from update import run_update

    return run_update()


def _run_check_updates_sync() -> tuple[bool, bool]:
    from check_updates import run_check

    return run_check()


@router.post(
    "/update",
    response_model=UpdateResponse,
    dependencies=[Depends(require_permissions("bmaster.settings.updates"))],
)
async def update_endpoint() -> UpdateResponse:
    try:
        backend_updated, frontend_updated = await asyncio.to_thread(_run_update_sync)
    except Exception as exc:
        return UpdateResponse(ok=False, status="failed", detail=str(exc))

    return UpdateResponse(
        ok=True,
        status="success",
        backend_updated=backend_updated,
        frontend_updated=frontend_updated,
    )


@router.get(
    "/check_updates",
    response_model=CheckUpdatesResponse,
    dependencies=[Depends(require_permissions("bmaster.settings.updates"))],
)
async def check_updates_endpoint() -> CheckUpdatesResponse:
    try:
        backend_has_updates, frontend_has_updates = await asyncio.to_thread(_run_check_updates_sync)
    except Exception as exc:
        return CheckUpdatesResponse(
            ok=False,
            status="failed",
            has_updates=False,
            detail=str(exc),
        )

    has_updates = backend_has_updates or frontend_has_updates
    return CheckUpdatesResponse(
        ok=True,
        status= "updates_available" if has_updates else "up_to_date",
        has_updates=has_updates,
        backend_has_updates=backend_has_updates,
        frontend_has_updates=frontend_has_updates,
    )


@router.get("/health")
async def health():
    return {"status": "ok"}


# @router.post(
#     "/net_settings",
#     dependencies=[Depends(require_permissions("bmaster.settings.net_settings.save"))],
# )
# async def save_network_settings(
#     ip: str = Form(...),
#     mask: str = Form(...),
#     gateway: str = Form(...),
#     dns: str = Form(...),
# ):
#     try:
#         payload = NetworkSettingsPayload(ip=ip, mask=mask, gateway=gateway, dns=dns)
#     except ValidationError as exc:
#         raise HTTPException(
#             status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
#             detail=exc.errors(),
#         )

#     try:
#         configs.update_network_settings(
#             ip=payload.ip,
#             mask=payload.mask,
#             gateway=payload.gateway,
#             dns=payload.dns,
#         )
#     except Exception:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Не удалось сохранить сетевые параметры",
#         )

#     return {"status": "ok"}
