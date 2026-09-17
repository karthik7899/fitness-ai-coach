"""Credentials entered through the UI."""

import pytest
from fastapi.testclient import TestClient

from app import settings_store
from app.config import settings as env_settings
from app.db import get_session
from app.main import app
from app.routers import settings as settings_router

SECRET = "AIzaSyTESTKEYVALUE0123456789abcd"


@pytest.fixture
def client(session, monkeypatch):
    # Never reach Google from a test.
    async def fake_verify(api_key: str, model: str):
        return (True, None) if api_key == SECRET else (False, "API key not valid.")

    monkeypatch.setattr(settings_router, "_verify", fake_verify)
    monkeypatch.setattr(env_settings, "gemini_api_key", "")
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_reports_nothing_configured_initially(client):
    gemini = client.get("/api/settings").json()["gemini"]
    assert gemini["configured"] is False
    assert gemini["source"] is None
    assert gemini["hint"] is None
    assert gemini["can_clear"] is False


def test_saving_a_key_verifies_it(client):
    body = client.put("/api/settings/gemini", json={"api_key": SECRET}).json()
    assert body["verified"] is True
    assert body["error"] is None
    assert body["gemini"]["configured"] is True
    assert body["gemini"]["source"] == "ui"
    assert body["gemini"]["can_clear"] is True


def test_a_bad_key_is_saved_but_reported_as_unverified(client):
    body = client.put("/api/settings/gemini", json={"api_key": "nonsense"}).json()
    assert body["verified"] is False
    assert "not valid" in body["error"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("400 INVALID_ARGUMENT {'error': {'status': 'API_KEY_INVALID'}}", "rejected by Google"),
        ("403 PERMISSION_DENIED for project", "lacks access"),
        ("429 RESOURCE_EXHAUSTED quota", "rate limited"),
    ],
)
def test_google_errors_are_made_readable(raw, expected):
    assert expected in settings_router._readable(Exception(raw))


def test_the_key_is_never_returned(client):
    client.put("/api/settings/gemini", json={"api_key": SECRET})
    for payload in (client.get("/api/settings").text, client.get("/api/settings").json()):
        assert SECRET not in str(payload)


def test_only_the_last_four_characters_are_shown(client):
    client.put("/api/settings/gemini", json={"api_key": SECRET})
    assert client.get("/api/settings").json()["gemini"]["hint"] == f"…{SECRET[-4:]}"


def test_clearing_removes_the_key(client):
    client.put("/api/settings/gemini", json={"api_key": SECRET})
    assert client.delete("/api/settings/gemini").status_code == 204
    assert client.get("/api/settings").json()["gemini"]["configured"] is False


def test_model_can_be_set_independently(client):
    body = client.put("/api/settings/gemini", json={"model": "gemini-3.5-flash"}).json()
    assert body["gemini"]["model"] == "gemini-3.5-flash"
    assert body["gemini"]["model_source"] == "ui"
    # No key yet, so nothing to verify against.
    assert body["verified"] is False


def test_an_empty_request_is_rejected(client):
    assert client.put("/api/settings/gemini", json={}).status_code == 400


def test_whitespace_only_values_are_treated_as_absent(client):
    assert client.put("/api/settings/gemini", json={"api_key": "   "}).status_code == 400


def test_a_stored_key_overrides_the_environment(session, monkeypatch):
    monkeypatch.setattr(env_settings, "gemini_api_key", "from-dotenv")
    assert settings_store.gemini_api_key(session) == ("from-dotenv", "env")

    settings_store.put(session, settings_store.GEMINI, {"api_key": SECRET})
    assert settings_store.gemini_api_key(session) == (SECRET, "ui")


def test_an_env_key_cannot_be_cleared_from_the_ui(session, monkeypatch):
    monkeypatch.setattr(env_settings, "gemini_api_key", "from-dotenv")
    described = settings_store.describe(session)["gemini"]
    assert described["configured"] is True
    assert described["source"] == "env"
    assert described["can_clear"] is False, "no button for something the UI cannot do"
