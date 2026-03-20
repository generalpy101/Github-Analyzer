"""Extended tests for server/llm_client.py — chat, context builder, streaming."""

import json
from unittest.mock import patch

from server.llm_client import (
    _build_chat_context, _extract_json, _load_prompt,
)


class TestBuildChatContext:
    def test_includes_username(self):
        ctx = _build_chat_context({"username": "testuser", "overall_score": 50})
        assert "@testuser" in ctx

    def test_includes_score(self):
        ctx = _build_chat_context({"username": "x", "overall_score": 75})
        assert "75" in ctx

    def test_includes_headline(self):
        ctx = _build_chat_context({"username": "x", "headline": "Strong developer"})
        assert "Strong developer" in ctx

    def test_includes_summary(self):
        ctx = _build_chat_context({"username": "x", "summary": "A great profile with many projects."})
        assert "great profile" in ctx

    def test_includes_repo_reviews(self):
        ctx = _build_chat_context({
            "username": "x",
            "repository_reviews": [
                {"repo_name": "my-repo", "score": 80, "recommendation": "showcase", "verdict": "Excellent work"},
            ],
        })
        assert "my-repo" in ctx
        assert "80" in ctx
        assert "showcase" in ctx

    def test_includes_recommendations(self):
        ctx = _build_chat_context({
            "username": "x",
            "top_recommendations": [
                {"priority": "high", "title": "Add tests", "description": "Improve coverage"},
            ],
        })
        assert "Add tests" in ctx

    def test_includes_profile_strengths(self):
        ctx = _build_chat_context({
            "username": "x",
            "profile_review": {"strengths": ["Has bio"], "improvements": ["Add email"]},
        })
        assert "Has bio" in ctx
        assert "Add email" in ctx

    def test_includes_github_data_bio(self):
        ctx = _build_chat_context(
            {"username": "x"},
            github_data={"profile": {"bio": "Full-stack dev"}},
        )
        assert "Full-stack dev" in ctx

    def test_includes_profile_readme(self):
        ctx = _build_chat_context(
            {"username": "x"},
            github_data={"profile_readme": "# Hello World\nI build things"},
        )
        assert "Hello World" in ctx

    def test_truncates_long_summary(self):
        long_summary = "x" * 5000
        ctx = _build_chat_context({"username": "x", "summary": long_summary})
        assert len(ctx) < 5000

    def test_limits_repos(self):
        repos = [{"repo_name": "r{}".format(i), "score": 50, "recommendation": "keep", "verdict": "ok"} for i in range(30)]
        ctx = _build_chat_context({"username": "x", "repository_reviews": repos})
        assert "r0" in ctx
        assert "r19" in ctx
        assert "r20" not in ctx


class TestLoadPrompt:
    def test_loads_prompt(self):
        prompt = _load_prompt()
        assert len(prompt) > 100
        assert "GitHub" in prompt

    def test_no_placeholder(self):
        prompt = _load_prompt()
        assert "PASTE CONTENTS" not in prompt


class TestExtractJsonEdgeCases:
    def test_nested_json(self):
        text = '{"a": {"b": [1, 2, 3]}, "c": "test"}'
        result = _extract_json(text)
        assert result["a"]["b"] == [1, 2, 3]

    def test_json_with_thinking_tags(self):
        text = '<think>Let me analyze this...</think>\n```json\n{"score": 42}\n```'
        result = _extract_json(text)
        assert result["score"] == 42

    def test_json_with_explanation_after(self):
        text = '{"key": "value"}\n\nHere is my explanation of the results...'
        result = _extract_json(text)
        assert result["key"] == "value"

    def test_deeply_nested(self):
        obj = {"level1": {"level2": {"level3": {"data": [1, 2, 3]}}}}
        result = _extract_json(json.dumps(obj))
        assert result["level1"]["level2"]["level3"]["data"] == [1, 2, 3]
