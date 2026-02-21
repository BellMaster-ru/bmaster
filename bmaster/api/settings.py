import asyncio
import ipaddress
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from bmaster.api.auth import require_permissions


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


NETPLAN_MANAGED_PATH = Path("/etc/netplan/99-bmaster.yaml")


class NetSettingsRequest(BaseModel):
    mode: Literal["dhcp", "static"]
    ip: str | None = None
    mask: str | None = None
    gateway: str | None = None
    dns: list[str] | None = None

    @model_validator(mode="after")
    def validate_by_mode(self) -> "NetSettingsRequest":
        if self.mode == "dhcp":
            return self

        missing_fields = [
            name for name in ("ip", "mask", "gateway", "dns")
            if getattr(self, name) in (None, "")
        ]
        if missing_fields:
            raise ValueError(
                f"Fields are required for static mode: {', '.join(missing_fields)}"
            )

        self.ip = _validate_ipv4(self.ip, "ip")
        self.gateway = _validate_ipv4(self.gateway, "gateway")
        self.mask = _validate_mask(self.mask)
        if not self.dns:
            raise ValueError("Field dns must contain at least one IPv4 address")
        self.dns = [_validate_ipv4(value, "dns") for value in self.dns]
        return self


class NetSettingsResponse(BaseModel):
    status: Literal["reboot_scheduled"]
    mode: Literal["dhcp", "static"]
    interface: str
    backend: Literal["networkmanager", "netplan"]


class NetSettingsCurrentResponse(BaseModel):
    status: Literal["ok"]
    mode: Literal["dhcp", "static"]
    interface: str
    backend: Literal["networkmanager", "netplan"]
    ip: str | None = None
    mask: str | None = None
    gateway: str | None = None
    dns: list[str] = Field(default_factory=list)


def _validate_ipv4(value: str | None, field_name: str) -> str:
    if value is None:
        raise ValueError(f"Field {field_name} is required")
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"Invalid IPv4 in field {field_name}: {value}") from exc


def _mask_to_prefix(mask: str) -> int:
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
    except Exception as exc:
        raise ValueError(f"Invalid subnet mask: {mask}") from exc


def _prefix_to_mask(prefix: int) -> str:
    try:
        return str(ipaddress.IPv4Network(f"0.0.0.0/{prefix}").netmask)
    except Exception as exc:
        raise ValueError(f"Invalid prefix: {prefix}") from exc


def _validate_mask(value: str | None) -> str:
    if value is None:
        raise ValueError("Field mask is required")
    _mask_to_prefix(value)
    return value


def _raise_net_error(status_code: int, detail: str) -> None:
    raise HTTPException(
        status_code=status_code,
        detail={"status": "error", "detail": detail},
    )


def _run_cmd(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=True, text=True)


def _safe_process_error(exc: subprocess.CalledProcessError) -> str:
    detail = (exc.stderr or exc.stdout or str(exc)).strip()
    return detail or str(exc)


def _get_default_interface() -> str:
    try:
        result = _run_cmd(["ip", "route", "show", "default"])
    except FileNotFoundError:
        _raise_net_error(500, "Command 'ip' is not available")
    except subprocess.CalledProcessError as exc:
        _raise_net_error(500, f"Failed to detect default interface: {_safe_process_error(exc)}")

    for line in result.stdout.splitlines():
        match = re.search(r"\bdev\s+(\S+)", line)
        if match:
            return match.group(1)

    _raise_net_error(400, "Default network interface not found")


def _detect_network_backend() -> Literal["networkmanager", "netplan", "unsupported"]:
    nmcli_path = shutil.which("nmcli")
    if nmcli_path:
        try:
            result = _run_cmd([nmcli_path, "-t", "-f", "RUNNING", "general"])
            if result.stdout.strip().lower() == "running":
                return "networkmanager"
        except subprocess.CalledProcessError:
            pass

    if shutil.which("netplan") and Path("/etc/netplan").is_dir():
        return "netplan"

    return "unsupported"


def _find_nm_connection(interface: str) -> str:
    try:
        result = _run_cmd(["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show"])
    except FileNotFoundError:
        _raise_net_error(500, "Command 'nmcli' is not available")
    except subprocess.CalledProcessError as exc:
        _raise_net_error(500, f"Failed to list NetworkManager connections: {_safe_process_error(exc)}")

    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        name, device = line.rsplit(":", 1)
        if name and device == interface:
            return name

    _raise_net_error(400, f"NetworkManager connection for interface '{interface}' not found")


def _apply_networkmanager_settings(req: NetSettingsRequest, interface: str) -> None:
    connection_name = _find_nm_connection(interface)

    command = [
        "nmcli", "connection", "modify", connection_name,
    ]
    if req.mode == "dhcp":
        command.extend([
            "ipv4.method", "auto",
            "ipv4.addresses", "",
            "ipv4.gateway", "",
            "ipv4.dns", "",
        ])
    else:
        prefix = _mask_to_prefix(req.mask or "")
        command.extend([
            "ipv4.method", "manual",
            "ipv4.addresses", f"{req.ip}/{prefix}",
            "ipv4.gateway", req.gateway or "",
            "ipv4.dns", ",".join(req.dns or []),
        ])

    try:
        _run_cmd(command)
    except FileNotFoundError:
        _raise_net_error(500, "Command 'nmcli' is not available")
    except subprocess.CalledProcessError as exc:
        _raise_net_error(500, f"Failed to update NetworkManager connection: {_safe_process_error(exc)}")


def _build_netplan_payload(req: NetSettingsRequest, interface: str) -> dict:
    iface_payload: dict[str, object]
    if req.mode == "dhcp":
        iface_payload = {"dhcp4": True}
    else:
        prefix = _mask_to_prefix(req.mask or "")
        iface_payload = {
            "dhcp4": False,
            "addresses": [f"{req.ip}/{prefix}"],
            "gateway4": req.gateway,
            "nameservers": {"addresses": req.dns or []},
        }

    return {
        "network": {
            "version": 2,
            "ethernets": {
                interface: iface_payload
            },
        }
    }


def _apply_netplan_settings(req: NetSettingsRequest, interface: str) -> None:
    previous_content: str | None = None
    if NETPLAN_MANAGED_PATH.exists():
        try:
            previous_content = NETPLAN_MANAGED_PATH.read_text(encoding="utf8")
        except Exception as exc:
            _raise_net_error(500, f"Failed to read existing netplan file: {exc}")

    payload = _build_netplan_payload(req, interface)
    try:
        NETPLAN_MANAGED_PATH.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf8",
        )
        _run_cmd(["netplan", "generate"])
    except Exception as exc:
        try:
            if previous_content is None:
                NETPLAN_MANAGED_PATH.unlink(missing_ok=True)
            else:
                NETPLAN_MANAGED_PATH.write_text(previous_content, encoding="utf8")
        except Exception:
            pass

        if isinstance(exc, subprocess.CalledProcessError):
            _raise_net_error(500, f"Failed to validate netplan config: {_safe_process_error(exc)}")
        if isinstance(exc, FileNotFoundError):
            _raise_net_error(500, "Command 'netplan' is not available")
        _raise_net_error(500, f"Failed to update netplan config: {exc}")


def _split_dns(raw: str) -> list[str]:
    return [part for part in re.split(r"[,\s;]+", raw.strip()) if part]


def _extract_ipv4_and_mask_from_cidr(cidr_value: str) -> tuple[str, str]:
    try:
        interface = ipaddress.IPv4Interface(cidr_value.strip())
        ip_value = str(interface.ip)
        mask_value = _prefix_to_mask(interface.network.prefixlen)
        return ip_value, mask_value
    except Exception as exc:
        raise ValueError(f"Invalid IPv4 CIDR value: {cidr_value}") from exc


def _read_networkmanager_settings(interface: str) -> NetSettingsCurrentResponse:
    connection_name = _find_nm_connection(interface)
    try:
        result = _run_cmd(
            [
                "nmcli",
                "-t",
                "-f",
                "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns",
                "connection",
                "show",
                connection_name,
            ]
        )
    except FileNotFoundError:
        _raise_net_error(500, "Command 'nmcli' is not available")
    except subprocess.CalledProcessError as exc:
        _raise_net_error(500, f"Failed to read NetworkManager settings: {_safe_process_error(exc)}")

    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()

    method = parsed.get("ipv4.method", "")
    if method == "auto":
        return NetSettingsCurrentResponse(
            status="ok",
            mode="dhcp",
            interface=interface,
            backend="networkmanager",
            dns=[],
        )

    if method != "manual":
        _raise_net_error(500, f"Unsupported NetworkManager ipv4.method: {method or '<empty>'}")

    addresses_raw = parsed.get("ipv4.addresses", "")
    address_candidate = _split_dns(addresses_raw)[0] if addresses_raw else ""
    if not address_candidate:
        _raise_net_error(500, "NetworkManager static profile has empty ipv4.addresses")

    try:
        ip_value, mask_value = _extract_ipv4_and_mask_from_cidr(address_candidate)
    except ValueError as exc:
        _raise_net_error(500, str(exc))

    gateway_raw = parsed.get("ipv4.gateway", "")
    gateway_value = _validate_ipv4(gateway_raw, "gateway") if gateway_raw else None

    dns_values: list[str] = []
    dns_raw = parsed.get("ipv4.dns", "")
    if dns_raw:
        dns_values = [_validate_ipv4(value, "dns") for value in _split_dns(dns_raw)]

    return NetSettingsCurrentResponse(
        status="ok",
        mode="static",
        interface=interface,
        backend="networkmanager",
        ip=ip_value,
        mask=mask_value,
        gateway=gateway_value,
        dns=dns_values,
    )


def _read_netplan_settings(default_interface: str) -> NetSettingsCurrentResponse:
    if not NETPLAN_MANAGED_PATH.exists():
        _raise_net_error(500, f"Managed netplan file not found: {NETPLAN_MANAGED_PATH}")

    try:
        data = yaml.safe_load(NETPLAN_MANAGED_PATH.read_text(encoding="utf8"))
    except Exception as exc:
        _raise_net_error(500, f"Failed to read netplan config: {exc}")

    if not isinstance(data, dict):
        _raise_net_error(500, "Invalid netplan config format")

    ethernets = (
        data.get("network", {}).get("ethernets", {})
        if isinstance(data.get("network"), dict)
        else {}
    )
    if not isinstance(ethernets, dict) or not ethernets:
        _raise_net_error(500, "No ethernet interfaces found in managed netplan config")

    interface = default_interface
    iface_cfg = ethernets.get(interface)
    if not isinstance(iface_cfg, dict):
        if len(ethernets) == 1:
            interface, iface_cfg = next(iter(ethernets.items()))
        else:
            _raise_net_error(500, f"Interface '{default_interface}' is not configured in managed netplan file")

    if bool(iface_cfg.get("dhcp4")):
        return NetSettingsCurrentResponse(
            status="ok",
            mode="dhcp",
            interface=interface,
            backend="netplan",
            dns=[],
        )

    addresses = iface_cfg.get("addresses")
    if not isinstance(addresses, list) or not addresses:
        _raise_net_error(500, "Netplan static config has empty addresses")

    first_address = str(addresses[0]).strip()
    try:
        ip_value, mask_value = _extract_ipv4_and_mask_from_cidr(first_address)
    except ValueError as exc:
        _raise_net_error(500, str(exc))

    gateway_raw = iface_cfg.get("gateway4")
    gateway_value = None
    if gateway_raw is not None:
        gateway_value = _validate_ipv4(str(gateway_raw), "gateway")

    nameservers = iface_cfg.get("nameservers", {})
    dns_entries = nameservers.get("addresses", []) if isinstance(nameservers, dict) else []
    if not isinstance(dns_entries, list):
        _raise_net_error(500, "Netplan nameservers.addresses must be a list")
    dns_values = [_validate_ipv4(str(value), "dns") for value in dns_entries]

    return NetSettingsCurrentResponse(
        status="ok",
        mode="static",
        interface=interface,
        backend="netplan",
        ip=ip_value,
        mask=mask_value,
        gateway=gateway_value,
        dns=dns_values,
    )

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
            try:
                subprocess.run(
                    ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except subprocess.CalledProcessError:
                pass

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
            try:
                result = subprocess.run(
                    ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                    capture_output=True,
                    text=True,
                    check=True
                )
                match = re.search(r"(\d+)%", result.stdout)
                if match:
                    return int(match.group(1))
            except subprocess.CalledProcessError:
                pass

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
    from service import run_update

    return run_update()


def _run_check_updates_sync() -> tuple[bool, bool]:
    from service import run_check

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


@router.get(
    "/net_settings",
    response_model=NetSettingsCurrentResponse,
    dependencies=[Depends(require_permissions("bmaster.settings.net_settings"))],
)
async def get_network_settings() -> NetSettingsCurrentResponse:
    if platform.system() != "Linux":
        _raise_net_error(400, "net_settings is supported only on Linux")

    interface = _get_default_interface()
    backend = _detect_network_backend()
    if backend == "unsupported":
        _raise_net_error(400, "Unsupported network backend. Supported: NetworkManager or netplan")

    if backend == "networkmanager":
        return _read_networkmanager_settings(interface)
    return _read_netplan_settings(interface)


@router.post(
    "/net_settings",
    response_model=NetSettingsResponse,
    dependencies=[Depends(require_permissions("bmaster.settings.net_settings"))],
)
async def save_network_settings(req: NetSettingsRequest) -> NetSettingsResponse:
    if platform.system() != "Linux":
        _raise_net_error(400, "net_settings is supported only on Linux")

    interface = _get_default_interface()
    backend = _detect_network_backend()
    if backend == "unsupported":
        _raise_net_error(400, "Unsupported network backend. Supported: NetworkManager or netplan")

    if backend == "networkmanager":
        _apply_networkmanager_settings(req, interface)
    else:
        _apply_netplan_settings(req, interface)

    try:
        subprocess.Popen(["sh", "-c", "sleep 5 && sudo systemctl reboot"])
    except Exception as exc:
        _raise_net_error(500, f"Network settings saved, but failed to schedule reboot: {exc}")

    return NetSettingsResponse(
        status="reboot_scheduled",
        mode=req.mode,
        interface=interface,
        backend=backend,
    )
