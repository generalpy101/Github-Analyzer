"""Integration tests for Flask app routes."""

import pytest

from app import app as flask_app


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


class TestPageRoutes:
    def test_home(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"GitHub Review" in resp.data

    def test_settings(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert b"Settings" in resp.data

    def test_404(self, client):
        resp = client.get("/nonexistent-page")
        assert resp.status_code == 404


class TestApiRoutes:
    def test_history(self, client):
        resp = client.get("/api/history")
        assert resp.status_code == 200
        assert resp.content_type == "application/json"

    def test_settings_get(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "provider" in data
        assert "extended_thinking" in data
        assert "batch_size" in data

    def test_ai_status(self, client):
        resp = client.get("/api/ai-status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "configured" in data

    def test_active_generation(self, client):
        resp = client.get("/api/active-generation")
        assert resp.status_code == 200

    def test_invalid_username(self, client):
        resp = client.post("/api/generate/!!!invalid!!!")
        assert resp.status_code == 400

    def test_nonexistent_report(self, client):
        resp = client.get("/report/99999/")
        assert resp.status_code == 404

    def test_nonexistent_repo_detail(self, client):
        resp = client.get("/report/99999/repo/fake")
        assert resp.status_code == 404


class TestHomeFeatures:
    def test_filter_checkboxes(self, client):
        resp = client.get("/")
        assert b"filter-public" in resp.data
        assert b"filter-private" in resp.data
        assert b"filter-forked" in resp.data
        assert b"filter-archived" in resp.data

    def test_settings_has_thinking_toggle(self, client):
        resp = client.get("/settings")
        assert b"thinking-toggle" in resp.data

    def test_settings_has_batch_size(self, client):
        resp = client.get("/settings")
        assert b"batch-size-input" in resp.data
