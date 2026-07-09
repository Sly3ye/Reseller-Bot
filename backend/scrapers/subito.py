"""Subito scraper — motore HTTP/JSON.

Invece di caricare un browser Playwright, interroghiamo direttamente l'API JSON
interna che il frontend di Subito usa via XHR (`hades.subito.it/v1/search/items`).
Restituisce l'intero annuncio in JSON — titolo, descrizione, prezzo, immagini,
geo e URL — in un'unica richiesta e in frazioni di secondo.
"""

import asyncio
import re
from dataclasses import replace

import httpx

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
    IMAGE_CONCURRENCY = 4    # download immagini paralleli in modalità deep

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
        deep: bool = False,
        strict_match: bool = True,
        pages: int = 1,
    ) -> list[ScrapedListing]:
        # Strict match keeps only titles containing every query token (sniper);
        # light/batch mode relaxes it — Subito's own relevance already scopes it.
        match_query = query if strict_match else None
        page_size = min(self.PAGE_SIZE, max(max_results, 30))

        listings: list[ScrapedListing] = []
        raw_images: dict[str, list[str]] = {}
        seen_urls: set[str] = set()

        headers = {"User-Agent": self.USER_AGENT, "Accept": "application/json"}
        async with httpx.AsyncClient(
            timeout=self.timeout_s, headers=headers, follow_redirects=True
        ) as client:
            start = 0
            count_all = None
            for _ in range(self.MAX_REQUESTS):
                if len(listings) >= max_results:
                    break

                payload = await self._fetch_page(
                    client, query, page_size, start, min_price, max_price
                )
                ads = payload.get("ads") or []
                if not ads:
                    break
                if count_all is None:
                    count_all = payload.get("count_all") or 0

                for ad in ads:
                    listing, images = self._parse_ad(ad)
                    if listing is None or listing.url in seen_urls:
                        continue
                    if match_query and not self._matches_query(listing.title, match_query):
                        continue
                    if not self._within_price(listing.price_amount, min_price, max_price):
                        continue

                    seen_urls.add(listing.url)
                    raw_images[listing.url] = images
                    listings.append(listing)
                    if len(listings) >= max_results:
                        break

                start += page_size
                if count_all and start >= count_all:
                    break

            listings = listings[:max_results]

            if deep and listings:
                listings = await self._store_all_images(client, listings, raw_images)

        return listings

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

        response = await client.get(self.HADES_URL, params=params)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------ parse

    def _parse_ad(self, ad: dict) -> tuple[ScrapedListing | None, list[str]]:
        url = (ad.get("urls") or {}).get("default")
        title = ad.get("subject")
        if not url or not title:
            return None, []

        features = ad.get("features") or []
        price_amount = self._parse_price(features)

        images = [
            img["cdn_base_url"] + self.IMAGE_RULE
            for img in ad.get("images") or []
            if img.get("cdn_base_url")
        ]

        listing = ScrapedListing(
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
            },
        )
        return listing, images

    def _feature(self, features: list[dict], uri: str) -> str | None:
        for feature in features:
            if feature.get("uri") == uri:
                values = feature.get("values") or []
                if values:
                    return values[0].get("value") or values[0].get("key")
        return None

    def _parse_price(self, features: list[dict]) -> int | None:
        raw = self._feature(features, "/price")
        if not raw:
            return None
        digits = re.sub(r"\D", "", raw.split(",")[0])
        return int(digits) if digits else None

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

    async def _store_all_images(
        self,
        client: httpx.AsyncClient,
        listings: list[ScrapedListing],
        raw_images: dict[str, list[str]],
    ) -> list[ScrapedListing]:
        semaphore = asyncio.Semaphore(self.IMAGE_CONCURRENCY)

        async def enrich(listing: ScrapedListing) -> ScrapedListing:
            async with semaphore:
                stored = await self._store_images(
                    client, raw_images.get(listing.url, []), listing.url
                )
            return replace(listing, image_urls=stored)

        return await asyncio.gather(*(enrich(item) for item in listings))

    async def _store_images(
        self,
        client: httpx.AsyncClient,
        image_urls: list[str],
        listing_url: str,
    ) -> list[str]:
        """Download every gallery image and persist it to Supabase Storage."""
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
