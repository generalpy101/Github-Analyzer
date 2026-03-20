"""Tests for server/fetch_github_data.py — tree analysis, PR/issue stats parsing."""

import json
from unittest.mock import patch

from server.fetch_github_data import (
    fetch_repo_tree, fetch_pr_stats, fetch_issue_stats,
    fetch_contribution_graph,
)


class TestFetchRepoTree:
    def _mock_tree(self, paths):
        items = []
        for p in paths:
            items.append({"path": p, "type": "blob" if "." in p else "tree"})
        return {"tree": items}

    def test_detects_tests(self):
        with patch("server.fetch_github_data.run_gh", return_value=self._mock_tree(["src/main.py", "tests/test_main.py"])):
            result = fetch_repo_tree("u", "r")
            assert result["has_tests"] is True

    def test_detects_ci(self):
        with patch("server.fetch_github_data.run_gh", return_value=self._mock_tree([".github/workflows/ci.yml", "src/app.js"])):
            result = fetch_repo_tree("u", "r")
            assert result["has_ci"] is True

    def test_detects_docker(self):
        with patch("server.fetch_github_data.run_gh", return_value=self._mock_tree(["Dockerfile", "src/app.py"])):
            result = fetch_repo_tree("u", "r")
            assert result["has_docker"] is True

    def test_detects_docs(self):
        with patch("server.fetch_github_data.run_gh", return_value=self._mock_tree(["docs/api.md", "CONTRIBUTING.md"])):
            result = fetch_repo_tree("u", "r")
            assert result["has_docs"] is True

    def test_detects_config_files(self):
        with patch("server.fetch_github_data.run_gh", return_value=self._mock_tree(["package.json", "tsconfig.json", "src/index.ts"])):
            result = fetch_repo_tree("u", "r")
            assert "package.json" in result["config_files"]
            assert "tsconfig.json" in result["config_files"]

    def test_counts_files_and_dirs(self):
        with patch("server.fetch_github_data.run_gh", return_value=self._mock_tree(["src", "src/main.py", "src/utils.py"])):
            result = fetch_repo_tree("u", "r")
            assert result["file_count"] == 2
            assert result["directory_count"] == 1

    def test_empty_tree(self):
        with patch("server.fetch_github_data.run_gh", return_value=None):
            result = fetch_repo_tree("u", "r")
            assert result["has_tests"] is False
            assert result["file_count"] == 0

    def test_no_infrastructure(self):
        with patch("server.fetch_github_data.run_gh", return_value=self._mock_tree(["main.py"])):
            result = fetch_repo_tree("u", "r")
            assert result["has_tests"] is False
            assert result["has_ci"] is False
            assert result["has_docker"] is False
            assert result["has_docs"] is False


class TestFetchPrStats:
    def test_with_prs(self):
        prs = [
            {"state": "closed", "merged_at": "2025-01-01", "requested_reviewers": [{"login": "rev"}]},
            {"state": "open", "merged_at": None, "requested_reviewers": []},
            {"state": "closed", "merged_at": "2025-02-01", "requested_reviewers": []},
        ]
        with patch("server.fetch_github_data.run_gh", return_value=prs):
            result = fetch_pr_stats("u", "r")
            assert result["total_prs"] == 3
            assert result["merged_prs"] == 2
            assert result["open_prs"] == 1
            assert result["merge_rate"] == 66.7
            assert result["has_code_reviews"] is True

    def test_no_prs(self):
        with patch("server.fetch_github_data.run_gh", return_value=[]):
            result = fetch_pr_stats("u", "r")
            assert result["total_prs"] == 0

    def test_api_failure(self):
        with patch("server.fetch_github_data.run_gh", return_value=None):
            result = fetch_pr_stats("u", "r")
            assert result["total_prs"] == 0


class TestFetchIssueStats:
    def test_with_issues(self):
        issues = [
            {"state": "open", "pull_request": None},
            {"state": "closed"},
            {"state": "closed"},
            {"state": "open", "pull_request": {"url": "..."}},
        ]
        with patch("server.fetch_github_data.run_gh", return_value=issues):
            result = fetch_issue_stats("u", "r")
            assert result["total_issues"] == 3
            assert result["open_issues"] == 1
            assert result["closed_issues"] == 2

    def test_no_issues(self):
        with patch("server.fetch_github_data.run_gh", return_value=[]):
            result = fetch_issue_stats("u", "r")
            assert result["total_issues"] == 0

    def test_api_failure(self):
        with patch("server.fetch_github_data.run_gh", return_value=None):
            result = fetch_issue_stats("u", "r")
            assert result["total_issues"] == 0


class TestFetchContributionGraph:
    def test_success(self):
        mock_response = {
            "data": {
                "user": {
                    "contributionsCollection": {
                        "contributionCalendar": {
                            "totalContributions": 42,
                            "weeks": [{"contributionDays": [{"date": "2025-01-01", "contributionCount": 5, "color": "#40c463"}]}],
                        }
                    }
                }
            }
        }
        with patch("server.fetch_github_data.run_gh", return_value=mock_response):
            result = fetch_contribution_graph("testuser")
            assert result["total_contributions"] == 42
            assert len(result["weeks"]) == 1

    def test_api_failure(self):
        with patch("server.fetch_github_data.run_gh", return_value=None):
            result = fetch_contribution_graph("testuser")
            assert result["total_contributions"] == 0
            assert result["weeks"] == []

    def test_malformed_response(self):
        with patch("server.fetch_github_data.run_gh", return_value={"data": {}}):
            result = fetch_contribution_graph("testuser")
            assert result["total_contributions"] == 0
