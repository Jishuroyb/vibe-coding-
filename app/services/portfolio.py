"""Orchestrates GitHub fetching + SQLite caching.

Flow: fresh cache -> serve it; stale/missing -> fetch from GitHub and re-cache;
GitHub failing (rate limit/offline) -> serve stale cache if we have one.
"""
from typing import Optional

from .. import database as db
from ..github_client import GitHubClient, GitHubError
from . import analytics

_client: Optional[GitHubClient] = None


def client() -> GitHubClient:
    global _client
    if _client is None:
        _client = GitHubClient()
    return _client


def normalize_username(raw: str) -> str:
    name = (raw or "").strip().lstrip("@")
    if not name or len(name) > 39 or not all(c.isalnum() or c == "-" for c in name):
        raise GitHubError("Enter a valid GitHub username.", 400)
    return name


def ensure_cached(username: str, force: bool = False) -> dict:
    """Make sure profile, repos and contributions are cached. Returns cache metadata."""
    profile = db.get_profile(username)
    contrib = db.get_contributions(username)
    fresh = (
        not force
        and profile and db.is_fresh(profile["fetched_at"])
        and contrib and db.is_fresh(contrib["fetched_at"])
        and db.repos_fetched_at(username)
    )
    if fresh:
        return {"cache": "hit", "fetched_at": profile["fetched_at"], "stale": False, "warning": None}

    gh = client()
    try:
        data = gh.fetch_profile(username)
        repos = gh.fetch_repos(username)
        days, source = gh.fetch_contributions(username)
    except GitHubError as exc:
        if profile and db.repos_fetched_at(username) and exc.status != 404:
            return {"cache": "stale", "fetched_at": profile["fetched_at"], "stale": True, "warning": exc.message}
        raise
    db.save_profile(username, data)
    db.save_repos(username, repos)
    db.save_contributions(username, days, source)
    return {"cache": "miss" if not profile else "refreshed", "fetched_at": db.get_profile(username)["fetched_at"],
            "stale": False, "warning": None}


def build_payload(username: str, sort: str = "stars", language: Optional[str] = None,
                  search: Optional[str] = None, include_forks: bool = False, force: bool = False) -> dict:
    meta = ensure_cached(username, force=force)
    profile = db.get_profile(username)["data"]
    all_repos = db.query_repos(username, include_forks=True)
    shown = db.query_repos(username, sort=sort, language=language, search=search, include_forks=include_forks)
    contrib = db.get_contributions(username)

    return {
        "profile": {
            "login": profile["login"], "name": profile.get("name") or profile["login"],
            "avatar_url": profile.get("avatar_url"), "bio": profile.get("bio"),
            "company": profile.get("company"), "location": profile.get("location"),
            "blog": profile.get("blog"), "html_url": profile.get("html_url"),
            "created_at": profile.get("created_at"),
        },
        "stats": analytics.profile_stats(profile, all_repos),
        "languages": analytics.language_breakdown(all_repos),
        "heatmap": analytics.build_heatmap(contrib["days"]),
        "streaks": analytics.streaks(contrib["days"]),
        "contribution_source": contrib["source"],
        "repos": shown,
        "available_languages": sorted({r["language"] for r in all_repos if r.get("language")}),
        "match": db.latest_match(username),
        "meta": meta,
    }
