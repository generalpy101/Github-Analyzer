#!/usr/bin/env python3
"""
GitHub Review — Local web app.

Usage:
    pip install -r requirements.txt
    python3 app.py
    # Open http://localhost:5959
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime

from flask import Flask, Response, render_template, request, jsonify

from server.config import load_config, save_config, get_redacted_config
from server.db import (
    init_db, get_run, get_latest_run, get_run_history, cancel_stale_runs,
    delete_run, mark_run_error,
)
from server.generate_report import render_overview, render_repos, render_repo_detail
from server.llm_client import test_connection as _test_llm_connection
from server.generation_manager import (
    start_generation, cancel_generation, get_progress, get_job, get_active_job,
    cleanup_old_jobs,
)

# Support both normal Python and PyInstaller frozen mode
if getattr(sys, "frozen", False):
    # PyInstaller bundles files into _MEIPASS temp directory
    BUNDLE_DIR = sys._MEIPASS
    # Use the directory containing the executable for runtime data/config/db
    BASE_DIR = os.path.dirname(sys.executable)
    TEMPLATES_DIR = os.path.join(BUNDLE_DIR, "templates")
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
app = Flask(__name__, template_folder=TEMPLATES_DIR)

RUNTIME_DATA_ROOT = os.path.join(BASE_DIR, "runtime", "data")
RUNTIME_OUTPUT_ROOT = os.path.join(BASE_DIR, "runtime", "output")
LEGACY_DATA_ROOT = os.path.join(BASE_DIR, "data")
LEGACY_OUTPUT_ROOT = os.path.join(BASE_DIR, "output")

# Initialize database on startup
init_db()
cancel_stale_runs()


def extract_username(input_str):
    """Extract GitHub username from a URL or plain username."""
    input_str = input_str.strip().rstrip("/")
    match = re.match(r"https?://github\.com/([a-zA-Z0-9_-]+)/?.*", input_str)
    if match:
        return match.group(1)
    match = re.match(r"^[a-zA-Z0-9_-]+$", input_str)
    if match:
        return input_str
    return None


def get_history():
    """Get list of analysis runs from the database."""
    runs = get_run_history(limit=50)
    history = []
    for r in runs:
        history.append({
            "id": r["id"],
            "username": r["username"],
            "generated_at": r["created_at"],
            "url": "/report/{}/".format(r["id"]),
            "overall_score": r["overall_score"],
            "status": r["status"],
            "provider": r["provider"] or "",
            "model": r["model"] or "",
            "is_ai_generated": bool(r["is_ai_generated"]),
        })
    return history


def _report_404(run=None, message="The requested page was not found."):
    """Render a context-aware 404 page."""
    return render_template("app_404.html", message=message, run=run), 404


# --- Error Handlers ---

@app.errorhandler(404)
def page_not_found(e):
    return render_template("app_404.html", message="The requested page was not found.", run=None), 404


@app.errorhandler(500)
def internal_error(e):
    return render_template("app_500.html"), 500


# --- Pages ---

@app.route("/")
def home():
    return render_template("app_home.html", history=get_history())


@app.route("/settings")
def settings():
    config = get_redacted_config()
    return render_template("app_settings.html", config=config)


# --- API ---

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify(get_redacted_config())


@app.route("/api/settings", methods=["POST"])
def api_save_settings():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    allowed = {"provider", "model", "api_key", "ollama_url", "top_repos", "batch_size", "extended_thinking"}
    filtered = {k: v for k, v in data.items() if k in allowed}
    save_config(filtered)
    return jsonify({"ok": True, "config": get_redacted_config()})


@app.route("/api/test-connection", methods=["POST"])
def api_test_connection():
    config = load_config()
    data = request.get_json() or {}
    for key in ("provider", "model", "api_key", "ollama_url"):
        if key in data and data[key]:
            config[key] = data[key]
    success, message = _test_llm_connection(config)
    return jsonify({"success": success, "message": message})


@app.route("/api/ai-status")
def api_ai_status():
    """Check if AI is configured and test the connection."""
    config = load_config()
    provider = config.get("provider", "anthropic")

    # Check basic configuration
    if provider != "ollama" and not config.get("api_key"):
        return jsonify({
            "configured": False,
            "connected": False,
            "message": "No API key set. Go to Settings to configure your LLM provider.",
        })

    # Always test actual connection
    success, message = _test_llm_connection(config)
    return jsonify({
        "configured": True,
        "connected": success,
        "message": message,
        "provider": provider,
        "model": config.get("model", ""),
    })


@app.route("/api/check-cache/<username>")
def api_check_cache(username):
    """Check if cached GitHub data exists for this user."""
    clean = extract_username(username)
    if not clean:
        return jsonify({"cached": False})
    data_path = os.path.join(RUNTIME_DATA_ROOT, clean, "github_data.json")
    if not os.path.isfile(data_path):
        # Backward compatibility with legacy location.
        data_path = os.path.join(LEGACY_DATA_ROOT, clean, "github_data.json")
    if os.path.isfile(data_path):
        mtime = os.path.getmtime(data_path)
        fetched_at = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        if os.path.getsize(data_path) > 100:
            return jsonify({"cached": True, "fetched_at": fetched_at, "username": clean})
    return jsonify({"cached": False, "username": clean})


# --- Generation API (background thread) ---

@app.route("/api/generate/<username>", methods=["POST"])
def api_generate(username):
    """Start a background generation. Returns run_id immediately."""
    clean = extract_username(username)
    if not clean:
        return jsonify({"error": "Invalid username: " + username}), 400

    config = load_config()
    use_cache = request.args.get("use_cache") == "1"

    # Check if AI is configured; if not, flag it so pipeline skips LLM
    ai_configured = True
    if config["provider"] != "ollama" and not config.get("api_key"):
        ai_configured = False
    config["_ai_configured"] = ai_configured

    cleanup_old_jobs()

    run_id, error = start_generation(clean, use_cache, config, BASE_DIR, TEMPLATES_DIR)

    if error == "already_running":
        return jsonify({"run_id": run_id, "conflict": True, "username": clean})

    return jsonify({"run_id": run_id, "conflict": False, "username": clean})


@app.route("/api/generation-progress/<int:run_id>")
def api_generation_progress(run_id):
    """SSE endpoint that streams progress from a background generation."""
    def stream():
        idx = 0
        while True:
            events = get_progress(run_id, after_index=idx)
            for evt in events:
                yield "event: {}\ndata: {}\n\n".format(evt["type"], json.dumps(evt["data"]))
                idx += 1
            job = get_job(run_id)
            if not job or job["status"] in ("complete", "error"):
                break
            time.sleep(0.3)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/api/active-generation")
def api_active_generation():
    """Check if a generation is currently running."""
    job = get_active_job()
    if job:
        return jsonify(job)
    return jsonify({"active": False})


@app.route("/api/cancel-generation/<int:run_id>", methods=["POST"])
def api_cancel_generation(run_id):
    """Cancel a running generation."""
    cancelled = cancel_generation(run_id)
    # Also mark in DB in case the thread doesn't get to it
    if cancelled:
        mark_run_error(run_id)
    return jsonify({"cancelled": cancelled})


@app.route("/api/stop-run/<int:run_id>", methods=["POST"])
def api_stop_run(run_id):
    """Stop/cancel any run — works for both active and stale pending runs."""
    # Try cancelling active generation first
    cancelled = cancel_generation(run_id)
    # Mark as error in DB regardless
    mark_run_error(run_id)
    return jsonify({"stopped": True})


@app.route("/api/delete-run/<int:run_id>", methods=["POST"])
def api_delete_run(run_id):
    """Delete a run from history."""
    # Don't delete if it's currently running
    active = get_active_job()
    if active and active.get("run_id") == run_id:
        return jsonify({"error": "Cannot delete a running generation. Stop it first."}), 400
    delete_run(run_id)
    return jsonify({"deleted": True})


@app.route("/api/history")
def api_history():
    return jsonify(get_history())


# --- Dynamic report rendering from DB ---

def _inject_detail_urls(review, run_id):
    """Add _detail_url to each repo review so cards link to the deep-dive page."""
    for r in review.get("repository_reviews", []):
        r["_detail_url"] = "/report/{}/repo/{}".format(run_id, r.get("repo_name", ""))


@app.route("/report/<int:run_id>/")
def serve_report(run_id):
    """Render overview page dynamically from DB."""
    run = get_run(run_id)
    if not run:
        return _report_404(message="Review not found.")
    if not run.get("review_json"):
        if run["status"] == "pending":
            return _report_404(run=run, message="This review is still being generated. Check back shortly.")
        return _report_404(run=run, message="This review was cancelled before it completed.")
    review = json.loads(run["review_json"])
    github_data = json.loads(run["github_data_json"]) if run.get("github_data_json") else {}
    _inject_detail_urls(review, run_id)
    nav_overview = "/report/{}/".format(run_id)
    nav_repos = "/report/{}/repos.html".format(run_id)
    return render_overview(review, TEMPLATES_DIR, back_url="/",
                           nav_overview_url=nav_overview, nav_repos_url=nav_repos,
                           github_data=github_data)


@app.route("/report/<int:run_id>/repos.html")
def serve_report_repos(run_id):
    """Render repos page dynamically from DB."""
    run = get_run(run_id)
    if not run:
        return _report_404(message="Review not found.")
    if not run.get("review_json"):
        if run["status"] == "pending":
            return _report_404(run=run, message="This review is still being generated. Check back shortly.")
        return _report_404(run=run, message="This review was cancelled before it completed.")
    review = json.loads(run["review_json"])
    _inject_detail_urls(review, run_id)
    nav_overview = "/report/{}/".format(run_id)
    nav_repos = "/report/{}/repos.html".format(run_id)
    return render_repos(review, TEMPLATES_DIR, back_url="/",
                        nav_overview_url=nav_overview, nav_repos_url=nav_repos)


@app.route("/report/<int:run_id>/repo/<repo_name>")
def serve_repo_detail(run_id, repo_name):
    """Render a single-repo deep-dive page."""
    run = get_run(run_id)
    if not run:
        return _report_404(message="Review not found.")
    if not run.get("review_json"):
        return _report_404(run=run, message="This review has no data yet.")
    review = json.loads(run["review_json"])
    github_data = json.loads(run["github_data_json"]) if run.get("github_data_json") else {}

    nav_overview = "/report/{}/".format(run_id)
    nav_repos = "/report/{}/repos.html".format(run_id)
    html = render_repo_detail(
        review, repo_name, github_data, TEMPLATES_DIR,
        run_id=run_id, back_url=nav_repos,
        nav_overview_url=nav_overview, nav_repos_url=nav_repos,
    )
    if html is None:
        return _report_404(message="Repository '{}' not found in this review.".format(repo_name))
    return html


# --- Backward compat: /reports/<username>/ redirects to latest run ---

@app.route("/reports/<username>/")
def serve_report_legacy(username):
    """Redirect to the latest run for backward compatibility."""
    run = get_latest_run(username)
    if run and run.get("review_json"):
        review = json.loads(run["review_json"])
        nav_overview = "/reports/{}/".format(username)
        nav_repos = "/reports/{}/repos.html".format(username)
        return render_overview(review, TEMPLATES_DIR, back_url="/",
                               nav_overview_url=nav_overview, nav_repos_url=nav_repos)
    report_dir = os.path.join(RUNTIME_OUTPUT_ROOT, username)
    if not os.path.isdir(report_dir):
        report_dir = os.path.join(LEGACY_OUTPUT_ROOT, username)
    index_path = os.path.join(report_dir, "index.html")
    if os.path.isfile(index_path):
        with open(index_path) as f:
            return f.read()
    return _report_404(message="No reviews found for this user.")


@app.route("/reports/<username>/repos.html")
def serve_report_legacy_repos(username):
    """Backward compat repos page."""
    run = get_latest_run(username)
    if run and run.get("review_json"):
        review = json.loads(run["review_json"])
        nav_overview = "/reports/{}/".format(username)
        nav_repos = "/reports/{}/repos.html".format(username)
        return render_repos(review, TEMPLATES_DIR, back_url="/",
                            nav_overview_url=nav_overview, nav_repos_url=nav_repos)
    report_dir = os.path.join(RUNTIME_OUTPUT_ROOT, username)
    if not os.path.isdir(report_dir):
        report_dir = os.path.join(LEGACY_OUTPUT_ROOT, username)
    repos_path = os.path.join(report_dir, "repos.html")
    if os.path.isfile(repos_path):
        with open(repos_path) as f:
            return f.read()
    return _report_404(message="No reviews found for this user.")


if __name__ == "__main__":
    print("GitHub Review — http://localhost:5959")
    app.run(host="127.0.0.1", port=5959, debug=False)
