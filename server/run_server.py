"""Start the companion server.

    python run_server.py            # http://localhost:8000  (laptop camera/mic work here)
    python run_server.py --https    # https://<laptop-LAN-IP>:8443 (needed for phone browsers)

Browsers only allow camera/microphone on https:// pages or on localhost, so a phone opening
the laptop's LAN address needs --https. A self-signed certificate is generated on first use
(the phone will show a one-time "not secure" warning to accept).
"""

import argparse
import ipaddress
import socket
from datetime import datetime, timedelta, timezone

import uvicorn

from app import config


def lan_ip() -> str:
    """Best guess at this machine's LAN address (no traffic is actually sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def ensure_cert(ip: str) -> tuple[str, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    config.CERT_DIR.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = config.CERT_DIR / f"cert-{ip}.pem", config.CERT_DIR / f"key-{ip}.pem"
    if cert_path.exists() and key_path.exists():
        return str(cert_path), str(key_path)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "elderly-companion.local")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.IPAddress(ipaddress.ip_address(ip)),
        ]), critical=False)
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.TraditionalOpenSSL,
                                           serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(cert_path), str(key_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--https", action="store_true", help="serve over HTTPS for phones")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    args = parser.parse_args()

    ip = lan_ip()
    kwargs = {}
    if args.https:
        port = args.port or 8443
        cert, key = ensure_cert(ip)
        kwargs = {"ssl_certfile": cert, "ssl_keyfile": key}
        print(f"\n  Laptop:  https://localhost:{port}\n  Phone:   https://{ip}:{port}"
              f"\n  Family dashboard: /dashboard\n")
    else:
        port = args.port or 8000
        print(f"\n  Check-in page:    http://localhost:{port}"
              f"\n  Family dashboard: http://localhost:{port}/dashboard\n")
    if args.reload:
        # 0.0.0.0 so other devices on the network (phone, Raspberry Pi) can reach the server.
        uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=True, **kwargs)
        return
    # Listen on IPv6 AND IPv4 at once. On Windows "localhost" resolves to ::1 first; with an
    # IPv4-only server every new connection waited ~2 s for the IPv6 attempt to fail.
    server = uvicorn.Server(uvicorn.Config("app.main:app", port=port, **kwargs))
    server.run(sockets=[dual_stack_socket(port)])


def dual_stack_socket(port: int) -> socket.socket:
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("::", port))
    except OSError:  # no IPv6 on this machine: plain IPv4 on all interfaces
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
    sock.listen(2048)
    sock.set_inheritable(True)
    return sock


if __name__ == "__main__":
    main()
