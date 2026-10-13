"""End-to-end tests through a real MCP client against the in-memory server."""

from __future__ import annotations

import json

import pytest
from mcp import Client

from carecircle.server import build_server


@pytest.fixture
def server(svc, family):
    return build_server(svc)


async def call(client: Client, name: str, **args):
    result = await client.call_tool(name, args)
    assert not result.is_error, result
    return result.structured_content


async def test_tool_catalog(server):
    async with Client(server) as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert {
            "log_checkin", "get_pending_items", "confirm_reminder", "create_reminder",
            "list_reminders", "cancel_reminder", "leave_message", "raise_alert",
            "acknowledge_alert", "get_recent_alerts", "get_daily_summary",
            "get_missed_checkins", "list_people",
        } <= names
        assert client.instructions and "not an emergency service" in client.instructions


async def test_single_elder_is_default(server):
    async with Client(server) as client:
        data = await call(client, "log_checkin", note="Good morning", mood="good")
        assert data["ok"] and data["person"] == "Amma" and data["concern_level"] == "info"
        assert data["first_checkin_today"] and not data["family_alerted"]


async def test_urgent_flow_alerts_family(server):
    async with Client(server) as client:
        data = await call(client, "log_checkin", person="Amma", note="I fell in the bathroom")
        assert data["concern_level"] == "urgent" and data["family_alerted"]
        assert data["will_notify"] == ["Rahul"]
        assert "emergency number" in data["assistant_guidance"]
        alerts = await call(client, "get_recent_alerts")
        assert alerts["alerts"][0]["severity"] == "urgent"
        ack = await call(client, "acknowledge_alert", alert_id=alerts["alerts"][0]["alert_id"])
        assert ack["acknowledged"]


async def test_reminder_lifecycle_with_clarification(server, clock):
    async with Client(server) as client:
        await call(client, "create_reminder", person="Amma", title="BP tablet", time="08:00", requested_by="Rahul")
        await call(client, "create_reminder", person="Amma", title="Vitamin D", time="08:00", days="daily")
        clock.advance(minutes=40)
        pending = await call(client, "get_pending_items")
        assert {r["reminder"] for r in pending["reminders_due"]} == {"BP tablet", "Vitamin D"}
        ask = await call(client, "confirm_reminder", status="taken")
        assert ask["needs_clarification"] and set(ask["options"]) == {"BP tablet", "Vitamin D"}
        done = await call(client, "confirm_reminder", status="taken", reminder="blood pressure tablet")
        assert done["reminder"] == "BP tablet" and done["status"] == "taken"
        listed = await call(client, "list_reminders")
        assert len(listed["reminders"]) == 2
        cancelled = await call(client, "cancel_reminder", reminder_id=listed["reminders"][0]["reminder_id"])
        assert cancelled["ok"]


async def test_messages_are_read_once(server):
    async with Client(server) as client:
        await call(client, "leave_message", sender="Rahul", recipient="Amma", message="I'll call at 7")
        first = await call(client, "get_pending_items")
        assert first["messages"][0]["from"] == "Rahul"
        assert (await call(client, "get_pending_items"))["messages"] == []


async def test_domain_errors_are_structured_not_exceptions(server):
    async with Client(server) as client:
        bad = await call(client, "log_checkin", person="Nobody")
        assert bad["ok"] is False and "couldn't find" in bad["error"]
        bad = await call(client, "create_reminder", person="Amma", title="x", time="99:99")
        assert bad["ok"] is False
        bad = await call(client, "raise_alert", person="Amma", reason="x", severity="info")
        assert bad["ok"] is False


async def test_manual_alert_and_summary(server):
    async with Client(server) as client:
        alert = await call(client, "raise_alert", person="Amma", reason="wants me to visit", severity="urgent")
        assert alert["new"] and alert["will_notify"] == ["Rahul"]
        await call(client, "log_checkin", note="morning", mood=5)
        summary = await call(client, "get_daily_summary", day="today")
        assert summary["checked_in"] and summary["mood_label"] == "great"
        assert (await call(client, "get_daily_summary", day="nonsense"))["ok"] is False


async def test_missed_checkins_and_people(server, clock):
    async with Client(server) as client:
        clock.advance(hours=3)  # 10:30 local
        states = await call(client, "get_missed_checkins")
        assert states["elders"][0]["state"] == "due"
        clock.advance(hours=1)
        assert (await call(client, "get_missed_checkins"))["elders"][0]["state"] == "missed"
        people = await call(client, "list_people")
        assert {p["name"] for p in people["people"]} == {"Amma", "Rahul", "Priya"}


async def test_multiple_elders_require_a_name(svc, family):
    from carecircle.models import Role

    svc.people.create("Dadi", Role.ELDER)
    async with Client(build_server(svc)) as c:
        data = (await c.call_tool("log_checkin", {"note": "hi"})).structured_content
        assert data["needs_clarification"] and set(data["options"]) == {"Amma", "Dadi"}


async def test_resource_and_prompt(server):
    async with Client(server) as client:
        await call(client, "log_checkin", note="morning")
        resources = await client.list_resource_templates()
        assert any("timeline" in t.uri_template for t in resources.resource_templates)
        content = await client.read_resource("care://people/Amma/timeline")
        payload = json.loads(content.contents[0].text)
        assert payload["person"] == "Amma" and len(payload["days"]) == 7
        prompt = await client.get_prompt("checkin_conversation", {"person": "Amma"})
        assert "Hindi" in prompt.messages[0].content.text
