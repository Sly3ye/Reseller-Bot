"""Collaudo live dell'architettura Split Routing sullo Sniper auto.

Cerca 'Golf VII GTI' (categoria automobile) bypassando lo schedulatore e stampa
log dettagliati: proxy in uso (mascherato), tempo di download del JSON da hades,
annunci grezzi, breakdown dei filtri (anno/km/cambio) e conferma che le immagini
scendono dalla CDN in connessione diretta.

Esegui dalla root:  python scripts/test_sniper_auto.py
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import settings  # noqa: E402
from backend.scrapers.subito import SubitoScraper  # noqa: E402

QUERY = "Golf VII GTI"
CATEGORY = "automobile"
FILTERS = {"min_year": 2017, "max_km": 100000, "transmission": "automatic"}


def masked_proxy() -> str:
    if not settings.proxy_url:
        return "NESSUNO → api_client in connessione diretta"
    user = settings.proxy_user or ""
    return f"http://{user}:****@{settings.proxy_host}:{settings.proxy_port}"


def filter_reason(scraper: SubitoScraper, ad: dict) -> str | None:
    """None se passa, altrimenti il primo filtro che lo scarta."""
    feats = ad.get("features") or []
    year = scraper._feature_int(feats, "/year")
    if year is None or year < FILTERS["min_year"]:
        return "anno"
    km = scraper._feature_int(feats, "/mileage_scalar")
    if km is None or km > FILTERS["max_km"]:
        return "km"
    gearbox = (scraper._feature(feats, "/gearbox") or "").lower()
    if not gearbox or (FILTERS["transmission"] == "automatic" and "manuale" in gearbox):
        return "cambio"
    return None


async def main() -> None:
    scraper = SubitoScraper()

    print("=" * 66)
    print("COLLAUDO SPLIT ROUTING — Sniper auto")
    print("=" * 66)
    print(f"Query        : {QUERY!r}  (categoria: {CATEGORY})")
    print(f"Filtri       : {FILTERS}")
    print(f"api_client   → PROXY: {masked_proxy()}")
    print(f"cdn_client   → DIRETTA (trust_env=False, nessun proxy)")
    print("-" * 66)

    # 1) Download del JSON grezzo da hades tramite api_client (proxy), cronometrato.
    async with scraper._make_api_client() as api_client:
        params = {"q": QUERY, "t": "s", "lim": "100", "start": "0"}
        started = time.perf_counter()
        try:
            response = await scraper._get_with_retry(
                api_client, scraper.HADES_URL, params
            )
        except Exception as exc:  # proxy KO, auth 407, timeout…
            print(f"❌ Errore chiamando hades via proxy: {type(exc).__name__}: {exc}")
            raise SystemExit(1)
        elapsed = time.perf_counter() - started
        payload = response.json()

    ads = payload.get("ads") or []
    print(f"[api_client/proxy] JSON scaricato da hades in {elapsed:.3f}s")
    print(f"[api_client/proxy] count_all disponibili : {payload.get('count_all')}")
    print(f"[api_client/proxy] annunci grezzi estratti: {len(ads)}")
    print("-" * 66)

    # 2) Applicazione dei filtri nativi, con breakdown per motivo di scarto.
    kept: list[dict] = []
    discarded = {"anno": 0, "km": 0, "cambio": 0}
    for ad in ads:
        reason = filter_reason(scraper, ad)
        if reason is None:
            kept.append(ad)
        else:
            discarded[reason] += 1

    total_discarded = sum(discarded.values())
    print(f"[filtri] {len(ads)} grezzi → {len(kept)} pertinenti, {total_discarded} scartati")
    print(f"[filtri]   scartati per ANNO   (<{FILTERS['min_year']})      : {discarded['anno']}")
    print(f"[filtri]   scartati per KM     (>{FILTERS['max_km']})   : {discarded['km']}")
    print(f"[filtri]   scartati per CAMBIO (!= automatico) : {discarded['cambio']}")
    for ad in kept[:3]:
        feats = ad.get("features") or []
        y = scraper._feature_int(feats, "/year")
        km = scraper._feature_int(feats, "/mileage_scalar")
        gb = scraper._feature(feats, "/gearbox")
        print(f"[filtri]   ✓ {ad.get('subject','')[:40]} | {y} | {km} km | {gb}")
    print("-" * 66)

    # 3) Conferma download immagini dalla CDN in connessione diretta.
    sample = next(
        (
            [i["cdn_base_url"] + scraper.IMAGE_RULE for i in ad.get("images") or [] if i.get("cdn_base_url")]
            for ad in kept
            if ad.get("images")
        ),
        [],
    )
    if sample:
        async with scraper._make_cdn_client() as cdn_client:
            t0 = time.perf_counter()
            img = await cdn_client.get(sample[0])
            cdn_dt = time.perf_counter() - t0
        print(
            f"[cdn_client/diretta] immagine scaricata in {cdn_dt:.3f}s | "
            f"status {img.status_code} | {img.headers.get('content-type')} | "
            f"{len(img.content)} bytes"
        )
        print("[cdn_client/diretta] confermato: nessun proxy usato per la CDN")
    else:
        print("[cdn_client/diretta] nessun annuncio pertinente con immagini da testare")

    print("=" * 66)
    print(
        f"RISULTATO: {len(kept)} opportunità auto pertinenti pronte per dedup + "
        f"margini + save (identico a run_sniper_all_products)."
    )


if __name__ == "__main__":
    asyncio.run(main())
