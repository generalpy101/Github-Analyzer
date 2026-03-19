"""Tests for server/fallback_review.py — algorithmic scoring."""

from server.fallback_review import compute_fallback_review, _infer_category, _months_ago


MINIMAL_GITHUB_DATA = {
    "username": "testuser",
    "profile": {
        "name": "Test User",
        "bio": "A developer",
        "avatar_url": "https://example.com/avatar.png",
        "location": "Earth",
        "company": None,
        "blog": None,
        "email": None,
        "twitter_username": None,
        "followers": 5,
        "created_at": "2022-01-01T00:00:00Z",
    },
    "profile_readme": None,
    "repositories": [
        {
            "name": "my-project",
            "description": "A cool project",
            "primaryLanguage": {"name": "Python"},
            "stargazerCount": 3,
            "forkCount": 1,
            "isPrivate": False,
            "isFork": False,
            "isArchived": False,
            "isEmpty": False,
            "pushedAt": "2025-06-01T00:00:00Z",
            "url": "https://github.com/testuser/my-project",
            "diskUsage": 500,
            "repositoryTopics": None,
            "licenseInfo": None,
        },
    ],
    "top_repo_details": {
        "my-project": {
            "languages": {"Python": 5000, "Shell": 200},
            "recent_commits": [
                {"sha": "abc1234", "message": "feat: add main feature", "date": "2025-06-01", "author": "Test User"},
            ],
            "has_readme": True,
            "license": "MIT",
            "topics": ["python"],
            "open_issues_count": 2,
            "file_tree_analysis": {
                "has_tests": True,
                "has_ci": False,
                "has_docker": False,
                "has_docs": False,
                "file_count": 20,
                "directory_count": 5,
                "config_files": ["requirements.txt"],
            },
            "pr_stats": {
                "total_prs": 3,
                "merged_prs": 2,
                "open_prs": 1,
                "merge_rate": 66.7,
                "has_code_reviews": False,
            },
            "issue_stats": {
                "total_issues": 2,
                "open_issues": 1,
                "closed_issues": 1,
                "close_rate": 50.0,
            },
        },
    },
    "summary_stats": {
        "total_repos": 1,
        "languages": {"Python": 1},
        "account_age_days": 1200,
    },
    "recent_activity": [],
    "recent_commits": [],
}


class TestComputeFallbackReview:
    def test_returns_required_fields(self):
        review = compute_fallback_review(MINIMAL_GITHUB_DATA)
        assert "username" in review
        assert "overall_score" in review
        assert "profile_review" in review
        assert "repository_reviews" in review
        assert "code_review" in review
        assert "repo_presentation" in review
        assert "activity_review" in review
        assert "categories" in review
        assert "top_recommendations" in review
        assert "summary" in review

    def test_scores_in_range(self):
        review = compute_fallback_review(MINIMAL_GITHUB_DATA)
        assert 0 <= review["overall_score"] <= 100
        assert 0 <= review["profile_review"]["score"] <= 100

    def test_repo_reviewed(self):
        review = compute_fallback_review(MINIMAL_GITHUB_DATA)
        repos = review["repository_reviews"]
        assert len(repos) == 1
        assert repos[0]["repo_name"] == "my-project"
        assert repos[0]["has_readme"] is True
        assert repos[0]["has_tests"] is True

    def test_infrastructure_fields_present(self):
        review = compute_fallback_review(MINIMAL_GITHUB_DATA)
        repo = review["repository_reviews"][0]
        assert "has_tests" in repo
        assert "has_ci" in repo
        assert "infrastructure_score" in repo
        assert "pr_activity" in repo

    def test_not_ai_generated(self):
        review = compute_fallback_review(MINIMAL_GITHUB_DATA)
        assert review["is_ai_generated"] is False

    def test_forks_excluded(self):
        data = dict(MINIMAL_GITHUB_DATA)
        data["repositories"] = [
            {"name": "orig", "isFork": False, "primaryLanguage": None,
             "stargazerCount": 0, "forkCount": 0, "isPrivate": False,
             "isArchived": False, "isEmpty": False, "pushedAt": "", "url": "",
             "diskUsage": 0, "repositoryTopics": None, "licenseInfo": None},
            {"name": "forked", "isFork": True, "primaryLanguage": None,
             "stargazerCount": 0, "forkCount": 0, "isPrivate": False,
             "isArchived": False, "isEmpty": False, "pushedAt": "", "url": "",
             "diskUsage": 0, "repositoryTopics": None, "licenseInfo": None},
        ]
        review = compute_fallback_review(data)
        names = [r["repo_name"] for r in review["repository_reviews"]]
        assert "orig" in names
        assert "forked" not in names


class TestInferCategory:
    def test_api_keyword(self):
        assert "Backend" in _infer_category("Python", "my-api", "")

    def test_cli_keyword(self):
        assert "CLI" in _infer_category("Go", "my-cli-tool", "")

    def test_language_fallback(self):
        assert "Web" in _infer_category("JavaScript", "something", "")

    def test_unknown_language(self):
        assert "Software" in _infer_category("Brainfuck", "test", "")


class TestMonthsAgo:
    def test_returns_iso_date(self):
        result = _months_ago(3)
        assert len(result) == 10
        assert result[4] == "-"
