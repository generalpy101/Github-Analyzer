"""Tests for chat feature — DB, API endpoints, and context builder."""

import json
from unittest.mock import patch

import pytest

import server.db as db_module
from server.db import (
    init_db, create_run, update_run, get_chat_messages, add_chat_message,
    delete_chat_messages,
)
from app import app as flask_app


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    test_db = str(tmp_path / "test.db")
    with patch.object(db_module, "DB_PATH", test_db):
        with patch.object(db_module, "LEGACY_DB_PATH", str(tmp_path / "legacy.db")):
            init_db()
            yield


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.fixture
def run_with_review():
    rid = create_run("testuser", "anthropic", "claude")
    review = {"username": "testuser", "overall_score": 60, "is_ai_generated": True,
              "headline": "Test", "repository_reviews": [], "summary": "Summary.",
              "profile_review": {"score": 50, "strengths": [], "improvements": []},
              "code_review": {"score": 50}, "repo_presentation": {"score": 50},
              "activity_review": {"score": 50}}
    update_run(rid, status="success", review_json=json.dumps(review),
               github_data_json=json.dumps({"username": "testuser", "profile": {"bio": "Dev"}}))
    return rid


class TestChatDb:
    def test_add_and_get(self):
        rid = create_run("u")
        add_chat_message(rid, "user", "Hello")
        add_chat_message(rid, "assistant", "Hi there!")
        msgs = get_chat_messages(rid)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["content"] == "Hi there!"

    def test_empty_history(self):
        rid = create_run("u")
        assert get_chat_messages(rid) == []

    def test_delete_messages(self):
        rid = create_run("u")
        add_chat_message(rid, "user", "msg1")
        add_chat_message(rid, "assistant", "msg2")
        delete_chat_messages(rid)
        assert get_chat_messages(rid) == []

    def test_messages_scoped_to_run(self):
        rid1 = create_run("u1")
        rid2 = create_run("u2")
        add_chat_message(rid1, "user", "for run 1")
        add_chat_message(rid2, "user", "for run 2")
        assert len(get_chat_messages(rid1)) == 1
        assert len(get_chat_messages(rid2)) == 1


class TestChatApiGet:
    def test_get_history(self, client, run_with_review):
        resp = client.get("/api/chat/{}".format(run_with_review))
        assert resp.status_code == 200
        data = resp.get_json()
        assert "messages" in data
        assert data["messages"] == []

    def test_get_nonexistent_run(self, client):
        resp = client.get("/api/chat/99999")
        assert resp.status_code == 404


class TestChatApiPost:
    def test_empty_message(self, client, run_with_review):
        resp = client.post("/api/chat/{}".format(run_with_review),
                           json={"message": ""})
        assert resp.status_code == 400

    def test_no_body(self, client, run_with_review):
        resp = client.post("/api/chat/{}".format(run_with_review), json={})
        assert resp.status_code == 400

    def test_nonexistent_run(self, client):
        resp = client.post("/api/chat/99999", json={"message": "hi"})
        assert resp.status_code == 404

    def test_successful_chat(self, client, run_with_review):
        with patch("app.chat_with_review", return_value="Here is my advice..."):
            resp = client.post("/api/chat/{}".format(run_with_review),
                               json={"message": "How to improve?"})
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["response"] == "Here is my advice..."
            assert len(data["messages"]) == 2

    def test_chat_error_handled(self, client, run_with_review):
        with patch("app.chat_with_review", side_effect=Exception("API timeout")):
            resp = client.post("/api/chat/{}".format(run_with_review),
                               json={"message": "test"})
            assert resp.status_code == 200
            data = resp.get_json()
            assert "error" in data["response"].lower() or "API timeout" in data["response"]
