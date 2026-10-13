"""CareCircle MCP server: the tools, resource and prompt Alexa+ talks to."""

from __future__ import annotations

import functools
import json
from datetime import date, datetime, timedelta
from typing import Any, Callable

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import __version__
from .errors import Ambiguous, CareCircleError, ValidationError
from .models import AlertKind, Person, ReminderStatus, Role, Severity
from .parsing import parse_days
from .safety import Assessment
from .services import Services
from .timeutil import get_zone, humanize_time, local_date

INSTRUCTIONS = """\
CareCircle helps a family stay gently in touch with an older relative who lives alone.
You speak with the ELDER (warm, short sentences, plain words, their language) and relay
to their CAREGIVERS. Typical flow: greet -> log_checkin with what they said (verbatim note)
-> get_pending_items -> read reminders/messages -> confirm_reminder when they say they took
something. Never diagnose or give medical advice. If a tool reports a concern, stay calm,
tell the person their family has been alerted, and encourage them to contact local emergency
services if they feel unsafe. CareCircle is a family notification aid, not an emergency service.
If a tool returns needs_clarification, ask the person to choose from `options`.
"""

_READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
_IDEMPOTENT_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def _safe(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Convert expected domain errors into structured, voice-friendly tool results."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return fn(*args, **kwargs)
        except Ambiguous as exc:
            return {"ok": False, "needs_clarification": True, "message": str(exc), "options": exc.options}
        except CareCircleError as exc:
            return {"ok": False, "error": str(exc)}

    return wrapper


def _parse_day(value: str | None, today: date) -> date:
    if value is None or not value.strip():
        return today
    text = value.strip().casefold()
    if text == "today":
        return today
    if text == "yesterday":
        return today - timedelta(days=1)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError("Date must be YYYY-MM-DD, 'today' or 'yesterday'") from exc


def _guidance(person: Person, assessment: Assessment, notified: list[str]) -> str:
    who = " and ".join(notified) if notified else "the family"
    if assessment.severity is Severity.URGENT:
        return (
            f"Stay calm and kind. Tell {person.name} you have alerted {who} right now. "
            "If they are in danger or feel very unwell, urge them to call their local emergency number. "
            "Do not diagnose. Keep them talking until help is confirmed."
        )
    if assessment.severity is Severity.ATTENTION:
        return (
            f"Acknowledge what {person.name} said with warmth. Let them know you have told {who}. "
            "Suggest rest or contacting their doctor if it continues. Do not diagnose."
        )
    return "All good. Respond warmly, then check pending reminders and messages."


def build_server(services: Services) -> MCPServer:
    s = services
    mcp = MCPServer(
        "CareCircle",
        title="CareCircle",
        description="Voice-first family check-ins, reminders and safety alerts.",
        instructions=INSTRUCTIONS,
        version=__version__,
    )

    # ---- helpers bound to services ------------------------------------------------
    def elder(person: str | None) -> Person:
        if person and person.strip():
            return s.people.find(person)
        elders = s.people.list(Role.ELDER)
        if len(elders) == 1:
            return elders[0]
        if not elders:
            raise ValidationError("No elder has been set up yet")
        raise Ambiguous("Whose check-in is this?", [p.name for p in elders])

    def local(person: Person, value: datetime) -> str:
        return humanize_time(value, get_zone(person.timezone))

    # ---- tools ---------------------------------------------------------------------
    @mcp.tool(annotations=_WRITE)
    @_safe
    def log_checkin(person: str | None = None, note: str = "", mood: int | str | None = None) -> dict[str, Any]:
        """Record that an elder has checked in today.

        Pass what they said in `note` (verbatim, any language). `mood` is optional: 1 (very low)
        to 5 (great) or a word like 'good'. Concerning phrases (falls, chest pain, dizziness...)
        automatically alert the family. Follow `assistant_guidance` in your reply.
        """
        elder_p = elder(person)
        result = s.checkins.log(elder_p.id, note, mood)
        notified = [p.name for p in s.alerts.recipients(result.alert.alert)] if result.alert else []
        due = s.reminders.due_events(elder_p.id)
        return {
            "ok": True,
            "person": elder_p.name,
            "recorded_at": local(elder_p, result.checkin.ts),
            "first_checkin_today": result.first_today,
            "concern_level": result.assessment.severity.label,
            "concern_categories": list(result.assessment.categories),
            "family_alerted": bool(result.alert and result.alert.created),
            "will_notify": notified,
            "pending_reminders": len(due),
            "unread_messages": len(s.messages.unread_for(elder_p.id)),
            "assistant_guidance": _guidance(elder_p, result.assessment, notified),
        }

    @mcp.tool(annotations=_WRITE)
    @_safe
    def get_pending_items(person: str | None = None) -> dict[str, Any]:
        """Get reminders that are due now and read-once messages from family.

        Calling this marks the messages as delivered, so read them out to the person.
        """
        p = elder(person)
        zone = get_zone(p.timezone)
        reminders = [
            {"reminder": e.title, "due": humanize_time(e.due_at, zone)}
            for e in s.reminders.due_events(p.id)
        ]
        messages = [
            {
                "from": s.people.get(m.from_id).name,
                "message": m.body,
                "sent": humanize_time(m.created_at, zone),
            }
            for m in s.messages.take_inbox(p.id)
        ]
        return {"ok": True, "person": p.name, "reminders_due": reminders, "messages": messages}

    @mcp.tool(annotations=_IDEMPOTENT_WRITE)
    @_safe
    def confirm_reminder(
        person: str | None = None, status: str = "taken", reminder: str | None = None
    ) -> dict[str, Any]:
        """Record that the person took ('taken') or skipped ('skipped') a due reminder.

        `reminder` is a spoken hint such as 'blood pressure tablet'. If several reminders are
        due and none is named, the result asks you to clarify.
        """
        p = elder(person)
        event = s.reminders.respond(p.id, status, reminder)
        return {"ok": True, "person": p.name, "reminder": event.title, "status": event.status.value}

    @mcp.tool(annotations=_WRITE)
    @_safe
    def create_reminder(
        person: str | None,
        title: str,
        time: str,
        days: str | list[str] | None = None,
        requested_by: str | None = None,
    ) -> dict[str, Any]:
        """Create a recurring reminder for an elder.

        `time` is 24-hour HH:MM in the elder's timezone. `days` is optional: 'daily' (default),
        'weekdays', 'weekends', or names like 'mon,wed,fri'. This is for routines only; never
        use it to change medication doses.
        """
        p = elder(person)
        by = s.people.find(requested_by).id if requested_by else None
        reminder = s.reminders.create(p.id, title, time, days=parse_days(days), created_by=by)
        return {
            "ok": True,
            "reminder_id": reminder.id,
            "person": p.name,
            "title": reminder.title,
            "time": reminder.at_time,
            "days": list(reminder.days),
        }

    @mcp.tool(annotations=_READ)
    @_safe
    def list_reminders(person: str | None = None) -> dict[str, Any]:
        """List an elder's active reminders."""
        p = elder(person)
        return {
            "ok": True,
            "person": p.name,
            "reminders": [
                {"reminder_id": r.id, "title": r.title, "time": r.at_time, "days": list(r.days)}
                for r in s.reminders.list(p.id)
            ],
        }

    @mcp.tool(annotations=_IDEMPOTENT_WRITE)
    @_safe
    def cancel_reminder(reminder_id: int) -> dict[str, Any]:
        """Cancel a reminder by its id (from list_reminders)."""
        r = s.reminders.deactivate(reminder_id)
        return {"ok": True, "cancelled": r.title}

    @mcp.tool(annotations=_WRITE)
    @_safe
    def leave_message(sender: str, recipient: str, message: str, private: bool = False) -> dict[str, Any]:
        """Leave a short message between people in the same family circle.

        Example: sender 'Rahul', recipient 'Amma', message 'I will call at 7'. Elders hear
        pending messages next time get_pending_items is called.
        """
        a, b = s.people.find(sender), s.people.find(recipient)
        msg = s.messages.send(a.id, b.id, message, private=private)
        return {"ok": True, "message_id": msg.id, "from": a.name, "to": b.name}

    @mcp.tool(annotations=_WRITE)
    @_safe
    def raise_alert(person: str | None, reason: str, severity: str = "attention") -> dict[str, Any]:
        """Manually alert an elder's caregivers. `severity` is 'attention' or 'urgent'.

        Use when the person asks you to contact family ('tell my son I need him').
        """
        p = elder(person)
        try:
            level = Severity[severity.strip().upper()]
        except KeyError as exc:
            raise ValidationError("Severity must be 'attention' or 'urgent'") from exc
        if level is Severity.INFO:
            raise ValidationError("Severity must be 'attention' or 'urgent'")
        raised = s.alerts.raise_alert(p.id, level, AlertKind.MANUAL, f"{p.name}: {reason.strip()}")
        return {
            "ok": True,
            "alert_id": raised.alert.id,
            "new": raised.created,
            "will_notify": [r.name for r in s.alerts.recipients(raised.alert)],
        }

    @mcp.tool(annotations=_IDEMPOTENT_WRITE)
    @_safe
    def acknowledge_alert(alert_id: int) -> dict[str, Any]:
        """A caregiver confirms they have seen and handled an alert."""
        alert = s.alerts.acknowledge(alert_id)
        return {"ok": True, "alert_id": alert.id, "acknowledged": True}

    @mcp.tool(annotations=_READ)
    @_safe
    def get_recent_alerts(person: str | None = None, limit: int = 10) -> dict[str, Any]:
        """Recent alerts for an elder, newest first."""
        p = elder(person)
        limit = max(1, min(limit, 50))
        return {
            "ok": True,
            "person": p.name,
            "alerts": [
                {
                    "alert_id": a.id,
                    "severity": a.severity.label,
                    "kind": a.kind.value,
                    "when": local(p, a.created_at),
                    "detail": a.detail,
                    "acknowledged": a.acknowledged_at is not None,
                }
                for a in s.alerts.list_for(p.id, limit=limit)
            ],
        }

    @mcp.tool(annotations=_READ)
    @_safe
    def get_daily_summary(person: str | None = None, day: str | None = None) -> dict[str, Any]:
        """Plain-language digest of an elder's day for a caregiver.

        `day` is YYYY-MM-DD, 'today' (default) or 'yesterday'.
        """
        p = elder(person)
        today = local_date(s.clock.now(), get_zone(p.timezone))
        return {"ok": True, **s.summaries.build(p.id, _parse_day(day, today)).to_dict()}

    @mcp.tool(annotations=_READ)
    @_safe
    def get_missed_checkins() -> dict[str, Any]:
        """Which elders have not checked in yet today, and whether they are only 'due' or 'missed'."""
        return {
            "ok": True,
            "elders": [
                {
                    "person": st.person.name,
                    "state": st.state,
                    "expected_by": local(st.person, st.deadline),
                }
                for st in s.monitor.checkin_statuses()
            ],
        }

    @mcp.tool(annotations=_READ)
    @_safe
    def list_people() -> dict[str, Any]:
        """Everyone in CareCircle, with roles and who they care for."""
        people = []
        for p in s.people.list():
            entry: dict[str, Any] = {"name": p.name, "role": p.role.value, "language": p.language}
            if p.role is not Role.ELDER:
                entry["cares_for"] = [e.name for e in s.people.elders_of(p.id)]
            people.append(entry)
        return {"ok": True, "people": people}

    # ---- resources -------------------------------------------------------------------
    @mcp.resource(
        "care://people/{person}/timeline",
        name="timeline",
        title="Seven-day timeline",
        description="JSON digest of an elder's last seven days.",
        mime_type="application/json",
    )
    def timeline(person: str) -> str:
        p = s.people.find(person, Role.ELDER)
        today = local_date(s.clock.now(), get_zone(p.timezone))
        days = [s.summaries.build(p.id, today - timedelta(days=i)).to_dict() for i in range(7)]
        return json.dumps({"person": p.name, "days": days}, ensure_ascii=False, indent=2)

    # ---- prompts ---------------------------------------------------------------------
    @mcp.prompt(title="Check-in conversation", description="Script for a warm daily check-in.")
    def checkin_conversation(person: str = "") -> str:
        p = elder(person or None)
        language = {"hi": "Hindi", "mr": "Marathi", "en": "English"}.get(p.language, p.language)
        return (
            f"You are a gentle voice companion for {p.name}. Speak in {language}, in short, warm "
            "sentences. 1) Greet them and ask how they feel today. 2) Call log_checkin with their "
            "exact words. 3) Call get_pending_items and read out due reminders and family messages. "
            "4) When they say they took something, call confirm_reminder. 5) If they ask you to "
            "contact family, use leave_message or raise_alert. Never diagnose or advise on medicine. "
            "If log_checkin reports a concern, follow assistant_guidance exactly."
        )

    return mcp
