import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]

load_dotenv(BACKEND_DIR / ".env")
load_dotenv()


def _normalize_supabase_url(url: str | None) -> str | None:
    if not url:
        return None

    return url.strip().removesuffix("/rest/v1/").removesuffix("/rest/v1")


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None = _normalize_supabase_url(os.getenv("SUPABASE_URL"))
    supabase_key: str | None = os.getenv("SUPABASE_KEY")
    environment: str = os.getenv("ENVIRONMENT", "development")

    # Rotating residential proxy (IPRoyal) — used ONLY for the hades API calls.
    # Image/CDN downloads go direct (see split routing in the scraper).
    proxy_host: str | None = os.getenv("PROXY_HOST") or None
    proxy_port: str | None = os.getenv("PROXY_PORT") or None
    proxy_user: str | None = os.getenv("PROXY_USER") or None
    proxy_pass: str | None = os.getenv("PROXY_PASS") or None

    @property
    def is_supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    @property
    def proxy_url(self) -> str | None:
        """http://user:pass@host:port, or None when the proxy isn't configured."""
        if not (self.proxy_host and self.proxy_port):
            return None
        auth = ""
        if self.proxy_user and self.proxy_pass:
            auth = f"{self.proxy_user}:{self.proxy_pass}@"
        return f"http://{auth}{self.proxy_host}:{self.proxy_port}"


settings = Settings()
