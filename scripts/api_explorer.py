"""Reverse-engineering di Subito.it — dove si nascondono i dati JSON degli annunci.

Subito è una SPA: la pagina HTML non contiene gli annunci, che vengono caricati
via XHR da un'API JSON interna. Sniffando le richieste di rete del frontend si
trova l'endpoint `hades.subito.it/v1/search/items`, che restituisce l'intero
array di annunci in JSON puro — titolo, descrizione, prezzo, immagini, geo e URL,
tutto in un'unica risposta e senza dover aprire un browser.

Esegui:  python scripts/api_explorer.py "iPhone 14"
"""

from __future__ import annotations

import json
import re
import sys
import time

import httpx

HADES_URL = "https://hades.subito.it/v1/search/items"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
    "Gecko/20100101 Firefox/126.0"
)
IMAGE_RULE = "?rule=fullscreen-1x-auto"


def _feature(features: list[dict], uri: str) -> str | None:
    for feature in features or []:
        if feature.get("uri") == uri:
            values = feature.get("values") or []
            if values:
                return values[0].get("value") or values[0].get("key")
    return None


def _parse_price(features: list[dict]) -> int | None:
    raw = _feature(features, "/price")
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw.split(",")[0])
    return int(digits) if digits else None


def parse_ad(ad: dict) -> dict:
    geo = ad.get("geo") or {}
    town = (geo.get("town") or {}).get("value")
    city = (geo.get("city") or {}).get("value")
    images = [
        img["cdn_base_url"] + IMAGE_RULE
        for img in ad.get("images") or []
        if img.get("cdn_base_url")
    ]
    return {
        "title": ad.get("subject"),
        "price": _parse_price(ad.get("features") or []),
        "condition": _feature(ad.get("features") or [], "/item_condition"),
        "location": town or city,
        "url": (ad.get("urls") or {}).get("default"),
        "images": images,
        "description": (ad.get("body") or "").strip(),
    }


def fetch_search(query: str, limit: int = 10, start: int = 0) -> dict:
    params = {"q": query, "t": "s", "lim": str(limit), "start": str(start)}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    resp = httpx.get(HADES_URL, params=params, headers=headers, timeout=25)
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "iPhone 14"

    started = time.perf_counter()
    payload = fetch_search(query, limit=10)
    elapsed = time.perf_counter() - started

    ads = payload.get("ads") or []
    print(f"Query: {query!r}")
    print(f"Endpoint JSON: {HADES_URL}")
    print(f"Totale annunci disponibili (count_all): {payload.get('count_all')}")
    print(f"Recuperati {len(ads)} annunci in {elapsed:.3f}s (pura richiesta HTTP)\n")

    for ad in ads[:5]:
        parsed = parse_ad(ad)
        print(f"• {parsed['title']}")
        print(
            f"    prezzo={parsed['price']} € | {parsed['condition']} | "
            f"{parsed['location']} | {len(parsed['images'])} foto"
        )
        print(f"    {parsed['url']}")

    print("\nEsempio annuncio grezzo → parsato:")
    if ads:
        print(json.dumps(parse_ad(ads[0]), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
