#!/usr/bin/env python3
"""
Generate a beautiful multi-page HTML report from a GitHub review JSON.

Usage:
    python generate_report.py data/review.json [--output runtime/output/]

Produces:
    runtime/output/index.html  - Overview dashboard (summary first)
    runtime/output/repos.html  - Detailed per-repo reviews with filtering
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from html import escape


def md_inline(text):
    """Convert inline markdown to HTML while escaping dangerous content.

    Supports: **bold**, *italic*, `code`, and [text](url) links.
    Everything else is HTML-escaped first so no raw HTML injection is possible.
    """
    if not text:
        return ""
    text = escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<em>\1</em>', text)
    text = re.sub(
        r'`([^`]+?)`', r'<code class="px-1 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-xs font-mono">\1</code>', text)
    text = re.sub(
        r'\[([^\]]+)\]\((https?://[^\)]+)\)',
        r'<a href="\2" target="_blank" class="text-blue-600 hover:underline">\1</a>',
        text,
    )
    return text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def score_color(score: int) -> str:
    if score >= 80:
        return "emerald"
    if score >= 60:
        return "blue"
    if score >= 40:
        return "amber"
    return "red"


def score_label(score: int) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 80:
        return "Great"
    if score >= 70:
        return "Good"
    if score >= 60:
        return "Above Average"
    if score >= 50:
        return "Average"
    if score >= 40:
        return "Below Average"
    return "Needs Work"


def ring_svg(score: int, size: int = 120, stroke: int = 8) -> str:
    color_map = {"emerald": "#10b981", "blue": "#3b82f6",
                 "amber": "#f59e0b", "red": "#ef4444"}
    color = color_map.get(score_color(score), "#3b82f6")
    radius = (size - stroke) / 2
    circumference = 2 * 3.14159 * radius
    offset = circumference - (score / 100) * circumference
    cx = cy = size / 2
    return (
        '<svg width="{sz}" height="{sz}" viewBox="0 0 {sz} {sz}" class="transform -rotate-90">'
        '<circle cx="{cx}" cy="{cy}" r="{r}" stroke="#e5e7eb" stroke-width="{sw}" fill="none"/>'
        '<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{c}" stroke-width="{sw}" fill="none"'
        ' stroke-linecap="round" stroke-dasharray="{circ}" stroke-dashoffset="{off}"'
        ' class="transition-all duration-1000 ease-out"/>'
        '</svg>'
    ).format(sz=size, cx=cx, cy=cy, r=radius, sw=stroke, c=color, circ=circumference, off=offset)


def list_items(items, icon="check", color="emerald"):
    icons = {
        "check": '<svg class="w-4 h-4 text-{c}-500 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>',
        "arrow": '<svg class="w-4 h-4 text-{c}-500 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/></svg>',
    }
    svg = icons.get(icon, icons["check"]).replace("{c}", color)
    html = '<ul class="space-y-2">'
    for item in items:
        html += '<li class="flex items-start gap-2">{svg}<span class="text-sm text-gray-600 dark:text-gray-300">{text}</span></li>'.format(
            svg=svg, text=md_inline(item)
        )
    html += "</ul>"
    return html


def priority_badge(priority):
    colors = {
        "high": "bg-red-100 text-red-700 border-red-200",
        "medium": "bg-amber-100 text-amber-700 border-amber-200",
        "low": "bg-blue-100 text-blue-700 border-blue-200",
    }
    cls = colors.get(priority, colors["medium"])
    return '<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border {cls}">{p}</span>'.format(
        cls=cls, p=escape(priority.upper())
    )


def complexity_badge(level):
    colors = {
        "high": "bg-purple-100 text-purple-700",
        "medium": "bg-blue-100 text-blue-700",
        "low": "bg-gray-100 text-gray-600",
    }
    cls = colors.get(level, colors["medium"])
    return '<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium {cls}">{l} Complexity</span>'.format(
        cls=cls, l=escape(level.title())
    )


def recommendation_badge(rec):
    colors = {
        "showcase": "bg-emerald-100 text-emerald-700 border-emerald-200",
        "improve": "bg-blue-100 text-blue-700 border-blue-200",
        "keep": "bg-gray-100 text-gray-600 border-gray-200",
        "archive": "bg-red-100 text-red-600 border-red-200",
    }
    icons_map = {"showcase": "&#9733;", "improve": "&#8593;",
                 "keep": "&#10003;", "archive": "&#8986;"}
    cls = colors.get(rec, colors["keep"])
    icon = icons_map.get(rec, "")
    return '<span class="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium border {cls}">{icon} {label}</span>'.format(
        cls=cls, icon=icon, label=escape(rec.title())
    )


def score_card(title, score, icon_svg):
    color = score_color(score)
    return """
    <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-sm border border-gray-100 dark:border-gray-700 p-6 hover:shadow-md transition-shadow">
        <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-{color}-50 flex items-center justify-center text-{color}-600">
                    {icon}
                </div>
                <h3 class="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider">{title}</h3>
            </div>
        </div>
        <div class="flex items-center gap-4">
            <div class="relative">
                {ring}
                <div class="absolute inset-0 flex items-center justify-center">
                    <span class="text-xl font-bold text-gray-800 dark:text-gray-100" style="transform: rotate(0deg)">{score}</span>
                </div>
            </div>
            <div>
                <div class="text-lg font-semibold text-{color}-600">{label}</div>
                <div class="text-sm text-gray-400">out of 100</div>
            </div>
        </div>
    </div>""".format(
        color=color, icon=icon_svg, title=escape(title),
        ring=ring_svg(score, 80, 6), score=score, label=score_label(score)
    )


def render_template(template_path, variables):
    """Load a template and replace {{var}} placeholders."""
    with open(template_path) as f:
        template = f.read()
    for key, value in variables.items():
        template = template.replace("{{" + key + "}}", str(value))
    return template


# ---------------------------------------------------------------------------
# Build section HTML
# ---------------------------------------------------------------------------

def build_score_cards(pr, cr, rp, ar):
    profile_icon = '<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>'
    code_icon = '<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/></svg>'
    pres_icon = '<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 10h16M4 14h16M4 18h16"/></svg>'
    act_icon = '<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>'
    return (
        score_card("Profile", pr.get("score", 0), profile_icon) +
        score_card("Code Quality", cr.get("score", 0), code_icon) +
        score_card("Presentation", rp.get("score", 0), pres_icon) +
        score_card("Activity", ar.get("score", 0), act_icon)
    )


def build_completeness(completeness):
    labels = {
        "has_bio": "Bio", "has_avatar": "Avatar", "has_location": "Location",
        "has_company": "Company", "has_website": "Website", "has_email": "Email",
        "has_social_links": "Social Links", "has_profile_readme": "Profile README",
        "has_pinned_repos": "Pinned Repos",
    }
    html = ""
    for key, label in labels.items():
        has = completeness.get(key, False)
        if has:
            html += (
                '<div class="flex items-center gap-2 p-2 rounded-lg bg-emerald-50">'
                '<svg class="w-4 h-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>'
                '<span class="text-sm text-emerald-700">{label}</span>'
                '</div>'
            ).format(label=label)
        else:
            html += (
                '<div class="flex items-center gap-2 p-2 rounded-lg bg-red-50">'
                '<svg class="w-4 h-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>'
                '<span class="text-sm text-red-600">{label}</span>'
                '</div>'
            ).format(label=label)
    return html


def build_rp_stats(rp):
    html = ""
    for label, pct in [("README", rp.get("repos_with_readme_pct", 0)),
                       ("Description", rp.get("repos_with_description_pct", 0)),
                       ("License", rp.get("repos_with_license_pct", 0)),
                       ("Topics", rp.get("repos_with_topics_pct", 0))]:
        bar_color = score_color(pct)
        html += (
            '<div>'
            '<div class="flex justify-between text-sm mb-1">'
            '<span class="text-gray-600 dark:text-gray-300">{label}</span>'
            '<span class="font-medium text-gray-800 dark:text-gray-100">{pct}%</span>'
            '</div>'
            '<div class="w-full bg-gray-100 dark:bg-gray-700 rounded-full h-2">'
            '<div class="bg-{c}-500 h-2 rounded-full" style="width: {pct}%"></div>'
            '</div>'
            '</div>'
        ).format(label=label, pct=pct, c=bar_color)
    return html


def build_highlights(highlights):
    html = ""
    for proj in highlights:
        langs = "".join(
            '<span class="px-2 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded text-xs">{l}</span>'.format(
                l=escape(l))
            for l in proj.get("languages", [])
        )
        html += """
        <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-6 hover:shadow-md transition-shadow">
            <div class="flex items-start justify-between mb-3">
                <div>
                    <h4 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{name}</h4>
                    <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">{desc}</p>
                </div>
                {badge}
            </div>
            <div class="flex flex-wrap gap-1.5 mb-4">{langs}</div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                    <h5 class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Strengths</h5>
                    {strengths}
                </div>
                <div>
                    <h5 class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Improvements</h5>
                    {improvements}
                </div>
            </div>
        </div>""".format(
            name=escape(proj.get("repo_name", "")),
            desc=md_inline(proj.get("description", "")),
            badge=complexity_badge(proj.get("technical_complexity", "medium")),
            langs=langs,
            strengths=list_items(
                proj.get("strengths", []), "check", "emerald"),
            improvements=list_items(
                proj.get("improvements", []), "arrow", "amber"),
        )
    return html


def build_categories(categories):
    cat_colors = ["blue", "purple", "emerald",
                  "amber", "rose", "cyan", "indigo", "teal"]
    html = ""
    for i, cat in enumerate(categories):
        c = cat_colors[i % len(cat_colors)]
        repos_tags = "".join(
            '<span class="px-2 py-0.5 bg-{c}-50 text-{c}-600 rounded text-xs font-medium">{r}</span>'.format(
                c=c, r=escape(r))
            for r in cat.get("repos", [])
        )
        html += """
        <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-5 hover:shadow-md transition-shadow">
            <div class="flex items-center gap-2 mb-2">
                <div class="w-2 h-2 rounded-full bg-{c}-500"></div>
                <h4 class="text-sm font-semibold text-gray-800 dark:text-gray-100">{name}</h4>
            </div>
            <p class="text-sm text-gray-500 dark:text-gray-400 mb-3">{desc}</p>
            <div class="flex flex-wrap gap-1.5">{tags}</div>
        </div>""".format(c=c, name=escape(cat.get("name", "")), desc=md_inline(cat.get("description", "")), tags=repos_tags)
    return html


def build_recommendations(recommendations):
    html = ""
    for rec in recommendations:
        html += """
        <div class="flex items-start gap-4 p-4 bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 hover:shadow-sm transition-shadow">
            <div class="shrink-0 mt-0.5">{badge}</div>
            <div>
                <h4 class="text-sm font-semibold text-gray-800 dark:text-gray-100">{title}</h4>
                <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">{desc}</p>
            </div>
        </div>""".format(
            badge=priority_badge(rec.get("priority", "medium")),
            title=md_inline(rec.get("title", "")),
            desc=md_inline(rec.get("description", "")),
        )
    return html


def build_summary(summary):
    html = ""
    for para in summary.split("\n\n"):
        para = para.strip()
        if para:
            html += '<p class="text-gray-200 leading-relaxed">{}</p>'.format(
                md_inline(para))
    return html


# ---------------------------------------------------------------------------
# Repo cards (for repos.html)
# ---------------------------------------------------------------------------

def build_repo_card(repo):
    name = escape(repo.get("repo_name", ""))
    url = escape(repo.get("url", ""))
    desc = md_inline(repo.get("description", "No description"))
    score = repo.get("score", 0)
    lang = escape(repo.get("primary_language", "") or "")
    is_private = repo.get("is_private", False)
    last_activity = escape(repo.get("last_activity", ""))
    stars = repo.get("stars", 0)
    forks = repo.get("forks", 0)
    open_issues = repo.get("open_issues", 0)
    commit_quality = md_inline(repo.get("commit_quality", ""))
    verdict = md_inline(repo.get("verdict", ""))
    rec = repo.get("recommendation", "keep")
    complexity = repo.get("technical_complexity", "medium")
    category = escape(repo.get("category", ""))
    all_langs = repo.get("all_languages", [])

    meta_badges = recommendation_badge(
        rec) + " " + complexity_badge(complexity)
    if is_private:
        meta_badges += ' <span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-700 text-gray-200">Private</span>'

    lang_tags = "".join(
        '<span class="px-2 py-0.5 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 rounded text-xs">{l}</span>'.format(
            l=escape(l))
        for l in all_langs[:6]
    )

    presence_html = ""
    for label, has in [("README", repo.get("has_readme", False)),
                       ("License", repo.get("has_license", False)),
                       ("Description", repo.get("has_description", False)),
                       ("Topics", repo.get("has_topics", False))]:
        if has:
            presence_html += '<span class="text-xs text-emerald-600">&#10003; {}</span>'.format(
                label)
        else:
            presence_html += '<span class="text-xs text-red-400">&#10007; {}</span>'.format(
                label)

    infra_html = ""
    for label, has in [("Tests", repo.get("has_tests", False)),
                       ("CI/CD", repo.get("has_ci", False)),
                       ("Docker", repo.get("has_docker", False)),
                       ("Docs", repo.get("has_docs", False))]:
        if has:
            infra_html += '<span class="text-xs text-blue-600">&#10003; {}</span>'.format(
                label)
        else:
            infra_html += '<span class="text-xs text-gray-400">&#10007; {}</span>'.format(
                label)

    observations = repo.get("code_observations", [])
    obs_html = list_items(observations, "check",
                          "blue") if observations else ""

    strengths_html = list_items(repo.get("strengths", []), "check", "emerald")
    improvements_html = list_items(
        repo.get("improvements", []), "arrow", "amber")

    commit_section = ""
    if commit_quality:
        commit_section = (
            '<div>'
            '<h5 class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">Commit Quality</h5>'
            '<p class="text-sm text-gray-600 dark:text-gray-300">' + commit_quality + '</p>'
            '</div>'
        )

    pr_activity = md_inline(repo.get("pr_activity", ""))
    pr_section = ""
    if pr_activity:
        pr_section = (
            '<div>'
            '<h5 class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">PR Activity</h5>'
            '<p class="text-sm text-gray-600 dark:text-gray-300">' + pr_activity + '</p>'
            '</div>'
        )

    obs_section = ""
    if observations:
        obs_section = (
            '<div>'
            '<h5 class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Code Observations</h5>'
            + obs_html +
            '</div>'
        )

    detail_url = repo.get("_detail_url", "")
    score_ring_small = ring_svg(score, 36, 3)

    name_link = '<a href="{}" class="text-lg font-semibold text-gray-800 dark:text-gray-100 hover:text-blue-600 transition-colors truncate">{}</a>'.format(
        escape(detail_url) if detail_url else url, name
    )
    gh_icon = ""
    if detail_url:
        gh_icon = (
            ' <a href="{}" target="_blank" title="View on GitHub" class="shrink-0 text-gray-400 hover:text-gray-600">'
            '<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">'
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>'
            '</svg></a>'
        ).format(url)

    return """
    <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 overflow-hidden hover:shadow-md transition-shadow"
         data-repo="{name}" data-score="{score}" data-recommendation="{rec}"
         data-category="{cat_lower}" data-activity="{activity}"
         data-description="{desc}" data-languages="{langs_str}"
         id="repo-{name}">
        <div class="p-5 border-b border-gray-50 dark:border-gray-700">
            <div class="flex items-start justify-between mb-2">
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1">
                        {name_link}{gh_icon}
                        <div class="relative shrink-0" style="width:36px;height:36px;">
                            {score_ring}
                            <div class="absolute inset-0 flex items-center justify-center">
                                <span class="text-[10px] font-bold text-gray-700 dark:text-gray-200" style="transform:rotate(0deg)">{score}</span>
                            </div>
                        </div>
                    </div>
                    <p class="text-sm text-gray-500 dark:text-gray-400">{desc}</p>
                </div>
            </div>
            <div class="flex flex-wrap items-center gap-2 mt-3">
                {meta_badges}
                <span class="text-xs text-gray-400">{category}</span>
            </div>
        </div>
        <div class="p-5 space-y-4">
            <div class="flex flex-wrap items-center justify-between gap-2">
                <div class="flex flex-wrap gap-1.5">{lang_tags}</div>
                <div class="flex items-center gap-4 text-xs text-gray-500">
                    <span>&#9733; {stars}</span>
                    <span>&#9741; {forks}</span>
                    <span>&#9679; {issues} issues</span>
                    <span>&#128197; {activity}</span>
                </div>
            </div>
            <div class="flex flex-wrap gap-3 p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">{presence}</div>
            <div class="flex flex-wrap gap-3 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
                <span class="text-xs font-medium text-blue-700 dark:text-blue-300 mr-1">Infra:</span>
                {infra}
            </div>
            {commit_section}
            {pr_section}
            {obs_section}
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                    <h5 class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Strengths</h5>
                    {strengths}
                </div>
                <div>
                    <h5 class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">Improvements</h5>
                    {improvements}
                </div>
            </div>
        </div>
        <div class="px-5 py-3 bg-gray-50 dark:bg-gray-700/50 border-t border-gray-100 dark:border-gray-700">
            <p class="text-sm text-gray-700 dark:text-gray-200"><span class="font-medium">Verdict:</span> {verdict}</p>
        </div>
    </div>""".format(
        name=name, score=score, rec=rec, cat_lower=category.lower(),
        activity=last_activity, desc=desc, langs_str=",".join(all_langs),
        name_link=name_link, gh_icon=gh_icon,
        score_ring=score_ring_small, meta_badges=meta_badges,
        category=category, lang_tags=lang_tags, stars=stars, forks=forks,
        issues=open_issues, presence=presence_html, infra=infra_html,
        commit_section=commit_section, pr_section=pr_section,
        obs_section=obs_section,
        strengths=strengths_html, improvements=improvements_html,
        verdict=verdict,
    )


# ---------------------------------------------------------------------------
# Contribution graph, language bar, and repo detail helpers
# ---------------------------------------------------------------------------

GRAPH_COLORS = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]
GRAPH_COLORS_DARK = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def build_contribution_graph(calendar_data):
    """Render a GitHub-style contribution heatmap from calendar data."""
    if not calendar_data or not calendar_data.get("weeks"):
        return ""

    weeks = calendar_data["weeks"]
    total = calendar_data.get("total_contributions", 0)

    max_count = max(
        (d.get("contributionCount", 0)
         for w in weeks for d in w.get("contributionDays", [])),
        default=1,
    ) or 1

    def level(count):
        if count == 0:
            return 0
        ratio = count / max_count
        if ratio < 0.25:
            return 1
        if ratio < 0.5:
            return 2
        if ratio < 0.75:
            return 3
        return 4

    cells = ""
    month_markers = []
    for wi, week in enumerate(weeks):
        for day in week.get("contributionDays", []):
            cnt = day.get("contributionCount", 0)
            lvl = level(cnt)
            date = day.get("date", "")
            cells += (
                '<div title="{cnt} contributions on {date}" '
                'style="grid-column:{col};grid-row:{row};width:11px;height:11px;border-radius:2px;'
                'background:{lc}" class="contrib-cell" data-dark="{dc}"></div>'
            ).format(
                cnt=cnt, date=date, col=wi + 1, row=int(date[8:10] if len(date) >= 10 else 1) % 7 + 1 if date else 1,
                lc=GRAPH_COLORS[lvl], dc=GRAPH_COLORS_DARK[lvl],
            )
            if date and date[8:10] in ("01", "02") and wi > 0:
                m = int(date[5:7]) - 1 if len(date) >= 7 else 0
                if not month_markers or month_markers[-1][1] != m:
                    month_markers.append((wi, m))

    month_labels_html = ""
    for col, mi in month_markers:
        month_labels_html += '<span style="position:absolute;left:{}px" class="text-[10px] text-gray-400">{}</span>'.format(
            col * 14, MONTH_LABELS[mi]
        )

    return (
        '<div class="bg-white dark:bg-gray-800 rounded-2xl border border-gray-100 dark:border-gray-700 p-6">'
        '<div class="flex items-center justify-between mb-4">'
        '<h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wider">Contribution Graph</h3>'
        '<span class="text-sm font-medium text-gray-700 dark:text-gray-200">{total} contributions in the last year</span>'
        '</div>'
        '<div class="overflow-x-auto pb-2">'
        '<div style="display:grid;grid-template-columns:repeat({cols},11px);grid-template-rows:repeat(7,11px);gap:3px;">'
        '{cells}'
        '</div>'
        '<div class="relative mt-1 h-4" style="width:{width}px;">{months}</div>'
        '</div>'
        '<div class="flex items-center gap-1 mt-3 justify-end text-[10px] text-gray-400">'
        '<span>Less</span>'
        '{legend}'
        '<span>More</span>'
        '</div>'
        '</div>'
    ).format(
        total=total,
        cols=len(weeks),
        cells=cells,
        width=len(weeks) * 14,
        months=month_labels_html,
        legend="".join(
            '<div style="width:11px;height:11px;border-radius:2px;background:{}" class="contrib-cell" data-dark="{}"></div>'.format(
                GRAPH_COLORS[i], GRAPH_COLORS_DARK[i]
            ) for i in range(5)
        ),
    )


def build_language_bar(languages_dict):
    """Render a horizontal stacked bar chart from a languages dict (lang: bytes)."""
    if not languages_dict:
        return '<p class="text-sm text-gray-400">No language data available</p>'

    total = sum(languages_dict.values()) or 1
    lang_colors = {
        "JavaScript": "#f1e05a", "TypeScript": "#3178c6", "Python": "#3572A5",
        "HTML": "#e34c26", "CSS": "#563d7c", "Go": "#00ADD8", "Rust": "#dea584",
        "Java": "#b07219", "C": "#555555", "C++": "#f34b7d", "C#": "#178600",
        "Ruby": "#701516", "PHP": "#4F5D95", "Shell": "#89e051", "Swift": "#F05138",
        "Kotlin": "#A97BFF", "Dart": "#00B4AB", "Lua": "#000080", "Astro": "#ff5a03",
    }

    bar_parts = ""
    legend_parts = ""
    for lang, bytes_count in sorted(languages_dict.items(), key=lambda x: -x[1]):
        pct = round(bytes_count / total * 100, 1)
        if pct < 0.5:
            continue
        color = lang_colors.get(lang, "#8b8b8b")
        bar_parts += '<div style="width:{}%;background:{};height:8px;" title="{} {}%"></div>'.format(
            pct, color, escape(lang), pct)
        legend_parts += (
            '<div class="flex items-center gap-1.5">'
            '<span style="width:8px;height:8px;border-radius:50%;background:{};" class="shrink-0"></span>'
            '<span class="text-xs text-gray-600 dark:text-gray-300">{}</span>'
            '<span class="text-xs text-gray-400">{}%</span>'
            '</div>'
        ).format(color, escape(lang), pct)

    return (
        '<div class="w-full flex rounded-full overflow-hidden mb-3">{bar}</div>'
        '<div class="flex flex-wrap gap-x-4 gap-y-1">{legend}</div>'
    ).format(bar=bar_parts, legend=legend_parts)


def build_commit_table(commits):
    """Render a table of recent commits."""
    if not commits:
        return '<p class="text-sm text-gray-400">No recent commits available</p>'

    rows = ""
    for c in commits:
        rows += (
            '<tr class="border-b border-gray-50 dark:border-gray-700">'
            '<td class="py-2 pr-3 text-xs font-mono text-blue-600">{sha}</td>'
            '<td class="py-2 pr-3 text-sm text-gray-700 dark:text-gray-200 truncate max-w-xs">{msg}</td>'
            '<td class="py-2 pr-3 text-xs text-gray-400 whitespace-nowrap">{author}</td>'
            '<td class="py-2 text-xs text-gray-400 whitespace-nowrap">{date}</td>'
            '</tr>'
        ).format(
            sha=escape(c.get("sha", "")),
            msg=escape(c.get("message", "")),
            author=escape(c.get("author", "")),
            date=escape(c.get("date", "")[:10]),
        )

    return (
        '<div class="overflow-x-auto">'
        '<table class="w-full">'
        '<thead><tr class="text-xs text-gray-400 uppercase tracking-wider text-left">'
        '<th class="pb-2 pr-3">SHA</th><th class="pb-2 pr-3">Message</th>'
        '<th class="pb-2 pr-3">Author</th><th class="pb-2">Date</th>'
        '</tr></thead>'
        '<tbody>{rows}</tbody>'
        '</table></div>'
    ).format(rows=rows)


def build_infra_grid(fta):
    """Render an infrastructure analysis grid."""
    items = [
        ("Tests", fta.get("has_tests", False), "Test suite detected",
         "No tests found"),
        ("CI/CD", fta.get("has_ci", False), "CI/CD pipeline configured",
         "No CI/CD configuration"),
        ("Docker", fta.get("has_docker", False), "Docker configuration present",
         "No Docker setup"),
        ("Documentation", fta.get("has_docs", False), "Documentation/contributing guides",
         "No dedicated docs"),
    ]
    html = ""
    for label, has, desc_yes, desc_no in items:
        if has:
            html += (
                '<div class="flex items-start gap-3 p-3 bg-emerald-50 dark:bg-emerald-900/20 rounded-lg">'
                '<svg class="w-5 h-5 text-emerald-500 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">'
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>'
                '<div><span class="text-sm font-medium text-emerald-700 dark:text-emerald-300">{label}</span>'
                '<p class="text-xs text-emerald-600 dark:text-emerald-400 mt-0.5">{desc}</p></div></div>'
            ).format(label=label, desc=desc_yes)
        else:
            html += (
                '<div class="flex items-start gap-3 p-3 bg-gray-50 dark:bg-gray-700/50 rounded-lg">'
                '<svg class="w-5 h-5 text-gray-400 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">'
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>'
                '<div><span class="text-sm font-medium text-gray-500">{label}</span>'
                '<p class="text-xs text-gray-400 mt-0.5">{desc}</p></div></div>'
            ).format(label=label, desc=desc_no)

    file_count = fta.get("file_count", 0)
    dir_count = fta.get("directory_count", 0)
    configs = fta.get("config_files", [])
    if file_count > 0 or configs:
        html += (
            '<div class="col-span-2 flex flex-wrap gap-3 text-xs text-gray-500 mt-1">'
            '<span>{files} files</span><span>{dirs} directories</span>'
        ).format(files=file_count, dirs=dir_count)
        for cfg in configs[:8]:
            html += '<span class="px-1.5 py-0.5 bg-gray-100 dark:bg-gray-700 rounded">{}</span>'.format(
                escape(cfg))
        html += '</div>'

    return html


def build_pr_stats_section(pr_stats, issue_stats=None):
    """Render PR and issue statistics."""
    total_prs = pr_stats.get("total_prs", 0)
    if total_prs == 0 and (not issue_stats or issue_stats.get("total_issues", 0) == 0):
        return '<p class="text-sm text-gray-400">No PR or issue data available</p>'

    html = ""
    if total_prs > 0:
        merged = pr_stats.get("merged_prs", 0)
        open_prs = pr_stats.get("open_prs", 0)
        rate = pr_stats.get("merge_rate", 0)
        has_reviews = pr_stats.get("has_code_reviews", False)

        html += (
            '<div class="space-y-3">'
            '<div>'
            '<div class="flex justify-between text-sm mb-1">'
            '<span class="text-gray-600 dark:text-gray-300">Merge Rate</span>'
            '<span class="font-medium text-gray-800 dark:text-gray-100">{rate}%</span>'
            '</div>'
            '<div class="w-full bg-gray-100 dark:bg-gray-700 rounded-full h-2">'
            '<div class="bg-emerald-500 h-2 rounded-full" style="width:{rate}%"></div>'
            '</div>'
            '</div>'
            '<div class="flex gap-4 text-sm">'
            '<span class="text-gray-600 dark:text-gray-300">{total} PRs</span>'
            '<span class="text-emerald-600">{merged} merged</span>'
            '<span class="text-blue-600">{open} open</span>'
            '</div>'
        ).format(rate=rate, total=total_prs, merged=merged, open=open_prs)

        if has_reviews:
            html += '<div class="text-xs text-purple-600">&#10003; Uses code reviews</div>'
        html += '</div>'

    if issue_stats and issue_stats.get("total_issues", 0) > 0:
        ti = issue_stats["total_issues"]
        ci = issue_stats.get("closed_issues", 0)
        oi = issue_stats.get("open_issues", 0)
        cr = issue_stats.get("close_rate", 0)
        html += (
            '<div class="mt-4 pt-4 border-t border-gray-100 dark:border-gray-700">'
            '<div class="flex gap-4 text-sm">'
            '<span class="text-gray-600 dark:text-gray-300">{total} issues</span>'
            '<span class="text-emerald-600">{closed} closed ({rate}%)</span>'
            '<span class="text-amber-600">{open} open</span>'
            '</div></div>'
        ).format(total=ti, closed=ci, open=oi, rate=cr)

    return html


def render_repo_detail(review, repo_name, github_data, templates_dir,
                       run_id=None, back_url="/", nav_overview_url="index.html",
                       nav_repos_url="repos.html"):
    """Render a single-repo deep-dive page."""
    v = _common_vars(review)
    repo_review = None
    for r in v["repo_reviews"]:
        if r.get("repo_name") == repo_name:
            repo_review = r
            break
    if not repo_review:
        return None

    details = (github_data or {}).get(
        "top_repo_details", {}).get(repo_name, {})

    languages = details.get("languages", {})
    commits = details.get("recent_commits", [])
    fta = details.get("file_tree_analysis", {})
    pr_st = details.get("pr_stats", {})
    issue_st = details.get("issue_stats", {})

    score = repo_review.get("score", 0)
    url = escape(repo_review.get("url", ""))
    desc = md_inline(repo_review.get("description", ""))
    rec = repo_review.get("recommendation", "keep")
    complexity = repo_review.get("technical_complexity", "medium")
    category = escape(repo_review.get("category", ""))
    infra_score = repo_review.get("infrastructure_score", 0)

    content_vars = {
        "repo_name": escape(repo_name),
        "repo_url": url,
        "repo_desc": desc,
        "score_ring": ring_svg(score, 100, 7),
        "score": str(score),
        "score_label": score_label(score),
        "score_color": score_color(score),
        "rec_badge": recommendation_badge(rec),
        "complexity_badge": complexity_badge(complexity),
        "category": category,
        "language_bar": build_language_bar(languages),
        "stars": str(repo_review.get("stars", 0)),
        "forks": str(repo_review.get("forks", 0)),
        "open_issues": str(repo_review.get("open_issues", 0)),
        "last_activity": escape(repo_review.get("last_activity", "")),
        "infra_grid": build_infra_grid(fta),
        "infra_score": str(infra_score),
        "infra_score_ring": ring_svg(infra_score, 60, 5),
        "pr_stats_html": build_pr_stats_section(pr_st, issue_st),
        "commit_table": build_commit_table(commits),
        "commit_quality": md_inline(repo_review.get("commit_quality", "")),
        "pr_activity": md_inline(repo_review.get("pr_activity", "")),
        "observations": list_items(repo_review.get("code_observations", []), "check", "blue"),
        "strengths": list_items(repo_review.get("strengths", []), "check", "emerald"),
        "improvements": list_items(repo_review.get("improvements", []), "arrow", "amber"),
        "verdict": md_inline(repo_review.get("verdict", "")),
        "ai_indicator": v["ai_indicator"],
    }

    content = render_template(os.path.join(
        templates_dir, "repo_detail.html"), content_vars)

    title = "{} - {} Review".format(escape(repo_name), v["username"])
    base_vars = {
        "title": title,
        "username": v["username"],
        "ai_indicator": v["ai_indicator"],
        "back_url": back_url,
        "nav_overview_class": "text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700",
        "nav_repos_class": "text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700",
        "nav_overview_url": nav_overview_url,
        "nav_repos_url": nav_repos_url,
        "repo_count": str(v["repo_count"]),
        "review_date": v["review_date"],
        "extra_css": "",
        "content": content,
        "run_id": str(run_id) if run_id else "",
        "chat_button": (
            '<button id="chat-toggle" class="no-print px-3 py-1.5 rounded-lg text-sm font-medium '
            'text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-50 '
            'dark:hover:bg-gray-700 flex items-center gap-1.5" title="Chat about this review">'
            '<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">'
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
            'd="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 '
            '01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>'
            '</svg>Chat</button>'
        ) if run_id else "",
    }
    return render_template(os.path.join(templates_dir, "base.html"), base_vars)


def build_all_repo_cards(repo_reviews):
    """Build cards sorted by recommendation order."""
    groups = {"showcase": [], "improve": [], "keep": [], "archive": []}
    for repo in repo_reviews:
        rec = repo.get("recommendation", "keep")
        groups.setdefault(rec, []).append(repo)
    for key in groups:
        groups[key].sort(key=lambda r: r.get("score", 0), reverse=True)
    ordered = groups["showcase"] + groups["improve"] + \
        groups["keep"] + groups["archive"]
    return "".join(build_repo_card(r) for r in ordered)


def build_quick_nav(repo_reviews):
    groups = {"showcase": [], "improve": [], "keep": [], "archive": []}
    for repo in repo_reviews:
        rec = repo.get("recommendation", "keep")
        groups.setdefault(rec, []).append(repo)
    for key in groups:
        groups[key].sort(key=lambda r: r.get("score", 0), reverse=True)
    ordered = groups["showcase"] + groups["improve"] + \
        groups["keep"] + groups["archive"]

    html = ""
    for repo in ordered:
        name = escape(repo.get("repo_name", ""))
        score = repo.get("score", 0)
        color = score_color(score)
        html += (
            '<a href="#repo-{name}" class="block px-2 py-1 rounded text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 truncate">'
            '<span class="inline-block w-2 h-2 rounded-full bg-{c}-500 mr-1.5"></span>'
            '{name} <span class="text-gray-400">({score})</span>'
            '</a>'
        ).format(name=name, c=color, score=score)
    return html


def build_category_filter_buttons(repo_reviews):
    cats = {}
    for repo in repo_reviews:
        cat = repo.get("category", "Other")
        cats[cat] = cats.get(cat, 0) + 1

    html = (
        '<button data-category="all" class="cat-filter-btn active w-full text-left px-3 py-2 rounded-lg text-sm font-medium bg-gray-100 text-gray-800">'
        'All <span class="text-gray-400 float-right">{total}</span>'
        '</button>'
    ).format(total=len(repo_reviews))

    for cat_name, count in sorted(cats.items()):
        html += (
            '<button data-category="{cat_lower}" class="cat-filter-btn w-full text-left px-3 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50">'
            '{cat} <span class="text-gray-400 float-right">{count}</span>'
            '</button>'
        ).format(cat=escape(cat_name), cat_lower=escape(cat_name.lower()), count=count)
    return html


# ---------------------------------------------------------------------------
# Main generation
# ---------------------------------------------------------------------------

AI_SPARKLE = (
    '<span class="inline-flex items-center gap-1 ml-2 px-2 py-0.5 rounded-full text-xs font-medium '
    'bg-purple-50 text-purple-600 border border-purple-200" title="AI-generated analysis">'
    '<svg class="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">'
    '<path d="M12 2l2.09 6.26L20 9.27l-4.91 3.82L16.18 20 12 16.77 7.82 20l1.09-6.91L4 9.27l5.91-1.01z"/>'
    '</svg> AI</span>'
)

ALGO_BADGE = (
    '<span class="inline-flex items-center gap-1 ml-2 px-2 py-0.5 rounded-full text-xs font-medium '
    'bg-gray-100 text-gray-500 border border-gray-200" title="Algorithmically computed">'
    '<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">'
    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z"/>'
    '</svg> Algorithmic</span>'
)


def build_fallback_banner(review, run_id=None):
    """Render a banner explaining why algorithmic scoring was used instead of AI."""
    if review.get("is_ai_generated", False):
        return ""
    reason = review.get("fallback_reason", "")
    detail = review.get("fallback_detail", "")
    if not reason:
        reason = "This review uses algorithmic scoring"

    detail_html = ""
    if detail:
        detail_html = (
            '<details class="mt-2">'
            '<summary class="text-xs text-amber-600 dark:text-amber-400 cursor-pointer hover:underline">'
            'Show technical details</summary>'
            '<p class="mt-1 text-xs text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-900/40 '
            'rounded-lg p-2 font-mono break-all">{detail}</p>'
            '</details>'
        ).format(detail=escape(detail))

    reanalyze_html = ""
    if run_id:
        reanalyze_html = (
            '<button onclick="reanalyzeRun({run_id})" id="reanalyze-btn" '
            'class="mt-3 px-4 py-2 bg-amber-600 text-white rounded-lg text-xs font-medium '
            'hover:bg-amber-500 transition-colors inline-flex items-center gap-1.5">'
            '<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">'
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
            'd="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 '
            '8.003 0 01-15.357-2m15.357 2H15"/></svg>'
            'Re-analyze with AI</button>'
            '<script>'
            'function reanalyzeRun(runId) {{'
            '  var btn = document.getElementById("reanalyze-btn");'
            '  btn.disabled = true; btn.textContent = "Starting...";'
            '  fetch("/api/reanalyze/" + runId, {{method: "POST"}})'
            '    .then(function(r) {{ return r.json(); }})'
            '    .then(function(data) {{'
            '      if (data.error) {{ btn.textContent = data.error; return; }}'
            '      window.location.href = "/";'
            '    }})'
            '    .catch(function(e) {{ btn.textContent = "Error: " + e.message; }});'
            '}}'
            '</script>'
        ).format(run_id=run_id)

    return (
        '<div class="mb-6 p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-2xl">'
        '<div class="flex items-start gap-3">'
        '<svg class="w-5 h-5 text-amber-500 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">'
        '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
        'd="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>'
        '<div class="flex-1">'
        '<p class="text-sm font-medium text-amber-800 dark:text-amber-200">{reason}</p>'
        '<p class="text-xs text-amber-600 dark:text-amber-400 mt-0.5">'
        'Scores are computed from repository metadata (stars, languages, README presence, etc.) '
        'rather than AI-powered analysis. Results may be less nuanced.</p>'
        '{detail_html}'
        '{reanalyze_html}'
        '</div>'
        '</div>'
        '</div>'
    ).format(reason=escape(reason), detail_html=detail_html, reanalyze_html=reanalyze_html)


def _common_vars(review):
    """Extract common variables used by both overview and repos pages."""
    username = escape(review.get("username", "unknown"))
    display_name = escape(review.get("display_name", username))
    headline = escape(review.get("headline", ""))
    overall = review.get("overall_score", 0)
    review_date = escape(review.get("review_date", ""))
    is_ai = review.get("is_ai_generated", False)

    pr = review.get("profile_review", {})
    cr = review.get("code_review", {})
    rp = review.get("repo_presentation", {})
    ar = review.get("activity_review", {})
    repo_reviews = review.get("repository_reviews", [])
    repo_count = len(repo_reviews)

    rec_counts = {"showcase": 0, "improve": 0, "keep": 0, "archive": 0}
    for r in repo_reviews:
        rec = r.get("recommendation", "keep")
        rec_counts[rec] = rec_counts.get(rec, 0) + 1

    ai_indicator = AI_SPARKLE if is_ai else ALGO_BADGE

    return {
        "username": username, "display_name": display_name,
        "headline": headline, "overall": overall,
        "review_date": review_date, "is_ai": is_ai,
        "pr": pr, "cr": cr, "rp": rp, "ar": ar,
        "repo_reviews": repo_reviews, "repo_count": repo_count,
        "rec_counts": rec_counts, "ai_indicator": ai_indicator,
    }


def _build_overview_html(review, templates_dir, github_data=None, run_id=None):
    """Build overview page HTML content (without base wrapper)."""
    v = _common_vars(review)
    pr, cr, rp, ar = v["pr"], v["cr"], v["rp"], v["ar"]
    repo_reviews = v["repo_reviews"]

    primary_langs = cr.get("language_diversity", {}).get(
        "primary_languages", [])
    secondary_langs = cr.get("language_diversity", {}).get(
        "secondary_languages", [])
    lang_tags = "".join(
        '<span class="px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-sm font-medium">{l}</span>'.format(
            l=escape(l))
        for l in primary_langs
    ) + "".join(
        '<span class="px-3 py-1 bg-gray-100 text-gray-600 rounded-full text-sm font-medium">{l}</span>'.format(
            l=escape(l))
        for l in secondary_langs
    )

    readme_text = pr.get("profile_readme_review", "")
    profile_readme_section = ""
    if readme_text:
        profile_readme_section = (
            '<div class="mt-6 bg-white dark:bg-gray-800 rounded-2xl border border-gray-100 dark:border-gray-700 p-6">'
            '<h3 class="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-3">Profile README Review</h3>'
            '<p class="text-sm text-gray-600 dark:text-gray-300 leading-relaxed">' +
            md_inline(readme_text) + '</p>'
            '</div>'
        )

    overview_vars = {
        "overall_ring": ring_svg(v["overall"], 160, 10),
        "overall_score": str(v["overall"]),
        "display_name": v["display_name"],
        "username": v["username"],
        "headline": v["headline"],
        "ai_indicator": v["ai_indicator"],
        "fallback_banner": build_fallback_banner(review, run_id=run_id),
        "lang_tags": lang_tags,
        "summary_html": build_summary(review.get("summary", "")),
        "score_cards": build_score_cards(pr, cr, rp, ar),
        "completeness_html": build_completeness(pr.get("completeness", {})),
        "profile_strengths": list_items(pr.get("strengths", []), "check", "emerald"),
        "profile_improvements": list_items(pr.get("improvements", []), "arrow", "amber"),
        "profile_readme_section": profile_readme_section,
        "rp_stats": build_rp_stats(rp),
        "rp_strengths": list_items(rp.get("strengths", []), "check", "emerald"),
        "rp_improvements": list_items(rp.get("improvements", []), "arrow", "amber"),
        "repo_count": str(v["repo_count"]),
        "highlights_html": build_highlights(cr.get("project_highlights", [])),
        "code_observations": list_items(cr.get("code_quality_observations", []), "check", "blue"),
        "code_strengths": list_items(cr.get("strengths", []), "check", "emerald"),
        "code_improvements": list_items(cr.get("improvements", []), "arrow", "amber"),
        "activity_pattern": md_inline(ar.get("activity_pattern", "")),
        "recent_focus": md_inline(ar.get("recent_focus", "")),
        "account_age": "{:.1f}".format(ar.get("account_age_years", 0)),
        "activity_strengths": list_items(ar.get("strengths", []), "check", "emerald"),
        "activity_improvements": list_items(ar.get("improvements", []), "arrow", "amber"),
        "categories_html": build_categories(review.get("categories", [])),
        "recs_html": build_recommendations(review.get("top_recommendations", [])),
        "contribution_graph_html": build_contribution_graph(
            (github_data or {}).get("contribution_calendar", {})
        ),
    }
    return render_template(os.path.join(templates_dir, "overview.html"), overview_vars), v


def _build_repos_html(review, templates_dir):
    """Build repos page HTML content (without base wrapper)."""
    v = _common_vars(review)
    repo_reviews = v["repo_reviews"]
    rec_counts = v["rec_counts"]

    repos_vars = {
        "repo_count": str(v["repo_count"]),
        "count_showcase": str(rec_counts.get("showcase", 0)),
        "count_improve": str(rec_counts.get("improve", 0)),
        "count_keep": str(rec_counts.get("keep", 0)),
        "count_archive": str(rec_counts.get("archive", 0)),
        "category_filter_buttons": build_category_filter_buttons(repo_reviews),
        "quick_nav_links": build_quick_nav(repo_reviews),
        "repo_cards": build_all_repo_cards(repo_reviews),
        "ai_indicator": v["ai_indicator"],
    }
    return render_template(os.path.join(templates_dir, "repos.html"), repos_vars), v


def _wrap_base(content, v, templates_dir, page="overview", extra_css="", back_url="/",
               nav_overview_url="index.html", nav_repos_url="repos.html", run_id=None):
    """Wrap page content in the base template."""
    is_overview = (page == "overview")
    base_vars = {
        "title": ("GitHub Review - " if is_overview else "Repository Reviews - ") + v["username"],
        "username": v["username"],
        "ai_indicator": v["ai_indicator"],
        "back_url": back_url,
        "nav_overview_class": "bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-100" if is_overview else "text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700",
        "nav_repos_class": "text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700" if is_overview else "bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-100",
        "nav_overview_url": nav_overview_url,
        "nav_repos_url": nav_repos_url,
        "repo_count": str(v["repo_count"]),
        "review_date": v["review_date"],
        "extra_css": extra_css,
        "content": content,
        "run_id": str(run_id) if run_id else "",
        "chat_button": (
            '<button id="chat-toggle" class="no-print px-3 py-1.5 rounded-lg text-sm font-medium '
            'text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-50 '
            'dark:hover:bg-gray-700 flex items-center gap-1.5" title="Chat about this review">'
            '<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">'
            '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
            'd="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 '
            '01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>'
            '</svg>Chat</button>'
        ) if run_id else "",
    }
    return render_template(os.path.join(templates_dir, "base.html"), base_vars)


REPOS_EXTRA_CSS = """
    .filter-btn.active { background: #f3f4f6; color: #1f2937; }
    .cat-filter-btn.active { background: #f3f4f6; color: #1f2937; }
"""


def render_overview(review, templates_dir, back_url="/",
                    nav_overview_url="index.html", nav_repos_url="repos.html",
                    github_data=None, run_id=None):
    """Render the overview page and return the full HTML string."""
    content, v = _build_overview_html(
        review, templates_dir, github_data=github_data, run_id=run_id)
    return _wrap_base(content, v, templates_dir, page="overview", back_url=back_url,
                      nav_overview_url=nav_overview_url, nav_repos_url=nav_repos_url,
                      run_id=run_id)


def render_repos(review, templates_dir, back_url="/",
                 nav_overview_url="index.html", nav_repos_url="repos.html",
                 run_id=None):
    """Render the repos page and return the full HTML string."""
    content, v = _build_repos_html(review, templates_dir)
    return _wrap_base(content, v, templates_dir, page="repos", extra_css=REPOS_EXTRA_CSS, back_url=back_url,
                      nav_overview_url=nav_overview_url, nav_repos_url=nav_repos_url,
                      run_id=run_id)


def generate(review, templates_dir, output_dir=None, github_data=None):
    """
    Generate the report pages.

    If output_dir is provided, writes files to disk (CLI usage).
    If output_dir is None, returns a dict of {"index.html": str, "repos.html": str}.
    """
    index_html = render_overview(
        review, templates_dir, github_data=github_data)
    repos_html = render_repos(review, templates_dir)

    if output_dir is None:
        return {"index.html": index_html, "repos.html": repos_html}

    os.makedirs(output_dir, exist_ok=True)

    with open(os.path.join(output_dir, "index.html"), "w") as f:
        f.write(index_html)
    print("Generated: {}/index.html".format(output_dir))

    with open(os.path.join(output_dir, "repos.html"), "w") as f:
        f.write(repos_html)
    print("Generated: {}/repos.html".format(output_dir))


def main():
    parser = argparse.ArgumentParser(
        description="Generate HTML report from GitHub review JSON")
    parser.add_argument("review_json", help="Path to the review JSON file")
    parser.add_argument(
        "--output", "-o", default="runtime/output", help="Output directory")
    parser.add_argument("--templates", "-t",
                        default="templates", help="Templates directory")
    args = parser.parse_args()

    with open(args.review_json) as f:
        review = json.load(f)

    generate(review, args.templates, args.output)


if __name__ == "__main__":
    main()
