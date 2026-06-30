"""Shared SSRF guard for webhook URLs.

Validates that a URL does not target private/loopback/reserved addresses.
Used at both save time (AlertConfigSerializer) and fire time (_fire_alert).

Residual risk: DNS rebinding — the hostname is resolved once at call time.
An attacker who controls DNS could serve a public IP at validation time and
switch to a private IP before the HTTP request fires. Full mitigation requires
passing the already-resolved IP to the HTTP client, which httpx does not expose
cleanly through its public API. The double-validation (save + fire) shrinks
the window to milliseconds, which is sufficient for this threat model.
"""
import ipaddress
import socket
from urllib.parse import urlparse


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_safe_webhook_url(url: str) -> bool:
    """Return False for URLs that resolve to private/internal addresses.

    Resolves with ``getaddrinfo`` (both IPv4 *and* IPv6 — ``gethostbyname`` only
    sees A records, so an AAAA-only host pointing at a private IPv6 used to slip
    through) and rejects if *any* resolved address is internal. IPv4-mapped IPv6
    addresses are unwrapped before the check.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname or ""
        if not hostname:
            return False
        blocked = {"localhost", "metadata.google.internal", "169.254.169.254"}
        if hostname.lower() in blocked:
            return False

        # A literal IP host: check it directly (getaddrinfo would echo it back).
        try:
            literal = ipaddress.ip_address(hostname)
            return not _is_blocked_ip(literal)
        except ValueError:
            pass

        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return True  # Unresolvable host is not reachable
        if not infos:
            return False
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) to catch loopback hidden in v6.
            if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
                ip = ip.ipv4_mapped
            if _is_blocked_ip(ip):
                return False
    except Exception:
        return False
    return True
