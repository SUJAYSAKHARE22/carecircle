from __future__ import annotations

from dataclasses import replace

import pytest
from starlette.testclient import TestClient

from carecircle.app import create_app
from carecircle.clock import OffsetClock
from carecircle.config import Settings
from carecircle.db import Database
from carecircle.models import Role
from carecircle.notifier import RecordingNotifier
from carecircle.services import build_services
from carecircle.web import CSP

H = {"X-Requested-With": "carecircle"}


def make(svc=None, **overrides):
    if svc is not None:
        settings = replace(svc.settings, **overrides)
        services = build_services(settings, db=svc.db, clock=svc.clock, notifier=RecordingNotifier())
    else:
        services = build_services(Settings(db_path=":memory:", **overrides), db=Database(":memory:"),
                                  notifier=RecordingNotifier())
    return services, TestClient(create_app(services), base_url="http://127.0.0.1:8000")


@pytest.fixture
def client(svc, family):
    services, c = make(svc)
    with c:
        yield c


def test_config_and_overview(client):
    cfg = client.get("/api/config").json()
    assert cfg["demo"] is False and cfg["llm"] is False and cfg["checkin_deadline"] == "10:00"
    data = client.get("/api/overview").json()
    assert {p["name"] for p in data["people"]} == {"Amma", "Rahul", "Priya"}
    amma = data["elders"][0]
    assert amma["name"] == "Amma" and amma["checkin_state"] == "ok"
    assert [m["relation"] for m in amma["members"]] == ["son", "daughter"]
    assert client.get("/api/overview").headers["cache-control"] == "no-store"


def test_mutations_require_csrf_header(client):
    assert client.post("/api/messages", json={"from": "Rahul", "to": "Amma", "body": "hi"}).status_code == 403
    assert client.delete("/api/reminders/1").status_code == 403
    assert client.post("/api/sim/turn", json={"text": "hi"}).status_code == 403


def test_reminder_crud(client):
    body = {"person": "Amma", "title": "BP tablet", "time": "08:00", "days": "weekdays", "requested_by": "Rahul"}
    created = client.post("/api/reminders", json=body, headers=H)
    assert created.status_code == 201
    overview = client.get("/api/overview").json()["elders"][0]
    assert overview["reminders"][0]["days"] == [0, 1, 2, 3, 4]
    assert client.delete(f"/api/reminders/{created.json()['id']}", headers=H).json() == {"ok": True}
    assert client.get("/api/overview").json()["elders"][0]["reminders"] == []


@pytest.mark.parametrize(
    "path, body, status",
    [("/api/reminders", {"person": "Amma", "title": "", "time": "08:00"}, 400),
     ("/api/reminders", {"person": "Amma", "title": "x", "time": "99:99"}, 400),
     ("/api/reminders", {"person": "Nobody", "title": "x", "time": "08:00"}, 404),
     ("/api/messages", {"from": "Rahul", "to": "Amma", "body": ""}, 400),
     ("/api/messages", {"from": "Rahul", "to": 5, "body": "x"}, 400)],
)
def test_validation_errors_are_http_errors(client, path, body, status):
    response = client.post(path, json=body, headers=H)
    assert response.status_code == status and "error" in response.json()


def test_bad_json_and_non_object(client):
    assert client.post("/api/messages", content=b"{nope", headers=H).status_code == 400
    assert client.post("/api/messages", content=b"[1,2]", headers=H).status_code == 400


def test_message_and_alert_ack_flow(client, svc, family):
    amma, *_ = family
    assert client.post("/api/messages", json={"from": "Rahul", "to": "Amma", "body": "Call at 7"}, headers=H).status_code == 201
    assert client.get("/api/overview").json()["elders"][0]["unread_messages"] == 1
    alert = svc.checkins.log(amma.id, "I fell").alert.alert
    shown = client.get("/api/overview").json()["elders"][0]["alerts"][0]
    assert shown["id"] == alert.id and shown["severity"] == "urgent" and not shown["acknowledged"]
    assert client.post(f"/api/alerts/{alert.id}/ack", headers=H).json()["ok"]
    assert client.get("/api/overview").json()["elders"][0]["alerts"][0]["acknowledged"]
    assert client.post("/api/alerts/9999/ack", headers=H).status_code == 404


def test_timeline(client):
    data = client.get("/api/timeline/Amma").json()
    assert data["person"] == "Amma" and len(data["days"]) == 7
    assert client.get("/api/timeline/Rahul").status_code == 404  # not an elder


def test_sim_turn_over_http(client):
    r = client.post("/api/sim/turn", json={"person": "Amma", "text": "I feel dizzy", "lang": "en"}, headers=H)
    body = r.json()
    assert r.status_code == 200 and body["agent"] == "rules" and body["tool_calls"][0]["name"] == "log_checkin"
    assert body["tool_calls"][0]["result"]["concern_level"] == "attention"
    assert client.post("/api/sim/turn", json={"person": "Amma", "text": ""}, headers=H).status_code == 400


def test_demo_endpoints_forbidden_unless_demo(client):
    for path in ("/api/demo/advance", "/api/demo/tick", "/api/demo/reset-clock"):
        assert client.post(path, json={"minutes": 5}, headers=H).status_code == 403


def test_demo_time_travel_triggers_escalation():
    services, c = make(demo_mode=True)
    assert isinstance(services.clock, OffsetClock)
    amma = services.people.create("Amma", Role.ELDER)
    rahul = services.people.create("Rahul", Role.CAREGIVER, telegram_chat_id="1")
    services.people.link(amma.id, rahul.id, "son")
    with c:
        assert c.post("/api/demo/advance", json={"minutes": 0}, headers=H).status_code == 400
        assert c.post("/api/demo/advance", json={"minutes": 5000}, headers=H).status_code == 400
        # jump a full day plus: whatever the wall clock is, the check-in deadline passes
        for _ in range(2):
            c.post("/api/demo/advance", json={"minutes": 24 * 60 - 1}, headers=H)
        assert c.post("/api/demo/tick", headers=H).json()["ok"]
        assert c.post("/api/demo/reset-clock", headers=H).json() == {"ok": True}
    assert services.clock.offset.total_seconds() == 0


def test_bearer_protects_api_but_not_pages_or_health(svc, family):
    _, c = make(svc, mcp_token="tok")
    with c:
        assert c.get("/api/overview").status_code == 401
        assert c.get("/api/overview", headers={"Authorization": "Bearer tok"}).status_code == 200
        assert c.get("/health").status_code == 200
        assert c.get("/dashboard").status_code == 200


def test_host_guard_applies_to_api(svc, family):
    _, c = make(svc)
    with c:
        assert c.get("/api/overview", headers={"host": "evil.example.com"}).status_code == 421
        assert c.get("/health", headers={"host": "evil.example.com"}).status_code == 421


# ---------------------------------------------------------------- static pages
@pytest.mark.parametrize("path, marker", [("/", "CareCircle"), ("/sim", "Alexa+ simulator"), ("/dashboard", "Caregiver dashboard")])
def test_pages_served_with_strict_csp(client, path, marker):
    r = client.get(path)
    assert r.status_code == 200 and marker in r.text
    assert r.headers["content-security-policy"] == CSP and "script-src 'self'" in CSP
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "<script>" not in r.text and "style=" not in r.text  # nothing the CSP would block


@pytest.mark.parametrize("asset", ["common.css", "common.js", "home.js", "simulator.js", "dashboard.js"])
def test_assets_served(client, asset):
    r = client.get(f"/static/{asset}")
    assert r.status_code == 200 and len(r.content) > 100


def test_asset_whitelist_blocks_traversal(client):
    for name in ("../app.py", "..%2Fapp.py", "secret.txt", "simulator.html"):
        assert client.get(f"/static/{name}").status_code == 404


def test_every_script_and_stylesheet_referenced_is_served(client):
    import re

    for page in ("/", "/sim", "/dashboard"):
        html = client.get(page).text
        for ref in re.findall(r'(?:src|href)="(/static/[^"]+)"', html):
            assert client.get(ref).status_code == 200, f"{page} references missing {ref}"
