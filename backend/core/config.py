import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    supabase_url: str | None = os.getenv("SUPABASE_URL")
    supabase_key: str | None = os.getenv("SUPABASE_KEY")
    environment: str = os.getenv("ENVIRONMENT", "development")

    @property
    def is_supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)


settings = Settings()
