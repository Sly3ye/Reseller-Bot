"""Ricerca ampia per categoria (sweep): UNA query copre tutto il mercato.

Il vecchio Sniper tech faceva una ricerca per target (36 query iPhone) che si
sovrapponevano quasi del tutto ("iPhone 13" restituisce anche 13 mini/Pro) e
lasciavano fuori i modelli senza target. Qui si cerca "iphone" ordinando per
data e si sfoglia all'indietro fino alla ricerca precedente: ogni annuncio
pubblicato passa una volta sola, qualunque modello sia, con ~1 richiesta per
giro invece di 36.

Ogni annuncio viene poi assegnato al target del SUO modello (non della query
che l'ha trovato): un "iPhone 13 Pro" va al target "iPhone 13 Pro" anche se è
uscito cercando "iphone". Così le statistiche per modello (venduti, tempo di
vendita, Market Intelligence) non mescolano modelli diversi. Gli iPhone senza
target (es. un 7) si salvano comunque, con target_id NULL: contano per le
varianti e per la copertura.

Due modalità:
- ``run_sweep``: schedulata, ritmo normale, immagini per i nuovi.
- ``deep_backfill``: una tantum, recupera TUTTO lo stock attivo. hades si
  ferma a 10.000 risultati per ricerca, quindi la query viene spezzata in
  fasce di prezzo, ognuna sotto il tetto (bisezione), e ogni fascia si
  sfoglia per intero. Senza immagini (le riempie lo sweep quando rivede
  l'annuncio).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from backend.core.database import get_db, has_column
from backend.scrapers.base import ScrapedListing
from backend.scrapers.subito import ScraperBlockedError, SubitoScraper
from backend.services.republish import merge_into_old
from backend.services.variants import iphone_model_key, mentions_iphone, model_text, normalize_iphone
from backend.tasks import (
    FIRST_SCAN_LOOKBACK,
    SINCE_MARGIN,
    anti_spam_bounds,
    finish_run,
    get_active_targets,
    persist_opportunities,
    update_target_last_scanned,
)

logger = logging.getLogger(__name__)

# Query ampia per categoria. Solo il tech: le auto hanno troppi modelli e
# volumi per una ricerca unica e restano sullo Sniper per target.
SWEEP_QUERY = {"smartphone": "iphone"}
# Tetto pagine per giro normale: 30 × 100 = 3.000 annunci ≈ 2 giorni di
# pubblicazioni iPhone. Basta a ricucire anche un fermo di una notte.
SWEEP_MAX_PAGES = 30
# hades: start massimo 10.000. Le fasce restano un po' sotto per sicurezza.
BAND_LIMIT = 9_800

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str | None) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


# ------------------------------------------------------------ target match

def build_target_index(targets: list[dict[str, Any]]) -> dict[str, Any]:
    """Indice per assegnare un annuncio al target del suo modello.

    - by_model: modelli numerici ("iPhone 13 Pro" → "iphone-13-pro").
    - by_tokens: modelli non numerici (X, XS Max, SE, 8 Plus), dal più
      specifico al meno: "iPhone 8 Plus" deve vincere su "iPhone 8".
    """
    by_model: dict[str, dict[str, Any]] = {}
    by_tokens: list[tuple[set[str], dict[str, Any]]] = []
    for target in targets:
        key = iphone_model_key(target["query"])
        if key:
            by_model.setdefault(key, target)
        else:
            by_tokens.append((_tokens(target["query"]), target))
    by_tokens.sort(key=lambda item: -len(item[0]))
    return {"by_model": by_model, "by_tokens": by_tokens}


def match_target(title: str | None, index: dict[str, Any]) -> dict[str, Any] | None:
    key = iphone_model_key(title)
    if key:
        # Modello numerico riconosciuto: o ha il suo target o nessuno (mai il
        # target di un altro modello per somiglianza di parole).
        return index["by_model"].get(key)
    title_tokens = _tokens(normalize_iphone(title))
    for tokens, target in index["by_tokens"]:
        if tokens <= title_tokens:
            return target
    return None


def is_relevant(listing: ScrapedListing, category: str) -> bool:
    """La query ampia pesca anche Samsung, Apple Watch, autoradio "iOS"...:
    teniamo solo gli annunci con "iphone" nel titolo (refusi compresi:
    "I phone 16 pro", "Iphon 13")."""
    if category == "smartphone":
        return mentions_iphone(listing.title)
    return True


async def persist_by_target(
    scraper: SubitoScraper,
    category: str,
    listings: list[ScrapedListing],
    index: dict[str, Any],
    download_images: bool,
) -> dict[str, Any]:
    """Raggruppa per target del modello e salva con la logica dello Sniper."""
    groups: dict[str | None, tuple[dict[str, Any] | None, list[ScrapedListing]]] = {}
    for listing in listings:
        if not is_relevant(listing, category):
            continue
        target = match_target(model_text(listing.title, listing.description), index)
        tid = target["id"] if target else None
        groups.setdefault(tid, (target, []))[1].append(listing)

    totals: dict[str, Any] = {
        "kept": 0, "new": 0, "updated": 0, "price_drops": 0, "unmatched": 0,
        "inserted_rows": [], "drop_events": [],
    }
    for tid, (target, items) in groups.items():
        result = await persist_opportunities(
            scraper, category, tid, items, download_images=download_images,
            query=target["query"] if target else None,
        )
        totals["kept"] += len(items)
        if tid is None:
            totals["unmatched"] += len(items)
        totals["new"] += result["new"]
        totals["updated"] += result["updated"]
        totals["price_drops"] += result["price_drops"]
        totals["inserted_rows"].extend(result.get("inserted_rows", []))
        totals["drop_events"].extend(result.get("drop_events", []))
    return totals


# ------------------------------------------------------------------- state

def _state_key(category: str) -> str:
    return f"sweep_last:{category}"


def get_last_sweep(db: Any, category: str) -> datetime | None:
    """Inizio dell'ultimo sweep riuscito (in app_settings, chiave interna)."""
    try:
        rows = (
            db.table("app_settings").select("value")
            .eq("key", _state_key(category)).limit(1).execute().data
        )
    except Exception:
        return None
    if not rows:
        return None
    value = rows[0].get("value")
    try:
        return datetime.fromisoformat(str((value or {}).get("at")))
    except (AttributeError, TypeError, ValueError):
        return None


def _save_state(db: Any, key: str, value: dict[str, Any]) -> None:
    """Stato interno in app_settings (chiavi ignorate dalle Impostazioni UI)."""
    db.table("app_settings").upsert(
        {"key": key, "value": value, "updated_at": datetime.now(timezone.utc).isoformat()},
        on_conflict="key",
    ).execute()


def set_last_sweep(db: Any, category: str, when: datetime) -> None:
    _save_state(db, _state_key(category), {"at": when.isoformat()})


# ------------------------------------------------------------------- sweep

async def run_sweep(
    category: str = "smartphone", max_pages: int = SWEEP_MAX_PAGES
) -> dict[str, Any]:
    """Giro schedulato: query ampia, all'indietro fino al giro precedente."""
    query = SWEEP_QUERY[category]
    db = get_db()
    targets = await asyncio.to_thread(get_active_targets, category)
    index = build_target_index(targets)

    started = datetime.now(timezone.utc)
    last = await asyncio.to_thread(get_last_sweep, db, category)
    since = (last - SINCE_MARGIN) if last else started - FIRST_SCAN_LOOKBACK

    scraper = SubitoScraper()
    anti_min, anti_max = anti_spam_bounds(category)
    blocked = False
    listings: list[ScrapedListing] = []
    try:
        listings = await scraper.search_text(
            query=query, min_price=anti_min, max_price=anti_max,
            strict_match=False, since=since, max_pages=max_pages,
        )
    except ScraperBlockedError as exc:
        blocked = True
        logger.warning("Sweep %s fermato: %s", category, exc)

    totals = await persist_by_target(
        scraper, category, listings, index, download_images=True
    )
    gap = bool(scraper.last_search.get("gap"))
    if not blocked:
        # Si avanza il segnalibro solo se il giro è andato a buon fine: dopo un
        # blocco il prossimo giro riparte dallo stesso punto, niente buchi.
        await asyncio.to_thread(set_last_sweep, db, category, started)
        for target in targets:
            await asyncio.to_thread(
                update_target_last_scanned, target["id"], db, started
            )

    logger.info(
        "Sweep %s: %d pagine, %d annunci iPhone (%d senza target), +%d nuovi, %d cali%s",
        category, scraper.last_search["pages"], totals["kept"], totals["unmatched"],
        totals["new"], totals["price_drops"],
        " — BUCO: non ricongiunto" if gap else "",
    )
    health = await finish_run(
        category, 1, 0 if blocked else 1, 1 if blocked else 0,
        len(listings), totals["new"], scraper.last_search["pages"],
        [query] if gap else [], blocked,
        {category: totals["inserted_rows"]} if totals["inserted_rows"] else {},
        {category: totals["drop_events"]} if totals["drop_events"] else {},
    )
    return {
        "mode": "sweep",
        "category": category,
        "pages": scraper.last_search["pages"],
        "gap": gap,
        "blocked": blocked,
        "status": health["status"],
        **{k: totals[k] for k in ("kept", "new", "updated", "price_drops", "unmatched")},
    }


# ------------------------------------------------------------ deep backfill

async def _count(scraper: SubitoScraper, query: str, lo: int, hi: int | None) -> int:
    payload = await scraper._fetch_page(query, 1, 0, lo, hi)
    return int(payload.get("count_all") or 0)


async def price_bands(
    scraper: SubitoScraper, query: str, lo: int, hi: int | None, top: int = 3000
) -> list[tuple[int, int | None, int]]:
    """Fasce [lo, hi] con meno di BAND_LIMIT risultati ciascuna (bisezione).
    ``top``: prima divisione per la fascia aperta in alto."""
    count = await _count(scraper, query, lo, hi)
    if count <= BAND_LIMIT:
        return [(lo, hi, count)] if count else []
    if hi is None:
        return (await price_bands(scraper, query, lo, top, top)
                + await price_bands(scraper, query, top + 1, None, top * 2))
    if hi - lo < 1:
        logger.warning("Fascia %d–%d ha %d annunci: oltre il tetto, parziale", lo, hi, count)
        return [(lo, hi, count)]
    mid = (lo + hi) // 2
    return (await price_bands(scraper, query, lo, mid, top)
            + await price_bands(scraper, query, mid + 1, hi, top))


# Un giro di un'ora non deve morire per qualche secondo di rete giù (reset
# TLS di hades visti il 2026-10-02): dopo i retry brevi dello scraper, attese
# lunghe e si riprende dalla stessa pagina. Un 403/429 invece ferma subito.
PATIENT_WAITS_S = (60, 180, 600)


async def _fetch_patiently(
    scraper: SubitoScraper, query: str, start: int, lo: int, hi: int | None
) -> dict[str, Any]:
    from curl_cffi.requests.exceptions import CurlError  # noqa: PLC0415

    for wait in (*PATIENT_WAITS_S, None):
        try:
            return await scraper._fetch_page(query, SubitoScraper.PAGE_SIZE, start, lo, hi)
        except CurlError as exc:
            if wait is None:
                raise
            logger.warning("Inventario: rete giù (%s), riprovo tra %ds dalla stessa pagina",
                           str(exc)[:80], wait)
            await asyncio.sleep(wait)
    raise RuntimeError("non raggiungibile")


async def walk_inventory(
    category: str = "smartphone",
    min_price: int | None = None,
    progress: Any = print,
) -> tuple[dict[str, Any], set[str]]:
    """Sfoglia TUTTO lo stock attivo della query ampia, fascia per fascia, e
    salva (senza immagini) nuovi annunci e variazioni di prezzo.

    Salva pagina per pagina (un blocco a metà non butta il lavoro fatto) ed è
    idempotente: rilanciarlo deduplica su listing_url. ``min_price`` riprende
    da una fascia (l'output indica da dove ripartire). Ritorna i totali (con
    ``complete`` = nessuna fascia oltre il tetto di hades) e gli URL visti.
    """
    query = SWEEP_QUERY[category]
    targets = await asyncio.to_thread(get_active_targets, category)
    index = build_target_index(targets)
    scraper = SubitoScraper()
    anti_min, anti_max = anti_spam_bounds(category)
    lo = max(anti_min, min_price or anti_min)

    bands = await price_bands(scraper, query, lo, anti_max)
    total_ads = sum(c for _, _, c in bands)
    progress(f"{len(bands)} fasce di prezzo, {total_ads} annunci totali da sfogliare")

    grand: dict[str, Any] = {
        "pages": 0, "kept": 0, "new": 0, "updated": 0, "unmatched": 0,
        "price_drops": 0, "read": 0, "short_bands": [],
        "complete": all(c <= BAND_LIMIT for _, _, c in bands),
    }
    seen_all: set[str] = set()
    for band_lo, band_hi, count in bands:
        progress(f"\nFascia {band_lo}–{band_hi or '∞'} €: {count} annunci "
                 f"(per riprendere da qui: --from {band_lo})")
        seen: set[str] = set()
        band_read = 0
        for start in range(0, min(count, SubitoScraper.MAX_DEPTH), SubitoScraper.PAGE_SIZE):
            payload = await _fetch_patiently(scraper, query, start, band_lo, band_hi)
            ads = payload.get("ads") or []
            band_read += len(ads)
            if not ads:
                break
            listings = scraper.select_ads(
                ads, min_price=band_lo, max_price=band_hi, seen_urls=seen
            )
            totals = await persist_by_target(
                scraper, category, listings, index, download_images=False
            )
            grand["pages"] += 1
            for key in ("kept", "new", "updated", "unmatched", "price_drops"):
                grand[key] += totals[key]
            progress(f"  start={start:<5} {len(ads):>3} grezzi → {totals['kept']:>3} iPhone, "
                     f"+{totals['new']} nuovi, {totals['updated']} già noti")
        seen_all |= seen
        grand["read"] += band_read
        # Una fascia letta per meno del 95% di quanto dichiarato (pagina vuota a
        # metà, risposte troncate) rende l'inventario NON completo: gli annunci
        # non letti passerebbero per venduti. Il 5% copre ciò che si vende o si
        # sposta di fascia durante le ore del giro.
        if band_read < 0.95 * min(count, SubitoScraper.MAX_DEPTH):
            grand["short_bands"].append(f"{band_lo}-{band_hi or ''}: {band_read}/{count}")
            grand["complete"] = False
    progress(f"\nFatto: { {k: v for k, v in grand.items()} }")
    # Fotografia della copertura per il cruscotto qualità: quanti annunci
    # dichiara Subito, quanti ne abbiamo visti, quanti erano iPhone veri.
    try:
        await asyncio.to_thread(
            _save_state, get_db(), f"inventory_last:{category}",
            {
                "at": datetime.now(timezone.utc).isoformat(),
                # read/subitoTotal = quanto della ricerca abbiamo letto (la
                # copertura vera); seen/kept = gli iPhone tenuti (il resto della
                # ricerca "iphone" sono cover, Samsung, accessori).
                "subitoTotal": total_ads, "read": grand["read"], "seen": len(seen_all),
                "kept": grand["kept"], "pages": grand["pages"], "complete": grand["complete"],
                "shortBands": grand["short_bands"], "fromPrice": lo,
            },
        )
    except Exception:
        logger.exception("Salvataggio statistiche inventario fallito")
    return grand, seen_all


async def deep_backfill(
    category: str = "smartphone",
    min_price: int | None = None,
    progress: Any = print,
) -> dict[str, Any]:
    """Recupero una tantum dell'intero stock attivo (vedi walk_inventory)."""
    grand, _ = await walk_inventory(category, min_price, progress)
    return grand


# Tetto di verifiche pagina-per-pagina per notte: gli annunci attivi nel DB ma
# assenti dall'inventario sono di solito qualche centinaio (i venduti del
# giorno). Un numero molto più alto indica un inventario anomalo: meglio
# fermarsi che scaricare migliaia di pagine dallo stesso IP.
MAX_VERIFY_PER_NIGHT = 3000


async def reconcile_inventory(category: str = "smartphone") -> dict[str, Any]:
    """Sostituisce il Garbage Collector per il tech (schedulato di notte).

    1. Inventario completo (~1 richiesta ogni 100 annunci) → URL attivi su
       Subito, più prezzi aggiornati per TUTTI gli annunci (ribassi completi).
    2. Annunci attivi nel DB ma assenti dall'inventario → candidati venduti.
    3. Solo i candidati si verificano pagina per pagina (un annuncio che ha
       cambiato fascia di prezzo durante il giro risulta ancora online e
       resta attivo) e i rimossi si marcano: alimenta il time-to-sale.

    Con il vecchio GC il tech costava una richiesta per annuncio attivo
    (decine di migliaia a notte); così ~540 + i candidati.
    """
    if _INVENTORY_LOCK.locked():
        logger.info("Inventario %s già in corso: salto", category)
        return {"mode": "reconcile", "category": category, "skipped": True}
    async with _INVENTORY_LOCK:
        try:
            result = await _reconcile(category)
        except Exception as exc:  # noqa: BLE001 (un inventario non deve morire in silenzio)
            logger.exception("Inventario %s fallito", category)
            result = {"mode": "reconcile", "category": category, "aborted": True,
                      "error": f"{type(exc).__name__}: {exc}"[:300]}
        await _record_inventory(category, result)
    # Motore Notturno A VALLE dell'inventario: medie e trend sul DB appena
    # riconciliato (prima girava a orario fisso, magari a inventario in corso).
    # Non dopo un inventario interrotto: il recupero lo ritenta ogni 30 min.
    if not result.get("aborted"):
        await run_nightly_once()
    return result


async def run_nightly_once() -> dict[str, Any] | None:
    """Motore Notturno al massimo una volta al giorno (ora italiana): parte a
    fine inventario, il job delle 06:00 è solo il ripiego. Per le auto fa
    scraping: due giri al giorno sarebbero richieste sprecate."""
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    from backend.tasks import run_nightly_batch_all_products  # noqa: PLC0415

    today = datetime.now(ZoneInfo("Europe/Rome")).date()
    if _NIGHTLY_DONE.get("day") == today:
        logger.info("Motore Notturno già eseguito oggi: salto")
        return None
    _NIGHTLY_DONE["day"] = today
    try:
        return await run_nightly_batch_all_products()
    except Exception:
        logger.exception("Motore Notturno fallito")
        return None


_NIGHTLY_DONE: dict[str, Any] = {}
_INVENTORY_LOCK = asyncio.Lock()
# Oltre quest'età l'ultimo inventario si rifà appena possibile (PC spento
# all'ora programmata: senza, i venduti di quella notte non si vedono mai).
INVENTORY_MAX_AGE_H = 26


async def _record_inventory(category: str, result: dict[str, Any]) -> None:
    """Esito di OGNI inventario (anche abortito) in app_settings, più un
    allarme se non è servito a riconciliare."""
    from backend.services.notifications import notify_system_alert  # noqa: PLC0415

    keys = ("aborted", "error", "complete", "read", "kept", "candidates",
            "checked", "removed", "republished_merged", "capped", "short_bands")
    outcome = {"at": datetime.now(timezone.utc).isoformat(),
               **{k: result[k] for k in keys if k in result}}
    try:
        await asyncio.to_thread(_save_state, get_db(), f"inventory_result:{category}", outcome)
    except Exception:
        logger.exception("Salvataggio esito inventario fallito")
    problem = None
    if result.get("aborted"):
        problem = f"interrotto ({result.get('error') or 'blocco Subito'}): nessun venduto marcato"
    elif result.get("complete") is False:
        bands = ", ".join(result.get("short_bands") or []) or "fascia oltre il tetto"
        problem = f"incompleto ({bands}): nessun venduto marcato"
    elif result.get("capped"):
        problem = f"{result['capped']} candidati oltre il tetto di verifica: inventario sospetto"
    if problem:
        try:
            await notify_system_alert(f"🟠 <b>Inventario {category}</b> {problem}")
        except Exception:
            logger.exception("Alert inventario fallito")


async def inventory_watchdog(category: str = "smartphone") -> dict[str, Any] | None:
    """Rifà l'inventario se l'ultimo completato è più vecchio di
    INVENTORY_MAX_AGE_H ore (PC spento all'ora programmata)."""
    try:
        rows = await asyncio.to_thread(
            lambda: get_db().table("app_settings").select("value")
            .eq("key", f"inventory_last:{category}").limit(1).execute().data
        )
        at = datetime.fromisoformat(str((rows[0]["value"] or {}).get("at"))) if rows else None
    except Exception:
        at = None
    if at and (datetime.now(timezone.utc) - at).total_seconds() < INVENTORY_MAX_AGE_H * 3600:
        return None
    logger.info("Inventario %s: l'ultimo è del %s, lo recupero ora", category, at)
    return await reconcile_inventory(category)


async def _reconcile(category: str) -> dict[str, Any]:
    from backend.services.garbage_collector import TABLES, verify_and_mark  # noqa: PLC0415

    try:
        grand, seen = await walk_inventory(category, progress=logger.info)
    except ScraperBlockedError as exc:
        logger.warning("Inventario %s interrotto (%s): nessun annuncio marcato", category, exc)
        return {"mode": "reconcile", "category": category, "aborted": True, "error": str(exc)[:200]}
    if not grand["complete"]:
        logger.warning("Inventario %s incompleto (%s): niente rimozioni",
                       category, grand.get("short_bands") or "fascia oltre il tetto")
        return {"mode": "reconcile", "category": category, **grand, "removed": 0}

    db = get_db()
    table = TABLES[category]
    anti_min, _ = anti_spam_bounds(category)
    cols = "id, listing_url, title, asking_price, seller_id, variant_key, found_at, updated_at"
    if has_column(table, "published_at", db):
        cols += ", published_at"
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        page = await asyncio.to_thread(
            lambda s=start: db.table(table).select(cols)
            .in_("status", ["nuovo", "visto"]).order("id").range(s, s + 999).execute().data
            or []
        )
        rows.extend(page)
        if len(page) < 1000:
            break
        start += 1000

    # Solo ciò che l'inventario POTEVA vedere: iPhone nel titolo e prezzo sopra
    # la soglia anti-spam. Il resto (vecchie righe rumorose) non si verifica.
    missing = [
        r for r in rows
        if r["listing_url"] not in seen
        and mentions_iphone(r.get("title"))
        and (r.get("asking_price") or 0) >= anti_min
    ]
    # Ripubblicazioni: un "mancante" con un gemello nato dopo la sua sparizione
    # non è venduto, è lo stesso oggetto rimesso online → fusione, niente verifica.
    still_online = [r for r in rows if r["listing_url"] in seen]
    merged = set(await asyncio.to_thread(
        merge_into_old, db, table, category, missing, still_online
    ))
    candidates = [
        {"id": r["id"], "listing_url": r["listing_url"]}
        for r in missing if r["id"] not in merged
    ]
    logger.info(
        "Inventario %s: %d attivi su Subito, %d attivi nel DB, %d candidati rimossi",
        category, len(seen), len(rows), len(candidates),
    )
    capped = 0
    if len(candidates) > MAX_VERIFY_PER_NIGHT:
        logger.warning(
            "Candidati %d oltre il tetto %d: inventario sospetto, verifico solo i primi",
            len(candidates), MAX_VERIFY_PER_NIGHT,
        )
        capped = len(candidates) - MAX_VERIFY_PER_NIGHT
        candidates = candidates[:MAX_VERIFY_PER_NIGHT]
    result = await verify_and_mark(db, table, candidates)
    logger.info("Inventario %s: %d verificati, %d marcati rimossi",
                category, result["checked"], result["removed"])
    return {"mode": "reconcile", "category": category, **grand,
            "republished_merged": len(merged), "candidates": len(candidates),
            "capped": capped, **result}
