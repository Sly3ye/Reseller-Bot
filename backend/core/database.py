import os
from functools import lru_cache
from urllib.parse import urlparse

from supabase import Client, create_client

from backend.core.config import settings

LISTING_IMAGES_BUCKET = "listing_images"


def _bypass_proxy_for_supabase(url: str) -> None:
    """Make httpx reach Supabase directly, ignoring any HTTP(S)_PROXY env var.

    A proxy configured in the shell (HTTPS_PROXY/ALL_PROXY) otherwise tunnels
    the Supabase REST/Storage calls and can fail (e.g. ProxyError 404).
    Supabase is a public host reachable directly, so we add it to NO_PROXY.
    """
    host = urlparse(url).hostname
    if not host:
        return
    for key in ("NO_PROXY", "no_proxy"):
        entries = [h.strip() for h in os.environ.get(key, "").split(",") if h.strip()]
        if host not in entries:
            entries.append(host)
            os.environ[key] = ",".join(entries)


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    if not settings.is_supabase_configured:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY in environment.")

    # Must run before create_client(): httpx reads proxy config at construction.
    _bypass_proxy_for_supabase(settings.supabase_url)

    return create_client(settings.supabase_url, settings.supabase_key)


def upload_image_to_storage(
    image_bytes: bytes,
    filename: str,
    *,
    bucket: str = LISTING_IMAGES_BUCKET,
    content_type: str = "image/jpeg",
) -> str:
    """Upload raw image bytes to a public Supabase Storage bucket.

    Returns the public URL of the stored object. Uses upsert so re-scraping
    the same listing overwrites its image instead of failing on conflict.
    Note: the bucket must already exist and be public, and the client must
    use a key allowed to write to Storage (the service role key bypasses RLS).
    """
    storage = get_supabase_client().storage.from_(bucket)
    storage.upload(
        path=filename,
        file=image_bytes,
        file_options={
            "content-type": content_type,
            "upsert": "true",
            "cache-control": "3600",
        },
    )
    return storage.get_public_url(filename)
