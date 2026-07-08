import asyncio
import json
import random
import re
from dataclasses import replace
from urllib.parse import urlencode, urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import BrowserType, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from backend.core.database import upload_image_to_storage
from backend.scrapers.base import BaseScraper, ScrapedListing, SearchRequest


class SubitoScraper(BaseScraper):
    BASE_URL = "https://www.subito.it/annunci-italia/vendita/usato/"
    HOME_URL = "https://www.subito.it/"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
        "Gecko/20100101 Firefox/126.0"
    )
    PRICE_RE = re.compile(
        r"(?<!\d)(?P<amount>\d{1,3}(?:\.\d{3})*|\d+)(?:,\d{2})?\s*(?:\u20ac|EUR)",
        re.IGNORECASE,
    )
    PROMOTED_MARKERS = {"promo", "vetrina"}
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
        headless: bool = True,
        timeout_ms: int = 30_000,
        browser_name: str = "firefox",
        organic_only: bool = True,
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.browser_name = browser_name
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
        request = SearchRequest(
            query=query,
            max_results=max_results,
            min_price=min_price,
            max_price=max_price,
        )
        # Strict match keeps only titles containing every query token (precision,
        # for the sniper). Light/batch mode relaxes it to gather more prices for
        # a market average, relying on Subito's own relevance + outlier cleaning.
        match_query = query if strict_match else None

        async with async_playwright() as playwright:
            browser_type = self._get_browser_type(playwright)
            browser = await browser_type.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent=self.USER_AGENT,
                locale="it-IT",
                timezone_id="Europe/Rome",
                viewport={"width": 1366, "height": 1200},
                extra_http_headers={
                    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            page = await context.new_page()

            listings: list[ScrapedListing] = []
            seen_urls: set[str] = set()

            try:
                await page.goto(self.HOME_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
                await self._human_delay(page)

                for page_num in range(1, max(1, pages) + 1):
                    url = self._build_search_url(request, page=page_num)
                    await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)

                    if page_num == 1:
                        await self._accept_cookies_if_present(page)

                    await self._human_delay(page)
                    try:
                        await self._wait_for_listing_cards(page)
                    except RuntimeError:
                        break  # No more results on this page: stop paginating.

                    await page.mouse.wheel(0, random.randint(450, 900))
                    await self._human_delay(page, min_ms=700, max_ms=1_400)
                    html = await page.content()

                    for listing in self._parse_results(
                        html, max_results=max_results, query=match_query
                    ):
                        if listing.url not in seen_urls:
                            seen_urls.add(listing.url)
                            listings.append(listing)

                    if len(listings) >= max_results:
                        break

                listings = listings[:max_results]

                if deep and listings:
                    listings = await self._enrich_listings(page, listings)
            finally:
                await context.close()
                await browser.close()

        return listings

    def _get_browser_type(self, playwright) -> BrowserType:
        try:
            return getattr(playwright, self.browser_name)
        except AttributeError as exc:
            raise ValueError(f"Unsupported Playwright browser: {self.browser_name}") from exc

    def _build_search_url(self, request: SearchRequest, page: int = 1) -> str:
        params: dict[str, str | int] = {"q": request.query}

        if request.min_price is not None:
            params["ps"] = request.min_price
        if request.max_price is not None:
            params["pe"] = request.max_price
        if page > 1:
            params["o"] = page  # Subito paginates via the "o" (page number) param.

        return f"{self.BASE_URL}?{urlencode(params)}"

    async def _accept_cookies_if_present(self, page: Page) -> None:
        cookie_buttons = [
            "button:has-text('Accetta')",
            "button:has-text('Accetto')",
            "button:has-text('Accetta tutto')",
            "button:has-text('Accept')",
        ]

        for selector in cookie_buttons:
            try:
                button = page.locator(selector).first
                if await button.count() > 0:
                    await button.click(timeout=2_500)
                    await self._human_delay(page, min_ms=600, max_ms=1_200)
                    return
            except PlaywrightTimeoutError:
                continue

    async def _wait_for_listing_cards(self, page: Page) -> None:
        try:
            await page.locator("article a[href$='.htm']").first.wait_for(timeout=self.timeout_ms)
        except PlaywrightTimeoutError as exc:
            title = await page.title()
            body = await page.locator("body").inner_text(timeout=5_000)
            snippet = " ".join(body.split())[:240]
            raise RuntimeError(f"Subito listings not found. Page title: {title}. Body: {snippet}") from exc

    async def _human_delay(
        self,
        page: Page,
        min_ms: int = 1_200,
        max_ms: int = 2_500,
    ) -> None:
        await page.wait_for_timeout(random.randint(min_ms, max_ms))

    async def _enrich_listings(
        self,
        page: Page,
        listings: list[ScrapedListing],
    ) -> list[ScrapedListing]:
        """Visit each listing's detail page to add description and stored images."""
        enriched: list[ScrapedListing] = []

        for index, listing in enumerate(listings):
            if index > 0:
                # 1-3s between requests to look human and avoid blocks.
                await self._human_delay(page, min_ms=1_000, max_ms=3_000)

            try:
                await page.goto(
                    listing.url, wait_until="domcontentloaded", timeout=self.timeout_ms
                )
                await self._human_delay(page, min_ms=800, max_ms=1_500)

                description, gallery_urls = await self._extract_detail(page)
                image_urls = await self._store_images(gallery_urls, listing.url)

                enriched.append(
                    replace(listing, description=description, image_urls=image_urls)
                )
            except Exception:
                # Never lose a listing because enrichment of one page failed.
                enriched.append(listing)

        return enriched

    async def _extract_detail(self, page: Page) -> tuple[str | None, list[str]]:
        """Return (description, high-res gallery image URLs) for a detail page.

        JSON-LD is the reliable source: it lists exactly this ad's photos at
        full resolution and carries the ad description. DOM/meta are fallbacks.
        """
        description, images = await self._extract_from_json_ld(page)

        if not description:
            description = await self._extract_description(page)
        if not images:
            images = await self._extract_gallery_from_dom(page)

        return description, images

    async def _extract_from_json_ld(self, page: Page) -> tuple[str | None, list[str]]:
        try:
            blocks = await page.evaluate(
                """() => [...document.querySelectorAll('script[type=\"application/ld+json\"]')]
                    .map((s) => s.textContent)"""
            )
        except Exception:
            return None, []

        description: str | None = None
        images: list[str] = []

        for block in blocks or []:
            try:
                data = json.loads(block)
            except Exception:
                continue

            for obj in self._iter_ld_objects(data):
                if not isinstance(obj, dict):
                    continue

                raw_image = obj.get("image")
                if raw_image and not images:
                    if isinstance(raw_image, str):
                        images = [raw_image]
                    elif isinstance(raw_image, list):
                        images = [url for url in raw_image if isinstance(url, str)]

                raw_desc = obj.get("description")
                if raw_desc and not description and isinstance(raw_desc, str):
                    description = raw_desc.strip()

        return description, self._dedupe_preserving_order(images)

    def _iter_ld_objects(self, data: Any):
        if isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                yield from data["@graph"]
            yield data
        elif isinstance(data, list):
            for item in data:
                yield from self._iter_ld_objects(item)

    async def _extract_description(self, page: Page) -> str | None:
        try:
            text = await page.evaluate(
                """() => {
                    let best = '';
                    document.querySelectorAll('[class*="description"]').forEach((el) => {
                        const t = (el.innerText || '').trim();
                        if (t.length > best.length) best = t;
                    });
                    return best;
                }"""
            )
            if text and len(text.strip()) >= 40:
                return text.strip()
        except Exception:
            pass

        for selector in (
            "meta[property='og:description']",
            "meta[name='description']",
        ):
            try:
                node = page.locator(selector).first
                if await node.count() > 0:
                    content = await node.get_attribute("content")
                    if content and content.strip():
                        return content.strip()
            except Exception:
                continue

        return None

    async def _extract_gallery_from_dom(self, page: Page) -> list[str]:
        try:
            urls = await page.evaluate(
                """() => {
                    const out = [];
                    document.querySelectorAll('img, source[srcset]').forEach((el) => {
                        const candidates = el.srcset
                            ? el.srcset.split(',').map((p) => p.trim().split(' ')[0])
                            : [el.currentSrc || el.src || ''];
                        candidates.forEach((u) => {
                            if (/images\\.(sbito|subito)/.test(u)
                                && /gallery-desktop/.test(u)
                                && !/thumbnail/.test(u)) {
                                out.push(u);
                            }
                        });
                    });
                    return out;
                }"""
            )
        except Exception:
            return []

        return self._dedupe_preserving_order(urls or [])

    def _dedupe_preserving_order(self, urls: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)
        return unique

    async def _store_images(
        self,
        image_urls: list[str],
        listing_url: str,
    ) -> list[str]:
        """Download every gallery image and persist them to Supabase Storage."""
        if not image_urls:
            return []

        slug = self._listing_slug(listing_url)
        stored: list[str] = []

        async with httpx.AsyncClient(
            timeout=30, headers={"User-Agent": self.USER_AGENT}, follow_redirects=True
        ) as client:
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

        path = urlparse(listing_url).path.rsplit("/", 1)[-1]
        cleaned = re.sub(r"[^a-zA-Z0-9_-]", "-", path) or "listing"
        return cleaned.removesuffix(".htm")

    def _parse_results(
        self,
        html: str,
        max_results: int,
        query: str | None = None,
    ) -> list[ScrapedListing]:
        soup = BeautifulSoup(html, "html.parser")
        listings: list[ScrapedListing] = []

        for article in soup.select("article"):
            anchor = article.select_one("a[href$='.htm'][href*='subito.it']")
            if not anchor:
                continue

            href = anchor.get("href")
            title = self._extract_title(article, anchor)
            price_text, price_amount = self._extract_price(article)

            if not href or not title or price_amount is None:
                continue

            if query and not self._matches_query(title, query):
                continue

            is_promoted = self._is_promoted(article)
            if self.organic_only and is_promoted:
                continue

            listing = ScrapedListing(
                source=self.source_name,
                title=title,
                price=price_text,
                price_amount=price_amount,
                url=href,
                location=self._extract_location(article),
                metadata={"promoted": is_promoted},
            )

            if listing.url not in {item.url for item in listings}:
                listings.append(listing)

            if len(listings) >= max_results:
                break

        return listings

    def _matches_query(self, title: str, query: str) -> bool:
        title_tokens = set(self._tokenize(title))
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return True

        return all(token in title_tokens for token in query_tokens)

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _extract_title(self, article, anchor) -> str | None:
        title = anchor.get("aria-label")
        if title:
            return title.strip()

        image = article.select_one("img[alt]")
        if image and image.get("alt"):
            return image["alt"].strip()

        title_node = article.select_one("h2, h3, [class*='title'], [data-testid*='title']")
        if title_node:
            return title_node.get_text(" ", strip=True)

        return None

    def _extract_price(self, article) -> tuple[str | None, int | None]:
        text = article.get_text(" ", strip=True).replace("\xa0", " ")
        match = self.PRICE_RE.search(text)
        if not match:
            return None, None

        amount = int(re.sub(r"\D", "", match.group("amount")))
        return f"{amount} EUR", amount

    def _extract_location(self, article) -> str | None:
        location_node = article.select_one(
            "[class*='town'], [class*='location'], [data-testid*='location']"
        )
        if location_node:
            return location_node.get_text(" ", strip=True)

        lines = [
            line.strip()
            for line in article.get_text("\n", strip=True).splitlines()
            if line.strip()
        ]
        for line in reversed(lines):
            if re.search(r"\([A-Z]{2}\)$", line):
                return line

        return None

    def _is_promoted(self, article) -> bool:
        lines = [
            line.strip().lower()
            for line in article.get_text("\n", strip=True).splitlines()
            if line.strip()
        ]
        return any(line in self.PROMOTED_MARKERS for line in lines[:3])
