"""Background generation manager.

Runs the review pipeline in a daemon thread so it survives client disconnects.
The SSE endpoint becomes a read-only poller of the in-memory progress store.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
import traceback
from datetime import datetime

from server.config import load_config
from server.db import create_run, update_run
from server.fallback_review import compute_fallback_review
from server.fetch_github_data import fetch_all
from server.generate_report import render_overview, render_repos, generate
from server.llm_client import generate_review, test_connection

# ---- In-memory progress store ----

_jobs = {}  # run_id -> {"status", "steps", "username", "run_id", "cancelled"}
_jobs_lock = threading.Lock()

_active_lock = threading.Lock()  # Only one generation at a time
_active_run_id = None
_active_username = None


def _emit(run_id, event_type, data):
    """Append a progress event to the job's step list."""
    with _jobs_lock:
        if run_id in _jobs:
            _jobs[run_id]["steps"].append({"type": event_type, "data": data})


def _is_cancelled(run_id):
    """Check if a job has been cancelled."""
    with _jobs_lock:
        job = _jobs.get(run_id)
        return job is not None and job.get("cancelled", False)


def _is_valid_review(review):
    """Check whether a review dict has meaningful data."""
    if not isinstance(review, dict) or len(review) < 3:
        return False
    if review.get("overall_score", 0) == 0 and not review.get("repository_reviews"):
        return False
    return True


# ---- Public API ----

def start_generation(username, use_cache, config, base_dir, templates_dir):
    """Start a background generation. Returns (run_id, error_message).

    If a generation is already running, returns the existing run_id with a conflict message.
    """
    global _active_run_id, _active_username

    # Try to acquire the generation lock
    if not _active_lock.acquire(blocking=False):
        # Already running
        return _active_run_id, "already_running"

    # Lock acquired — we own it now
    try:
        run_id = create_run(username, config.get("provider"), config.get("model"))

        with _jobs_lock:
            _jobs[run_id] = {
                "status": "running",
                "steps": [],
                "username": username,
                "run_id": run_id,
                "cancelled": False,
                "started_at": time.time(),
            }

        _active_run_id = run_id
        _active_username = username

        t = threading.Thread(
            target=_run_pipeline,
            args=(run_id, username, use_cache, config, base_dir, templates_dir),
            daemon=True,
        )
        t.start()

        return run_id, None
    except Exception:
        _active_lock.release()
        raise


def cancel_generation(run_id):
    """Request cancellation of a running generation."""
    with _jobs_lock:
        job = _jobs.get(run_id)
        if job and job["status"] == "running":
            job["cancelled"] = True
            return True
    return False


def get_progress(run_id, after_index=0):
    """Return new events since after_index."""
    with _jobs_lock:
        job = _jobs.get(run_id)
        if not job:
            return []
        return list(job["steps"][after_index:])


def get_job(run_id):
    """Return job info dict or None."""
    with _jobs_lock:
        job = _jobs.get(run_id)
        if job:
            return {
                "status": job["status"],
                "username": job["username"],
                "run_id": job["run_id"],
                "step_count": len(job["steps"]),
            }
    return None


def get_active_job():
    """Return info about the currently running generation, or None."""
    with _jobs_lock:
        rid = _active_run_id
        if rid and rid in _jobs and _jobs[rid]["status"] == "running":
            job = _jobs[rid]
            return {
                "active": True,
                "run_id": rid,
                "username": job["username"],
            }
    return None


def cleanup_old_jobs():
    """Remove completed jobs older than 5 minutes from memory."""
    cutoff = time.time() - 300
    with _jobs_lock:
        to_delete = [
            rid for rid, job in _jobs.items()
            if job["status"] in ("complete", "error") and job.get("started_at", 0) < cutoff
        ]
        for rid in to_delete:
            del _jobs[rid]


# ---- Pipeline (runs in background thread) ----

def _run_pipeline(run_id, username, use_cache, config, base_dir, templates_dir):
    """The actual generation pipeline. Runs in a daemon thread."""
    global _active_run_id, _active_username

    try:
        data_dir = os.path.join(base_dir, "runtime", "data", username)
        os.makedirs(data_dir, exist_ok=True)
        data_path = os.path.join(data_dir, "github_data.json")
        legacy_data_path = os.path.join(base_dir, "data", username, "github_data.json")

        # Keep old cache files usable after directory restructure.
        if not os.path.isfile(data_path) and os.path.isfile(legacy_data_path):
            try:
                shutil.copy2(legacy_data_path, data_path)
            except OSError:
                pass

        # Step 1: Fetch GitHub data
        if use_cache and os.path.isfile(data_path) and os.path.getsize(data_path) > 100:
            _emit(run_id, "progress", {
                "step": 1, "total": 4,
                "message": "Using cached GitHub data for @{}...".format(username),
            })
            _emit(run_id, "log", {"message": "Using cached data from {}".format(data_path)})
        else:
            _emit(run_id, "progress", {
                "step": 1, "total": 4,
                "message": "Fetching GitHub data for @{}...".format(username),
            })

            def on_fetch_progress(msg):
                _emit(run_id, "log", {"message": msg})

            _emit(run_id, "log", {"message": "Starting GitHub data fetch for @{}...".format(username)})
            fetch_all(username, data_path, config.get("top_repos", 15), on_progress=on_fetch_progress)
            _emit(run_id, "log", {"message": "GitHub data fetch complete."})

        if _is_cancelled(run_id):
            _finish_cancelled(run_id)
            return

        with open(data_path) as f:
            gh_data = json.load(f)
        repo_count = gh_data.get("summary_stats", {}).get("total_repos", 0)

        # Store github data in DB
        update_run(run_id, github_data_json=json.dumps(gh_data))

        _emit(run_id, "progress", {
            "step": 2, "total": 4,
            "message": "Fetched {} repositories. Sending to {} ({})...".format(
                repo_count, config["provider"].title(), config.get("model", "default")
            ),
        })

        # Step 2: LLM analysis (with fallback)
        review = None
        status = "algorithmic"
        is_ai = False
        llm_error = None
        skip_llm = False

        if _is_cancelled(run_id):
            _finish_cancelled(run_id)
            return

        # Skip LLM entirely if AI is not configured
        if not config.get("_ai_configured", True):
            skip_llm = True
            llm_error = "No API key configured. Go to Settings to set up your LLM provider."
            _emit(run_id, "log", {"message": "AI is not configured. Skipping LLM analysis."})
            _emit(run_id, "progress", {
                "step": 2, "total": 4,
                "message": "AI not configured. Using algorithmic analysis...",
                "warning": True,
            })
        else:
            # Test connection before sending data
            _emit(run_id, "log", {"message": "Testing {} connection...".format(config["provider"].title())})
            try:
                conn_ok, conn_msg = test_connection(config)
            except Exception as e:
                conn_ok, conn_msg = False, str(e)

            if not conn_ok:
                skip_llm = True
                llm_error = "Connection to {} failed: {}".format(
                    config["provider"].title(), conn_msg
                )
                _emit(run_id, "log", {"message": "Connection test failed: {}".format(conn_msg)})
                _emit(run_id, "progress", {
                    "step": 2, "total": 4,
                    "message": "AI connection failed. Using algorithmic analysis...",
                    "warning": True,
                })
            else:
                _emit(run_id, "log", {"message": "Connection OK. {}".format(conn_msg)})

        if not skip_llm:
            try:
                _emit(run_id, "log", {
                    "message": "Sending {} repos to {} ({})...".format(
                        repo_count, config["provider"].title(), config.get("model", "default")
                    ),
                })

                def on_batch_progress(msg):
                    _emit(run_id, "log", {"message": msg})

                review = generate_review(data_path, config, on_progress=on_batch_progress)
                if _is_valid_review(review):
                    status = "success"
                    is_ai = True
                    review["is_ai_generated"] = True
                    _emit(run_id, "log", {"message": "LLM response received and validated."})
                else:
                    llm_error = "LLM returned incomplete data"
                    _emit(run_id, "log", {"message": "LLM returned incomplete data."})
                    review = None
            except Exception as e:
                llm_error = str(e)
                _emit(run_id, "log", {"message": "LLM error: {}".format(llm_error)})
                review = None

        # Fallback if LLM failed
        if review is None:
            _emit(run_id, "progress", {
                "step": 2, "total": 4,
                "message": "LLM unavailable ({}). Using algorithmic analysis...".format(
                    llm_error or "unknown error"
                ),
                "warning": True,
            })
            _emit(run_id, "log", {"message": "Computing algorithmic fallback scores..."})
            review = compute_fallback_review(gh_data)
            review["fallback_reason"] = "AI analysis unavailable"
            review["fallback_detail"] = llm_error or "Unknown error"
            status = "algorithmic"
            is_ai = False
            _emit(run_id, "log", {"message": "Algorithmic analysis complete. Score: {}".format(review.get("overall_score", 0))})

        if _is_cancelled(run_id):
            _finish_cancelled(run_id)
            return

        _emit(run_id, "progress", {
            "step": 3, "total": 4,
            "message": "Analysis complete. Generating HTML report...",
        })

        # Step 3: Store review in DB
        update_run(
            run_id,
            review_json=json.dumps(review),
            overall_score=review.get("overall_score", 0),
            status=status,
            is_ai_generated=1 if is_ai else 0,
        )

        # Also write files for CLI compatibility
        _emit(run_id, "log", {"message": "Writing report files..."})
        output_dir = os.path.join(base_dir, "runtime", "output", username)
        os.makedirs(output_dir, exist_ok=True)
        review_path = os.path.join(data_dir, "review.json")
        with open(review_path, "w") as f:
            json.dump(review, f, indent=2)
        generate(review, templates_dir, output_dir, github_data=gh_data)
        _emit(run_id, "log", {"message": "Report files written to {}.".format(output_dir)})

        _emit(run_id, "progress", {
            "step": 4, "total": 4,
            "message": "Done!",
        })

        _emit(run_id, "complete", {
            "username": username,
            "run_id": run_id,
            "report_url": "/report/{}/".format(run_id),
            "status": status,
            "is_ai_generated": is_ai,
        })

        with _jobs_lock:
            if run_id in _jobs:
                _jobs[run_id]["status"] = "complete"

    except Exception as e:
        traceback.print_exc()
        _emit(run_id, "error", {"message": str(e)})
        with _jobs_lock:
            if run_id in _jobs:
                _jobs[run_id]["status"] = "error"
        try:
            update_run(run_id, status="error")
        except Exception:
            pass

    finally:
        _active_run_id = None
        _active_username = None
        try:
            _active_lock.release()
        except RuntimeError:
            pass  # Lock was already released


def _finish_cancelled(run_id):
    """Mark a cancelled job as error in both memory and DB."""
    _emit(run_id, "error", {"message": "Generation was cancelled."})
    with _jobs_lock:
        if run_id in _jobs:
            _jobs[run_id]["status"] = "error"
    try:
        update_run(run_id, status="error")
    except Exception:
        pass
