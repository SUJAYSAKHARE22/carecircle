"""HTTP hardening shared by the MCP endpoint and the web API."""

from __future__ import annotations

import hmac
import logging
from typing import Awaitable, Callable, Iterable, MutableMapping
from urllib.parse import urlsplit

from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from .config import Settings

log = logging.getLogger("carecircle.security")

Scope = MutableMapping[str, object]
Receive = Callable[[], Awaitable[MutableMapping[str, object]]]
Send = Callable[[MutableMapping[str, object]], Awaitable[None]]

LOOPBACK = ("127.0.0.1", "localhost", "[::1]", "::1")


def allowed_hostnames(settings: Settings) -> set[str] | None:
    """Hostnames we answer to, or None when the guard is intentionally off (public bind)."""
    extra = {urlsplit(f"//{h}").hostname or h for h in settings.allowed_hosts}
    if settings.host in LOOPBACK or extra:
        return {h.strip("[]").lower() for h in LOOPBACK} | {h.lower() for h in extra}
    return None


def host_allowed(host_header: str, settings: Settings) -> bool:
    allowed = allowed_hostnames(settings)
    if allowed is None:
        return True
    hostname = (urlsplit(f"//{host_header}").hostname or "").lower()
    return hostname in allowed


def transport_security(settings: Settings) -> TransportSecuritySettings:
    """DNS-rebinding protection for the MCP transport."""
    allowed = allowed_hostnames(settings)
    if allowed is None:
        log.warning(
            "Binding to %s without CARECIRCLE_ALLOWED_HOSTS: DNS-rebinding protection is off. "
            "Set CARECIRCLE_MCP_TOKEN and/or CARECIRCLE_ALLOWED_HOSTS.", settings.host,
        )
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    hosts = sorted({f"{h}:*" for h in allowed if h != "::1"} | {"[::1]:*"} | set(settings.allowed_hosts) | allowed)
    origins = [f"http://{h}" for h in hosts] + [f"https://{h}" for h in settings.allowed_hosts]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins
    )


class HostGuardMiddleware:
    """Reject requests whose Host header isn't ours (DNS-rebinding defence for every route)."""

    def __init__(self, app, settings: Settings) -> None:
        self._app = app
        self._settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {k.lower(): v for k, v in scope["headers"]}  # type: ignore[union-attr]
            host = headers.get(b"host", b"").decode("latin-1")
            if not host_allowed(host, self._settings):
                response = JSONResponse({"error": "invalid host"}, status_code=421)
                await response(scope, receive, send)  # type: ignore[arg-type]
                return
        await self._app(scope, receive, send)


class BearerAuthMiddleware:
    """Require `Authorization: Bearer <token>` on protected prefixes (constant-time compare)."""

    def __init__(self, app, token: str, protected_prefixes: Iterable[str] = ("/mcp", "/api")) -> None:
        self._app = app
        self._token = token.encode()
        self._prefixes = tuple(protected_prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope["path"]).startswith(self._prefixes):
            headers = {k.lower(): v for k, v in scope["headers"]}  # type: ignore[union-attr]
            supplied = headers.get(b"authorization", b"")
            ok = supplied.startswith(b"Bearer ") and hmac.compare_digest(supplied[7:], self._token)
            if not ok:
                response = JSONResponse(
                    {"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
                )
                await response(scope, receive, send)  # type: ignore[arg-type]
                return
        await self._app(scope, receive, send)
