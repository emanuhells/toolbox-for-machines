"""SSRF protection: validate URLs before making external requests."""

import ipaddress
import socket
from urllib.parse import urlparse

from toolbox.errors import ToolboxError

_BLOCKED_HOSTNAMES = {
    "localhost",
    "searxng",
    "camoufox",
    "whisper",
}

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_GENERIC_ERROR = "URL not allowed: blocked host"


def validate_external_url(url: str) -> None:
    """Raise ToolboxError(400) if the URL targets a private or internal host.

    Checks scheme, hostname blocklist, suffix blocklist (.local, .internal),
    and resolved IP addresses.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        raise ToolboxError(_GENERIC_ERROR, status_code=400)

    if parsed.scheme not in ("http", "https"):
        raise ToolboxError(_GENERIC_ERROR, status_code=400)

    hostname = parsed.hostname
    if not hostname:
        raise ToolboxError(_GENERIC_ERROR, status_code=400)

    hostname_lower = hostname.lower()

    # Exact hostname blocklist
    if hostname_lower in _BLOCKED_HOSTNAMES:
        raise ToolboxError(_GENERIC_ERROR, status_code=400)

    # Suffix blocklist
    if hostname_lower.endswith(".local") or hostname_lower.endswith(".internal"):
        raise ToolboxError(_GENERIC_ERROR, status_code=400)

    # Resolve and check all returned addresses
    try:
        results = socket.getaddrinfo(hostname, None)
    except OSError:
        # Can't resolve — treat as blocked to be safe
        raise ToolboxError(_GENERIC_ERROR, status_code=400)

    for _family, _type, _proto, _canonname, sockaddr in results:
        addr_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        for network in _PRIVATE_NETWORKS:
            if addr in network:
                raise ToolboxError(_GENERIC_ERROR, status_code=400)
