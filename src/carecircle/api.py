"""JSON API behind the dashboard and simulator pages."""

from __future__ import annotations

import functools
import json
import logging
from dataclasses import asdict
from datetime import timedelta
from typing import Any, Awaitable, Callable

from mcp.server.mcpserver import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import __version__
from .agent import Simulator
from .clock import OffsetClock
from .errors import Ambiguous, CareCircleError, NotFound, ValidationError
from .i18n import normalize_language
from .models import Role
from .parsing import parse_days
from .scheduler import Scheduler
from .services import Services
from .timeutil import get_zone, humanize_time, local_date

log = logging.getLogger("carecircle.api")

Handler = Callable[[Request], Awaitable[Response]]
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "carecircle"


def _json(data: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store"})


def api_route(*, mutating: bool = False) -> Callable[[Handler], Handler]:
    """Map domain errors to HTTP and enforce the anti-CSRF header on state changes."""

    def decorate(fn: Handler) -> Handler:
        @functools.wraps(fn)
        async def wrapper(request: Request) -> Response:
            if mutating and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
                return _json({"error": f"missing {CSRF_HEADER} header"}, 403)
            try:
                return await fn(request)
            except NotFound as exc:
                return _json({"error": str(exc)}, 404)
            except Ambiguous as exc:
                return _json({"error": str(exc), "options": exc.options}, 409)
            except (CareCircleError, ValueError) as exc:
                return _json({"error": str(exc)}, 400)
            except json.JSONDecodeError:
                return _json({"error": "request body must be valid JSON"}, 400)
            except Exception:
                log.exception("Unhandled error in %s", fn.__name__)
                return _json({"error": "internal error"}, 500)

        return wrapper

    return decorate


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def _text(data: dict[str, Any], key: str, *, required: bool = True, default: str = "") -> str:
    value = data.get(key, default)
    if value is None:
        value = default
    if not isinstance(value, str):
        raise ValueError(f"{key} must be text")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{key} is required")
    return value


def register_api(mcp: MCPServer, services: Services, scheduler: Scheduler) -> Simulator:
    s = services
    simulator = Simulator(s, mcp)

    def elder_view(elder) -> dict[str, Any]:
        zone = get_zone(elder.timezone)
        today = local_date(s.clock.now(), zone)
        status = next((c for c in s.monitor.checkin_statuses() if c.person.id == elder.id), None)
        members = [
            {"name": m.name, "role": m.role.value, "relation": s.people.relation(elder.id, m.id),
             "telegram": bool(m.telegram_chat_id)}
            for m in s.people.members_of(elder.id)
        ]
        return {
            "name": elder.name,
            "language": elder.language,
            "timezone": elder.timezone,
            "checkin_state": status.state if status else "ok",
            "expected_by": humanize_time(status.deadline, zone) if status else None,
            "summary": s.summaries.build(elder.id, today).to_dict(),
            "alerts": [
                {
                    "id": a.id, "severity": a.severity.label, "kind": a.kind.value, "detail": a.detail,
                    "when": humanize_time(a.created_at, zone),
                    "notified": a.notified_at is not None,
                    "acknowledged": a.acknowledged_at is not None,
                }
                for a in s.alerts.list_for(elder.id, limit=15)
            ],
            "reminders": [
                {"id": r.id, "title": r.title, "time": r.at_time, "days": list(r.days)}
                for r in s.reminders.list(elder.id)
            ],
            "events_today": [
                {"title": e.title, "due": humanize_time(e.due_at, zone), "status": e.status.value}
                for e in s.reminders.events_for_day(elder.id, today)
            ],
            "unread_messages": len(s.messages.unread_for(elder.id)),
            "members": members,
        }

    @mcp.custom_route("/api/config", ["GET"])
    @api_route()
    async def config(_: Request) -> Response:
        st = s.settings
        elders = s.people.list(Role.ELDER)
        zone = get_zone(elders[0].timezone if elders else st.timezone)
        return _json(
            {
                "version": __version__,
                "demo": st.demo_mode,
                "llm": simulator.llm_enabled,
                "telegram": bool(st.telegram_bot_token),
                "auth": bool(st.mcp_token),
                "timezone": st.timezone,
                "now": humanize_time(s.clock.now(), zone),
                "checkin_deadline": st.checkin_deadline.strftime("%H:%M"),
            }
        )

    @mcp.custom_route("/api/overview", ["GET"])
    @api_route()
    async def overview(_: Request) -> Response:
        return _json(
            {
                "people": [
                    {"name": p.name, "role": p.role.value, "language": p.language,
                     "telegram": bool(p.telegram_chat_id)}
                    for p in s.people.list()
                ],
                "elders": [elder_view(e) for e in s.people.list(Role.ELDER)],
            }
        )

    @mcp.custom_route("/api/timeline/{person}", ["GET"])
    @api_route()
    async def timeline(request: Request) -> Response:
        p = s.people.find(request.path_params["person"], Role.ELDER)
        today = local_date(s.clock.now(), get_zone(p.timezone))
        days = [s.summaries.build(p.id, today - timedelta(days=i)).to_dict() for i in range(7)]
        return _json({"person": p.name, "days": days})

    @mcp.custom_route("/api/alerts/{alert_id}/ack", ["POST"])
    @api_route(mutating=True)
    async def ack(request: Request) -> Response:
        alert = s.alerts.acknowledge(int(request.path_params["alert_id"]))
        return _json({"ok": True, "id": alert.id})

    @mcp.custom_route("/api/reminders", ["POST"])
    @api_route(mutating=True)
    async def add_reminder(request: Request) -> Response:
        data = await _body(request)
        person = s.people.find(_text(data, "person"), Role.ELDER)
        by = _text(data, "requested_by", required=False)
        reminder = s.reminders.create(
            person.id,
            _text(data, "title"),
            _text(data, "time"),
            days=parse_days(data.get("days")),
            created_by=s.people.find(by).id if by else None,
        )
        return _json({"ok": True, "id": reminder.id}, 201)

    @mcp.custom_route("/api/reminders/{reminder_id}", ["DELETE"])
    @api_route(mutating=True)
    async def delete_reminder(request: Request) -> Response:
        s.reminders.deactivate(int(request.path_params["reminder_id"]))
        return _json({"ok": True})

    @mcp.custom_route("/api/messages", ["POST"])
    @api_route(mutating=True)
    async def send_message(request: Request) -> Response:
        data = await _body(request)
        sender, recipient = s.people.find(_text(data, "from")), s.people.find(_text(data, "to"))
        message = s.messages.send(sender.id, recipient.id, _text(data, "body"), private=bool(data.get("private")))
        return _json({"ok": True, "id": message.id}, 201)

    @mcp.custom_route("/api/sim/turn", ["POST"])
    @api_route(mutating=True)
    async def sim_turn(request: Request) -> Response:
        data = await _body(request)
        result = await simulator.turn(
            _text(data, "person", required=False) or None,
            _text(data, "text"),
            normalize_language(_text(data, "lang", required=False) or None) if data.get("lang") else None,
            use_llm=bool(data.get("use_llm")),
        )
        return _json(result.to_dict())

    @mcp.custom_route("/api/demo/advance", ["POST"])
    @api_route(mutating=True)
    async def demo_advance(request: Request) -> Response:
        if not (s.settings.demo_mode and isinstance(s.clock, OffsetClock)):
            return _json({"error": "demo mode is off (set CARECIRCLE_DEMO=1)"}, 403)
        minutes = float((await _body(request)).get("minutes", 0))
        if not 0 < minutes <= 24 * 60:
            raise ValidationError("minutes must be between 1 and 1440")
        s.clock.advance(minutes=minutes)
        report = scheduler.tick()
        return _json({"ok": True, "report": asdict(report)})

    @mcp.custom_route("/api/demo/tick", ["POST"])
    @api_route(mutating=True)
    async def demo_tick(_: Request) -> Response:
        if not s.settings.demo_mode:
            return _json({"error": "demo mode is off (set CARECIRCLE_DEMO=1)"}, 403)
        return _json({"ok": True, "report": asdict(scheduler.tick())})

    @mcp.custom_route("/api/demo/reset-clock", ["POST"])
    @api_route(mutating=True)
    async def demo_reset(_: Request) -> Response:
        if not (s.settings.demo_mode and isinstance(s.clock, OffsetClock)):
            return _json({"error": "demo mode is off (set CARECIRCLE_DEMO=1)"}, 403)
        s.clock.reset()
        return _json({"ok": True})

    return simulator
