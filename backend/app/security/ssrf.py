"""SSRF defense: resolve-then-pin URL validation.

String validation alone is insufficient because of DNS rebinding: the name a
URL carries can resolve somewhere new between check and fetch. So the rule is
resolve the host to its final IPs, validate EVERY resolved IP against the
blocklist, and pin any subsequent connection to a validated IP. Redirects must
never be followed without revalidating each hop through this module.
"""

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

# Cloud metadata and pseudo-metadata addresses, blocked explicitly even though
# most also fail the is_global test. Belt and suspenders.
_METADATA_IPS = frozenset(
    {
        "169.254.169.254",
        "169.254.170.2",
        "100.100.100.200",
        "192.0.0.192",
        "fd00:ec2::254",
    }
)

# Special-use ranges where Python's is_global says True for a few members
# (e.g. 192.0.0.9 and 192.0.0.10 in 192.0.0.0/24). Blocked wholesale.
_SPECIAL_USE_NETWORKS = (
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("100.64.0.0/10"),
)

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class SSRFError(Exception):
    pass


@dataclass(frozen=True)
class PinnedTarget:
    url: str
    scheme: str
    host: str
    port: int
    ip: str


def resolve_and_validate(url: str) -> PinnedTarget:
    """Validate a URL and resolve its host to a publicly routable IP.

    This function validates and resolves; it does not itself pin the socket.
    The caller must connect to the returned PinnedTarget.ip (not re-resolve
    the hostname) and must re-run this check on every redirect hop, or DNS
    rebinding defeats the whole exercise. Raises SSRFError on any violation.
    Never logs the full URL: it may carry a token in its query string.
    """
    try:
        parts = urlsplit(url)
        if parts.scheme not in _ALLOWED_SCHEMES:
            raise SSRFError(f"scheme {parts.scheme!r} is not allowed")
        if parts.username is not None or parts.password is not None:
            raise SSRFError("userinfo in URLs is not allowed")
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:  # malformed brackets, out-of-range ports
        raise SSRFError("malformed URL") from exc
    if not host:
        raise SSRFError("URL has no host")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        _validate_ip(literal)
        return PinnedTarget(url=url, scheme=parts.scheme, host=host, port=port, ip=str(literal))

    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFError("host does not resolve") from exc
    if not infos:
        raise SSRFError("host does not resolve")

    ips = [ipaddress.ip_address(str(info[4][0])) for info in infos]
    for ip in ips:
        _validate_ip(ip)
    return PinnedTarget(url=url, scheme=parts.scheme, host=host, port=port, ip=str(ips[0]))


def _validate_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if str(ip) in _METADATA_IPS:
        raise SSRFError("metadata address blocked")
    checkable = ip.ipv4_mapped if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped else ip
    for network in _SPECIAL_USE_NETWORKS:
        if network.version == checkable.version and checkable in network:
            raise SSRFError("special-use address blocked")
    if (
        checkable.is_loopback
        or checkable.is_private
        or checkable.is_link_local
        or checkable.is_multicast
        or checkable.is_reserved
        or checkable.is_unspecified
        or not checkable.is_global
    ):
        raise SSRFError("non-public address blocked")
