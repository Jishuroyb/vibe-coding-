"""SQLite caching layer.

Tables
------
profiles       one row per user (raw GitHub profile JSON + fetched_at)
repos          one row per repo (flattened metadata so filtering/sorting happens in SQL)
contributions  daily contribution counts per user (JSON blob + source)
settings       key/value user settings (username, theme, last job description)
match_history  every Tech Stack Compatibility run
chat_history   DevBot conversation log (short follow-up context)
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Optional

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    username   TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repos (
    username    TEXT NOT NULL,
    name        TEXT NOT NULL,
    description TEXT,
    language    TEXT,
    stars       INTEGER NOT NULL DEFAULT 0,
    forks       INTEGER NOT NULL DEFAULT 0,
    is_fork     INTEGER NOT NULL DEFAULT 0,
    archived    INTEGER NOT NULL DEFAULT 0,
    topics      TEXT NOT NULL DEFAULT '[]',
    url         TEXT,
    pushed_at   TEXT,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (username, name)
);
CREATE INDEX IF NOT EXISTS idx_repos_user ON repos(username);
CREATE TABLE IF NOT EXISTS contributions (
    username   TEXT PRIMARY KEY,
    days       TEXT NOT NULL,
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS match_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL,
    percentage REAL NOT NULL,
    result     TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def is_fresh(fetched_at: Optional[str]) -> bool:
    if not fetched_at:
        return False
    return now_utc() - parse_iso(fetched_at) < timedelta(minutes=settings.cache_ttl_minutes)


# ---------- profiles ----------
def get_profile(username: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT data, fetched_at FROM profiles WHERE username=?", (username.lower(),)).fetchone()
    if not row:
        return None
    return {"data": json.loads(row["data"]), "fetched_at": row["fetched_at"]}


def save_profile(username: str, data: dict) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO profiles(username,data,fetched_at) VALUES(?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET data=excluded.data, fetched_at=excluded.fetched_at",
            (username.lower(), json.dumps(data), iso(now_utc())),
        )


# ---------- repos ----------
def save_repos(username: str, repos: list[dict]) -> None:
    stamp = iso(now_utc())
    with connect() as conn:
        conn.execute("DELETE FROM repos WHERE username=?", (username.lower(),))
        conn.executemany(
            "INSERT INTO repos(username,name,description,language,stars,forks,is_fork,archived,topics,url,pushed_at,fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    username.lower(), r["name"], r.get("description"), r.get("language"),
                    r.get("stargazers_count", 0), r.get("forks_count", 0), int(r.get("fork", False)),
                    int(r.get("archived", False)), json.dumps(r.get("topics", [])),
                    r.get("html_url"), r.get("pushed_at"), stamp,
                )
                for r in repos
            ],
        )


def repos_fetched_at(username: str) -> Optional[str]:
    with connect() as conn:
        row = conn.execute("SELECT MAX(fetched_at) AS t FROM repos WHERE username=?", (username.lower(),)).fetchone()
    return row["t"] if row else None


_SORTS = {
    "stars": "stars DESC, forks DESC",
    "forks": "forks DESC, stars DESC",
    "updated": "pushed_at DESC",
    "name": "name COLLATE NOCASE ASC",
}


def query_repos(username: str, sort: str = "stars", language: Optional[str] = None,
                search: Optional[str] = None, include_forks: bool = False) -> list[dict]:
    sql = "SELECT * FROM repos WHERE username=?"
    params: list[Any] = [username.lower()]
    if not include_forks:
        sql += " AND is_fork=0"
    if language:
        sql += " AND language=?"
        params.append(language)
    if search:
        sql += " AND (name LIKE ? OR description LIKE ? OR topics LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    sql += f" ORDER BY {_SORTS.get(sort, _SORTS['stars'])}"  # whitelist lookup => no injection
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["topics"] = json.loads(d["topics"])
        d["is_fork"] = bool(d["is_fork"])
        d["archived"] = bool(d["archived"])
        out.append(d)
    return out


# ---------- contributions ----------
def save_contributions(username: str, days: list[dict], source: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO contributions(username,days,source,fetched_at) VALUES(?,?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET days=excluded.days, source=excluded.source, fetched_at=excluded.fetched_at",
            (username.lower(), json.dumps(days), source, iso(now_utc())),
        )


def get_contributions(username: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT days, source, fetched_at FROM contributions WHERE username=?", (username.lower(),)).fetchone()
    if not row:
        return None
    return {"days": json.loads(row["days"]), "source": row["source"], "fetched_at": row["fetched_at"]}


# ---------- settings ----------
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def all_settings() -> dict:
    with connect() as conn:
        return {r["key"]: r["value"] for r in conn.execute("SELECT key,value FROM settings").fetchall()}


# ---------- match history ----------
def save_match(username: str, result: dict) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO match_history(username,percentage,result,created_at) VALUES(?,?,?,?)",
            (username.lower(), result["percentage"], json.dumps(result), iso(now_utc())),
        )


def latest_match(username: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(
            "SELECT result FROM match_history WHERE username=? ORDER BY id DESC LIMIT 1", (username.lower(),)
        ).fetchone()
    return json.loads(row["result"]) if row else None


def match_history(username: str, limit: int = 5) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT percentage, created_at FROM match_history WHERE username=? ORDER BY id DESC LIMIT ?",
            (username.lower(), limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- chat ----------
def add_chat(username: str, role: str, content: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO chat_history(username,role,content,created_at) VALUES(?,?,?,?)",
            (username.lower(), role, content, iso(now_utc())),
        )


def recent_chat(username: str, limit: int = 6) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM chat_history WHERE username=? ORDER BY id DESC LIMIT ?",
            (username.lower(), limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]
