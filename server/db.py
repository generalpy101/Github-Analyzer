"""SQLite database layer for storing analysis runs."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime

# In frozen (PyInstaller) mode, store DB next to the executable
if getattr(sys, "frozen", False):
    _base = os.path.dirname(sys.executable)
else:
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join(_base, "runtime", "db", "github_review.db")
LEGACY_DB_PATH = os.path.join(_base, "github_review.db")


def _get_conn():
    """Get a database connection with WAL mode and row factory."""
    _ensure_db_location()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            provider TEXT,
            model TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            overall_score INTEGER DEFAULT 0,
            is_ai_generated INTEGER NOT NULL DEFAULT 0,
            github_data_json TEXT,
            review_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_runs_username ON runs(username);
        CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at);

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_chat_run_id ON chat_messages(run_id);
    """)
    conn.close()


def create_run(username, provider=None, model=None):
    """Insert a new run and return its ID."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO runs (username, provider, model) VALUES (?, ?, ?)",
        (username, provider, model),
    )
    run_id = cur.lastrowid
    conn.commit()
    conn.close()
    return run_id


def update_run(run_id, **kwargs):
    """Update columns on a run. Only known columns are accepted."""
    allowed = {
        "status", "overall_score", "is_ai_generated",
        "github_data_json", "review_json", "provider", "model",
    }
    filtered = {k: v for k, v in kwargs.items() if k in allowed}
    if not filtered:
        return
    cols = ", ".join("{} = ?".format(k) for k in filtered)
    vals = list(filtered.values()) + [run_id]
    conn = _get_conn()
    conn.execute("UPDATE runs SET {} WHERE id = ?".format(cols), vals)
    conn.commit()
    conn.close()


def get_run(run_id):
    """Fetch a single run by ID. Returns dict or None."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)


def get_latest_run(username):
    """Fetch the most recent run for a username. Returns dict or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM runs WHERE username = ? ORDER BY created_at DESC LIMIT 1",
        (username,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return dict(row)


def get_run_history(limit=50):
    """Fetch recent runs ordered by created_at desc."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, username, created_at, provider, model, status, "
        "overall_score, is_ai_generated FROM runs "
        "ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_user_runs(username):
    """Fetch all runs for a specific username, newest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, username, created_at, provider, model, status, "
        "overall_score, is_ai_generated FROM runs "
        "WHERE username = ? ORDER BY created_at DESC",
        (username,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cancel_stale_runs():
    """Mark ALL pending runs as error on startup.

    At app startup there can be no legitimately running generations,
    so any pending run is stale (left behind by a crash or Ctrl-C).
    """
    conn = _get_conn()
    conn.execute("UPDATE runs SET status = 'error' WHERE status = 'pending'")
    conn.commit()
    conn.close()


def delete_run(run_id):
    """Delete a run from the database."""
    conn = _get_conn()
    conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
    conn.commit()
    conn.close()


def mark_run_error(run_id):
    """Mark a specific run as error (cancelled)."""
    conn = _get_conn()
    conn.execute(
        "UPDATE runs SET status = 'error' WHERE id = ? AND status = 'pending'",
        (run_id,),
    )
    conn.commit()
    conn.close()


def get_chat_messages(run_id):
    """Fetch all chat messages for a run, ordered chronologically."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, created_at FROM chat_messages "
        "WHERE run_id = ? ORDER BY id ASC",
        (run_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_chat_message(run_id, role, content):
    """Insert a chat message and return its ID."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO chat_messages (run_id, role, content) VALUES (?, ?, ?)",
        (run_id, role, content),
    )
    msg_id = cur.lastrowid
    conn.commit()
    conn.close()
    return msg_id


def delete_chat_messages(run_id):
    """Delete all chat messages for a run."""
    conn = _get_conn()
    conn.execute("DELETE FROM chat_messages WHERE run_id = ?", (run_id,))
    conn.commit()
    conn.close()


def _ensure_db_location():
    """Create runtime DB directory and migrate legacy DB files if present."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH) or not os.path.exists(LEGACY_DB_PATH):
        return

    try:
        os.replace(LEGACY_DB_PATH, DB_PATH)
        for suffix in ("-wal", "-shm"):
            legacy_sidecar = LEGACY_DB_PATH + suffix
            runtime_sidecar = DB_PATH + suffix
            if os.path.exists(legacy_sidecar) and not os.path.exists(runtime_sidecar):
                os.replace(legacy_sidecar, runtime_sidecar)
    except OSError:
        # Non-fatal; sqlite will create DB_PATH if migration cannot happen.
        pass
