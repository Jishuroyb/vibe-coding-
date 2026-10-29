"""Pure functions that turn cached GitHub data into dashboard-ready numbers.

Everything the UI shows (levels, percentages, streaks, month labels) is computed here
so the frontend only has to draw.
"""
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

# Language colours (GitHub-like) for the pie chart + repo tags.
LANGUAGE_COLORS = {
    "Python": "#3572A5", "JavaScript": "#F1E05A", "TypeScript": "#3178C6", "Java": "#B07219",
    "C++": "#F34B7D", "C": "#6E7B8B", "C#": "#178600", "Go": "#00ADD8", "Rust": "#DEA584",
    "Ruby": "#701516", "PHP": "#4F5D95", "Swift": "#F05138", "Kotlin": "#A97BFF", "Dart": "#00B4AB",
    "HTML": "#E34C26", "CSS": "#8B5CF6", "Shell": "#89E051", "Jupyter Notebook": "#DA5B0B",
    "SQL": "#E38C00", "Scala": "#C22D40", "R": "#198CE7", "Lua": "#4C5AA8", "Vue": "#41B883",
    "Dockerfile": "#384D54", "Makefile": "#427819", "Objective-C": "#438EFF", "Perl": "#0298C3",
}
FALLBACK_COLORS = ["#0F6B7A", "#C98A1B", "#7A5C99", "#4E8F5B", "#B5523B", "#5B7DB1", "#8A8F3C", "#A05A7A"]


def language_color(name: str, index: int = 0) -> str:
    return LANGUAGE_COLORS.get(name, FALLBACK_COLORS[index % len(FALLBACK_COLORS)])


# ---------------------------------------------------------------- languages
def language_breakdown(repos: Iterable[dict], top_n: int = 6) -> list[dict]:
    """Share of non-fork repos per primary language. Tail is grouped into 'Other'."""
    counts = Counter(r["language"] for r in repos if r.get("language") and not r.get("is_fork"))
    total = sum(counts.values())
    if not total:
        return []
    ordered = counts.most_common()
    head, tail = ordered[:top_n], ordered[top_n:]
    items = [{"name": n, "repos": c} for n, c in head]
    if tail:
        items.append({"name": "Other", "repos": sum(c for _, c in tail)})
    for i, item in enumerate(items):
        item["percent"] = round(item["repos"] * 100 / total, 1)
        item["color"] = "#9AA5A8" if item["name"] == "Other" else language_color(item["name"], i)
    return items


# ---------------------------------------------------------------- profile stats
def profile_stats(profile: dict, repos: list[dict]) -> dict:
    own = [r for r in repos if not r.get("is_fork")]
    return {
        "followers": profile.get("followers", 0),
        "following": profile.get("following", 0),
        "public_repos": profile.get("public_repos", len(repos)),
        "total_stars": sum(r["stars"] for r in own),
        "total_forks": sum(r["forks"] for r in own),
        "original_repos": len(own),
    }


# ---------------------------------------------------------------- contributions
def _level_thresholds(counts: list[int]) -> list[int]:
    """Quartile thresholds over non-zero days -> levels 1..4 (like GitHub)."""
    nz = sorted(c for c in counts if c > 0)
    if not nz:
        return [1, 2, 3]
    def q(p: float) -> int:
        return nz[min(len(nz) - 1, int(len(nz) * p))]
    return [q(0.25), q(0.5), q(0.75)]


def _level(count: int, th: list[int]) -> int:
    if count <= 0:
        return 0
    if count <= th[0]:
        return 1
    if count <= th[1]:
        return 2
    if count <= th[2]:
        return 3
    return 4


def build_heatmap(days: list[dict], today: Optional[date] = None, weeks: int = 53) -> dict:
    """Return a Sunday-first week grid covering the last `weeks` weeks, with intensity levels."""
    today = today or date.today()
    by_date = {d["date"]: d["count"] for d in days}
    end = today
    # align the grid so its final column contains `today`
    start = end - timedelta(days=(weeks - 1) * 7 + ((end.weekday() + 1) % 7))
    th = _level_thresholds(list(by_date.values()))

    grid, month_labels = [], []
    cursor, last_month = start, None
    for w in range(weeks):
        col = []
        for _ in range(7):
            if cursor > end:
                col.append(None)
            else:
                iso = cursor.isoformat()
                count = by_date.get(iso, 0)
                col.append({"date": iso, "count": count, "level": _level(count, th)})
            cursor += timedelta(days=1)
        first = next((c for c in col if c), None)
        if first:
            m = datetime.fromisoformat(first["date"]).strftime("%b")
            if m != last_month and (not month_labels or w - month_labels[-1]["week"] >= 3):
                month_labels.append({"week": w, "label": m})
            last_month = m
        grid.append(col)
    return {"weeks": grid, "months": month_labels, "thresholds": th}


def streaks(days: list[dict], today: Optional[date] = None) -> dict:
    today = today or date.today()
    active = {date.fromisoformat(d["date"]) for d in days if d["count"] > 0}
    counts = [d["count"] for d in days]
    if not active:
        return {"current": 0, "longest": 0, "active_days": 0, "total": 0, "busiest_day": None, "avg_per_active_day": 0}

    # longest run of consecutive active days
    longest = run = 0
    prev = None
    for d in sorted(active):
        run = run + 1 if prev and (d - prev).days == 1 else 1
        longest = max(longest, run)
        prev = d

    # current streak: allow today to be empty (day isn't over) but nothing older
    cursor = today if today in active else today - timedelta(days=1)
    current = 0
    while cursor in active:
        current += 1
        cursor -= timedelta(days=1)

    busiest = max(days, key=lambda d: d["count"])
    return {
        "current": current,
        "longest": longest,
        "active_days": len(active),
        "total": sum(counts),
        "busiest_day": {"date": busiest["date"], "count": busiest["count"]},
        "avg_per_active_day": round(sum(counts) / len(active), 1),
    }
