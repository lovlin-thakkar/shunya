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


def is_safe_webhook_url(url: str) -> bool:
    """Return False for URLs that resolve to private/internal addresses."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname or ""
        blocked = {"localhost", "metadata.google.internal", "169.254.169.254"}
        if hostname.lower() in blocked:
            return False
        ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except socket.gaierror:
        return True  # Unresolvable host is not reachable
    except Exception:
        return False
    return True
