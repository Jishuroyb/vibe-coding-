"""Thin GitHub API client.

* REST  -> profile, repositories, public events
* GraphQL -> full-year contribution calendar (needs GITHUB_TOKEN; GitHub requires auth for GraphQL)

Without a token we fall back to public events (last ~90 days, approximate) so the
dashboard still renders a heatmap.
"""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

from .config import settings


class GitHubError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.message = message
        self.status = status


class GitHubClient:
    def __init__(self) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "dev-portfolio-dashboard",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        self._http = httpx.Client(base_url=settings.github_api, headers=headers, timeout=15)

    # ---- helpers ----
    def _get(self, path: str, **params):
        try:
            resp = self._http.get(path, params=params or None)
        except httpx.HTTPError as exc:
            raise GitHubError(f"Could not reach GitHub: {exc}") from exc
        if resp.status_code == 404:
            raise GitHubError("GitHub user not found.", 404)
        if resp.status_code in (403, 429):
            remaining = resp.headers.get("x-ratelimit-remaining")
            if remaining == "0" or resp.status_code == 429:
                raise GitHubError("GitHub rate limit reached. Add a GITHUB_TOKEN or try again later.", 429)
            raise GitHubError("GitHub refused the request (403).", 403)
        if resp.status_code >= 400:
            raise GitHubError(f"GitHub returned {resp.status_code}.", 502)
        return resp.json()

    # ---- REST ----
    def fetch_profile(self, username: str) -> dict:
        return self._get(f"/users/{username}")

    def fetch_repos(self, username: str, max_pages: int = 5) -> list[dict]:
        repos: list[dict] = []
        for page in range(1, max_pages + 1):
            batch = self._get(f"/users/{username}/repos", per_page=100, page=page, type="owner", sort="pushed")
            repos.extend(batch)
            if len(batch) < 100:
                break
        return repos

    # ---- contributions ----
    def fetch_contributions(self, username: str) -> tuple[list[dict], str]:
        """Returns (days, source). days = [{'date': 'YYYY-MM-DD', 'count': int}] for the last ~year."""
        if settings.github_token:
            try:
                return self._contributions_graphql(username), "graphql"
            except GitHubError:
                pass  # fall back to events rather than failing the whole page
        return self._contributions_from_events(username), "events"

    def _contributions_graphql(self, username: str) -> list[dict]:
        query = """
        query($login: String!) {
          user(login: $login) {
            contributionsCollection {
              contributionCalendar {
                weeks { contributionDays { date contributionCount } }
              }
            }
          }
        }"""
        try:
            resp = self._http.post("/graphql", json={"query": query, "variables": {"login": username}})
        except httpx.HTTPError as exc:
            raise GitHubError(f"GraphQL request failed: {exc}") from exc
        payload = resp.json() if resp.content else {}
        if resp.status_code != 200 or payload.get("errors") or not payload.get("data", {}).get("user"):
            raise GitHubError("GraphQL contribution query failed.")
        weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
        return [
            {"date": d["date"], "count": d["contributionCount"]}
            for w in weeks for d in w["contributionDays"]
        ]

    def _contributions_from_events(self, username: str) -> list[dict]:
        counts: Counter = Counter()
        for page in (1, 2, 3):
            try:
                events = self._get(f"/users/{username}/events/public", per_page=100, page=page)
            except GitHubError:
                break
            if not events:
                break
            for ev in events:
                day = ev["created_at"][:10]
                if ev["type"] == "PushEvent":
                    counts[day] += max(1, ev.get("payload", {}).get("size", 1) or 1)
                elif ev["type"] in {"PullRequestEvent", "IssuesEvent", "PullRequestReviewEvent", "CreateEvent"}:
                    counts[day] += 1
            if len(events) < 100:
                break
        return [{"date": d, "count": c} for d, c in sorted(counts.items())]
