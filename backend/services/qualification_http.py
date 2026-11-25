"""Public-only, DNS-pinned HTTP transport. No proxy, cookies, auth or JS runtime.

Resolve and validate ALL A/AAAA answers, connect to a numeric approved address,
verify the peer, and retain the original hostname for TLS/SNI and Host. Redirects
pass through the same checks and the caller's robots policy before each request.
"""
from __future__ import annotations

from dataclasses import dataclass
import http.client
import ipaddress
import io
import re
import socket
import ssl
import time
import threading
import weakref
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import dns.exception
import dns.resolver

USER_AGENT = "GmapScrapQualification/1.0"
MAX_BODY = 2 * 1024 * 1024
_host_locks = weakref.WeakValueDictionary()
_host_locks_guard = threading.Lock()
_last_request = {}


class FetchError(ValueError):
    """Only a bounded reason code, never raw server responses or credentials."""


def normalize_url(value: str) -> str:
    value = (value or "").strip()
    if not value or len(value) > 2048 or re.search(r"[\x00-\x20\x7f\\]", value):
        raise FetchError("invalid_url")
    if "://" not in value:
        value = "https://" + value
    try:
        p = urlsplit(value)
        if p.scheme.lower() not in {"http", "https"} or p.username is not None or p.password is not None:
            raise FetchError("invalid_url")
        host = (p.hostname or "").rstrip(".").lower()
        if not host or "%" in host:
            raise FetchError("invalid_host")
        host = host.encode("idna").decode("ascii")
        port = p.port
        if port not in {None, 80 if p.scheme.lower() == "http" else 443}:
            raise FetchError("port_not_allowed")
        try:
            address = ipaddress.ip_address(host)
            public_ip(str(address))
            host = f"[{host}]" if address.version == 6 else host
        except ipaddress.AddressValueError:
            pass
        except ValueError as error:
            if isinstance(error, FetchError):
                raise
            if ":" in host or not re.fullmatch(r"[a-z0-9.-]+", host):
                raise FetchError("invalid_host") from None
            if re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", host):
                raise FetchError("noncanonical_ip")
        bare = host.strip("[]")
        if bare in {"localhost", "metadata.google.internal", "instance-data"} or bare.endswith((".localhost", ".local", ".internal", ".home", ".lan")):
            raise FetchError("non_public_host")
        path = quote(p.path or "/", safe="/%:@!$&'()*+,;=-._~")
        query = quote(p.query, safe="%=&?/:@!$'()*+,;~-._")
        return urlunsplit((p.scheme.lower(), host, path, query, ""))
    except (UnicodeError, ValueError) as error:
        if isinstance(error, FetchError):
            raise
        raise FetchError("invalid_url") from None


def public_ip(value: str) -> str:
    ip = ipaddress.ip_address(value)
    if (not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified
            or str(ip) == "168.63.129.16"  # Azure platform/metadata virtual IP
            or getattr(ip, "ipv4_mapped", None) is not None
            or getattr(ip, "sixtofour", None) is not None
            or getattr(ip, "teredo", None) is not None
            or ip in ipaddress.ip_network("64:ff9b::/96")
            or ip in ipaddress.ip_network("64:ff9b:1::/48")):
        raise FetchError("non_public_address")
    return str(ip)


def resolve_public(host: str) -> list[str]:
    try:
        return [public_ip(host)]
    except ValueError as error:
        if isinstance(error, FetchError):
            raise
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 3
    resolver.timeout = 2
    addresses = []
    for kind in ("A", "AAAA"):
        try:
            answers = resolver.resolve(host, kind, search=False)
            addresses.extend(public_ip(answer.address) for answer in answers)
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            continue
        except dns.exception.DNSException:
            # A failed AAAA lookup cannot establish that all answers are public.
            raise FetchError("dns_unavailable") from None
    if not addresses:
        raise FetchError("dns_unavailable")
    return list(dict.fromkeys(addresses))


class DeadlineReader(io.RawIOBase):
    def __init__(self, sock, deadline, timeout, source=None):
        self.socket, self.deadline, self.timeout, self.received = sock, deadline, timeout, 0
        self.source = source

    def readable(self): return True

    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0: raise FetchError("site_budget_exceeded")
        self.socket.settimeout(min(self.timeout, remaining))
        count = self.source.readinto(buffer) if self.source is not None else self.socket.recv_into(buffer)
        self.received += count
        if self.received > MAX_BODY + 65536: raise FetchError("response_too_large")
        return count

    def close(self):
        if self.source is not None: self.source.close()
        super().close()


class DeadlineSocket:
    def __init__(self, sock, deadline, timeout):
        self.socket, self.deadline, self.timeout = sock, deadline, timeout

    def __getattr__(self, name): return getattr(self.socket, name)

    def makefile(self, *_, **__):
        # Keep socket.makefile's reference accounting: HTTPConnection closes its
        # socket immediately for Connection: close responses, before body reads.
        source = self.socket.makefile("rb", buffering=0)
        return io.BufferedReader(DeadlineReader(self.socket, self.deadline, self.timeout, source))


class PinnedConnection(http.client.HTTPConnection):
    def __init__(self, host: str, address: str, scheme: str, timeout: float):
        super().__init__(host, 443 if scheme == "https" else 80, timeout=timeout)
        self.address, self.scheme = address, scheme
        self.deadline = time.monotonic() + timeout

    def connect(self):
        address = public_ip(self.address)
        sock = socket.socket(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            # Numeric address: no second DNS lookup, including after TLS upgrade.
            sock.connect((address, self.port))
            if public_ip(sock.getpeername()[0]) != address:
                raise FetchError("peer_mismatch")
            if self.scheme == "https":
                context = ssl.create_default_context()
                context.set_alpn_protocols(["http/1.1"])
                sock = context.wrap_socket(sock, server_hostname=self.host)
            self.sock = DeadlineSocket(sock, self.deadline, self.timeout)
        except BaseException:
            sock.close()
            raise


@dataclass(frozen=True)
class Page:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def text(self):
        return self.body.decode("utf-8", errors="replace")


class PublicHTTP:
    def __init__(self, *, timeout=6, max_requests=28, max_bytes=8 * 1024 * 1024, seconds=75):
        self.timeout, self.max_requests, self.max_bytes = timeout, max_requests, max_bytes
        self.deadline = time.monotonic() + seconds
        self.requests, self.bytes = 0, 0
        self.host_delays = {}

    def get(self, url: str, *, before_request=None) -> Page:
        current = normalize_url(url)
        for redirect in range(5):
            if self.requests >= self.max_requests or time.monotonic() >= self.deadline:
                raise FetchError("site_budget_exceeded")
            if before_request:
                before_request(current)
            p = urlsplit(current)
            addresses = resolve_public(p.hostname)
            page = self._request(current, addresses[0])
            if page.status in {301, 302, 303, 307, 308}:
                location = page.headers.get("location")
                if not location or redirect == 4:
                    raise FetchError("redirect_limit")
                current = normalize_url(urljoin(current, location))
                continue
            return page
        raise FetchError("redirect_limit")

    def _request(self, url: str, address: str) -> Page:
        host = urlsplit(url).hostname.removeprefix("www.")
        with _host_locks_guard:
            lock = _host_locks.get(host)
            if lock is None:
                lock = threading.Lock()
                _host_locks[host] = lock
        if not lock.acquire(timeout=max(0, self.deadline - time.monotonic())):
            raise FetchError("site_budget_exceeded")
        try: return self._perform_request(url, address)
        finally: lock.release()

    def _perform_request(self, url: str, address: str) -> Page:
        p = urlsplit(url)
        for attempt in range(2):
            # Runs while holding the host lock, including retries. Slow requests
            # cannot cause waiting workers to bunch up and violate crawl-delay.
            host = p.hostname.removeprefix("www.")
            current = time.monotonic()
            delay = max(self.host_delays.get(host, .5), 1 if attempt else .5)
            wait = max(0, _last_request.get(host, 0) + delay - current)
            if current + wait >= self.deadline: raise FetchError("site_budget_exceeded")
            if wait: time.sleep(wait)
            _last_request[host] = time.monotonic()
            if len(_last_request) > 2000:
                with _host_locks_guard:
                    for key in list(_last_request):
                        if _last_request[key] < current - 120: _last_request.pop(key, None)
            remaining = self.deadline - time.monotonic()
            if self.requests >= self.max_requests or remaining <= 0:
                raise FetchError("site_budget_exceeded")
            self.requests += 1
            connection = PinnedConnection(p.hostname, address, p.scheme, min(self.timeout, remaining))
            connection.deadline = self.deadline
            response = None
            try:
                connection.request("GET", urlunsplit(("", "", p.path, p.query, "")), headers={
                    "Host": p.netloc, "User-Agent": USER_AGENT, "Accept-Encoding": "identity",
                    "Accept": "text/html,application/json,application/xml,text/xml,application/rss+xml,*/*;q=0.1",
                    "Connection": "close",
                })
                response = connection.getresponse()
                headers = {k.lower(): v for k, v in response.getheaders()}
                if headers.get("content-encoding", "identity").lower() not in {"", "identity"}:
                    raise FetchError("encoded_response_rejected")
                if int(headers.get("content-length", "0")) > MAX_BODY:
                    raise FetchError("response_too_large")
                parts, length = [], 0
                while True:
                    if time.monotonic() > self.deadline:
                        raise FetchError("site_budget_exceeded")
                    chunk = response.read(16384)
                    if not chunk:
                        break
                    parts.append(chunk)
                    length += len(chunk)
                    self.bytes += len(chunk)
                    if length > MAX_BODY or self.bytes > self.max_bytes:
                        raise FetchError("response_too_large")
                # Never retry blocking/rate-limit responses or bypass them.
                if response.status in {502, 503, 504} and attempt == 0:
                    continue
                return Page(url, response.status, headers, b"".join(parts))
            except ssl.SSLError:
                raise FetchError("tls_error") from None
            except (TimeoutError, OSError, http.client.HTTPException):
                if attempt:
                    raise FetchError("network_error") from None
            except ValueError as error:
                if isinstance(error, FetchError):
                    raise
                raise FetchError("invalid_response") from None
            finally:
                if response is not None: response.close()
                connection.close()
        raise FetchError("network_error")
