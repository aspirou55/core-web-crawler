"""SSRF guard: refuse to fetch URLs that point inside our own network.

The threat (Server-Side Request Forgery): our /crawl endpoint fetches any URL
a caller supplies. Without this check, a caller could supply an address that
is only reachable FROM our server — the AWS metadata endpoint
(http://169.254.169.254/, which hands out IAM credentials), localhost admin
panels, or private VPC services — and our server would fetch it and hand back
the contents. The fix: resolve the hostname to IP addresses first, and refuse
anything that is not a public internet address.

Known limitation (documented, acceptable for a demo): we validate the IPs at
check time and requests re-resolves DNS at fetch time, so a hostile DNS server
could answer differently twice ("DNS rebinding"). Production-grade fixes pin
the validated IP for the actual connection.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}


class BlockedUrlError(ValueError):
    """Raised when a URL must not be fetched by this server."""


def _reject_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, host: str) -> None:
    checks = (
        (ip.is_loopback, "loopback (this machine itself)"),
        (ip.is_private, "private network"),
        (ip.is_link_local, "link-local (includes cloud metadata endpoints)"),
        (ip.is_reserved, "reserved"),
        (ip.is_multicast, "multicast"),
        (ip.is_unspecified, "unspecified (0.0.0.0)"),
    )
    for bad, label in checks:
        if bad:
            raise BlockedUrlError(f"{host} resolves to {ip}, a {label} address")


def validate_public_url(url: str) -> None:
    """Raise BlockedUrlError unless `url` points at a public internet host.

    Checks, in order:
    1. Scheme is http/https (blocks file://, ftp://, gopher:// tricks).
    2. A hostname is present.
    3. Every IP the hostname resolves to is a public address. We check every
       one because an attacker controlling DNS can mix a safe IP with an
       internal one and hope we only look at the first.
    """
    parsed = urlparse(url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedUrlError(f"scheme {parsed.scheme!r} is not allowed (http/https only)")

    host = parsed.hostname
    if not host:
        raise BlockedUrlError("URL has no hostname")

    try:
        # getaddrinfo returns every IPv4/IPv6 address the name resolves to.
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise BlockedUrlError(f"cannot resolve host {host!r}: {exc}") from exc

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        _reject_ip(ip, host)
