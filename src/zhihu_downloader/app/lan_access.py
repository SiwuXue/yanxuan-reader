"""LAN access gate for the single-user local web application."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import secrets
import threading
import time
from collections.abc import Iterable
from urllib.parse import urlparse

LAN_SESSION_COOKIE = "zhihu_lan_session"
LAN_UNLOCK_PATH = "/api/lan/unlock"
LAN_UNLOCK_ASSETS = frozenset({"/lan-unlock.css", "/lan-unlock.js"})
LAN_CODE_LENGTH = 8
LAN_MAX_FAILED_ATTEMPTS = 5
LAN_LOCKOUT_SECONDS = 300

_PRIVATE_V4_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


def is_private_ipv4(value: str) -> bool:
    """Return whether value belongs to an RFC 1918 IPv4 network."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and any(
        address in network for network in _PRIVATE_V4_NETWORKS
    )


class LanAccessGuard:
    """Per-process unlock code, sessions, and failed-attempt throttling."""

    def __init__(self, code: str, hosts: Iterable[str]) -> None:
        if len(code) != LAN_CODE_LENGTH or not code.isascii() or not code.isdigit():
            raise ValueError("LAN access code must be eight ASCII digits")
        normalized: set[str] = set()
        for host in hosts:
            address = ipaddress.ip_address(str(host))
            if not isinstance(address, ipaddress.IPv4Address) or not is_private_ipv4(str(address)):
                raise ValueError("LAN hosts must be private IPv4 addresses")
            normalized.add(str(address))
        if not normalized:
            raise ValueError("LAN access requires at least one private IPv4 address")

        self._code = code
        self.hosts = frozenset(normalized)
        self._sessions: set[str] = set()
        self._attempts: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def is_local_client(client_host: str) -> bool:
        try:
            return ipaddress.ip_address(client_host).is_loopback
        except ValueError:
            return False

    def is_lan_client(self, client_host: str) -> bool:
        return is_private_ipv4(client_host)

    def origin_allowed(self, value: str, request_host: str) -> bool:
        """Accept only HTTP origins for the exact advertised host and port."""
        try:
            parsed = urlparse(str(value))
            hostname = parsed.hostname
        except ValueError:
            return False
        return bool(
            parsed.scheme.lower() == "http"
            and hostname in self.hosts
            and parsed.netloc.lower() == str(request_host).lower()
        )

    def authenticated(self, token: str | None) -> bool:
        if not token:
            return False
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock:
            return digest in self._sessions

    def verify_code(
        self,
        code: str,
        client_host: str,
        *,
        now: float | None = None,
    ) -> tuple[str | None, int]:
        """Return a new session token, or None and remaining lockout seconds."""
        instant = time.monotonic() if now is None else now
        key = client_host
        with self._lock:
            failures, locked_until = self._attempts.get(key, (0, 0.0))
            if locked_until > instant:
                return None, max(1, math.ceil(locked_until - instant))
            if locked_until:
                failures = 0

            valid = hmac.compare_digest(
                str(code).encode("utf-8"), self._code.encode("ascii"))
            if valid:
                self._attempts.pop(key, None)
                token = secrets.token_urlsafe(32)
                self._sessions.add(hashlib.sha256(token.encode("utf-8")).hexdigest())
                return token, 0

            failures += 1
            if failures >= LAN_MAX_FAILED_ATTEMPTS:
                self._attempts[key] = (0, instant + LAN_LOCKOUT_SECONDS)
                return None, LAN_LOCKOUT_SECONDS
            self._attempts[key] = (failures, 0.0)
            return None, 0
