"""HTTP-layer tests: health, bearer auth, host protection."""

from __future__ import annotations

from dataclasses import replace

import pytest
from starlette.testclient import TestClient

from carecircle.app import create_app, transport_security
from carecircle.config import Settings
from carecircle.services import build_services

INIT = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


def make_client(svc, **overrides) -> TestClient:
    settings = replace(svc.settings, **overrides)
    services = build_services(settings, db=svc.db, clock=svc.clock)
    return TestClient(create_app(services), base_url="http://127.0.0.1:8000")


def test_health_is_open_and_reports_auth_mode(svc, family):
    with make_client(svc, mcp_token="tok") as client:
        body = client.get("/health").json()
    assert body["status"] == "ok" and body["elders"] == 1 and body["auth"] == "bearer"


@pytest.mark.parametrize("auth", [None, "Bearer wrong", "Basic tok", "tok"])
def test_mcp_requires_exact_bearer_token(svc, auth):
    headers = dict(HEADERS, **({"authorization": auth} if auth else {}))
    with make_client(svc, mcp_token="tok") as client:
        response = client.post("/mcp", json=INIT, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_valid_token_reaches_mcp(svc):
    headers = dict(HEADERS, authorization="Bearer tok")
    with make_client(svc, mcp_token="tok") as client:
        response = client.post("/mcp", json=INIT, headers=headers)
    assert response.status_code not in (401, 421)


def test_no_token_configured_means_open(svc):
    with make_client(svc) as client:
        response = client.post("/mcp", json=INIT, headers=HEADERS)
    assert response.status_code not in (401, 421)


def test_foreign_host_header_is_rejected(svc):
    with make_client(svc) as client:
        response = client.post("/mcp", json=INIT, headers=dict(HEADERS, host="evil.example.com"))
    assert response.status_code == 421


def test_allowed_hosts_extend_protection(svc):
    settings = replace(svc.settings, allowed_hosts=("care.example.com",))
    security = transport_security(settings)
    assert security.enable_dns_rebinding_protection
    assert "care.example.com" in security.allowed_hosts
    assert "https://care.example.com" in security.allowed_origins
