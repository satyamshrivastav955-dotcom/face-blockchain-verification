"""
Outbound-request guard for untrusted URLs (SSRF defence).

Candidate image URLs come from a search provider, i.e. from the open web, so
they are attacker-influenced. Without a guard a hostile result such as
``http://169.254.169.254/latest/meta-data/`` or a public name that resolves to
``127.0.0.1`` would make this tool talk to local services or a cloud metadata
endpoint.

What this module enforces
-------------------------
* only ``http``/``https``; no embedded credentials; a host is required;
* ports limited to 80 and 443;
* every address the host resolves to must be a globally routable unicast
  address (IPv4 *and* IPv6; loopback, private, link-local, reserved, multicast,
  unspecified, carrier-grade NAT and documentation ranges are refused, as are
  IPv4-mapped / 6to4 / NAT64 / Teredo forms that embed such an address);
* the TCP connection is made to the *validated* address
  (:class:`GuardedAdapter`), so a name cannot resolve to a public address for
  the check and to a private one for the connect (DNS rebinding);
* proxies are never inherited from the environment, because a proxy would make
  the request from somewhere this check cannot see.

Residual limitations (documented in the README): validation depends on the OS
resolver's answer, an HTTPS-terminating intermediary is outside this process's
control, and the guard does not defend against a *public* server that is itself
a confused deputy.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

__all__ = [
    "UnsafeURLError",
    "ParsedURL",
    "validate_url",
    "resolve_public_addresses",
    "is_public_address",
    "make_guarded_session",
    "ALLOWED_PORTS",
    "MAX_URL_LENGTH",
]

ALLOWED_PORTS = (80, 443)
MAX_URL_LENGTH = 2048
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".localdomain", ".home.arpa")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")


class UnsafeURLError(ValueError):
    """A URL (or a redirect target, or a resolved address) is not allowed."""


@dataclass(frozen=True)
class ParsedURL:
    url: str
    scheme: str
    host: str
    port: int


def _redact(url: str) -> str:
    """Host-only description for error messages: attacker URLs are not echoed in full."""
    try:
        host = urlsplit(url).hostname or "?"
    except ValueError:
        host = "?"
    return host[:80]


def validate_url(url: str) -> ParsedURL:
    """Syntactic validation only (no DNS). Raises :class:`UnsafeURLError`."""
    if not isinstance(url, str) or not url.strip():
        raise UnsafeURLError("empty URL")
    if url != url.strip() or any(ord(c) < 0x21 or ord(c) == 0x7F for c in url):
        raise UnsafeURLError("URL contains whitespace or control characters")
    if len(url) > MAX_URL_LENGTH:
        raise UnsafeURLError("URL is too long")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("malformed URL") from exc
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise UnsafeURLError(f"unsupported URL scheme {scheme!r} (only http and https)")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UnsafeURLError("URLs with embedded credentials are refused")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURLError("URL has no host")
    if host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeURLError(f"host {host!r} is not a public name")
    effective_port = port or (443 if scheme == "https" else 80)
    if effective_port not in ALLOWED_PORTS:
        raise UnsafeURLError(f"port {effective_port} is not allowed (only 80 and 443)")
    return ParsedURL(url=url, scheme=scheme, host=host, port=effective_port)


def is_public_address(addr: str) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    return _is_public(ip)


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return _is_public(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return _is_public(ip.sixtofour)
        if ip.teredo is not None:
            return _is_public(ip.teredo[0]) and _is_public(ip.teredo[1])
        if ip in _NAT64:
            return _is_public(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return bool(
        ip.is_global
        and not ip.is_multicast
        and not ip.is_loopback
        and not ip.is_private
        and not ip.is_link_local
        and not ip.is_reserved
        and not ip.is_unspecified
    )


def _system_resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError) as exc:
        raise UnsafeURLError(f"could not resolve host {host[:80]!r}") from exc
    return [str(info[4][0]) for info in infos]


# Replaceable for tests; the signature is (host, port) -> list of address strings.
resolver: Callable[[str, int], list[str]] = _system_resolve


def resolve_public_addresses(host: str, port: int) -> list[str]:
    """Resolve *host* and require **every** answer to be public.

    Requiring all answers (not just one) closes the trick of publishing one
    public and one private A record.
    """
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        addresses = resolver(host, port)
    else:
        addresses = [str(literal)]
    if not addresses:
        raise UnsafeURLError(f"host {host[:80]!r} did not resolve")
    unique = list(dict.fromkeys(addresses))
    for addr in unique:
        if not is_public_address(addr):
            raise UnsafeURLError(f"host {host[:80]!r} resolves to a non-public address; refused")
    return unique


# ---------------------------------------------------------------------------
# Connection pinning
# ---------------------------------------------------------------------------


def _build_guarded_classes():
    """Create urllib3 connection/pool classes that connect only to validated IPs."""
    from urllib3.connection import HTTPConnection, HTTPSConnection
    from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
    from urllib3.util.connection import create_connection

    def _pinned_socket(conn):
        host = conn._dns_host
        addresses = resolve_public_addresses(host, conn.port)
        last_error: Exception | None = None
        for addr in addresses:
            try:
                return create_connection(
                    (addr, conn.port),
                    conn.timeout,
                    source_address=conn.source_address,
                    socket_options=conn.socket_options,
                )
            except OSError as exc:
                last_error = exc
        raise last_error or OSError("no usable address")

    class GuardedHTTPConnection(HTTPConnection):
        def _new_conn(self):
            return _pinned_socket(self)

    class GuardedHTTPSConnection(HTTPSConnection):
        def _new_conn(self):
            return _pinned_socket(self)

    class GuardedHTTPPool(HTTPConnectionPool):
        ConnectionCls = GuardedHTTPConnection

    class GuardedHTTPSPool(HTTPSConnectionPool):
        ConnectionCls = GuardedHTTPSConnection

    return GuardedHTTPPool, GuardedHTTPSPool


def make_guarded_session():
    """A ``requests.Session`` whose connections are pinned to validated public IPs.

    ``trust_env`` is off so proxy variables, ``.netrc`` and ``REQUESTS_CA_BUNDLE``
    tricks cannot reroute the request.
    """
    import requests
    from requests.adapters import HTTPAdapter

    http_pool, https_pool = _build_guarded_classes()

    class GuardedAdapter(HTTPAdapter):
        def init_poolmanager(self, *args, **kwargs):
            super().init_poolmanager(*args, **kwargs)
            self.poolmanager.pool_classes_by_scheme = {
                "http": http_pool,
                "https": https_pool,
            }

    session = requests.Session()
    session.trust_env = False
    session.proxies = {}
    adapter = GuardedAdapter(max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session
