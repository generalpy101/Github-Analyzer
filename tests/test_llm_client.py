"""Tests for server/llm_client.py — JSON extraction, batching, merging."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

from server.llm_client import (
    _extract_json,
    _split_github_data,
    _merge_reviews,
    _validate_review,
    _call_llm_with_retry,
    DEFAULT_BATCH_SIZE,
)


class TestExtractJson:
    def test_plain_json(self):
        result = _extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_code_fence(self):
        text = '```json\n{"score": 42}\n```'
        assert _extract_json(text) == {"score": 42}

    def test_json_in_bare_fence(self):
        text = '```\n{"score": 42}\n```'
        assert _extract_json(text) == {"score": 42}

    def test_json_with_surrounding_text(self):
        text = 'Here is the review:\n{"score": 42, "name": "test"}\nDone!'
        result = _extract_json(text)
        assert result["score"] == 42

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Could not extract"):
            _extract_json("This is not JSON at all")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _extract_json("")


class TestSplitGithubData:
    def _make_data(self, n_repos):
        repos = [{"name": "repo-{}".format(i), "isFork": False} for i in range(n_repos)]
        return {
            "repositories": repos,
            "top_repo_details": {"repo-0": {"languages": {}}},
            "profile": {"name": "test"},
            "summary_stats": {},
        }

    def test_small_data_single_chunk(self):
        data = self._make_data(3)
        chunks = _split_github_data(data, 5)
        assert len(chunks) == 1

    def test_exact_batch_size(self):
        data = self._make_data(5)
        chunks = _split_github_data(data, 5)
        assert len(chunks) == 1

    def test_splits_correctly(self):
        data = self._make_data(12)
        chunks = _split_github_data(data, 5)
        assert len(chunks) == 3
        assert len(chunks[0][1]) == 5
        assert len(chunks[1][1]) == 5
        assert len(chunks[2][1]) == 2

    def test_preserves_details(self):
        data = self._make_data(3)
        chunks = _split_github_data(data, 5)
        assert "repo-0" in chunks[0][0]["top_repo_details"]

    def test_first_chunk_has_full_context(self):
        data = self._make_data(12)
        chunks = _split_github_data(data, 5)
        assert "profile" in chunks[0][0]
        assert "summary_stats" in chunks[0][0]

    def test_later_chunks_stripped(self):
        data = self._make_data(12)
        chunks = _split_github_data(data, 5)
        for chunk, _ in chunks[1:]:
            assert "profile" not in chunk
            assert "_batch_note" in chunk
            assert "username" in chunk

    def test_forks_excluded(self):
        data = {
            "repositories": [
                {"name": "orig", "isFork": False},
                {"name": "forked", "isFork": True},
            ],
            "top_repo_details": {},
            "profile": {},
            "summary_stats": {},
        }
        chunks = _split_github_data(data, 5)
        assert len(chunks) == 1
        names = chunks[0][1]
        assert "orig" in names
        assert "forked" not in names


class TestMergeReviews:
    def test_merges_repos(self):
        base = {"overall_score": 70, "repository_reviews": [{"repo_name": "a", "score": 80}]}
        additions = [{"repository_reviews": [{"repo_name": "b", "score": 60}]}]
        merged = _merge_reviews(base, additions)
        assert len(merged["repository_reviews"]) == 2
        assert merged["overall_score"] == 70

    def test_empty_additions(self):
        base = {"overall_score": 50, "repository_reviews": [{"repo_name": "a", "score": 50}]}
        merged = _merge_reviews(base, [])
        assert len(merged["repository_reviews"]) == 1


class TestValidateReview:
    def test_valid(self):
        _validate_review({"overall_score": 50, "username": "x", "repository_reviews": [{"score": 50}]})

    def test_empty_dict(self):
        with pytest.raises(ValueError, match="empty"):
            _validate_review({})

    def test_zero_score_no_repos(self):
        with pytest.raises(ValueError, match="no scores"):
            _validate_review({"overall_score": 0, "repository_reviews": [], "username": "x"})


class TestCallLlmWithRetry:
    def test_succeeds_first_try(self):
        good = json.dumps({"score": 42, "username": "x", "overall_score": 42})
        with patch("server.llm_client._call_llm", return_value=good):
            result = _call_llm_with_retry("p", "{}", {})
            assert result["score"] == 42

    def test_retries_on_bad_json(self):
        calls = [0]
        def mock(prompt, data, config, on_stream=None):
            calls[0] += 1
            if calls[0] == 1:
                return "not json"
            return json.dumps({"score": 42})
        with patch("server.llm_client._call_llm", side_effect=mock):
            result = _call_llm_with_retry("p", "{}", {})
            assert calls[0] == 2
            assert result["score"] == 42

    def test_exhausts_retries(self):
        with patch("server.llm_client._call_llm", return_value="garbage"):
            with pytest.raises(ValueError):
                _call_llm_with_retry("p", "{}", {})

    def test_logs_progress_on_failure(self):
        msgs = []
        with patch("server.llm_client._call_llm", return_value="bad"):
            with pytest.raises(ValueError):
                _call_llm_with_retry("p", "{}", {}, on_progress=lambda m: msgs.append(m))
        assert any("not valid JSON" in m for m in msgs)
        assert any("Response preview" in m for m in msgs)
