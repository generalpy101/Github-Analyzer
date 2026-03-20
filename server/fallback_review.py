"""Algorithmic fallback review — computes scores from raw GitHub data without an LLM."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def compute_fallback_review(github_data: dict) -> dict:
    """
    Generate a complete review dict (matching the LLM schema) purely from
    the raw github_data structure.  Used when the LLM call fails or returns
    incomplete results.
    """
    profile = github_data.get("profile", {})
    repos = github_data.get("repositories", [])
    stats = github_data.get("summary_stats", {})
    details = github_data.get("top_repo_details", {})
    readme_raw = github_data.get("profile_readme")
    username = github_data.get("username", "unknown")
    display_name = profile.get("name") or username

    # ── Profile score ────────────────────────────────────────────────
    pr_score = 0
    completeness = {
        "has_bio": bool(profile.get("bio")),
        "has_avatar": bool(profile.get("avatar_url")),
        "has_location": bool(profile.get("location")),
        "has_company": bool(profile.get("company")),
        "has_website": bool(profile.get("blog")),
        "has_email": bool(profile.get("email")),
        "has_social_links": bool(profile.get("twitter_username")),
        "has_profile_readme": bool(readme_raw),
        "has_pinned_repos": False,  # Can't determine from data alone
    }
    weights = {
        "has_bio": 15, "has_avatar": 10, "has_location": 10,
        "has_company": 10, "has_website": 10, "has_email": 10,
        "has_profile_readme": 15, "has_social_links": 5,
        "has_pinned_repos": 5,
    }
    for key, has in completeness.items():
        if has:
            pr_score += weights.get(key, 0)
    followers = profile.get("followers", 0)
    if followers > 0:
        pr_score += 5
    if followers > 10:
        pr_score += 3
    if followers > 50:
        pr_score += 2
    pr_score = min(pr_score, 100)

    pr_strengths = []
    pr_improvements = []
    field_labels = {
        "has_bio": ("Has a bio describing their work", "Add a bio describing your role and interests"),
        "has_avatar": ("Has a profile avatar", "Add a profile avatar"),
        "has_location": ("Location is listed", "Add your location"),
        "has_company": ("Company/organization is listed", "Add your company or organization"),
        "has_website": ("Website or blog is linked", "Add a personal website or blog link"),
        "has_email": ("Public email is provided", "Add a public email for contact"),
        "has_social_links": ("Social media links present", "Add social links (Twitter, LinkedIn)"),
        "has_profile_readme": ("Has a profile README", "Create a profile README to introduce yourself"),
        "has_pinned_repos": ("Has pinned repositories", "Pin your best repositories to your profile"),
    }
    for key, (strength_text, improvement_text) in field_labels.items():
        if completeness[key]:
            pr_strengths.append(strength_text)
        else:
            pr_improvements.append(improvement_text)

    readme_review = ""
    if readme_raw:
        readme_review = "Profile README is present. Consider customizing it with project highlights, current focus, and contact links."
    else:
        readme_review = "No profile README found. Adding one would help visitors understand your work."

    # ── Repository reviews ───────────────────────────────────────────
    now = datetime.now(timezone.utc)
    repo_reviews = []
    original_repos = [r for r in repos if not r.get("isFork", False)]

    for repo in original_repos:
        name = repo.get("name", "")
        detail = details.get(name, {})
        has_detail = bool(detail)
        score = 20  # base

        has_desc = bool(repo.get("description", "").strip())
        has_readme = detail.get("has_readme", True) if has_detail else None
        has_license = bool(detail.get("license") or repo.get("licenseInfo"))
        raw_topics = repo.get("repositoryTopics") or detail.get("topics", [])
        if isinstance(raw_topics, dict):
            raw_topics = raw_topics.get("nodes", [])
        has_topics = bool(raw_topics)

        if has_desc:
            score += 10
        if has_readme is True or has_readme is None:
            score += 15
        if has_license:
            score += 10
        if has_topics:
            score += 10

        stars = repo.get("stargazerCount", 0)
        if stars > 0:
            score += 5
        if stars > 5:
            score += 5

        # Recent activity
        pushed_at = repo.get("pushedAt", "")
        last_activity = pushed_at[:10] if pushed_at else ""
        if pushed_at:
            try:
                pushed_dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                days_ago = (now - pushed_dt).days
                if days_ago < 180:
                    score += 10
            except (ValueError, TypeError):
                pass

        # Commits
        commits = detail.get("recent_commits", [])
        if commits:
            score += 5

        # Multi-language
        langs = detail.get("languages", {})
        if isinstance(langs, dict) and len(langs) > 1:
            score += 5
        all_languages = list(langs.keys()) if isinstance(langs, dict) else []

        # Infrastructure analysis from file tree (None = unknown for repos without details)
        fta = detail.get("file_tree_analysis", {})
        if has_detail:
            has_tests = fta.get("has_tests", False)
            has_ci = fta.get("has_ci", False)
            has_docker = fta.get("has_docker", False)
            has_docs_dir = fta.get("has_docs", False)
        else:
            has_tests = None
            has_ci = None
            has_docker = None
            has_docs_dir = None
        if has_tests is True:
            score += 10
        if has_ci is True:
            score += 10
        if has_docker is True:
            score += 5
        if has_docs_dir is True:
            score += 5

        infra_points = (
            (35 if has_tests is True else 0) +
            (35 if has_ci is True else 0) +
            (15 if has_docker is True else 0) +
            (15 if has_docs_dir is True else 0)
        )
        infrastructure_score = min(infra_points, 100)

        # PR stats
        pr_st = detail.get("pr_stats", {})
        pr_total = pr_st.get("total_prs", 0)
        pr_merge_rate = pr_st.get("merge_rate", 0)
        pr_has_reviews = pr_st.get("has_code_reviews", False)
        if pr_total > 0:
            pr_activity = "{}% merge rate across {} PRs".format(pr_merge_rate, pr_total)
            if pr_has_reviews:
                pr_activity += " with code reviews"
        else:
            pr_activity = ""

        score = min(score, 100)

        # Recommendation
        if score >= 70:
            recommendation = "showcase"
        elif score >= 50:
            recommendation = "improve"
        elif score >= 30:
            recommendation = "keep"
        else:
            recommendation = "archive"

        # Primary language
        pl = repo.get("primaryLanguage")
        if isinstance(pl, dict):
            primary_lang = pl.get("name", "")
        else:
            primary_lang = pl or ""
        if not all_languages and primary_lang:
            all_languages = [primary_lang]

        # Category
        category = _infer_category(primary_lang, name, repo.get("description", ""))

        # Complexity
        disk = repo.get("diskUsage", 0) or 0
        lang_count = len(all_languages)
        if disk > 5000 or lang_count > 3:
            complexity = "high"
        elif disk > 1000 or lang_count > 1:
            complexity = "medium"
        else:
            complexity = "low"

        # Commit quality
        if commits:
            avg_len = sum(len(c.get("message", "")) for c in commits) / len(commits)
            commit_quality = "Descriptive commit messages" if avg_len > 15 else "Short commit messages — consider more detail"
        else:
            commit_quality = "No recent commits available"

        # Strengths / improvements
        strengths = []
        improvements = []
        observations = []
        if has_readme is True:
            strengths.append("Has a README file")
        elif has_readme is False:
            improvements.append("Add a README explaining the project")
        if has_desc:
            strengths.append("Has a description")
        else:
            improvements.append("Add a project description")
        if has_license:
            strengths.append("Has a license")
        else:
            improvements.append("Add a license to clarify usage terms")
        if has_topics:
            strengths.append("Has topic tags for discoverability")
        else:
            improvements.append("Add topic tags for discoverability")
        if has_tests is True:
            strengths.append("Has test suite")
        elif has_tests is False:
            improvements.append("Add tests to improve reliability")
        if has_ci is True:
            strengths.append("Has CI/CD pipeline")
        elif has_ci is False:
            improvements.append("Add CI/CD for automated testing")
        if has_docker is True:
            strengths.append("Has Docker configuration")
        if has_docs_dir is True:
            strengths.append("Has docs/contributing guidelines")
        if stars > 0:
            strengths.append("{} star{}".format(stars, "s" if stars != 1 else ""))
        if pr_total > 0:
            observations.append("{} PRs ({}% merged)".format(pr_total, pr_merge_rate))
        if primary_lang:
            observations.append("Primary language: {}".format(primary_lang))
        if lang_count > 1:
            observations.append("Uses {} languages".format(lang_count))

        # Verdict
        if score >= 70:
            verdict = "Well-maintained project worth showcasing."
        elif score >= 50:
            verdict = "Decent project with room for improvement in documentation and presentation."
        elif score >= 30:
            verdict = "Basic project — improve documentation or consider archiving if inactive."
        else:
            verdict = "Minimal project — needs significant work or should be archived."

        open_issues = detail.get("open_issues_count", 0)

        repo_reviews.append({
            "repo_name": name,
            "url": repo.get("url", ""),
            "description": repo.get("description", "") or "No description provided.",
            "primary_language": primary_lang,
            "all_languages": all_languages,
            "stars": stars,
            "forks": repo.get("forkCount", 0),
            "is_private": repo.get("isPrivate", False),
            "score": score,
            "technical_complexity": complexity,
            "category": category,
            "has_readme": bool(has_readme) if has_readme is not None else True,
            "has_license": has_license,
            "has_description": has_desc,
            "has_topics": has_topics,
            "has_tests": bool(has_tests) if has_tests is not None else False,
            "has_ci": bool(has_ci) if has_ci is not None else False,
            "has_docker": bool(has_docker) if has_docker is not None else False,
            "has_docs": bool(has_docs_dir) if has_docs_dir is not None else False,
            "open_issues": open_issues,
            "last_activity": last_activity,
            "commit_quality": commit_quality,
            "pr_activity": pr_activity,
            "infrastructure_score": infrastructure_score,
            "code_observations": observations or ["No detailed observations available"],
            "strengths": strengths or ["Repository exists and is accessible"],
            "improvements": improvements or ["No immediate improvements identified"],
            "verdict": verdict,
            "recommendation": recommendation,
        })

    # ── Code review score ────────────────────────────────────────────
    repo_scores = sorted([r["score"] for r in repo_reviews], reverse=True)
    top_scores = repo_scores[:5] if repo_scores else [0]
    cr_score = int(sum(top_scores) / len(top_scores))

    languages = stats.get("languages", {})
    sorted_langs = sorted(languages.items(), key=lambda x: x[1], reverse=True)
    primary_langs = [l[0] for l in sorted_langs[:5]]
    secondary_langs = [l[0] for l in sorted_langs[5:]]

    # Project highlights (top 3 repos)
    top_repos = sorted(repo_reviews, key=lambda r: r["score"], reverse=True)[:3]
    highlights = []
    for r in top_repos:
        highlights.append({
            "repo_name": r["repo_name"],
            "description": r["description"],
            "technical_complexity": r["technical_complexity"],
            "languages": r["all_languages"],
            "strengths": r["strengths"][:2],
            "improvements": r["improvements"][:2],
        })

    # ── Presentation score ───────────────────────────────────────────
    total = len(original_repos) or 1
    pct_readme = int(sum(1 for r in repo_reviews if r["has_readme"]) / total * 100)
    pct_desc = int(sum(1 for r in repo_reviews if r["has_description"]) / total * 100)
    pct_license = int(sum(1 for r in repo_reviews if r["has_license"]) / total * 100)
    pct_topics = int(sum(1 for r in repo_reviews if r["has_topics"]) / total * 100)
    rp_score = int((pct_readme + pct_desc + pct_license + pct_topics) / 4)

    # ── Activity score ───────────────────────────────────────────────
    recent_activity = github_data.get("recent_activity", [])
    recent_commits = github_data.get("recent_commits", [])
    account_age_days = stats.get("account_age_days", 1)
    account_age_years = round(account_age_days / 365.25, 1)

    ar_score = 0
    ar_score += min(len(recent_activity) * 2, 30)
    ar_score += min(len(recent_commits) * 3, 30)
    if account_age_years > 1:
        ar_score += 10
    if account_age_years > 3:
        ar_score += 10
    # Bonus for recently active repos
    active_repos = sum(1 for r in repo_reviews
                       if r.get("last_activity", "") >= _months_ago(6))
    ar_score += min(active_repos * 2, 20)
    ar_score = min(ar_score, 100)

    # Activity pattern
    if recent_activity:
        event_types = {}
        for ev in recent_activity:
            t = ev.get("type", "Unknown")
            event_types[t] = event_types.get(t, 0) + 1
        top_events = sorted(event_types.items(), key=lambda x: x[1], reverse=True)[:3]
        activity_pattern = "Recent activity includes: {}".format(
            ", ".join("{} ({})".format(t, c) for t, c in top_events)
        )
    else:
        activity_pattern = "No recent public activity detected."

    # Recent focus
    if recent_commits:
        repo_freq = {}
        for c in recent_commits:
            rname = c.get("repo", "")
            repo_freq[rname] = repo_freq.get(rname, 0) + 1
        top_repo = max(repo_freq.items(), key=lambda x: x[1])[0]
        recent_focus = "Most recent work focused on {}".format(top_repo)
    else:
        recent_focus = "No recent commit activity detected."

    # ── Overall score ────────────────────────────────────────────────
    overall = int(pr_score * 0.15 + cr_score * 0.35 + rp_score * 0.20 + ar_score * 0.30)

    # ── Categories ───────────────────────────────────────────────────
    cat_map = {}
    for r in repo_reviews:
        cat = r.get("category", "Other")
        if cat not in cat_map:
            cat_map[cat] = {"name": cat, "repos": [], "description": ""}
        cat_map[cat]["repos"].append(r["repo_name"])
    categories = list(cat_map.values())
    for cat in categories:
        cat["description"] = "{} project{} in this category".format(
            len(cat["repos"]), "s" if len(cat["repos"]) != 1 else ""
        )

    # ── Recommendations ──────────────────────────────────────────────
    recs = []
    if pr_score < 50:
        recs.append({
            "priority": "high",
            "title": "Improve your GitHub profile",
            "description": "Fill in your bio, add social links, and create a custom profile README to make a strong first impression.",
        })
    if rp_score < 50:
        recs.append({
            "priority": "high",
            "title": "Add READMEs and descriptions to repositories",
            "description": "Only {}% of your repos have READMEs. Adding documentation makes your projects more approachable.".format(pct_readme),
        })
    if pct_license < 30:
        recs.append({
            "priority": "medium",
            "title": "Add licenses to your repositories",
            "description": "Only {}% of repos have licenses. Without a license, others can't legally use your code.".format(pct_license),
        })
    archive_count = sum(1 for r in repo_reviews if r["recommendation"] == "archive")
    if archive_count > 3:
        recs.append({
            "priority": "medium",
            "title": "Archive or remove inactive projects",
            "description": "{} repositories scored below 30. Consider archiving them to keep your profile clean.".format(archive_count),
        })
    showcase_count = sum(1 for r in repo_reviews if r["recommendation"] == "showcase")
    if showcase_count > 0:
        recs.append({
            "priority": "low",
            "title": "Highlight your best work",
            "description": "You have {} strong project{}. Pin them to your profile and mention them in your README.".format(
                showcase_count, "s" if showcase_count != 1 else ""
            ),
        })
    if not recs:
        recs.append({
            "priority": "low",
            "title": "Keep up the good work",
            "description": "Your profile is in decent shape. Continue contributing and improving documentation.",
        })

    # ── Summary ──────────────────────────────────────────────────────
    summary = _build_summary(username, display_name, overall, pr_score, cr_score,
                             rp_score, ar_score, len(original_repos), primary_langs,
                             showcase_count, archive_count)

    return {
        "username": username,
        "display_name": display_name,
        "review_date": datetime.now().strftime("%Y-%m-%d"),
        "overall_score": overall,
        "headline": _build_headline(display_name, primary_langs, overall),
        "is_ai_generated": False,
        "profile_review": {
            "score": pr_score,
            "completeness": completeness,
            "profile_readme_review": readme_review,
            "strengths": pr_strengths,
            "improvements": pr_improvements,
        },
        "repository_reviews": repo_reviews,
        "code_review": {
            "score": cr_score,
            "language_diversity": {
                "primary_languages": primary_langs,
                "secondary_languages": secondary_langs,
                "total_count": len(languages),
            },
            "project_highlights": highlights,
            "code_quality_observations": [
                "{} original repositories analyzed".format(len(original_repos)),
                "{} programming languages used".format(len(languages)),
                "Top languages: {}".format(", ".join(primary_langs[:3])) if primary_langs else "No languages detected",
            ],
            "strengths": [
                "Uses {} different programming languages".format(len(languages)),
            ] + (["Has projects scoring 70+ (showcase quality)"] if showcase_count > 0 else []),
            "improvements": [
                "Improve commit message quality across projects",
                "Add tests and CI/CD to key repositories",
            ],
        },
        "repo_presentation": {
            "score": rp_score,
            "repos_with_readme_pct": pct_readme,
            "repos_with_description_pct": pct_desc,
            "repos_with_license_pct": pct_license,
            "repos_with_topics_pct": pct_topics,
            "strengths": (
                ["{}% of repos have READMEs".format(pct_readme)] if pct_readme > 50 else []
            ) + (
                ["{}% of repos have descriptions".format(pct_desc)] if pct_desc > 50 else []
            ) or ["Some repositories have basic documentation"],
            "improvements": (
                ["Add READMEs to more repositories (currently {}%)".format(pct_readme)] if pct_readme < 80 else []
            ) + (
                ["Add descriptions (currently {}%)".format(pct_desc)] if pct_desc < 80 else []
            ) + (
                ["Add licenses (currently {}%)".format(pct_license)] if pct_license < 50 else []
            ) + (
                ["Add topic tags (currently {}%)".format(pct_topics)] if pct_topics < 50 else []
            ) or ["Keep improving documentation"],
        },
        "activity_review": {
            "score": ar_score,
            "account_age_years": account_age_years,
            "activity_pattern": activity_pattern,
            "recent_focus": recent_focus,
            "strengths": [
                "Account is {:.1f} years old".format(account_age_years),
            ] + (
                ["{} recent activity events detected".format(len(recent_activity))] if recent_activity else []
            ) + (
                ["{} recent commits".format(len(recent_commits))] if recent_commits else []
            ) or ["Long-standing GitHub presence"],
            "improvements": (
                ["Increase public contribution frequency"] if len(recent_activity) < 10 else []
            ) + (
                ["Make commits more regularly"] if len(recent_commits) < 5 else []
            ) or ["Maintain current activity level"],
        },
        "categories": categories,
        "top_recommendations": recs,
        "summary": summary,
    }


# ── Helpers ──────────────────────────────────────────────────────────


LANG_CATEGORY_MAP = {
    "Python": "Python Development",
    "JavaScript": "Web Development",
    "TypeScript": "Web Development",
    "HTML": "Web Development",
    "CSS": "Web Development",
    "Go": "Systems & Backend",
    "Rust": "Systems Programming",
    "C": "Systems Programming",
    "C++": "Systems Programming",
    "Java": "Enterprise Development",
    "Kotlin": "Mobile Development",
    "Swift": "Mobile/Apple Development",
    "Ruby": "Web Development",
    "PHP": "Web Development",
    "Shell": "DevOps & Scripting",
    "Lua": "Scripting & Embedded",
    "C#": "Game/Enterprise Development",
}


def _infer_category(language, name, description):
    """Infer project category from language and name."""
    desc_lower = (description or "").lower()
    name_lower = name.lower()

    # Check for common patterns in name/description
    if any(kw in name_lower for kw in ("api", "server", "backend")):
        return "Backend & API"
    if any(kw in name_lower for kw in ("cli", "tool", "util")):
        return "CLI & Tools"
    if any(kw in name_lower for kw in ("clone", "replica")):
        return "Systems Programming"
    if any(kw in desc_lower for kw in ("bot", "automation")):
        return "Automation"
    if any(kw in desc_lower for kw in ("game", "unity")):
        return "Game Development"
    if any(kw in desc_lower for kw in ("machine learning", "ml", "ai", "data")):
        return "Data & ML"

    return LANG_CATEGORY_MAP.get(language, "Software Development")


def _months_ago(n):
    """Return ISO date string for n months ago (approximate)."""
    now = datetime.now(timezone.utc)
    year = now.year
    month = now.month - n
    while month <= 0:
        month += 12
        year -= 1
    return "{:04d}-{:02d}-01".format(year, month)


def _build_headline(display_name, primary_langs, overall):
    """Generate a short headline."""
    if not primary_langs:
        lang_str = "software"
    elif len(primary_langs) == 1:
        lang_str = primary_langs[0]
    else:
        lang_str = "{} and {}".format(primary_langs[0], primary_langs[1])

    if overall >= 80:
        tone = "Strong"
    elif overall >= 60:
        tone = "Solid"
    elif overall >= 40:
        tone = "Developing"
    else:
        tone = "Early-stage"

    return "{} {} developer profile with {} focus".format(tone, lang_str, lang_str)


def _build_summary(username, display_name, overall, pr, cr, rp, ar,
                   repo_count, langs, showcase, archive):
    """Generate a multi-paragraph summary."""
    paragraphs = []

    # Para 1: Overview
    paragraphs.append(
        "{name} (@{user}) has {count} original repositories across {lang_count} "
        "programming languages. The overall profile scores {score}/100, "
        "reflecting a {level} developer presence on GitHub.".format(
            name=display_name, user=username, count=repo_count,
            lang_count=len(langs),
            score=overall,
            level="strong" if overall >= 70 else "moderate" if overall >= 45 else "developing",
        )
    )

    # Para 2: Strengths
    strengths = []
    if cr >= 60:
        strengths.append("solid code quality across top projects")
    if pr >= 60:
        strengths.append("a well-filled profile")
    if ar >= 60:
        strengths.append("consistent activity")
    if langs:
        strengths.append("experience with {}".format(", ".join(langs[:3])))
    if showcase > 0:
        strengths.append("{} showcase-worthy project{}".format(showcase, "s" if showcase != 1 else ""))
    if strengths:
        paragraphs.append("Key strengths include {}.".format(", ".join(strengths)))

    # Para 3: Improvements
    areas = []
    if pr < 50:
        areas.append("profile completeness (score: {})".format(pr))
    if rp < 50:
        areas.append("repository documentation and presentation (score: {})".format(rp))
    if ar < 50:
        areas.append("contribution activity (score: {})".format(ar))
    if archive > 3:
        areas.append("cleaning up {} low-quality repositories".format(archive))
    if areas:
        paragraphs.append("Areas for improvement include {}.".format(", ".join(areas)))

    return "\n\n".join(paragraphs)
