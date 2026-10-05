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
from backend.scrapers.subito import ScraperBlockedError, SubitoScraper, current_job
from backend.services.republish import merge_into_old
from backend.scrapers.nlp_parser import _is_accessory_listing
from backend.services.variants import (
    in_iphone_scope, iphone_model_key, mentions_iphone, model_text, normalize_iphone,
)
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
SWEEP_QUERY = {"smartphone": "iphone", "automobile": ""}
# Categoria Subito sfogliata per intero (query vuota): tutte le auto.
SWEEP_CATEGORY_ID = {"automobile": "2"}
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
    "I phone 16 pro", "Iphon 13") e, se il modello si riconosce, solo
    nell'ambito (iPhone 12 e successivi, IPHONE_MIN_GEN). Modello non
    riconosciuto: si tiene, lo legge l'AI dalla descrizione."""
    if category == "smartphone":
        if not mentions_iphone(listing.title):
            return False
        model = iphone_model_key(model_text(listing.title, listing.description))
        return in_iphone_scope(model) is not False
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
    current_job.set(f"sweep_{category}")
    query = SWEEP_QUERY[category]
    db = get_db()
    targets = await asyncio.to_thread(get_active_targets, category)
    index = build_target_index(targets)

    started = datetime.now(timezone.utc)
    last = await asyncio.to_thread(get_last_sweep, db, category)
    since = (last - SINCE_MARGIN) if last else started - FIRST_SCAN_LOOKBACK

    scraper = SubitoScraper(category_id=SWEEP_CATEGORY_ID.get(category))
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

    # Auto: foto solo per le occasioni (mezzo milione di gallerie = terabyte);
    # restano le URL originali (raw_image_urls).
    totals = await persist_by_target(
        scraper, category, listings, index, download_images=category != "automobile"
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
        "Sweep %s: %d pagine, %d annunci tenuti (%d senza target), +%d nuovi, %d cali%s",
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


# ------------------------------------------------------- testa della coda

# Quanti URL ricordare per categoria: la pagina 1 ne ha 100, così le letture
# successive non chiedono al DB annunci già visti un minuto prima.
_HEAD_SEEN_MAX = 5000
_head_seen: dict[str, dict[str, None]] = {}


async def head_poll(category: str = "smartphone") -> dict[str, Any]:
    """Testa della coda (Goal Version §3): solo la pagina 1, ogni 30–60 s.

    I nuovi davvero si salvano SUBITO senza foto (le scarica dopo il job
    delle foto) e si notificano nello stesso giro: l'alert parte secondi dopo
    l'indicizzazione invece che a fine sweep (in media 7,5 min di attesa per
    gli iPhone, 15 per le auto) e senza aspettare il download delle gallerie.
    Lo sweep resta come rete di sicurezza per ciò che la testa non vede.

    Subito indicizza a ondate (~ogni 10 minuti): un'ondata di auto supera
    spesso i 100 annunci della pagina 1 (+100 misurati il 5/10). Se la pagina
    è quasi tutta nuova si legge subito la successiva, fino a HEAD_MAX_PAGES.
    """
    current_job.set(f"testa_{category}")
    scraper = SubitoScraper(category_id=SWEEP_CATEGORY_ID.get(category))
    new = checked = 0
    for page in range(HEAD_MAX_PAGES):
        outcome = await _head_page(scraper, category, page * SubitoScraper.PAGE_SIZE)
        if outcome.get("error"):
            return {"mode": "head", "category": category, "new": new, **outcome}
        new += outcome["new"]
        checked += outcome["checked"]
        # Pagina satura (quasi tutta nuova): l'ondata continua oltre.
        if outcome["listings"] < HEAD_MIN_PAGE or outcome["new"] < HEAD_SATURATED * outcome["listings"]:
            break
    if new:
        logger.info("Testa %s: +%d nuovi, notificati subito", category, new)
    return {"mode": "head", "category": category, "new": new, "checked": checked, "pages": page + 1}


HEAD_MAX_PAGES = 3
HEAD_MIN_PAGE = 50       # pagine più corte: niente da inseguire oltre
HEAD_SATURATED = 0.9     # quota di nuovi oltre cui si legge la pagina successiva


async def _head_page(scraper: SubitoScraper, category: str, start: int) -> dict[str, Any]:
    """Una pagina della testa: salva i nuovi senza foto e li notifica subito."""
    from backend.tasks import notify_new_rows  # noqa: PLC0415

    anti_min, anti_max = anti_spam_bounds(category)
    try:
        payload = await scraper._fetch_page(SWEEP_QUERY[category], SubitoScraper.PAGE_SIZE, start,
                                            anti_min, anti_max)
    except ScraperBlockedError as exc:
        return {"blocked": True, "error": str(exc)[:120]}
    except Exception as exc:  # noqa: BLE001 (rete giù: il prossimo giro riprova)
        logger.warning("Testa %s: %s", category, str(exc)[:120])
        return {"error": str(exc)[:120]}
    listings = [
        listing for listing in scraper.select_ads(payload.get("ads") or [], min_price=anti_min,
                                                  max_price=anti_max)
        if is_relevant(listing, category)
    ]
    seen = _head_seen.setdefault(category, {})
    fresh = [listing for listing in listings if listing.url not in seen]
    for listing in listings:
        seen[listing.url] = None
    while len(seen) > _HEAD_SEEN_MAX:
        seen.pop(next(iter(seen)))
    if not fresh:
        return {"new": 0, "checked": 0, "listings": len(listings)}
    targets = await asyncio.to_thread(get_active_targets, category)
    totals = await persist_by_target(
        scraper, category, fresh, build_target_index(targets), download_images=False
    )
    if totals["inserted_rows"] or totals["drop_events"]:
        await notify_new_rows(
            {category: totals["inserted_rows"]} if totals["inserted_rows"] else {},
            {category: totals["drop_events"]} if totals["drop_events"] else {},
        )
    return {"new": totals["new"], "checked": len(fresh), "listings": len(listings)}


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
    bands_override: list[tuple[int, int | None]] | None = None,
) -> tuple[dict[str, Any], set[str]]:
    """Sfoglia TUTTO lo stock attivo della query ampia, fascia per fascia, e
    salva (senza immagini) nuovi annunci e variazioni di prezzo.

    Salva pagina per pagina (un blocco a metà non butta il lavoro fatto) ed è
    idempotente: rilanciarlo deduplica su listing_url. ``min_price`` riprende
    da una fascia (l'output indica da dove ripartire). Ritorna i totali (con
    ``complete`` = nessuna fascia oltre il tetto di hades) e gli URL visti.
    ``bands_override``: solo queste fasce (inventario auto a rotazione), ognuna
    ri-suddivisa se nel frattempo ha superato il tetto di hades.
    """
    query = SWEEP_QUERY[category]
    targets = await asyncio.to_thread(get_active_targets, category)
    index = build_target_index(targets)
    scraper = SubitoScraper(category_id=SWEEP_CATEGORY_ID.get(category))
    anti_min, anti_max = anti_spam_bounds(category)
    lo = max(anti_min, min_price or anti_min)

    if bands_override is not None:
        bands = []
        for b_lo, b_hi in bands_override:
            bands += await price_bands(scraper, query, b_lo, b_hi)
    else:
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
    if bands_override is not None:
        return grand, seen_all  # una fetta: la fotografia di copertura è per il ciclo
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
    current_job.set("storico")
    grand, _ = await walk_inventory(category, min_price, progress)
    return grand


# Tetto di verifiche pagina-per-pagina per notte: gli annunci attivi nel DB ma
# assenti dall'inventario sono di solito qualche centinaio (i venduti del
# giorno). Un numero molto più alto indica un inventario anomalo: meglio
# fermarsi che scaricare migliaia di pagine dallo stesso IP.
MAX_VERIFY_PER_NIGHT = 3000
BLIND_VERIFY_PER_NIGHT = 50


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
    lock = _inventory_lock(category)
    if lock.locked():
        logger.info("Inventario %s già in corso: salto", category)
        return {"mode": "reconcile", "category": category, "skipped": True}
    async with lock:
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
# Un lock per categoria: iPhone e auto possono girare nella stessa notte (il
# ritmo delle richieste lo serializza comunque il pacer globale).
_INVENTORY_LOCKS: dict[str, asyncio.Lock] = {}


def _inventory_lock(category: str) -> asyncio.Lock:
    return _INVENTORY_LOCKS.setdefault(category, asyncio.Lock())


# ------------------------------------------------- inventario auto a rotazione

# Oltre questa quota di attivi "spariti" in un ciclo, qualcosa non va (ciclo
# rotto, fasce saltate): niente rimozioni, allarme.
AUTO_MAX_REMOVED_SHARE = 0.25


def _load_state(db: Any, key: str) -> dict[str, Any]:
    try:
        rows = db.table("app_settings").select("value").eq("key", key).limit(1).execute().data
        return (rows[0]["value"] or {}) if rows else {}
    except Exception:
        return {}


async def reconcile_auto_inventory(category: str = "automobile") -> dict[str, Any]:
    """Inventario di TUTTE le auto, a rotazione (AUTO_INVENTORY_SLICES notti).

    537k annunci = ~5.400 richieste: dallo stesso IP degli iPhone non si fanno
    in una notte. Le fasce di prezzo si fissano a inizio ciclo e ogni notte se
    ne sfoglia una fetta (fasce k, k+N, k+2N...). Una notte saltata o una
    fetta incompleta non fa avanzare il ciclo.

    Venduti SENZA verifica pagina per pagina (migliaia di sparizioni al giorno
    non si verificano una per una): a fine ciclo, ogni auto attiva non vista
    da quando il ciclo è cominciato (``updated_at`` < inizio ciclo) è sparita,
    con data = l'ultima volta vista. Precisione della data: ±durata del ciclo,
    accettabile su tempi di vendita di settimane. Le ripubblicazioni dello
    stesso venditore si fondono prima (services/republish.merge_into_old).
    """
    lock = _inventory_lock(category)
    if lock.locked():
        return {"mode": "auto_slice", "category": category, "skipped": True}
    async with lock:
        try:
            result = await _auto_slice(category)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Inventario %s fallito", category)
            result = {"mode": "auto_slice", "category": category, "aborted": True,
                      "error": f"{type(exc).__name__}: {exc}"[:300]}
        await _record_inventory(category, result)
    return result


async def _auto_slice(category: str) -> dict[str, Any]:
    current_job.set(f"inventario_{category}")
    from backend.core.config import settings  # noqa: PLC0415

    db = get_db()
    key = f"inventory_cycle:{category}"
    state = await asyncio.to_thread(_load_state, db, key)
    n = max(1, settings.auto_inventory_slices)
    now = datetime.now(timezone.utc)
    if not state.get("bands") or state.get("next", 0) == 0:
        # Nuovo ciclo: fasce fissate ora (ognuna sotto il tetto di hades).
        scraper = SubitoScraper(category_id=SWEEP_CATEGORY_ID.get(category))
        anti_min, anti_max = anti_spam_bounds(category)
        bands = await price_bands(scraper, SWEEP_QUERY[category], anti_min, anti_max)
        state = {"bands": [[lo, hi] for lo, hi, _ in bands], "slices": n, "next": 0,
                 "cycleStart": now.isoformat(), "walked": {},
                 "subitoTotal": sum(c for _, _, c in bands)}
    k = int(state["next"])
    mine = [tuple(b) for i, b in enumerate(state["bands"]) if i % int(state["slices"]) == k]
    try:
        grand, _seen = await walk_inventory(category, progress=logger.info, bands_override=mine)
    except ScraperBlockedError as exc:
        await asyncio.to_thread(_save_state, db, key, state)
        return {"mode": "auto_slice", "category": category, "aborted": True, "error": str(exc)[:200]}
    if not grand["complete"]:
        await asyncio.to_thread(_save_state, db, key, state)
        return {"mode": "auto_slice", "category": category, "slice": k, **grand}

    state["walked"][str(k)] = datetime.now(timezone.utc).isoformat()
    state["read"] = int(state.get("read", 0)) + grand["read"]
    result: dict[str, Any] = {"mode": "auto_slice", "category": category, "slice": k,
                              "slices": state["slices"], **grand}
    if k + 1 < int(state["slices"]):
        state["next"] = k + 1
    else:
        state["next"] = 0  # ciclo completo: il prossimo giro ne apre uno nuovo
        result.update(await asyncio.to_thread(_close_auto_cycle, db, category, state))
        # Copertura del ciclo per il cruscotto (come l'inventario iPhone).
        await asyncio.to_thread(_save_state, db, f"inventory_last:{category}", {
            "at": datetime.now(timezone.utc).isoformat(), "subitoTotal": state.get("subitoTotal"),
            "read": state.get("read"), "complete": True, "cycleStart": state["cycleStart"],
        })
    await asyncio.to_thread(_save_state, db, key, state)
    return result


def _close_auto_cycle(db: Any, category: str, state: dict[str, Any]) -> dict[str, Any]:
    """Fine ciclo: le auto attive non viste dall'inizio del ciclo sono sparite."""
    from backend.core.database import _get_pool  # noqa: PLC0415
    from backend.services.garbage_collector import TABLES  # noqa: PLC0415

    table = TABLES[category]
    cutoff = state["cycleStart"]
    cols = ("id, listing_url, title, asking_price, seller_id, variant_key, found_at, "
            "updated_at, published_at")
    with _get_pool().connection() as conn:
        active_n = conn.execute(
            f"select count(*) as n from public.{table} where status in ('nuovo','visto')"
        ).fetchone()["n"]
        missing = [dict(r) for r in conn.execute(
            f"select {cols} from public.{table} where status in ('nuovo','visto') and updated_at < %s",
            (cutoff,),
        ).fetchall()]
        if not missing:
            return {"candidates": 0, "removed": 0}
        if len(missing) > AUTO_MAX_REMOVED_SHARE * max(active_n, 1):
            logger.warning("Ciclo %s: %d spariti su %d attivi, oltre la soglia: niente rimozioni",
                           category, len(missing), active_n)
            return {"candidates": len(missing), "removed": 0, "capped": len(missing)}
        # Ripubblicazioni: solo i venditori dei "mancanti", tra gli attivi visti.
        sellers = sorted({str(r["seller_id"]) for r in missing if r.get("seller_id")})
        still_online: list[dict[str, Any]] = []
        for i in range(0, len(sellers), 500):
            still_online += [dict(r) for r in conn.execute(
                f"select {cols} from public.{table} where status in ('nuovo','visto') "
                f"and updated_at >= %s and seller_id = any(%s)",
                (cutoff, sellers[i:i + 500]),
            ).fetchall()]
    merged = set(merge_into_old(db, table, category, missing, still_online))
    gone = [r["id"] for r in missing if r["id"] not in merged]
    with _get_pool().connection() as conn, conn.cursor() as cur:
        for i in range(0, len(gone), 1000):
            # updated_at NON si tocca: resta l'ultima volta vista = data di sparizione.
            cur.execute(
                f"update public.{table} set status = 'venduto_rimosso' where id = any(%s)",
                (gone[i:i + 1000],),
            )
    logger.info("Ciclo %s chiuso: %d spariti, %d ripubblicazioni fuse", category, len(gone), len(merged))
    return {"candidates": len(missing), "removed": len(gone), "republished_merged": len(merged)}
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
    INVENTORY_MAX_AGE_H ore (PC spento all'ora programmata). Per le auto:
    l'ultima fetta del ciclo a rotazione."""
    if category == "automobile":
        state = await asyncio.to_thread(_load_state, get_db(), f"inventory_cycle:{category}")
        walked = [datetime.fromisoformat(v) for v in (state.get("walked") or {}).values()]
        last = max(walked) if walked else None
        if last and (datetime.now(timezone.utc) - last).total_seconds() < INVENTORY_MAX_AGE_H * 3600:
            return None
        return await reconcile_auto_inventory(category)
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
    current_job.set(f"inventario_{category}")
    from backend.services.garbage_collector import TABLES  # noqa: PLC0415

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

    # Solo ciò che l'inventario POTEVA vedere: iPhone nel titolo, prezzo sopra
    # la soglia anti-spam e non un accessorio (select_ads li scarta prima di
    # segnarli come visti: altrimenti si riverificherebbero ogni notte).
    missing = [
        r for r in rows
        if r["listing_url"] not in seen
        and mentions_iphone(r.get("title"))
        and not _is_accessory_listing(r.get("title"))
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
    # Righe vecchie senza "iphone" nel titolo (salvate dai vecchi target):
    # l'inventario non può vederle e resterebbero attive per sempre. Qualcuna
    # a notte si verifica pagina per pagina, finché non sono esaurite.
    blind = [r for r in rows if r["listing_url"] not in seen and not mentions_iphone(r.get("title"))]
    blind.sort(key=lambda r: str(r.get("updated_at") or ""))
    candidates += [{"id": r["id"], "listing_url": r["listing_url"]} for r in blind[:BLIND_VERIFY_PER_NIGHT]]
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
    # In coda nel DB e verificati a pezzi: ogni pezzo marca subito i rimossi,
    # così un riavvio (o la macchina spenta) non butta ore di verifiche.
    await asyncio.to_thread(save_verify_queue, db, category, candidates, "inventario")
    result = await _drain_verify_queue(db, category)
    logger.info("Inventario %s: %d verificati, %d marcati rimossi",
                category, result["checked"], result["removed"])
    return {"mode": "reconcile", "category": category, **grand,
            "republished_merged": len(merged), "candidates": len(candidates),
            "capped": capped, **result}


# ----------------------------------------------- coda delle verifiche (venduti)

# Pagine per pezzo: dopo ognuno i rimossi si marcano e la coda si accorcia.
VERIFY_CHUNK = 50


def _verify_queue_key(category: str) -> str:
    return f"verify_queue:{category}"


def save_verify_queue(db: Any, category: str, candidates: list[dict[str, Any]], source: str) -> None:
    """Candidati venduti da verificare, in app_settings (sostituisce la coda)."""
    items = [{"id": str(c["id"]), "listing_url": c["listing_url"]} for c in candidates]
    _save_state(db, _verify_queue_key(category),
                {"at": datetime.now(timezone.utc).isoformat(), "source": source, "items": items})


def verify_queue_size(category: str) -> int:
    from backend.core.database import get_db  # noqa: PLC0415

    return len(_load_state(get_db(), _verify_queue_key(category)).get("items") or [])


def _mark_removed_ids(table: str, ids: list[str]) -> int:
    from backend.core.database import _get_pool  # noqa: PLC0415

    with _get_pool().connection() as conn:
        cur = conn.execute(
            f"update public.{table} set status = 'venduto_rimosso', updated_at = now() "
            "where id = any(%s::uuid[]) and status in ('nuovo', 'visto')",
            (ids,),
        )
        return cur.rowcount


async def _drain_verify_queue(db: Any, category: str) -> dict[str, int]:
    """Verifica la coda a pezzi (senza lock: lo tiene chi chiama)."""
    from backend.services.garbage_collector import TABLES, check_pages  # noqa: PLC0415

    table = TABLES[category]
    key = _verify_queue_key(category)
    totals = {"checked": 0, "removed": 0}
    while True:
        state = await asyncio.to_thread(_load_state, db, key)
        items = state.get("items") or []
        if not items:
            break
        part = items[:VERIFY_CHUNK]
        results, run = await check_pages(part)
        removed = [listing_id for listing_id, gone in results.items() if gone]
        if removed:
            totals["removed"] += await asyncio.to_thread(_mark_removed_ids, table, removed)
        totals["checked"] += len(results)
        # Via dalla coda solo le pagine verificate davvero (i blocchi restano),
        # sulla coda RILETTA ora: durante il pezzo può essere cambiata (potata
        # dall'archivio dei fuori ambito, il 5/10 riscriverla vecchia ne ha
        # rimesse dentro ~200).
        state = await asyncio.to_thread(_load_state, db, key)
        state["items"] = [it for it in (state.get("items") or []) if it["id"] not in results]
        await asyncio.to_thread(_save_state, db, key, state)
        logger.info("Verifiche %s: %d pagine, %d rimossi (in coda %d)",
                    category, len(results), len(removed), len(state["items"]))
        if run.get("aborted") or not results:
            logger.warning("Verifiche %s ferme (blocchi): %d restano in coda", category, len(state["items"]))
            break
    return totals


async def drain_verify_queue(category: str = "smartphone") -> dict[str, Any]:
    """Job: riprende le verifiche lasciate in coda (riavvio, macchina spenta,
    blocchi). Salta se l'inventario è in corso: le fa lui alla fine."""
    lock = _inventory_lock(category)
    if lock.locked():
        return {"category": category, "skipped": "inventario in corso"}
    async with lock:
        if not verify_queue_size(category):
            return {"category": category, "checked": 0, "removed": 0}
        result = await _drain_verify_queue(get_db(), category)
    if result["checked"]:
        logger.info("Verifiche in coda %s: %d verificate, %d marcate rimosse",
                    category, result["checked"], result["removed"])
    return {"category": category, **result}
