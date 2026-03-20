"""Extended tests for server/generate_report.py — render functions and builders."""

import os
from server.generate_report import (
    score_card, ring_svg, render_template,
    build_score_cards, build_completeness, build_rp_stats,
    build_highlights, build_categories, build_recommendations,
    build_repo_card, build_all_repo_cards, build_quick_nav,
    build_category_filter_buttons, build_contribution_graph,
    _common_vars,
)


SAMPLE_REVIEW = {
    "username": "testuser",
    "display_name": "Test User",
    "headline": "A developer",
    "overall_score": 65,
    "review_date": "2025-01-01",
    "is_ai_generated": True,
    "profile_review": {"score": 70, "completeness": {}, "strengths": [], "improvements": []},
    "code_review": {
        "score": 60, "language_diversity": {"primary_languages": ["Python"], "secondary_languages": []},
        "project_highlights": [], "code_quality_observations": [], "strengths": [], "improvements": [],
    },
    "repo_presentation": {"score": 50, "strengths": [], "improvements": []},
    "activity_review": {"score": 55, "account_age_years": 3.0, "activity_pattern": "", "recent_focus": "", "strengths": [], "improvements": []},
    "repository_reviews": [
        {"repo_name": "proj-a", "url": "https://github.com/t/a", "description": "Project A",
         "score": 80, "recommendation": "showcase", "technical_complexity": "high",
         "category": "Web", "primary_language": "Python", "all_languages": ["Python"],
         "stars": 10, "forks": 2, "is_private": False, "open_issues": 1,
         "last_activity": "2025-01-01", "has_readme": True, "has_license": True,
         "has_description": True, "has_topics": True, "has_tests": True, "has_ci": True,
         "has_docker": False, "has_docs": False, "commit_quality": "Good commits",
         "pr_activity": "Active PRs", "infrastructure_score": 70,
         "code_observations": ["Clean code"], "strengths": ["Well tested"],
         "improvements": ["Add Docker"], "verdict": "Solid project"},
        {"repo_name": "proj-b", "url": "https://github.com/t/b", "description": "Project B",
         "score": 40, "recommendation": "archive", "technical_complexity": "low",
         "category": "Tool", "primary_language": "Shell", "all_languages": ["Shell"],
         "stars": 0, "forks": 0, "is_private": False, "open_issues": 0,
         "last_activity": "2024-01-01", "has_readme": False, "has_license": False,
         "has_description": False, "has_topics": False, "has_tests": False, "has_ci": False,
         "has_docker": False, "has_docs": False, "commit_quality": "",
         "pr_activity": "", "infrastructure_score": 0,
         "code_observations": [], "strengths": [], "improvements": ["Add README"],
         "verdict": "Needs work"},
    ],
    "categories": [{"name": "Web", "repos": ["proj-a"], "description": "Web projects"}],
    "top_recommendations": [{"priority": "high", "title": "Add tests", "description": "More tests needed"}],
    "summary": "Test summary.",
}


class TestRingSvg:
    def test_renders_svg(self):
        svg = ring_svg(75, 100, 6)
        assert "<svg" in svg
        assert "100" in svg

    def test_zero_score(self):
        svg = ring_svg(0, 80, 4)
        assert "<svg" in svg


class TestScoreCard:
    def test_renders(self):
        html = score_card("Test", 70, '<svg></svg>')
        assert "Test" in html
        assert "70" in html


class TestBuildScoreCards:
    def test_renders_four_cards(self):
        html = build_score_cards(
            {"score": 70}, {"score": 60}, {"score": 50}, {"score": 40}
        )
        assert "Profile" in html
        assert "Code Quality" in html
        assert "Presentation" in html
        assert "Activity" in html


class TestBuildCompleteness:
    def test_has_and_missing(self):
        html = build_completeness({"has_bio": True, "has_avatar": False})
        assert "Bio" in html
        assert "Avatar" in html


class TestBuildRpStats:
    def test_renders_bars(self):
        html = build_rp_stats({"repos_with_readme_pct": 80, "repos_with_description_pct": 60,
                                "repos_with_license_pct": 40, "repos_with_topics_pct": 20})
        assert "README" in html
        assert "80%" in html


class TestBuildHighlights:
    def test_renders(self):
        html = build_highlights([{
            "repo_name": "test", "description": "A project",
            "technical_complexity": "high", "languages": ["Python"],
            "strengths": ["Good"], "improvements": ["Better"],
        }])
        assert "test" in html


class TestBuildCategories:
    def test_renders(self):
        html = build_categories([{"name": "Web", "repos": ["a"], "description": "Web stuff"}])
        assert "Web" in html


class TestBuildRecommendations:
    def test_renders(self):
        html = build_recommendations([{"priority": "high", "title": "Do this", "description": "Details"}])
        assert "Do this" in html
        assert "HIGH" in html


class TestBuildRepoCard:
    def test_renders_card(self):
        repo = SAMPLE_REVIEW["repository_reviews"][0]
        html = build_repo_card(repo)
        assert "proj-a" in html
        assert "80" in html
        assert "Infra:" in html
        assert "Tests" in html

    def test_card_with_detail_url(self):
        repo = dict(SAMPLE_REVIEW["repository_reviews"][0])
        repo["_detail_url"] = "/report/1/repo/proj-a"
        html = build_repo_card(repo)
        assert "/report/1/repo/proj-a" in html


class TestBuildAllRepoCards:
    def test_sorted_by_recommendation(self):
        html = build_all_repo_cards(SAMPLE_REVIEW["repository_reviews"])
        pos_a = html.find("proj-a")
        pos_b = html.find("proj-b")
        assert pos_a < pos_b


class TestBuildQuickNav:
    def test_renders_links(self):
        html = build_quick_nav(SAMPLE_REVIEW["repository_reviews"])
        assert "proj-a" in html
        assert "proj-b" in html


class TestBuildCategoryFilterButtons:
    def test_renders(self):
        html = build_category_filter_buttons(SAMPLE_REVIEW["repository_reviews"])
        assert "All" in html
        assert "Web" in html


class TestContributionGraph:
    def test_empty(self):
        assert build_contribution_graph({}) == ""
        assert build_contribution_graph(None) == ""

    def test_renders(self):
        html = build_contribution_graph({
            "total_contributions": 100,
            "weeks": [{"contributionDays": [
                {"date": "2025-06-01", "contributionCount": 5, "color": "#40c463"},
                {"date": "2025-06-02", "contributionCount": 0, "color": "#ebedf0"},
            ]}],
        })
        assert "100 contributions" in html
        assert "Less" in html


class TestCommonVars:
    def test_extracts_fields(self):
        v = _common_vars(SAMPLE_REVIEW)
        assert v["username"] == "testuser"
        assert v["overall"] == 65
        assert v["repo_count"] == 2
        assert v["rec_counts"]["showcase"] == 1
        assert v["rec_counts"]["archive"] == 1
        assert "AI" in v["ai_indicator"]
