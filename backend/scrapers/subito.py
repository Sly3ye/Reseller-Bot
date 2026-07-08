from urllib.parse import urlencode

from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

from backend.scrapers.base import BaseScraper, ScrapedListing, SearchRequest


class SubitoScraper(BaseScraper):
    BASE_URL = "https://www.subito.it/annunci-italia/vendita/usato/"

    def __init__(self, headless: bool = True, timeout_ms: int = 20_000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms

    @property
    def source_name(self) -> str:
        return "subito"

    async def search(self, request: SearchRequest) -> list[ScrapedListing]:
        url = self._build_search_url(request)

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.headless)
            page = await browser.new_page()

            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                await self._accept_cookies_if_present(page)
                await page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
                html = await page.content()
            finally:
                await browser.close()

        return self._parse_results(html, request.max_results)

    def _build_search_url(self, request: SearchRequest) -> str:
        params: dict[str, str | int] = {"q": request.query}

        if request.min_price is not None:
            params["ps"] = request.min_price
        if request.max_price is not None:
            params["pe"] = request.max_price

        return f"{self.BASE_URL}?{urlencode(params)}"

    async def _accept_cookies_if_present(self, page) -> None:
        cookie_buttons = [
            "button:has-text('Accetta')",
            "button:has-text('Accetto')",
            "button:has-text('Accept')",
        ]

        for selector in cookie_buttons:
            try:
                button = page.locator(selector).first
                if await button.count() > 0:
                    await button.click(timeout=2_000)
                    return
            except PlaywrightTimeoutError:
                continue

    def _parse_results(self, html: str, max_results: int) -> list[ScrapedListing]:
        soup = BeautifulSoup(html, "html.parser")
        listings: list[ScrapedListing] = []

        for anchor in soup.select("a[href*='/annunci-']"):
            href = anchor.get("href")
            if not href or href.startswith("#"):
                continue

            title = self._extract_title(anchor)
            if not title:
                continue

            listing = ScrapedListing(
                source=self.source_name,
                title=title,
                url=href,
                price=self._extract_price(anchor),
                location=self._extract_location(anchor),
            )

            if listing.url not in {item.url for item in listings}:
                listings.append(listing)

            if len(listings) >= max_results:
                break

        return listings

    def _extract_title(self, anchor) -> str | None:
        title_node = anchor.select_one("h2, h3, [class*='title'], [data-testid*='title']")
        title = title_node.get_text(" ", strip=True) if title_node else anchor.get_text(" ", strip=True)
        return title or None

    def _extract_price(self, anchor) -> str | None:
        text = anchor.get_text(" ", strip=True)
        for token in text.split():
            if "€" in token or "EUR" in token.upper():
                return token
        return None

    def _extract_location(self, anchor) -> str | None:
        location_node = anchor.select_one("[class*='town'], [class*='location'], [data-testid*='location']")
        if location_node:
            return location_node.get_text(" ", strip=True)
        return None
