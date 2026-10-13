"""Command line entry point: `python -m carecircle serve`."""

from __future__ import annotations

import argparse
import logging

import uvicorn

from .app import create_app
from .config import Settings
from .services import build_services


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="carecircle", description="CareCircle MCP server")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="Run the Streamable HTTP MCP server (default)")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    host = getattr(args, "host", None) or settings.host
    port = getattr(args, "port", None) or settings.port
    if (host, port) != (settings.host, settings.port):
        from dataclasses import replace

        settings = replace(settings, host=host, port=port)

    services = build_services(settings)
    logging.getLogger("carecircle").info("MCP endpoint: http://%s:%s/mcp", host, port)
    uvicorn.run(create_app(services), host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
