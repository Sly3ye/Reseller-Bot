"""Subito scraper — motore HTTP/JSON con split routing.

Interroghiamo l'API JSON interna del frontend Subito (`hades.subito.it/v1/
search/items`), che restituisce l'intero annuncio in JSON in frazioni di secondo.

Due client:
- api_client  → chiamate di ricerca/paginazione verso hades, in connessione
  DIRETTA (il proxy residenziale a pagamento è dismesso dal 2026-10-02). Usa
  curl_cffi con impronta TLS di un browser reale: hades è protetto da Akamai
  Bot Manager, che blocca (403) i client dall'impronta "non-browser" come httpx.
  Da un solo IP il ritmo è tutto: ogni chiamata passa dal ``HadesPacer``
  (pausa minima globale + stop su blocco), invece di ritentare a raffica.
- cdn_client  → download concorrente delle immagini dalla CDN (httpx diretto).
"""

import asyncio
import io
import logging
import random
import re
import time
from dataclasses import replace
from datetime import datetime
from typing import Any

import httpx
import imagehash
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import CurlError
from PIL import Image
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from backend.core.config import settings
from backend.core.database import upload_image_to_storage
from backend.services.valuation import normalize_km
from backend.scrapers.base import BaseScraper, ScrapedListing, SearchRequest
from backend.scrapers.nlp_parser import parse_listing

logger = logging.getLogger(__name__)

# 403/429 = Akamai/Subito ci sta limitando. Da IP fisso ritentare subito
# peggiora il blocco: si ferma tutto per il cooldown (vedi HadesPacer).
BLOCK_STATUS = frozenset({403, 429})
# Errori lato server: transitori, vale un retry breve.
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


class RetryableHTTPError(Exception):
    """Sollevata su uno status 5xx per innescare il retry di tenacity."""


class ScraperBlockedError(Exception):
    """Subito ci ha bloccato (403/429) o siamo ancora nel cooldown: il giro
    deve fermarsi, non passare al target successivo."""


class HadesPacer:
    """Ritmo globale verso hades, condiviso da tutti i job del processo.

    - Tra due richieste passa almeno ``gap_s`` (±25% di jitter: un intervallo
      perfettamente regolare è a sua volta una firma da bot).
    - Su blocco: stop per ``cooldown`` (raddoppia se i blocchi si ripetono, max
      4h) e ``gap_s`` raddoppia fino a ``scraper_max_gap_s``.
    - Ogni richiesta riuscita riporta ``gap_s`` verso il minimo del 2%: dopo un
      blocco il ritmo torna su gradualmente, non di colpo.
    """

    MAX_COOLDOWN_S = 4 * 3600

    def __init__(self) -> None:
        self.gap_s = settings.scraper_min_gap_s
        self._next_at = 0.0
        self._blocked_until = 0.0
        self.consecutive_blocks = 0
        self.total_blocks = 0
        self._lock: asyncio.Lock | None = None

    def blocked_for(self) -> float:
        """Secondi di cooldown residui (0 = libero)."""
        return max(0.0, self._blocked_until - time.monotonic())

    async def wait_turn(self) -> None:
        if self.blocked_for():
            raise ScraperBlockedError(
                f"cooldown anti-blocco attivo ancora {self.blocked_for():.0f}s"
            )
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            delay = self._next_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_at = time.monotonic() + self.gap_s * random.uniform(0.75, 1.25)

    def on_success(self) -> None:
        self.consecutive_blocks = 0
        self.gap_s = max(settings.scraper_min_gap_s, self.gap_s * 0.98)

    def on_block(self, status: int) -> None:
        self.consecutive_blocks += 1
        self.total_blocks += 1
        cooldown = min(
            settings.scraper_block_cooldown_s * 2 ** (self.consecutive_blocks - 1),
            self.MAX_COOLDOWN_S,
        )
        self._blocked_until = time.monotonic() + cooldown
        self.gap_s = min(self.gap_s * 2, settings.scraper_max_gap_s)
        logger.warning(
            "hades HTTP %s: blocco n.%d consecutivo → pausa %.0f min, ritmo 1 richiesta/%.0fs",
            status, self.consecutive_blocks, cooldown / 60, self.gap_s,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "gapS": round(self.gap_s, 1),
            "minGapS": settings.scraper_min_gap_s,
            "blockedForS": round(self.blocked_for()),
            "consecutiveBlocks": self.consecutive_blocks,
            "totalBlocks": self.total_blocks,
        }


pacer = HadesPacer()


class SubitoScraper(BaseScraper):
    HADES_URL = "https://hades.subito.it/v1/search/items"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
        "Gecko/20100101 Firefox/126.0"
    )
    IMAGE_RULE = "?rule=fullscreen-1x-auto"
    PAGE_SIZE = 100          # max annunci per richiesta all'API
    MAX_DEPTH = 10_000       # hades non restituisce risultati oltre start=10000
    MAX_REQUESTS = 8         # tetto di sicurezza sulle pagine per una search
    IMAGE_CONCURRENCY = 6    # download immagini paralleli (CDN diretta)

    MAX_RETRIES = 3          # tentativi su errori di rete/5xx (mai su 403/429)
    API_TIMEOUT_S = 15.0

    LISTING_ID_RE = re.compile(r"-(\d+)\.htm(?:$|[?#])")
    CONTENT_TYPE_EXT = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }

    def __init__(
        self,
        headless: bool = True,          # legacy: nessun browser, ignorato
        timeout_ms: int = 30_000,
        browser_name: str = "firefox",  # legacy: ignorato
        organic_only: bool = True,      # legacy: hades restituisce già annunci reali
        category_id: str | None = None,
    ) -> None:
        self.timeout_s = timeout_ms / 1000
        # Categoria Subito (es. "2" = Auto): con una query vuota si sfoglia
        # TUTTA la categoria, non una ricerca testuale.
        self.category_id = category_id
        self.organic_only = organic_only
        self.last_search: dict[str, Any] = {"pages": 0, "gap": False, "oldest_published": None}

    @property
    def source_name(self) -> str:
        return "subito"

    # --------------------------------------------------------------- clients

    def _make_api_client(self) -> AsyncSession:
        """Sessione per l'API hades con impronta TLS di un browser reale (curl_cffi).

        Subito è dietro Akamai Bot Manager, che blocca con 403 i client
        dall'impronta TLS "non-browser" come httpx, a prescindere da IP e header.
        curl_cffi imita il fingerprint di Safari/Firefox (configurabile via
        SCRAPER_IMPERSONATE) e passa. Connessione diretta, salvo un proxy
        opzionale in config; le immagini restano su httpx (vedi _make_cdn_client).
        Sessione usa e getta, una per richiesta: ripesca un'impronta dal pool.
        """
        proxies = None
        if settings.proxy_url:
            proxies = {"http": settings.proxy_url, "https": settings.proxy_url}
        # Rotazione: un profilo a caso dal pool a ogni richiesta, così un
        # eventuale flag Akamai su un profilo non blocca tutto.
        pool = settings.impersonate_pool or ["safari"]
        return AsyncSession(
            impersonate=random.choice(pool),
            proxies=proxies,
            timeout=min(self.timeout_s, self.API_TIMEOUT_S),
            headers={"Accept": "application/json"},
        )

    def _make_cdn_client(self) -> httpx.AsyncClient:
        """Client per la CDN immagini: sempre diretto, mai dal proxy a consumo."""
        return httpx.AsyncClient(
            timeout=self.timeout_s,
            headers={"User-Agent": self.USER_AGENT},
            follow_redirects=True,
            trust_env=False,  # nessun proxy per le immagini (banda gratuita)
        )

    # ---------------------------------------------------------------- search

    async def search(self, request: SearchRequest) -> list[ScrapedListing]:
        return await self.search_text(
            query=request.query,
            max_results=request.max_results,
            min_price=request.min_price,
            max_price=request.max_price,
        )

    async def search_text(
        self,
        query: str,
        max_results: int = 5,
        min_price: int | None = None,
        max_price: int | None = None,
        strict_match: bool = True,
        filters: dict[str, Any] | None = None,
        max_pages: int | None = None,
        since: datetime | None = None,
    ) -> list[ScrapedListing]:
        """Fetch listings from the hades API. Does NOT download images.

        Applies, in-block: title strict-match, price bounds and category-native
        strict_filters (year/km/transmission) so irrelevant ads are discarded
        before margins/save. Raw CDN image URLs are kept in metadata for a
        later, separate call to :meth:`store_images` over the direct CDN client.

        ``max_pages`` caps the number of API requests: the sniper processes
        exactly N blocks instead of paginating to fill a quota.

        ``since`` (modalità Sniper, ordine per data): si pagina finché la pagina
        è piena e il suo annuncio più vecchio è stato pubblicato DOPO ``since``
        (= la scansione precedente), cioè finché potrebbero esserci annunci mai
        visti più indietro; ``max_pages`` resta il tetto. In questa modalità
        ``max_results`` non ferma la paginazione. L'esito finisce in
        ``self.last_search``: pagine lette e ``gap`` = tetto raggiunto senza
        ricongiungersi (annunci persi: target da scansionare più spesso).
        """
        match_query = query if strict_match else None
        page_size = self.PAGE_SIZE if since else min(self.PAGE_SIZE, max(max_results, 30))
        request_cap = max_pages if max_pages is not None else self.MAX_REQUESTS
        self.last_search = {"pages": 0, "gap": False, "oldest_published": None}

        listings: list[ScrapedListing] = []
        seen_urls: set[str] = set()

        start = 0
        count_all: int | None = None
        for page_index in range(request_cap):
            if since is None and len(listings) >= max_results:
                break

            payload = await self._fetch_page(
                query, page_size, start, min_price, max_price
            )
            self.last_search["pages"] = page_index + 1
            ads = payload.get("ads") or []
            if not ads:
                break
            if count_all is None:
                count_all = payload.get("count_all") or 0
            published = [p for p in (self._published_at(ad) for ad in ads) if p]
            oldest = min(published) if published else None
            self.last_search["oldest_published"] = oldest

            listings.extend(
                self.select_ads(
                    ads, filters=filters, match_query=match_query,
                    min_price=min_price, max_price=max_price, seen_urls=seen_urls,
                )
            )
            if since is None and len(listings) >= max_results:
                break

            start += page_size
            if count_all and start >= count_all:
                break
            if since is not None:
                caught_up = len(ads) < page_size or oldest is None or oldest <= since
                if caught_up:
                    break
                # Tetto di pagine nostro, o di hades (10.000 risultati max).
                if page_index + 1 == request_cap or start >= self.MAX_DEPTH:
                    self.last_search["gap"] = True
                    break

        return listings if since is not None else listings[:max_results]

    def select_ads(
        self,
        ads: list[dict],
        *,
        filters: dict[str, Any] | None = None,
        match_query: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        seen_urls: set[str] | None = None,
    ) -> list[ScrapedListing]:
        """Parsing + scrematura di una pagina grezza di hades (filtri nativi,
        accessori, strict match sul titolo, prezzo). ``seen_urls`` deduplica tra
        pagine e viene aggiornato."""
        seen = seen_urls if seen_urls is not None else set()
        out: list[ScrapedListing] = []
        for ad in ads:
            if filters and not self._passes_filters(ad, filters):
                continue
            listing = self._parse_ad(ad)
            if listing is None or listing.url in seen:
                continue
            if (listing.metadata or {}).get("is_accessory"):
                # Cover/vetro/caricatore "per iPhone": non è il telefono,
                # inquinerebbe prezzi medi e valore equo del tech.
                continue
            if filters and not self._passes_listing_filters(listing, filters):
                continue
            if match_query and not self._matches_query(listing.title, match_query):
                continue
            if not self._within_price(listing.price_amount, min_price, max_price):
                continue
            seen.add(listing.url)
            out.append(listing)
        return out

    @staticmethod
    def _published_at(ad: dict) -> datetime | None:
        """Data di pubblicazione (es. '2026-10-02T09:56:57.363+0200')."""
        raw = (ad.get("dates") or {}).get("display_iso8601")
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            try:
                return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S%z")
            except ValueError:
                return None

    async def _fetch_page(
        self,
        query: str,
        limit: int,
        start: int,
        min_price: int | None,
        max_price: int | None,
    ) -> dict:
        params: dict[str, str] = {
            "t": "s",              # t=s → vendita
            "sort": "datedesc",    # più recenti prima: ogni giro dello sniper
                                   # vede gli ultimi pubblicati, non i "rilevanti"
            "lim": str(limit),
            "start": str(start),
        }
        if query:
            params["q"] = query
        if self.category_id:
            params["c"] = self.category_id
        if min_price is not None:
            params["ps"] = str(min_price)
        if max_price is not None:
            params["pe"] = str(max_price)

        response = await self._get_with_retry(self.HADES_URL, params)
        return response.json()

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=2, max=30) + wait_random(0, 3),
        retry=retry_if_exception_type((CurlError, RetryableHTTPError)),
        reraise=True,
    )
    async def _get_with_retry(self, url: str, params: dict[str, str]):
        """GET a ritmo controllato (``pacer``), con retry SOLO su errori di rete
        e 5xx. Un 403/429 non si ritenta: apre il cooldown e solleva
        ``ScraperBlockedError``, così il giro si ferma invece di insistere
        dallo stesso IP (il modo più rapido per allungare il blocco).
        """
        await pacer.wait_turn()
        async with self._make_api_client() as client:
            response = await client.get(url, params=params)
            if response.status_code in BLOCK_STATUS:
                pacer.on_block(response.status_code)
                raise ScraperBlockedError(f"HTTP {response.status_code} da hades")
            if response.status_code in RETRYABLE_STATUS:
                raise RetryableHTTPError(f"HTTP {response.status_code} da hades")
            if response.status_code >= 400:
                # altri 4xx/5xx: errore reale, non si ritenta (fuori dal retry set)
                raise RuntimeError(
                    f"HTTP {response.status_code} da hades (non ritentabile)"
                )
            pacer.on_success()
            return response

    # ----------------------------------------------------------------- parse

    def _parse_ad(self, ad: dict) -> ScrapedListing | None:
        url = (ad.get("urls") or {}).get("default")
        title = ad.get("subject")
        if not url or not title:
            return None

        features = ad.get("features") or []
        price_amount = self._parse_price(features)
        images = [
            img["cdn_base_url"] + self.IMAGE_RULE
            for img in ad.get("images") or []
            if img.get("cdn_base_url")
        ]

        description = (ad.get("body") or "").strip() or None
        seller_id, seller_type = self._parse_seller(ad)

        # Pre-parsing NLP su titolo+descrizione: difetti, urgenza, allestimenti
        # normalizzati e fallback su km/anno quando l'API non li espone.
        nlp = parse_listing(title, description)
        published = self._published_at(ad)

        return ScrapedListing(
            source=self.source_name,
            title=title.strip(),
            url=url,
            price=f"{price_amount} EUR" if price_amount is not None else None,
            price_amount=price_amount,
            location=self._parse_location(ad),
            description=description,
            image_urls=[],
            metadata={
                "condition": self._feature(features, "/item_condition"),
                # Pubblicazione su Subito (≠ found_at = quando l'abbiamo visto):
                # base corretta per età dell'annuncio e tempo di vendita.
                "published_at": published.isoformat() if published else None,
                "image_count": len(images),
                "raw_images": images,
                # Campi strutturati auto (None per gli smartphone). Preferiamo il
                # dato nativo dell'API; se assente, ripieghiamo sull'NLP.
                "year": self._feature_int(features, "/year") or nlp["year"],
                # "184" nel campo km = 184.000 (vedi valuation.normalize_km).
                "km": normalize_km(
                    self._feature_int(features, "/mileage_scalar") or nlp["km"],
                    self._feature_int(features, "/year") or nlp["year"],
                ),
                "transmission": self._feature(features, "/gearbox"),
                "fuel": self._feature(features, "/fuel"),
                # Auto: marca/modello(generazione)/versione, kW, carrozzeria...
                **self._car_fields(features),
                # Variante tech (None per le auto): segmentazione di mercato.
                "storage_gb": nlp["storage_gb"],
                "battery_pct": nlp["battery_pct"],
                "color": nlp["color"],
                # Segnale NLP.
                "features": nlp["features"],
                "defects_noted": nlp["defects_noted"],
                "urgency_flags": nlp["urgency_flags"],
                "exclude_from_iqr": nlp["exclude_from_iqr"],
                "is_accessory": nlp["is_accessory"],
                # Venditore (Shadow Dealer).
                "seller_id": seller_id,
                "seller_type": seller_type,
            },
        )

    def _parse_seller(self, ad: dict) -> tuple[str | None, str]:
        """Estrae (seller_id, seller_type) da advertiser.

        ``company`` true o la presenza di uno ``shop_id`` → concessionario;
        altrimenti privato. Lo Shadow Dealer potrà riclassificare un privato con
        troppi annunci attivi come ``finto_privato`` in fase di persistenza.
        """
        advertiser = ad.get("advertiser") or {}
        seller_id = advertiser.get("user_id")
        is_pro = bool(advertiser.get("company")) or bool(advertiser.get("shop_id"))
        seller_type = "dealer" if is_pro else "privato"
        return (str(seller_id) if seller_id is not None else None, seller_type)

    def _passes_filters(self, ad: dict, filters: dict[str, Any]) -> bool:
        """Category-native strict filters (cars): year, mileage, transmission."""
        features = ad.get("features") or []

        min_year = filters.get("min_year")
        max_year = filters.get("max_year")
        if min_year is not None or max_year is not None:
            year = self._feature_int(features, "/year")
            if year is None:
                return False
            if min_year is not None and year < int(min_year):
                return False
            if max_year is not None and year > int(max_year):
                return False

        max_km = filters.get("max_km")
        if max_km is not None:
            km = self._feature_int(features, "/mileage_scalar")
            if km is None or km > int(max_km):
                return False

        transmission = filters.get("transmission")
        if transmission:
            gearbox = (self._feature(features, "/gearbox") or "").lower()
            if not gearbox:
                return False
            is_manual = "manuale" in gearbox
            if transmission == "automatic" and is_manual:
                return False
            if transmission == "manual" and not is_manual:
                return False

        return True

    def _passes_listing_filters(
        self, listing: ScrapedListing, filters: dict[str, Any]
    ) -> bool:
        """Strict filters basati sull'NLP (tech): variante memoria e batteria.

        ``storage_gb``: l'annuncio deve dichiarare ESATTAMENTE quel taglio —
        chi non lo dichiara viene scartato, così la media del target resta
        pura per variante (un 13 128GB non si mescola col 256GB).
        ``min_battery``: applicato solo quando la batteria è dichiarata.
        """
        meta = listing.metadata or {}

        storage = filters.get("storage_gb")
        if storage is not None and meta.get("storage_gb") != int(storage):
            return False

        min_battery = filters.get("min_battery")
        if min_battery is not None:
            battery = meta.get("battery_pct")
            if battery is not None and battery < int(min_battery):
                return False

        return True

    def _feature(self, features: list[dict], uri: str) -> str | None:
        for feature in features:
            if feature.get("uri") == uri:
                values = feature.get("values") or []
                if values:
                    return values[0].get("value") or values[0].get("key")
        return None

    @staticmethod
    def _feature_values(features: list[dict], uri: str) -> list[str]:
        """Tutti i valori di un campo (es. /car = [marca, modello, versione])."""
        for feature in features:
            if feature.get("uri") == uri:
                return [str(v.get("value") or v.get("key") or "") for v in feature.get("values") or []]
        return []

    def _car_fields(self, features: list[dict]) -> dict[str, Any]:
        """Dati strutturati di un'auto (migrazione 23). Vuoti sugli iPhone."""
        car = self._feature_values(features, "/car")
        power = re.search(r"(\d+)\s*kw", self._feature(features, "/power") or "", re.IGNORECASE)
        reg = re.match(r"(\d{1,2})/(\d{4})", self._feature(features, "/register_date") or "")
        return {
            "car_brand": car[0] if len(car) > 0 else None,
            "car_model": car[1] if len(car) > 1 else None,
            "car_version": car[2] if len(car) > 2 else None,
            "power_kw": int(power.group(1)) if power else None,
            "body_type": self._feature(features, "/car_type"),
            "doors": self._feature(features, "/doors"),
            "register_month": int(reg.group(1)) if reg else None,
            "emission_class": self._feature(features, "/pollution"),
        }

    def _feature_int(self, features: list[dict], uri: str) -> int | None:
        for feature in features:
            if feature.get("uri") == uri:
                values = feature.get("values") or []
                if values:
                    digits = re.sub(r"\D", "", str(values[0].get("key") or ""))
                    return int(digits) if digits else None
        return None

    def _parse_price(self, features: list[dict]) -> int | None:
        for feature in features:
            if feature.get("uri") == "/price":
                values = feature.get("values") or []
                if not values:
                    return None
                raw = str(values[0].get("key") or values[0].get("value") or "")
                digits = re.sub(r"\D", "", raw.split(",")[0])
                return int(digits) if digits else None
        return None

    def _parse_location(self, ad: dict) -> str | None:
        geo = ad.get("geo") or {}
        town = (geo.get("town") or {}).get("value")
        city = (geo.get("city") or {}).get("value")
        return town or city

    def _within_price(
        self, price: int | None, min_price: int | None, max_price: int | None
    ) -> bool:
        if price is None:
            return min_price is None and max_price is None
        if min_price is not None and price < min_price:
            return False
        if max_price is not None and price > max_price:
            return False
        return True

    def _matches_query(self, title: str, query: str) -> bool:
        title_tokens = set(self._tokenize(title))
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return True
        return all(token in title_tokens for token in query_tokens)

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    # ------------------------------------------------------------ image store

    async def store_images(
        self, listings: list[ScrapedListing]
    ) -> list[ScrapedListing]:
        """Download every listing's gallery from the CDN (direct) and persist it.

        Run this AFTER dedup/filtering so we only pay to store images for the
        opportunities we actually keep. Uses the direct cdn_client, never the proxy.
        """
        if not listings:
            return listings

        semaphore = asyncio.Semaphore(self.IMAGE_CONCURRENCY)

        async with self._make_cdn_client() as cdn_client:

            async def enrich(listing: ScrapedListing) -> ScrapedListing:
                raw_images = list(listing.metadata.get("raw_images") or [])
                async with semaphore:
                    stored, image_hash = await self._download_and_store(
                        cdn_client, raw_images, listing.url
                    )
                return replace(
                    listing,
                    image_urls=stored,
                    metadata={**listing.metadata, "image_hash": image_hash},
                )

            return list(await asyncio.gather(*(enrich(item) for item in listings)))

    async def _download_and_store(
        self,
        client: httpx.AsyncClient,
        image_urls: list[str],
        listing_url: str,
    ) -> tuple[list[str], str | None]:
        """Scarica e salva la galleria; ritorna (url_salvati, pHash prima foto)."""
        if not image_urls:
            return [], None

        slug = self._listing_slug(listing_url)
        stored: list[str] = []
        image_hash: str | None = None

        for index, image_url in enumerate(image_urls):
            try:
                response = await client.get(image_url)
                response.raise_for_status()
                content = response.content
                content_type = (
                    response.headers.get("content-type", "image/jpeg")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
            except Exception:
                continue

            # pHash sulla PRIMA foto effettivamente scaricata (anti-ripubblicazione).
            if image_hash is None:
                image_hash = self._perceptual_hash(content)

            extension = self.CONTENT_TYPE_EXT.get(content_type, ".jpg")
            filename = f"{self.source_name}/{slug}/{index:02d}{extension}"

            try:
                public_url = await asyncio.to_thread(
                    upload_image_to_storage,
                    content,
                    filename,
                    content_type=content_type,
                )
                stored.append(public_url)
            except Exception:
                continue

        return stored, image_hash

    @staticmethod
    def _perceptual_hash(content: bytes) -> str | None:
        """Perceptual hash (pHash a 64 bit) dei byte immagine, come stringa esadecimale."""
        try:
            with Image.open(io.BytesIO(content)) as img:
                return str(imagehash.phash(img))
        except Exception:
            return None

    def _listing_slug(self, listing_url: str) -> str:
        match = self.LISTING_ID_RE.search(listing_url)
        if match:
            return match.group(1)
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "-", listing_url.rsplit("/", 1)[-1])
        return cleaned.removesuffix(".htm") or "listing"
