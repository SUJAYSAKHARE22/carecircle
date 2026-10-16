"""ASGI application: Streamable HTTP MCP endpoint, web UI, JSON API, health check."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import __version__
from .api import register_api
from .models import Role
from .scheduler import Scheduler
from .security import (  # noqa: F401  (re-exported for callers and tests)
    BearerAuthMiddleware, HostGuardMiddleware, transport_security,
)
from .server import build_server
from .services import Services
from .web import register_web


def create_app(services: Services) -> Starlette:
    settings = services.settings
    mcp = build_server(services)
    scheduler = Scheduler(services)

    @mcp.custom_route("/health", ["GET"])
    async def health(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service": "carecircle",
                "version": __version__,
                "elders": len(services.people.list(Role.ELDER)),
                "auth": "bearer" if settings.mcp_token else "none",
                "demo": settings.demo_mode,
            }
        )

    register_web(mcp)
    register_api(mcp, services, scheduler)

    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        host=settings.host,
        transport_security=transport_security(settings),
    )
    # Middleware order: the last one added runs first, so the host guard is outermost.
    if settings.mcp_token:
        app.add_middleware(BearerAuthMiddleware, token=settings.mcp_token)
    app.add_middleware(HostGuardMiddleware, settings=settings)
    app.state.services = services
    app.state.scheduler = scheduler
    return app
