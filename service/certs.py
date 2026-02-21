from datetime import UTC, datetime, timedelta
from pathlib import Path
import ipaddress
import re
import socket
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def setup_cert(key_path, cert_path, days_valid=3650, regenerate: bool = False):
    key_path = Path(key_path)
    cert_path = Path(cert_path)
    if not regenerate and key_path.exists() and cert_path.exists():
        print("[!] Certificate already exists, skipped generation")
        return False

    dns_names = ["localhost"]
    ip_map = {"127.0.0.1": None}

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 80))
            primary_ip = ipaddress.IPv4Address(s.getsockname()[0])
            if not primary_ip.is_loopback and not primary_ip.is_multicast and not primary_ip.is_unspecified:
                ip_map[str(primary_ip)] = None
    except Exception:
        pass

    try:
        _, _, host_ips = socket.gethostbyname_ex(socket.gethostname())
        for ip in host_ips:
            parsed_ip = ipaddress.IPv4Address(ip)
            if not parsed_ip.is_loopback and not parsed_ip.is_multicast and not parsed_ip.is_unspecified:
                ip_map[str(parsed_ip)] = None
    except Exception:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            ip = info[4][0]
            parsed_ip = ipaddress.IPv4Address(ip)
            if not parsed_ip.is_loopback and not parsed_ip.is_multicast and not parsed_ip.is_unspecified:
                ip_map[str(parsed_ip)] = None
    except Exception:
        pass

    ip_tool_output = ""
    try:
        ip_tool_output = subprocess.run(
            ["ip", "-o", "-f", "inet", "addr", "show"],
            check=False,
            capture_output=True,
            text=True,
        ).stdout
    except Exception:
        pass

    for ip in re.findall(r"inet\s+(\d+\.\d+\.\d+\.\d+)(?:/\d+)?", ip_tool_output):
        try:
            parsed_ip = ipaddress.IPv4Address(ip)
            if not parsed_ip.is_loopback and not parsed_ip.is_multicast and not parsed_ip.is_unspecified:
                ip_map[str(parsed_ip)] = None
        except ValueError:
            pass

    ifconfig_output = ""
    try:
        ifconfig_output = subprocess.run(
            ["ifconfig"],
            check=False,
            capture_output=True,
            text=True,
        ).stdout
    except Exception:
        pass

    for ip in re.findall(r"inet\s+(\d+\.\d+\.\d+\.\d+)", ifconfig_output):
        try:
            parsed_ip = ipaddress.IPv4Address(ip)
            if not parsed_ip.is_loopback and not parsed_ip.is_multicast and not parsed_ip.is_unspecified:
                ip_map[str(parsed_ip)] = None
        except ValueError:
            pass

    ipconfig_output = ""
    try:
        ipconfig_output = subprocess.run(
            ["ipconfig"],
            check=False,
            capture_output=True,
            text=True,
        ).stdout
    except Exception:
        pass

    for line in ipconfig_output.splitlines():
        line_lower = line.lower()
        if "ipv4" not in line_lower:
            continue
        ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
        if not ip_match:
            continue
        try:
            parsed_ip = ipaddress.IPv4Address(ip_match.group(1))
            if not parsed_ip.is_loopback and not parsed_ip.is_multicast and not parsed_ip.is_unspecified:
                ip_map[str(parsed_ip)] = None
        except ValueError:
            pass

    ip_objects = sorted((ipaddress.IPv4Address(ip) for ip in ip_map), key=int)
    common_name = "localhost"

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)

    san_entries = [x509.DNSName(name) for name in dns_names]
    san_entries.extend(x509.IPAddress(ip) for ip in ip_objects)

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=days_valid))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(private_key=private_key, algorithm=hashes.SHA256())
    )

    key_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))

    fingerprint = ":".join(f"{b:02X}" for b in certificate.fingerprint(hashes.SHA256()))
    print(" === Certificate info ===")
    print(f"Common Name: {common_name}")
    print("IP addresses in SAN:")
    for ip in ip_objects:
        print(f"  - {ip}")
    print(f"DNS names in SAN: {', '.join(dns_names)}")
    print(f"Valid for: {days_valid} days")
    print(f"SHA-256 fingerprint: {fingerprint}")
    print(f"Key: {key_path}")
    print(f"Certificate: {cert_path}")
    return True
