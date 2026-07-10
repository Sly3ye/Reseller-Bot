import os
import threading
from urllib.parse import urlparse

from supabase import Client, create_client

from backend.core.config import settings

LISTING_IMAGES_BUCKET = "listing_images"

# Un client Supabase per thread. Il client sync di supabase-py usa httpx in
# HTTP/2 (una sola connessione multiplexata) e NON è thread-safe: condividerlo
# tra i thread dello scheduler (asyncio.to_thread) e i worker delle richieste
# API corrompe la connessione ("[WinError 10035] socket non a blocchi").
# Isolando un client per thread ogni connessione è usata da un solo thread.
_thread_local = threading.local()
_proxy_bypassed = False
_bypass_lock = threading.Lock()


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


def get_supabase_client() -> Client:
    """Return this thread's Supabase client (created on first use).

    Thread-local (non un singleton globale): vedi la nota su _thread_local —
    evita l'uso concorrente della stessa connessione HTTP/2 da più thread.
    """
    if not settings.is_supabase_configured:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY in environment.")

    client = getattr(_thread_local, "client", None)
    if client is not None:
        return client

    # os.environ è globale al processo: basta impostarlo una volta, prima del
    # primo create_client() (httpx legge la config proxy alla costruzione).
    global _proxy_bypassed
    if not _proxy_bypassed:
        with _bypass_lock:
            if not _proxy_bypassed:
                _bypass_proxy_for_supabase(settings.supabase_url)
                _proxy_bypassed = True

    client = create_client(settings.supabase_url, settings.supabase_key)
    _thread_local.client = client
    return client


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
