"""Central configuration, read once from environment variables (.env supported)."""
import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader so we don't need an extra dependency."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@dataclass(frozen=True)
class Settings:
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "claude-sonnet-5-5")
    cache_ttl_minutes: int = int(os.getenv("CACHE_TTL_MINUTES", "60"))
    default_username: str = os.getenv("DEFAULT_USERNAME", "torvalds")
    db_path: str = os.getenv("DB_PATH", "portfolio_cache.db")
    github_api: str = "https://api.github.com"


settings = Settings()
