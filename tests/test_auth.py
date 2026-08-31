"""Tests for HTTP Basic Auth and access control across all routes."""
import base64
import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _basic_auth_header(username, password):
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}"}


PROTECTED_ROUTES = [
    "/",
    "/dashboard",
    "/journey",
    "/retention",
    "/cohorts",
    "/funnels",
    "/events",
    "/settings",
    "/api/status",
]


@pytest.mark.parametrize("route", PROTECTED_ROUTES)
def test_unauthenticated_requests_blocked(client, route):
    response = client.get(route)
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


@pytest.mark.parametrize("route", PROTECTED_ROUTES)
def test_invalid_credentials_blocked(client, route):
    headers = _basic_auth_header("wrong_user", "wrong_pass")
    response = client.get(route, headers=headers)
    assert response.status_code == 401


from magnetar.config import DASH_PASS, DASH_USER


def test_valid_credentials_granted(client):
    headers = _basic_auth_header(DASH_USER, DASH_PASS)
    response = client.get("/dashboard", headers=headers)
    assert response.status_code == 200


def test_health_check_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json["status"] == "ok"
