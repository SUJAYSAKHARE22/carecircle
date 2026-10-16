"""Serves the static dashboard and simulator pages with a strict Content-Security-Policy."""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

WEB_DIR = Path(__file__).parent / "web"

_PAGES = {"/": "index.html", "/sim": "simulator.html", "/dashboard": "dashboard.html"}
_ASSETS = {
    "common.css": "text/css; charset=utf-8",
    "common.js": "text/javascript; charset=utf-8",
    "home.js": "text/javascript; charset=utf-8",
    "simulator.js": "text/javascript; charset=utf-8",
    "dashboard.js": "text/javascript; charset=utf-8",
}
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-cache",
}


def _serve(filename: str, media_type: str) -> Response:
    path = WEB_DIR / filename
    if not path.is_file():
        return PlainTextResponse("not found", status_code=404)
    return Response(path.read_bytes(), media_type=media_type, headers=_HEADERS)


def register_web(mcp: MCPServer) -> None:
    for route, filename in _PAGES.items():

        def make(name: str):
            async def page(_: Request) -> Response:
                return _serve(name, "text/html; charset=utf-8")

            return page

        mcp.custom_route(route, ["GET"], name=f"page-{filename}")(make(filename))

    @mcp.custom_route("/static/{asset}", ["GET"])
    async def asset(request: Request) -> Response:
        name = request.path_params["asset"]
        if name not in _ASSETS:
            return PlainTextResponse("not found", status_code=404)
        return _serve(name, _ASSETS[name])
