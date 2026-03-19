"""Tests for server/db.py — database operations."""

import os
import tempfile
from unittest.mock import patch

import pytest

import server.db as db_module
from server.db import (
    init_db, create_run, update_run, get_run, get_latest_run,
    get_run_history, delete_run, mark_run_error, cancel_stale_runs,
)


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Redirect DB to a temp file for each test."""
    test_db = str(tmp_path / "test.db")
    with patch.object(db_module, "DB_PATH", test_db):
        with patch.object(db_module, "LEGACY_DB_PATH", str(tmp_path / "legacy.db")):
            init_db()
            yield test_db


class TestCreateAndGetRun:
    def test_create_returns_id(self):
        rid = create_run("testuser", "anthropic", "claude")
        assert isinstance(rid, int)
        assert rid > 0

    def test_get_run(self):
        rid = create_run("testuser")
        run = get_run(rid)
        assert run is not None
        assert run["username"] == "testuser"
        assert run["status"] == "pending"

    def test_get_nonexistent(self):
        assert get_run(99999) is None


class TestUpdateRun:
    def test_update_status(self):
        rid = create_run("user1")
        update_run(rid, status="success", overall_score=75)
        run = get_run(rid)
        assert run["status"] == "success"
        assert run["overall_score"] == 75

    def test_update_ignores_unknown_fields(self):
        rid = create_run("user1")
        update_run(rid, unknown_field="ignored")
        run = get_run(rid)
        assert run["status"] == "pending"


class TestHistory:
    def test_get_run_history(self):
        create_run("user1")
        create_run("user2")
        history = get_run_history(limit=10)
        assert len(history) == 2

    def test_history_limit(self):
        for i in range(5):
            create_run("user{}".format(i))
        history = get_run_history(limit=3)
        assert len(history) == 3

    def test_get_latest_run(self):
        rid1 = create_run("same_user")
        rid2 = create_run("same_user")
        latest = get_latest_run("same_user")
        assert latest["id"] in (rid1, rid2)
        assert latest["username"] == "same_user"


class TestDeleteRun:
    def test_delete(self):
        rid = create_run("user1")
        delete_run(rid)
        assert get_run(rid) is None

    def test_delete_nonexistent(self):
        delete_run(99999)


class TestMarkError:
    def test_mark_pending_as_error(self):
        rid = create_run("user1")
        mark_run_error(rid)
        run = get_run(rid)
        assert run["status"] == "error"

    def test_mark_only_pending(self):
        rid = create_run("user1")
        update_run(rid, status="success")
        mark_run_error(rid)
        run = get_run(rid)
        assert run["status"] == "success"


class TestCancelStaleRuns:
    def test_cancels_pending(self):
        rid1 = create_run("user1")
        rid2 = create_run("user2")
        update_run(rid2, status="success")
        cancel_stale_runs()
        assert get_run(rid1)["status"] == "error"
        assert get_run(rid2)["status"] == "success"
