"""Subito scraper — motore HTTP/JSON con split routing.

Interroghiamo l'API JSON interna del frontend Subito (`hades.subito.it/v1/
search/items`), che restituisce l'intero annuncio in JSON in frazioni di secondo.

Split routing (per contenere il budget del proxy residenziale a consumo):
- api_client  → chiamate di ricerca/paginazione verso hades, INSTRADATE dal
  proxy residenziale rotante IPRoyal (con retry ed exponential backoff).
- cdn_client  → download concorrente delle immagini dalla CDN, a connessione
  DIRETTA e gratuita (mai attraverso il proxy).
"""

import asyncio
import re
from dataclasses import replace
from typing import Any

import httpx

from backend.core.config import settings
from backend.core.database import upload_image_to_storage
from backend.scrapers.base import BaseScraper, ScrapedListing, SearchRequest


class SubitoScraper(BaseScraper):
    HADES_URL = "https://hades.subito.it/v1/search/items"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
        "Gecko/20100101 Firefox/126.0"
    )
    IMAGE_RULE = "?rule=fullscreen-1x-auto"
    PAGE_SIZE = 100          # max annunci per richiesta all'API
    MAX_REQUESTS = 8         # tetto di sicurezza sulle pagine per una search
    IMAGE_CONCURRENCY = 6    # download immagini paralleli (CDN diretta)

    MAX_RETRIES = 3          # tentativi sull'api_client (nodo proxy che fallisce)
    RETRY_BACKOFF_BASE = 0.5  # secondi: backoff 0.5s, 1.0s tra i tentativi

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
    ) -> None:
        self.timeout_s = timeout_ms / 1000
        self.organic_only = organic_only

    @property
    def source_name(self) -> str:
        return "subito"

    # --------------------------------------------------------------- clients

    def _make_api_client(self) -> httpx.AsyncClient:
        """Client per l'API hades, instradato dal proxy residenziale (se configurato)."""
        return httpx.AsyncClient(
            timeout=self.timeout_s,
            headers={"User-Agent": self.USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
            trust_env=False,          # ignora proxy d'ambiente: lo impostiamo noi
            proxy=settings.proxy_url,  # None → connessione diretta
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
    ) -> list[ScrapedListing]:
        """Fetch listings from the hades API (via proxy). Does NOT download images.

        Applies, in-block: title strict-match, price bounds and category-native
        strict_filters (year/km/transmission) so irrelevant ads are discarded
        before margins/save. Raw CDN image URLs are kept in metadata for a
        later, separate call to :meth:`store_images` over the direct CDN client.

        ``max_pages`` caps the number of API requests (i.e. proxy calls): the
        sniper processes exactly N blocks instead of paginating to fill a quota.
        """
        match_query = query if strict_match else None
        page_size = min(self.PAGE_SIZE, max(max_results, 30))
        request_cap = max_pages if max_pages is not None else self.MAX_REQUESTS

        listings: list[ScrapedListing] = []
        seen_urls: set[str] = set()

        async with self._make_api_client() as api_client:
            start = 0
            count_all: int | None = None
            for _ in range(request_cap):
                if len(listings) >= max_results:
                    break

                payload = await self._fetch_page(
                    api_client, query, page_size, start, min_price, max_price
                )
                ads = payload.get("ads") or []
                if not ads:
                    break
                if count_all is None:
                    count_all = payload.get("count_all") or 0

                for ad in ads:
                    if filters and not self._passes_filters(ad, filters):
                        continue
                    listing = self._parse_ad(ad)
                    if listing is None or listing.url in seen_urls:
                        continue
                    if match_query and not self._matches_query(listing.title, match_query):
                        continue
                    if not self._within_price(listing.price_amount, min_price, max_price):
                        continue

                    seen_urls.add(listing.url)
                    listings.append(listing)
                    if len(listings) >= max_results:
                        break

                start += page_size
                if count_all and start >= count_all:
                    break

        return listings[:max_results]

    async def _fetch_page(
        self,
        client: httpx.AsyncClient,
        query: str,
        limit: int,
        start: int,
        min_price: int | None,
        max_price: int | None,
    ) -> dict:
        params: dict[str, str] = {
            "q": query,
            "t": "s",              # t=s → vendita
            "lim": str(limit),
            "start": str(start),
        }
        if min_price is not None:
            params["ps"] = str(min_price)
        if max_price is not None:
            params["pe"] = str(max_price)

        response = await self._get_with_retry(client, self.HADES_URL, params)
        return response.json()

    async def _get_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, str],
    ) -> httpx.Response:
        """GET con retry ed exponential backoff: se un nodo proxy fallisce, riprova."""
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc  # timeout/errori di rete del nodo residenziale
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code < 500:
                    raise  # 4xx: errore nostro, inutile riprovare
                last_exc = exc

            if attempt < self.MAX_RETRIES - 1:
                await asyncio.sleep(self.RETRY_BACKOFF_BASE * (2**attempt))

        assert last_exc is not None
        raise last_exc

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

        return ScrapedListing(
            source=self.source_name,
            title=title.strip(),
            url=url,
            price=f"{price_amount} EUR" if price_amount is not None else None,
            price_amount=price_amount,
            location=self._parse_location(ad),
            description=(ad.get("body") or "").strip() or None,
            image_urls=[],
            metadata={
                "condition": self._feature(features, "/item_condition"),
                "image_count": len(images),
                "raw_images": images,
            },
        )

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

    def _feature(self, features: list[dict], uri: str) -> str | None:
        for feature in features:
            if feature.get("uri") == uri:
                values = feature.get("values") or []
                if values:
                    return values[0].get("value") or values[0].get("key")
        return None

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
                    stored = await self._download_and_store(
                        cdn_client, raw_images, listing.url
                    )
                return replace(listing, image_urls=stored)

            return list(await asyncio.gather(*(enrich(item) for item in listings)))

    async def _download_and_store(
        self,
        client: httpx.AsyncClient,
        image_urls: list[str],
        listing_url: str,
    ) -> list[str]:
        if not image_urls:
            return []

        slug = self._listing_slug(listing_url)
        stored: list[str] = []

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

        return stored

    def _listing_slug(self, listing_url: str) -> str:
        match = self.LISTING_ID_RE.search(listing_url)
        if match:
            return match.group(1)
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "-", listing_url.rsplit("/", 1)[-1])
        return cleaned.removesuffix(".htm") or "listing"
