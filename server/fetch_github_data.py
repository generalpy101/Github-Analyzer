#!/usr/bin/env python3
"""
Fetch comprehensive GitHub profile data using the `gh` CLI.

Usage:
    python fetch_github_data.py <username> [--output runtime/data/github_data.json]

Requires: `gh` CLI installed and authenticated.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Optional, Union


def run_gh(args: list, ignore_errors: bool = False) -> Optional[Union[dict, list, str]]:
    """Run a gh CLI command and return parsed JSON output."""
    cmd = ["gh"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            if ignore_errors:
                return None
            print(f"  Warning: {' '.join(cmd)} failed: {result.stderr.strip()}", file=sys.stderr)
            return None
        if not result.stdout.strip():
            return None
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout.strip() if result.stdout.strip() else None
    except subprocess.TimeoutExpired:
        print(f"  Warning: {' '.join(cmd)} timed out", file=sys.stderr)
        return None


def fetch_profile(username: str) -> Optional[dict]:
    """Fetch user profile data."""
    print(f"Fetching profile for {username}...")
    return run_gh(["api", f"users/{username}"])


def fetch_repos(username: str) -> list:
    """Fetch all repos with metadata."""
    print("Fetching repositories...")
    fields = [
        "name", "description", "primaryLanguage", "stargazerCount", "forkCount",
        "isPrivate", "isFork", "isArchived", "createdAt", "updatedAt",
        "pushedAt", "url", "licenseInfo", "repositoryTopics",
        "hasWikiEnabled", "hasIssuesEnabled", "homepageUrl",
        "defaultBranchRef", "diskUsage", "isEmpty",
    ]
    repos = run_gh([
        "repo", "list", username,
        "--limit", "200",
        "--json", ",".join(fields),
    ])
    return repos if repos else []


def fetch_repo_tree(username: str, repo_name: str, default_branch: str = "main") -> dict:
    """Analyze the file tree of a repo to detect infrastructure patterns."""
    tree = run_gh(
        ["api", f"repos/{username}/{repo_name}/git/trees/{default_branch}?recursive=1"],
        ignore_errors=True,
    )
    result = {
        "has_tests": False, "has_ci": False, "has_docker": False,
        "has_docs": False, "file_count": 0, "directory_count": 0,
        "config_files": [],
    }
    if not tree or not isinstance(tree, dict):
        return result

    test_patterns = ("test/", "tests/", "__tests__/", "spec/", "_test.go", "_test.py", ".test.js", ".test.ts", ".spec.ts", ".spec.js")
    ci_patterns = (".github/workflows/", ".gitlab-ci.yml", "Jenkinsfile", ".circleci/", ".travis.yml")
    docker_patterns = ("Dockerfile", "docker-compose.yml", "docker-compose.yaml")
    docs_patterns = ("docs/", "CONTRIBUTING.md", "CHANGELOG.md", "CHANGES.md")
    config_names = {"package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Gemfile", "pom.xml", "build.gradle", "Makefile", "CMakeLists.txt", "setup.py", "requirements.txt", "tsconfig.json"}

    for item in tree.get("tree", []):
        path = item.get("path", "")
        kind = item.get("type", "")
        if kind == "blob":
            result["file_count"] += 1
        elif kind == "tree":
            result["directory_count"] += 1

        path_lower = path.lower()
        if not result["has_tests"] and any(p in path_lower for p in test_patterns):
            result["has_tests"] = True
        if not result["has_ci"] and any(p in path for p in ci_patterns):
            result["has_ci"] = True
        if not result["has_docker"] and any(p in path for p in docker_patterns):
            result["has_docker"] = True
        if not result["has_docs"] and any(p in path_lower for p in docs_patterns):
            result["has_docs"] = True

        basename = path.rsplit("/", 1)[-1]
        if basename in config_names and basename not in result["config_files"]:
            result["config_files"].append(basename)

    return result


def fetch_pr_stats(username: str, repo_name: str) -> dict:
    """Fetch pull request statistics for a repo."""
    prs = run_gh(
        ["api", f"repos/{username}/{repo_name}/pulls?state=all&per_page=100"],
        ignore_errors=True,
    )
    result = {
        "total_prs": 0, "merged_prs": 0, "open_prs": 0,
        "merge_rate": 0.0, "has_code_reviews": False,
    }
    if not prs or not isinstance(prs, list):
        return result

    result["total_prs"] = len(prs)
    for pr in prs:
        if pr.get("state") == "open":
            result["open_prs"] += 1
        if pr.get("merged_at"):
            result["merged_prs"] += 1
        if pr.get("requested_reviewers"):
            result["has_code_reviews"] = True

    if result["total_prs"] > 0:
        result["merge_rate"] = round(result["merged_prs"] / result["total_prs"] * 100, 1)

    return result


def fetch_issue_stats(username: str, repo_name: str) -> dict:
    """Fetch issue statistics for a repo (excluding PRs)."""
    issues = run_gh(
        ["api", f"repos/{username}/{repo_name}/issues?state=all&per_page=100&filter=all"],
        ignore_errors=True,
    )
    result = {"total_issues": 0, "open_issues": 0, "closed_issues": 0, "close_rate": 0.0}
    if not issues or not isinstance(issues, list):
        return result

    for issue in issues:
        if issue.get("pull_request"):
            continue
        result["total_issues"] += 1
        if issue.get("state") == "open":
            result["open_issues"] += 1
        else:
            result["closed_issues"] += 1

    if result["total_issues"] > 0:
        result["close_rate"] = round(result["closed_issues"] / result["total_issues"] * 100, 1)

    return result


def fetch_repo_details(username: str, repo_name: str) -> dict:
    """Fetch detailed data for a single repo."""
    details = {}

    # Languages breakdown
    langs = run_gh(["api", f"repos/{username}/{repo_name}/languages"], ignore_errors=True)
    details["languages"] = langs if langs else {}

    # Recent commits (last 5)
    commits = run_gh(
        ["api", f"repos/{username}/{repo_name}/commits?per_page=5"],
        ignore_errors=True,
    )
    if commits and isinstance(commits, list):
        details["recent_commits"] = [
            {
                "sha": c.get("sha", "")[:7],
                "message": c.get("commit", {}).get("message", "").split("\n")[0],
                "date": c.get("commit", {}).get("author", {}).get("date", ""),
                "author": c.get("commit", {}).get("author", {}).get("name", ""),
            }
            for c in commits
        ]
    else:
        details["recent_commits"] = []

    # Check README existence
    readme = run_gh(["api", f"repos/{username}/{repo_name}/readme"], ignore_errors=True)
    details["has_readme"] = readme is not None and isinstance(readme, dict)

    # Full repo info (topics, homepage, etc.)
    full = run_gh(["api", f"repos/{username}/{repo_name}"], ignore_errors=True)
    if full and isinstance(full, dict):
        details["topics"] = full.get("topics", [])
        details["homepage"] = full.get("homepage", "")
        details["has_pages"] = full.get("has_pages", False)
        details["default_branch"] = full.get("default_branch", "main")
        details["open_issues_count"] = full.get("open_issues_count", 0)
        details["watchers_count"] = full.get("watchers_count", 0)
        details["network_count"] = full.get("network_count", 0)
        details["license"] = full.get("license", {}).get("spdx_id") if full.get("license") else None
    else:
        details["topics"] = []
        details["homepage"] = ""
        details["has_pages"] = False
        details["default_branch"] = "main"
        details["open_issues_count"] = 0
        details["license"] = None

    # File tree analysis (tests, CI, Docker, docs)
    branch = details.get("default_branch", "main")
    details["file_tree_analysis"] = fetch_repo_tree(username, repo_name, branch)

    # PR and issue statistics
    details["pr_stats"] = fetch_pr_stats(username, repo_name)
    details["issue_stats"] = fetch_issue_stats(username, repo_name)

    return details


def fetch_contribution_graph(username: str) -> dict:
    """Fetch the contribution calendar heatmap data via GraphQL."""
    query = json.dumps({
        "query": (
            '{ user(login: "' + username + '") { contributionsCollection { '
            'contributionCalendar { totalContributions weeks { contributionDays { '
            'contributionCount date color } } } } } }'
        )
    })
    result = run_gh(["api", "graphql", "-f", "query=" + json.loads(query)["query"]], ignore_errors=True)
    if not result or not isinstance(result, dict):
        return {"total_contributions": 0, "weeks": []}

    try:
        cal = result["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        return {
            "total_contributions": cal.get("totalContributions", 0),
            "weeks": cal.get("weeks", []),
        }
    except (KeyError, TypeError):
        return {"total_contributions": 0, "weeks": []}


def fetch_contribution_activity(username: str) -> list:
    """Fetch recent public events."""
    print("Fetching recent activity...")
    events = run_gh(["api", f"users/{username}/events?per_page=100"], ignore_errors=True)
    if not events or not isinstance(events, list):
        return []

    summary = []
    for e in events[:100]:
        summary.append({
            "type": e.get("type", ""),
            "repo": e.get("repo", {}).get("name", ""),
            "created_at": e.get("created_at", ""),
        })
    return summary


def fetch_profile_readme(username: str) -> Optional[str]:
    """Fetch profile README content."""
    print("Fetching profile README...")
    readme = run_gh(["api", f"repos/{username}/{username}/readme"], ignore_errors=True)
    if readme and isinstance(readme, dict) and "content" in readme:
        import base64
        try:
            return base64.b64decode(readme["content"]).decode("utf-8")
        except Exception:
            return None
    return None


def fetch_recent_commits(username: str) -> list:
    """Fetch recent commits across all repos."""
    print("Fetching recent commits...")
    result = run_gh(
        ["api", f"search/commits?q=author:{username}&sort=author-date&per_page=20"],
        ignore_errors=True,
    )
    if not result or not isinstance(result, dict):
        return []

    commits = []
    for item in result.get("items", []):
        commits.append({
            "repo": item.get("repository", {}).get("full_name", ""),
            "message": item.get("commit", {}).get("message", "").split("\n")[0],
            "date": item.get("commit", {}).get("author", {}).get("date", ""),
            "url": item.get("html_url", ""),
        })
    return commits


def fetch_all(username, output_path="runtime/data/github_data.json", top_repos_count=15, on_progress=None):
    """
    Fetch all GitHub data for a user and write to output_path.

    Args:
        username: GitHub username
        output_path: Path to write JSON output
        top_repos_count: Number of top repos to fetch details for
        on_progress: Optional callback(message) for progress updates

    Returns:
        The output dict
    """
    def progress(msg):
        print(msg)
        if on_progress:
            on_progress(msg)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    # 1. Profile
    profile = fetch_profile(username)
    if not profile:
        raise RuntimeError("Could not fetch profile. Is `gh` authenticated?")

    # 2. All repos
    repos = fetch_repos(username)
    progress("Found {} repositories".format(len(repos)))

    # 3. Sort repos: non-fork, non-archived, by most recently pushed
    interesting_repos = [
        r for r in repos
        if not r.get("isFork", False) and not r.get("isArchived", False) and not r.get("isEmpty", False)
    ]
    interesting_repos.sort(key=lambda r: r.get("pushedAt", ""), reverse=True)
    top_repos = interesting_repos[:top_repos_count]

    # 4. Fetch details for top repos
    repo_details = {}
    for i, repo in enumerate(top_repos):
        name = repo["name"]
        progress("Fetching details for {} ({}/{})".format(name, i + 1, len(top_repos)))
        repo_details[name] = fetch_repo_details(username, name)

    # 5. Activity & commits
    progress("Fetching activity and commits...")
    activity = fetch_contribution_activity(username)
    recent_commits = fetch_recent_commits(username)

    # 6. Contribution graph (calendar heatmap)
    progress("Fetching contribution graph...")
    contribution_calendar = fetch_contribution_graph(username)

    # 7. Profile README
    profile_readme = fetch_profile_readme(username)

    # 8. Compute summary stats
    all_languages = {}
    for repo in repos:
        pl = repo.get("primaryLanguage")
        lang = pl.get("name") if isinstance(pl, dict) else pl
        if lang:
            all_languages[lang] = all_languages.get(lang, 0) + 1

    total_stars = sum(r.get("stargazerCount", 0) for r in repos)
    total_forks = sum(r.get("forkCount", 0) for r in repos)
    fork_repos = [r for r in repos if r.get("isFork", False)]
    private_repos = [r for r in repos if r.get("isPrivate", False)]

    # Build output
    output = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "username": username,
        "profile": {
            "name": profile.get("name"),
            "bio": profile.get("bio"),
            "company": profile.get("company"),
            "location": profile.get("location"),
            "blog": profile.get("blog"),
            "email": profile.get("email"),
            "twitter_username": profile.get("twitter_username"),
            "hireable": profile.get("hireable"),
            "avatar_url": profile.get("avatar_url"),
            "html_url": profile.get("html_url"),
            "public_repos": profile.get("public_repos"),
            "public_gists": profile.get("public_gists"),
            "followers": profile.get("followers"),
            "following": profile.get("following"),
            "created_at": profile.get("created_at"),
            "updated_at": profile.get("updated_at"),
        },
        "profile_readme": profile_readme,
        "summary_stats": {
            "total_repos": len(repos),
            "public_repos": len(repos) - len(private_repos),
            "private_repos": len(private_repos),
            "forked_repos": len(fork_repos),
            "original_repos": len(repos) - len(fork_repos),
            "total_stars": total_stars,
            "total_forks": total_forks,
            "languages": all_languages,
            "account_age_days": (datetime.utcnow() - datetime.fromisoformat(
                profile.get("created_at", "2020-01-01T00:00:00Z").replace("Z", "+00:00")
            ).replace(tzinfo=None)).days,
        },
        "repositories": repos,
        "top_repo_details": repo_details,
        "recent_activity": activity,
        "recent_commits": recent_commits,
        "contribution_calendar": contribution_calendar,
    }

    # Write output
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    progress("Data written to {}".format(output_path))
    return output


def main():
    parser = argparse.ArgumentParser(description="Fetch GitHub profile data for review")
    parser.add_argument("username", help="GitHub username to analyze")
    parser.add_argument("--output", "-o", default="runtime/data/github_data.json", help="Output JSON file path")
    parser.add_argument("--top-repos", "-n", type=int, default=15, help="Number of top repos to fetch details for")
    args = parser.parse_args()

    try:
        output = fetch_all(args.username, args.output, args.top_repos)
    except RuntimeError as e:
        print("Error: {}".format(e), file=sys.stderr)
        sys.exit(1)

    username = args.username
    all_languages = output["summary_stats"]["languages"]
    total_stars = output["summary_stats"]["total_stars"]
    total_forks = output["summary_stats"]["total_forks"]
    print("\nDone!")
    print("  Profile: {} ({})".format(output["profile"].get("name"), username))
    print("  Repos: {} total".format(output["summary_stats"]["total_repos"]))
    print("  Languages: {}".format(", ".join(sorted(all_languages.keys()))))
    print("  Stars: {} | Forks: {}".format(total_stars, total_forks))


if __name__ == "__main__":
    main()
