"""Tests for server/generate_report.py helper functions."""

from server.generate_report import (
    md_inline,
    score_color,
    score_label,
    build_summary,
    build_fallback_banner,
    build_language_bar,
    build_commit_table,
    build_infra_grid,
    build_pr_stats_section,
)


class TestMdInline:
    def test_plain_text(self):
        assert md_inline("hello world") == "hello world"

    def test_bold(self):
        assert "<strong>bold</strong>" in md_inline("**bold**")

    def test_italic(self):
        assert "<em>italic</em>" in md_inline("*italic*")

    def test_code(self):
        result = md_inline("`useState`")
        assert "<code" in result
        assert "useState" in result

    def test_link(self):
        result = md_inline("[click](https://example.com)")
        assert 'href="https://example.com"' in result
        assert "click" in result

    def test_mixed(self):
        result = md_inline("Use **bold** and `code` together")
        assert "<strong>bold</strong>" in result
        assert "<code" in result

    def test_xss_prevention(self):
        result = md_inline("<script>alert(1)</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_xss_in_bold(self):
        result = md_inline("**<img onerror=alert(1)>**")
        assert "<img" not in result

    def test_empty(self):
        assert md_inline("") == ""
        assert md_inline(None) == ""


class TestScoreHelpers:
    def test_score_color(self):
        assert score_color(90) == "emerald"
        assert score_color(70) == "blue"
        assert score_color(50) == "amber"
        assert score_color(20) == "red"

    def test_score_label(self):
        assert score_label(95) == "Excellent"
        assert score_label(75) == "Good"
        assert score_label(55) == "Average"
        assert score_label(25) == "Needs Work"


class TestBuildSummary:
    def test_paragraphs(self):
        html = build_summary("First paragraph.\n\nSecond paragraph.")
        assert html.count("<p") == 2
        assert "First paragraph." in html
        assert "Second paragraph." in html

    def test_empty(self):
        assert build_summary("") == ""

    def test_markdown_in_summary(self):
        html = build_summary("Uses **React** extensively.")
        assert "<strong>React</strong>" in html


class TestFallbackBanner:
    def test_ai_review_no_banner(self):
        assert build_fallback_banner({"is_ai_generated": True}) == ""

    def test_algorithmic_with_reason(self):
        banner = build_fallback_banner({
            "is_ai_generated": False,
            "fallback_reason": "AI unavailable",
            "fallback_detail": "Connection timeout",
        })
        assert "AI unavailable" in banner
        assert "Connection timeout" in banner
        assert "<details" in banner

    def test_algorithmic_no_reason(self):
        banner = build_fallback_banner({"is_ai_generated": False})
        assert len(banner) > 0
        assert "algorithmic" in banner.lower()


class TestLanguageBar:
    def test_renders_languages(self):
        html = build_language_bar({"Python": 5000, "JavaScript": 3000})
        assert "Python" in html
        assert "JavaScript" in html

    def test_empty(self):
        html = build_language_bar({})
        assert "No language data" in html

    def test_none(self):
        html = build_language_bar(None)
        assert "No language data" in html


class TestCommitTable:
    def test_renders_commits(self):
        commits = [
            {"sha": "abc1234", "message": "fix bug",
                "author": "dev", "date": "2025-01-01T00:00:00Z"},
        ]
        html = build_commit_table(commits)
        assert "abc1234" in html
        assert "fix bug" in html
        assert "dev" in html

    def test_empty(self):
        html = build_commit_table([])
        assert "No recent commits" in html


class TestInfraGrid:
    def test_all_present(self):
        fta = {"has_tests": True, "has_ci": True, "has_docker": True, "has_docs": True,
               "file_count": 100, "directory_count": 20, "config_files": ["package.json"]}
        html = build_infra_grid(fta)
        assert "Test suite detected" in html
        assert "CI/CD pipeline configured" in html
        assert "package.json" in html

    def test_none_present(self):
        fta = {"has_tests": False, "has_ci": False, "has_docker": False, "has_docs": False,
               "file_count": 0, "directory_count": 0, "config_files": []}
        html = build_infra_grid(fta)
        assert "No tests found" in html
        assert "No CI/CD" in html


class TestPrStats:
    def test_with_prs(self):
        html = build_pr_stats_section(
            {"total_prs": 10, "merged_prs": 8, "open_prs": 2,
                "merge_rate": 80.0, "has_code_reviews": True}
        )
        assert "80.0%" in html
        assert "10 PRs" in html
        assert "code reviews" in html

    def test_no_prs(self):
        html = build_pr_stats_section({"total_prs": 0})
        assert "No PR or issue data" in html

    def test_with_issues(self):
        html = build_pr_stats_section(
            {"total_prs": 0},
            {"total_issues": 5, "open_issues": 2,
                "closed_issues": 3, "close_rate": 60.0},
        )
        assert "5 issues" in html
        assert "60.0%" in html
