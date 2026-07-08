from functools import lru_cache

from supabase import Client, create_client

from backend.core.config import settings


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    if not settings.is_supabase_configured:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY in environment.")

    return create_client(settings.supabase_url, settings.supabase_key)
