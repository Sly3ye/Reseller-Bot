from functools import lru_cache

from supabase import Client, create_client

from backend.core.config import settings

LISTING_IMAGES_BUCKET = "listing_images"


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    if not settings.is_supabase_configured:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY in environment.")

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
