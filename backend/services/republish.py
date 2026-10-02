"""Ripubblicazioni riconosciute SENZA foto (venditore + variante + prezzo).

Chi non vende spesso cancella l'annuncio e lo ripubblica per tornare in cima.
Se non lo riconosciamo, lo stesso telefono conta due volte e la sparizione
del primo annuncio passa per una VENDITA che non c'è stata: time-to-sale e
sell-through ne escono falsati. L'anti-ripubblicazione storica usa il pHash
della prima foto, ma le righe da inventario/backfill non hanno immagini. Qui
lo stesso oggetto si riconosce da:

- stesso venditore (``seller_id``),
- stessa variante canonica (per il tech: modello riconosciuto + memoria),
- prezzo entro ±15%,
- il nuovo annuncio compare attorno a quando il vecchio è sparito.

Due momenti:
(a) **allo Sniper/Sweep** (``find_revivable``): il nuovo arriva quando il
    vecchio è già stato marcato sparito → si "resuscita" il vecchio record.
(b) **all'inventario** (``merge_into_old``): il vecchio risulta sparito ma il
    nuovo è già in DB come riga a sé → il vecchio prende URL e prezzo del
    nuovo, il nuovo si elimina. In entrambi i casi il record conserva la data
    di nascita originale: l'età dell'annuncio resta vera.

La condizione temporale protegge i negozi con più pezzi dello stesso modello:
un secondo iPhone 13 128GB già online da settimane non è una ripubblicazione.
In più (dal 2026-10-02) un venditore con DUE pezzi della stessa variante online
insieme è un negozio: per lui niente abbinamento (un privato non ha due iPhone
13 128GB identici in vendita), altrimenti ogni pezzo nuovo cancellava la
vendita del precedente.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.services.variants import iphone_model_key, model_text

logger = logging.getLogger(__name__)

PRICE_TOLERANCE = 0.15
# (a) Il vecchio è sparito da al massimo N giorni.
REVIVE_WINDOW = timedelta(days=14)
# (b) Il nuovo è nato non prima di N giorni dall'ultima volta che il vecchio è
# stato visto online.
NEW_AFTER_OLD_SEEN = timedelta(days=2)

SOLD_STATUSES = ("venduto_rimosso", "scaduto")


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def identity(category: str, seller_id: Any, variant_key: Any, title: Any) -> tuple | None:
    """Chiave "stesso oggetto dello stesso venditore", o None se non affidabile.
    Per il tech serve un modello riconosciuto: una variante di ripiego ricavata
    dal titolo non basta a dire che due annunci sono lo stesso telefono."""
    if not seller_id or not variant_key:
        return None
    if category != "automobile" and iphone_model_key(title) is None:
        return None
    return (str(seller_id), str(variant_key))


def shop_identities(category: str, active: list[dict[str, Any]], min_pieces: int) -> set[tuple]:
    """Identità (venditore, variante) con almeno ``min_pieces`` righe attive."""
    counts: dict[tuple, int] = {}
    for row in active:
        key = identity(category, row.get("seller_id"), row.get("variant_key"),
                       model_text(row.get("title"), row.get("description")))
        if key:
            counts[key] = counts.get(key, 0) + 1
    return {k for k, n in counts.items() if n >= min_pieces}


def _close_price(a: Any, b: Any) -> bool:
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= PRICE_TOLERANCE


def match_pairs(
    category: str,
    news: list[dict[str, Any]],
    olds: list[dict[str, Any]],
    time_ok: Any,
    shops: set[tuple] | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Abbina ogni nuovo al vecchio più vicino di prezzo con la stessa identità.

    ``news``/``olds``: dict con seller_id, variant_key, title, price. Ogni
    vecchio si usa una volta sola. ``time_ok(new, old)`` applica la regola
    temporale del momento (a) o (b). ``shops``: identità (venditore,
    variante) con più pezzi online insieme, mai abbinate. Funzione pura.
    """
    shops = shops or set()
    by_identity: dict[tuple, list[dict[str, Any]]] = {}
    for old in olds:
        key = identity(category, old.get("seller_id"), old.get("variant_key"),
                       model_text(old.get("title"), old.get("description")))
        if key:
            by_identity.setdefault(key, []).append(old)

    claimed: set[Any] = set()
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for new in news:
        key = identity(category, new.get("seller_id"), new.get("variant_key"),
                       model_text(new.get("title"), new.get("description")))
        if not key or key in shops:
            continue
        best = None
        for old in by_identity.get(key, []):
            if old["id"] in claimed or old["id"] == new.get("id"):
                continue
            if not _close_price(new.get("price"), old.get("price")):
                continue
            if not time_ok(new, old):
                continue
            gap = abs(float(new["price"]) - float(old["price"]))
            if best is None or gap < best[0]:
                best = (gap, old)
        if best:
            claimed.add(best[1]["id"])
            pairs.append((new, best[1]))
    return pairs


# ------------------------------------------------------------- (a) revive

def find_revivable(
    db: Any, table: str, category: str, candidates: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(a) Nuovi annunci che sono la ripubblicazione di un record già sparito.
    ``candidates``: {key, seller_id, variant_key, title, price}. Ritorna le
    coppie (candidato, vecchio record)."""
    sellers = sorted({str(c["seller_id"]) for c in candidates if c.get("seller_id")})
    if not sellers:
        return []
    cutoff = (datetime.now(timezone.utc) - REVIVE_WINDOW).isoformat()
    try:
        rows = (
            db.table(table)
            .select("id, seller_id, variant_key, title, description, asking_price, updated_at")
            .in_("seller_id", sellers)
            .in_("status", list(SOLD_STATUSES))
            .gte("updated_at", cutoff)
            .execute()
            .data
            or []
        )
    except Exception:
        logger.exception("Ripubblicazioni (a): lettura dei record spariti fallita")
        return []
    olds = [{**r, "price": r.get("asking_price")} for r in rows]
    # Il candidato non è ancora in DB: se il venditore ha GIÀ un pezzo della
    # stessa variante online, col candidato sono due → negozio.
    try:
        active = (
            db.table(table)
            .select("seller_id, variant_key, title, description")
            .in_("seller_id", sellers)
            .in_("status", ["nuovo", "visto"])
            .execute()
            .data
            or []
        )
    except Exception:
        logger.exception("Ripubblicazioni (a): lettura degli attivi fallita")
        return []
    shops = shop_identities(category, active, min_pieces=1)
    return match_pairs(category, candidates, olds, lambda new, old: True, shops)


# -------------------------------------------------------------- (b) merge

def merge_into_old(
    db: Any,
    table: str,
    category: str,
    missing: list[dict[str, Any]],
    active: list[dict[str, Any]],
) -> list[str]:
    """(b) All'inventario: ``missing`` sono i record attivi in DB ma assenti da
    Subito, ``active`` quelli ancora online. Se un "mancante" ha un gemello
    nato dopo la sua sparizione, è una ripubblicazione: il vecchio record
    prende URL/prezzo del gemello (resta attivo, con la sua data di nascita),
    storico prezzi e pipeline del gemello passano al vecchio, il gemello si
    elimina. Ritorna gli id dei vecchi record fusi (da NON verificare/marcare)."""

    def born(row: dict[str, Any]) -> datetime | None:
        return _parse_ts(row.get("published_at") or row.get("found_at"))

    def time_ok(new: dict[str, Any], old: dict[str, Any]) -> bool:
        new_born, old_seen = born(new), _parse_ts(old.get("updated_at"))
        return bool(new_born and old_seen and new_born >= old_seen - NEW_AFTER_OLD_SEEN)

    news = [{**r, "price": r.get("asking_price")} for r in active]
    olds = [{**r, "price": r.get("asking_price")} for r in missing]
    # Due o più pezzi della stessa variante ancora online = negozio.
    pairs = match_pairs(category, news, olds, time_ok, shop_identities(category, active, 2))

    merged: list[str] = []
    now = datetime.now(timezone.utc).isoformat()
    for twin, old in pairs:
        try:
            # Ordine prudente (ogni passo è una transazione a sé): il gemello
            # libera l'URL (vincolo unique) spostandosi su uno temporaneo, il
            # vecchio lo prende, e solo allora il gemello si cancella. Se un
            # passo fallisce non si perde nessun annuncio.
            db.table(table).update(
                {"listing_url": f"{twin['listing_url']}#ripubblicato-{twin['id']}"}
            ).eq("id", twin["id"]).execute()
            db.table(table).update(
                {
                    "listing_url": twin["listing_url"],
                    "asking_price": twin["asking_price"],
                    "updated_at": now,
                }
            ).eq("id", old["id"]).execute()
            db.table("price_history").update({"listing_id": old["id"]}).eq(
                "listing_id", twin["id"]
            ).execute()
            db.table("deals").update({"listing_id": old["id"]}).eq(
                "listing_id", twin["id"]
            ).execute()
            db.table(table).delete().eq("id", twin["id"]).execute()
            merged.append(old["id"])
        except Exception:
            logger.exception("Fusione ripubblicazione %s ← %s fallita", old["id"], twin["id"])
    if merged:
        logger.info("Inventario %s: %d ripubblicazioni fuse nel record originale", table, len(merged))
    return merged
