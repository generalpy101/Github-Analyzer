"""Tests for server/generation_manager.py — in-memory job management."""

from unittest.mock import patch
import server.generation_manager as gm


class TestEmit:
    def test_emits_to_existing_job(self):
        gm._jobs[999] = {"status": "running", "steps": [], "username": "t", "run_id": 999, "cancelled": False, "started_at": 0}
        gm._emit(999, "progress", {"step": 1})
        assert len(gm._jobs[999]["steps"]) == 1
        assert gm._jobs[999]["steps"][0]["type"] == "progress"
        del gm._jobs[999]

    def test_emit_nonexistent_job(self):
        gm._emit(88888, "progress", {"step": 1})


class TestIsCancelled:
    def test_not_cancelled(self):
        gm._jobs[998] = {"status": "running", "steps": [], "username": "t", "run_id": 998, "cancelled": False, "started_at": 0}
        assert gm._is_cancelled(998) is False
        del gm._jobs[998]

    def test_cancelled(self):
        gm._jobs[997] = {"status": "running", "steps": [], "username": "t", "run_id": 997, "cancelled": True, "started_at": 0}
        assert gm._is_cancelled(997) is True
        del gm._jobs[997]

    def test_nonexistent(self):
        assert gm._is_cancelled(77777) is False


class TestIsValidReview:
    def test_valid(self):
        assert gm._is_valid_review({"overall_score": 50, "username": "x", "repository_reviews": [{"score": 50}]}) is True

    def test_empty(self):
        assert gm._is_valid_review({}) is False

    def test_zero_score_no_repos(self):
        assert gm._is_valid_review({"overall_score": 0, "repository_reviews": [], "username": "x"}) is False

    def test_not_dict(self):
        assert gm._is_valid_review("string") is False


class TestGetProgress:
    def test_returns_events(self):
        gm._jobs[996] = {
            "status": "running", "steps": [
                {"type": "progress", "data": {"step": 1}},
                {"type": "log", "data": {"message": "test"}},
            ],
            "username": "t", "run_id": 996, "cancelled": False, "started_at": 0,
        }
        events = gm.get_progress(996, after_index=0)
        assert len(events) == 2
        events2 = gm.get_progress(996, after_index=1)
        assert len(events2) == 1
        del gm._jobs[996]

    def test_nonexistent(self):
        assert gm.get_progress(66666) == []


class TestGetJob:
    def test_returns_info(self):
        gm._jobs[995] = {"status": "running", "steps": [{"type": "p", "data": {}}], "username": "usr", "run_id": 995, "cancelled": False, "started_at": 0}
        info = gm.get_job(995)
        assert info["status"] == "running"
        assert info["username"] == "usr"
        assert info["step_count"] == 1
        del gm._jobs[995]

    def test_nonexistent(self):
        assert gm.get_job(55555) is None


class TestGetActiveJob:
    def test_no_active(self):
        old_rid = gm._active_run_id
        gm._active_run_id = None
        assert gm.get_active_job() is None
        gm._active_run_id = old_rid

    def test_active(self):
        gm._jobs[994] = {"status": "running", "steps": [], "username": "act", "run_id": 994, "cancelled": False, "started_at": 0}
        old_rid = gm._active_run_id
        gm._active_run_id = 994
        result = gm.get_active_job()
        assert result["active"] is True
        assert result["username"] == "act"
        gm._active_run_id = old_rid
        del gm._jobs[994]


class TestCancelGeneration:
    def test_cancel_running(self):
        gm._jobs[993] = {"status": "running", "steps": [], "username": "t", "run_id": 993, "cancelled": False, "started_at": 0}
        assert gm.cancel_generation(993) is True
        assert gm._jobs[993]["cancelled"] is True
        del gm._jobs[993]

    def test_cancel_nonexistent(self):
        assert gm.cancel_generation(44444) is False


class TestCleanupOldJobs:
    def test_removes_old_completed(self):
        import time
        gm._jobs[992] = {"status": "complete", "steps": [], "username": "t", "run_id": 992, "cancelled": False, "started_at": time.time() - 600}
        gm._jobs[991] = {"status": "running", "steps": [], "username": "t", "run_id": 991, "cancelled": False, "started_at": time.time() - 600}
        gm.cleanup_old_jobs()
        assert 992 not in gm._jobs
        assert 991 in gm._jobs
        del gm._jobs[991]
