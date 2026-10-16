"""Command line interface: serve, seed-demo, link-telegram, tick."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace

import uvicorn

from .app import create_app
from .config import Settings
from .errors import CareCircleError
from .models import Role
from .services import Services, build_services

log = logging.getLogger("carecircle")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="carecircle", description="CareCircle MCP server")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Run the server (default)")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--demo", action="store_true", help="Seed demo data and enable time travel")
    serve.add_argument("--no-scheduler", action="store_true", help="Do not run background monitoring")

    sub.add_parser("seed-demo", help="Create the demo family and reminders (idempotent)")

    link = sub.add_parser("link-telegram", help="Link a person to a Telegram chat id")
    link.add_argument("name")
    link.add_argument("chat_id")

    sub.add_parser("tick", help="Run one monitor + dispatch pass and exit")
    sub.add_parser("add-person", help="Add a person").add_argument("name")
    return parser


def _start_background(services: Services, app, *, scheduler: bool) -> None:
    if scheduler:
        app.state.scheduler.start()
    token = services.settings.telegram_bot_token
    if token:
        from .notifier import BotCommands, TelegramClient, TelegramPoller

        TelegramPoller(TelegramClient(token), BotCommands(services)).start()
        log.info("Telegram bot polling started")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    command = args.command or "serve"

    if command == "serve":
        if getattr(args, "demo", False):
            settings = replace(settings, demo_mode=True)
        host = getattr(args, "host", None) or settings.host
        port = getattr(args, "port", None) or settings.port
        settings = replace(settings, host=host, port=port)
        services = build_services(settings)
        if settings.demo_mode:
            from .demo import seed_demo

            seed_demo(services)
        app = create_app(services)
        _start_background(services, app, scheduler=not getattr(args, "no_scheduler", False))
        log.info("MCP endpoint:  http://%s:%s/mcp", host, port)
        log.info("Simulator:     http://%s:%s/sim", host, port)
        log.info("Dashboard:     http://%s:%s/dashboard", host, port)
        uvicorn.run(app, host=host, port=port, log_level="info")
        return 0

    services = build_services(settings)
    try:
        if command == "seed-demo":
            from .demo import seed_demo

            print(seed_demo(services))
        elif command == "link-telegram":
            person = services.people.find(args.name)
            services.people.set_telegram_chat(person.id, args.chat_id)
            print(f"Linked {person.name} to Telegram chat {args.chat_id}")
        elif command == "tick":
            from .scheduler import Scheduler

            print(Scheduler(services).tick())
        elif command == "add-person":
            print(services.people.create(args.name, Role.FAMILY))
    except CareCircleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
