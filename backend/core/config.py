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

    # Proxy HTTP opzionale per le chiamate hades. DISMESSO dal 2026-10-02 (niente
    # servizi a pagamento): si va in connessione diretta a ritmo controllato.
    # Lasciato configurabile solo per eventuali proxy gratuiti/self-hosted.
    proxy_host: str | None = os.getenv("PROXY_HOST") or None
    proxy_port: str | None = os.getenv("PROXY_PORT") or None
    proxy_user: str | None = os.getenv("PROXY_USER") or None
    proxy_pass: str | None = os.getenv("PROXY_PASS") or None

    # Impronte browser di curl_cffi per le chiamate a hades (Akamai Bot Manager
    # blocca httpx con 403). Pool separato da virgola: lo scraper ne sceglie una
    # a caso per ogni target, così se Akamai flagga un profilo gli altri reggono.
    # "safari"/"firefox" testati OK; aggiungi "chrome" per più varietà.
    scraper_impersonate: str = os.getenv("SCRAPER_IMPERSONATE", "safari,firefox")

    # Ritmo verso hades da UN solo IP (vedi scripts/probe_rate_limit.py per
    # misurare il limite reale della macchina). Pausa minima tra due richieste,
    # condivisa da tutti i job; su blocco (403/429) la pausa raddoppia fino al
    # massimo e lo scraper si ferma per il cooldown (che raddoppia se il blocco
    # si ripete), poi torna verso il minimo un passo alla volta.
    scraper_min_gap_s: float = float(os.getenv("SCRAPER_MIN_GAP_S", "6"))
    scraper_max_gap_s: float = float(os.getenv("SCRAPER_MAX_GAP_S", "120"))
    scraper_block_cooldown_s: float = float(os.getenv("SCRAPER_BLOCK_COOLDOWN_S", "900"))
    # Cadenza dei giri Sniper. Misurato il 2026-10-02: il target iPhone più
    # vivace pubblica ~290 annunci/giorno (~12/h), una pagina ne contiene 100 →
    # 15' lascia un margine enorme. Se scrape_runs.gaps sale, abbassala.
    sniper_tech_interval_min: int = int(os.getenv("SNIPER_TECH_INTERVAL_MIN", "15"))
    sniper_auto_interval_min: int = int(os.getenv("SNIPER_AUTO_INTERVAL_MIN", "30"))

    @property
    def impersonate_pool(self) -> list[str]:
        return [p.strip() for p in self.scraper_impersonate.split(",") if p.strip()]

    # Chat Telegram per gli alert di SISTEMA (scraper down/ripristino). Se vuoto,
    # ripiega sulle chat dei verticali; se anche quelle mancano, no-op.
    telegram_chat_ops: str | None = os.getenv("TELEGRAM_CHAT_ID_OPS") or None

    # AI locale (Ollama) per l'analisi semantica delle descrizioni. Dal backend
    # in Docker, Ollama sul Mac/host si raggiunge via host.docker.internal.
    ai_enabled: bool = os.getenv("AI_ENABLED", "true").lower() in ("1", "true", "yes")
    # false = solo dashboard/API, nessun job (raccolta, inventario, foto...):
    # per una seconda macchina che non deve far divergere il DB principale.
    scheduler_enabled: bool = os.getenv("SCHEDULER_ENABLED", "true").lower() in ("1", "true", "yes")
    # true = raccolta di TUTTE le auto di Subito (categoria intera) invece dei
    # target auto: sweep dei nuovi + inventario a rotazione su più notti.
    # Spento finché il feed auto non filtra lato DB (537k annunci).
    auto_full_category: bool = os.getenv("AUTO_FULL_CATEGORY", "false").lower() in ("1", "true", "yes")
    auto_inventory_slices: int = int(os.getenv("AUTO_INVENTORY_SLICES", "4"))
    # Solo questi job (id separati da virgola), es. un container che fa solo
    # le foto mentre un altro raccoglie. Vuoto = tutti.
    scheduler_only: str = os.getenv("SCHEDULER_ONLY", "")
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
    # Deal Score minimo per notificare un affare (usa la valutazione a valore
    # equo + AI, non il margine grezzo): filtra i falsi positivi.
    alert_min_score: float = float(os.getenv("ALERT_MIN_SCORE", "55"))

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
