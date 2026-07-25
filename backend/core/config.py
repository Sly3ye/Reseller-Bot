import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]

load_dotenv(BACKEND_DIR / ".env")
load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Postgres self-hosted (locale o VPS). Default: istanza locale di sviluppo.
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/reseller"
    )
    environment: str = os.getenv("ENVIRONMENT", "development")

    # Storage immagini su filesystem (sostituisce lo Storage di Supabase).
    # media_root: dove salvare i file; public_media_base_url: da dove il browser
    # li carica (il backend serve /media). In produzione punta al dominio/IP del VPS.
    media_root: str = os.getenv("MEDIA_ROOT", str(BACKEND_DIR.parent / "media"))
    public_media_base_url: str = os.getenv(
        "PUBLIC_MEDIA_BASE_URL", "http://localhost:8000"
    )

    # Rotating residential proxy (IPRoyal) — used ONLY for the hades API calls.
    # Image/CDN downloads go direct (see split routing in the scraper).
    proxy_host: str | None = os.getenv("PROXY_HOST") or None
    proxy_port: str | None = os.getenv("PROXY_PORT") or None
    proxy_user: str | None = os.getenv("PROXY_USER") or None
    proxy_pass: str | None = os.getenv("PROXY_PASS") or None

    # Impronte browser di curl_cffi per le chiamate a hades (Akamai Bot Manager
    # blocca httpx con 403). Pool separato da virgola: lo scraper ne sceglie una
    # a caso per ogni target, così se Akamai flagga un profilo gli altri reggono.
    # "safari"/"firefox" testati OK; aggiungi "chrome" per più varietà.
    scraper_impersonate: str = os.getenv("SCRAPER_IMPERSONATE", "safari,firefox")

    @property
    def impersonate_pool(self) -> list[str]:
        return [p.strip() for p in self.scraper_impersonate.split(",") if p.strip()]

    # Chat Telegram per gli alert di SISTEMA (scraper down/ripristino). Se vuoto,
    # ripiega sulle chat dei verticali; se anche quelle mancano, no-op.
    telegram_chat_ops: str | None = os.getenv("TELEGRAM_CHAT_ID_OPS") or None

    # AI locale (Ollama) per l'analisi semantica delle descrizioni. Dal backend
    # in Docker, Ollama sul Mac/host si raggiunge via host.docker.internal.
    ai_enabled: bool = os.getenv("AI_ENABLED", "true").lower() in ("1", "true", "yes")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3")

    # Telegram alerts — un bot, due chat (una per verticale). Lascia vuoto
    # per disattivare le notifiche di quel verticale.
    telegram_bot_token: str | None = os.getenv("TELEGRAM_BOT_TOKEN") or None
    telegram_chat_tech: str | None = os.getenv("TELEGRAM_CHAT_ID_TECH") or None
    telegram_chat_auto: str | None = os.getenv("TELEGRAM_CHAT_ID_AUTO") or None
    # Soglia di margine (%) sopra cui una NUOVA opportunità viene notificata.
    alert_min_margin_pct: float = float(os.getenv("ALERT_MIN_MARGIN_PCT", "20"))
    # Calo di prezzo (%) sopra cui notificare anche senza margine sopra soglia.
    alert_min_drop_pct: float = float(os.getenv("ALERT_MIN_DROP_PCT", "10"))

    def telegram_chat_for(self, category: str) -> str | None:
        """Chat di destinazione per la categoria; None → notifiche disattivate."""
        if not self.telegram_bot_token:
            return None
        if category == "automobile":
            return self.telegram_chat_auto
        return self.telegram_chat_tech

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
