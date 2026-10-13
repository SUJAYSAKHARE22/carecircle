"""ASGI application: Streamable HTTP MCP endpoint, health check, optional bearer auth."""

from __future__ import annotations

import hmac
import logging
from typing import Awaitable, Callable, MutableMapping

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import __version__
from .config import Settings
from .models import Role
from .server import build_server
from .services import Services

log = logging.getLogger("carecircle")

Scope = MutableMapping[str, object]
Receive = Callable[[], Awaitable[MutableMapping[str, object]]]
Send = Callable[[MutableMapping[str, object]], Awaitable[None]]

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class BearerAuthMiddleware:
    """Require `Authorization: Bearer <token>` on the MCP endpoint (constant-time compare)."""

    def __init__(self, app, token: str, protected_prefix: str = "/mcp") -> None:
        self._app = app
        self._token = token.encode()
        self._prefix = protected_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope["path"]).startswith(self._prefix):
            headers = {k.lower(): v for k, v in scope["headers"]}  # type: ignore[union-attr]
            supplied = headers.get(b"authorization", b"")
            expected_prefix = b"Bearer "
            ok = supplied.startswith(expected_prefix) and hmac.compare_digest(
                supplied[len(expected_prefix):], self._token
            )
            if not ok:
                response = JSONResponse(
                    {"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
                )
                await response(scope, receive, send)  # type: ignore[arg-type]
                return
        await self._app(scope, receive, send)


def transport_security(settings: Settings) -> TransportSecuritySettings:
    """DNS-rebinding protection. Loopback binds are locked to loopback Host headers;
    anything else must list its public hostnames in CARECIRCLE_ALLOWED_HOSTS."""
    if settings.host in _LOOPBACK or settings.allowed_hosts:
        hosts = [f"{h}:*" for h in _LOOPBACK if h != "::1"] + ["[::1]:*"]
        hosts += list(settings.allowed_hosts) + [f"{h}:*" for h in settings.allowed_hosts]
        origins = [f"http://{h}" for h in hosts] + [f"https://{h}" for h in settings.allowed_hosts]
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origins
        )
    log.warning(
        "Binding to %s without CARECIRCLE_ALLOWED_HOSTS: DNS-rebinding protection is off. "
        "Set CARECIRCLE_MCP_TOKEN and/or CARECIRCLE_ALLOWED_HOSTS.", settings.host,
    )
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


def create_app(services: Services) -> Starlette:
    settings = services.settings
    mcp = build_server(services)

    @mcp.custom_route("/health", ["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service": "carecircle",
                "version": __version__,
                "elders": len(services.people.list(Role.ELDER)),
                "auth": "bearer" if settings.mcp_token else "none",
            }
        )

    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host=settings.host,
        transport_security=transport_security(settings),
    )
    if settings.mcp_token:
        app.add_middleware(BearerAuthMiddleware, token=settings.mcp_token)
    return app
