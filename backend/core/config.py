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

    @property
    def is_supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)


settings = Settings()
