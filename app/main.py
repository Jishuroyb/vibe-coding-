"""FastAPI entrypoint: JSON API + static single-page frontend.

All business logic (aggregation, scoring, streaks, validation) lives server-side;
the frontend only renders what these endpoints return.
"""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import database as db
from .config import settings
from .github_client import GitHubError
from .services import assistant, matcher, portfolio

STATIC_DIR = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()  # create cache tables on boot
    yield


app = FastAPI(title="GitHub Developer Portfolio", version="1.0.0", lifespan=lifespan)


def _user(raw: str) -> str:
    try:
        return portfolio.normalize_username(raw)
    except GitHubError as exc:
        raise HTTPException(exc.status, exc.message)


def _payload(username: str, **kwargs) -> dict:
    try:
        return portfolio.build_payload(username, **kwargs)
    except GitHubError as exc:
        raise HTTPException(exc.status, exc.message)


# ------------------------------------------------------------------ models
class MatchRequest(BaseModel):
    username: str
    job_description: str = Field(min_length=10, max_length=20000)


class ChatRequest(BaseModel):
    username: str
    message: str = Field(min_length=1, max_length=500)


class SettingsUpdate(BaseModel):
    username: Optional[str] = None
    theme: Optional[str] = Field(default=None, pattern="^(light|dark)$")
    job_description: Optional[str] = Field(default=None, max_length=20000)


# ------------------------------------------------------------------ routes
@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "github_token": bool(settings.github_token), "llm": assistant.llm_available(),
            "cache_ttl_minutes": settings.cache_ttl_minutes}


@app.get("/api/portfolio/{username}")
def get_portfolio(
    username: str,
    sort: str = Query("stars", pattern="^(stars|forks|updated|name)$"),
    language: Optional[str] = None,
    q: Optional[str] = Query(None, max_length=60),
    include_forks: bool = False,
    refresh: bool = False,
) -> dict:
    name = _user(username)
    data = _payload(name, sort=sort, language=language, search=q, include_forks=include_forks, force=refresh)
    db.set_setting("username", name)
    return data


@app.post("/api/match")
def run_match(body: MatchRequest) -> dict:
    name = _user(body.username)
    portfolio_data = _payload(name)  # also guarantees the cache exists
    repos = db.query_repos(name, include_forks=True)
    result = matcher.compute_match(body.job_description, repos)
    db.save_match(name, result)
    db.set_setting("job_description", body.job_description)
    result["history"] = db.match_history(name)
    return result


@app.get("/api/settings")
def read_settings() -> dict:
    s = db.all_settings()
    return {"username": s.get("username", settings.default_username), "theme": s.get("theme", "light"),
            "job_description": s.get("job_description", "")}


@app.put("/api/settings")
def update_settings(body: SettingsUpdate) -> dict:
    for key, value in body.model_dump(exclude_none=True).items():
        if key == "username":
            value = _user(value)
        db.set_setting(key, value)
    return read_settings()


@app.post("/api/chat")
def chat(body: ChatRequest) -> dict:
    name = _user(body.username)
    data = _payload(name, include_forks=True)
    history = db.recent_chat(name)
    reply = assistant.chat(body.message, data, history)
    db.add_chat(name, "user", body.message)
    db.add_chat(name, "assistant", reply["answer"])
    return reply


@app.get("/api/coach/{username}")
def coach(username: str) -> dict:
    name = _user(username)
    return assistant.coach(_payload(name, include_forks=True))


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
