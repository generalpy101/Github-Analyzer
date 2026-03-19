"""Tests for apply_repo_filters in server/fetch_github_data.py."""

from server.fetch_github_data import apply_repo_filters

SAMPLE_REPOS = [
    {"name": "public1", "isPrivate": False, "isFork": False, "isArchived": False, "isEmpty": False, "stargazerCount": 5, "forkCount": 1, "primaryLanguage": {"name": "Python"}},
    {"name": "public2", "isPrivate": False, "isFork": False, "isArchived": False, "isEmpty": False, "stargazerCount": 0, "forkCount": 0, "primaryLanguage": None},
    {"name": "fork1", "isPrivate": False, "isFork": True, "isArchived": False, "isEmpty": False, "stargazerCount": 0, "forkCount": 0, "primaryLanguage": {"name": "JavaScript"}},
    {"name": "private1", "isPrivate": True, "isFork": False, "isArchived": False, "isEmpty": False, "stargazerCount": 0, "forkCount": 0, "primaryLanguage": {"name": "Go"}},
    {"name": "archived1", "isPrivate": False, "isFork": False, "isArchived": True, "isEmpty": False, "stargazerCount": 0, "forkCount": 0, "primaryLanguage": None},
    {"name": "empty1", "isPrivate": False, "isFork": False, "isArchived": False, "isEmpty": True, "stargazerCount": 0, "forkCount": 0, "primaryLanguage": None},
]

SAMPLE_DATA = {
    "repositories": SAMPLE_REPOS,
    "top_repo_details": {"public1": {"languages": {"Python": 1000}}},
    "summary_stats": {"total_repos": 6, "languages": {"Python": 1}},
}


def _names(filtered):
    return [r["name"] for r in filtered["repositories"]]


class TestApplyRepoFilters:
    def test_public_only(self):
        result = apply_repo_filters(SAMPLE_DATA, {"include_public": True})
        names = _names(result)
        assert names == ["public1", "public2"]
        assert result["summary_stats"]["total_repos"] == 2

    def test_private_only(self):
        names = _names(apply_repo_filters(SAMPLE_DATA, {"include_private": True}))
        assert names == ["private1"]

    def test_forked_only(self):
        names = _names(apply_repo_filters(SAMPLE_DATA, {"include_forked": True}))
        assert names == ["fork1"]

    def test_archived_only(self):
        names = _names(apply_repo_filters(SAMPLE_DATA, {"include_archived": True}))
        assert names == ["archived1"]

    def test_all_filters(self):
        names = _names(apply_repo_filters(SAMPLE_DATA, {
            "include_public": True, "include_private": True,
            "include_forked": True, "include_archived": True,
        }))
        assert len(names) == 5
        assert "empty1" not in names

    def test_no_filters_returns_all(self):
        result = apply_repo_filters(SAMPLE_DATA, {})
        assert len(result["repositories"]) == len(SAMPLE_REPOS)

    def test_none_filters_returns_all(self):
        result = apply_repo_filters(SAMPLE_DATA, None)
        assert result is SAMPLE_DATA

    def test_public_plus_archived(self):
        names = _names(apply_repo_filters(SAMPLE_DATA, {
            "include_public": True, "include_archived": True,
        }))
        assert "public1" in names
        assert "archived1" in names
        assert "fork1" not in names

    def test_stats_recalculated(self):
        result = apply_repo_filters(SAMPLE_DATA, {"include_public": True})
        stats = result["summary_stats"]
        assert stats["total_repos"] == 2
        assert stats["total_stars"] == 5
        assert stats["forked_repos"] == 0

    def test_details_filtered(self):
        result = apply_repo_filters(SAMPLE_DATA, {"include_forked": True})
        assert "public1" not in result["top_repo_details"]
