from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchRequest:
    query: str
    max_results: int = 20
    min_price: int | None = None
    max_price: int | None = None


@dataclass(frozen=True)
class ScrapedListing:
    source: str
    title: str
    url: str
    price: str | None = None
    price_amount: int | None = None
    location: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseScraper(ABC):
    """Strategy interface for marketplace scrapers."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable source name for listings produced by this scraper."""

    @abstractmethod
    async def search(self, request: SearchRequest) -> list[ScrapedListing]:
        """Search listings on the underlying marketplace."""

    async def close(self) -> None:
        """Release resources held by the scraper, when needed."""
