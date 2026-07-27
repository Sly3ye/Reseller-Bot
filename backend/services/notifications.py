"""Notifiche Telegram — l'occhio del cecchino sul telefono.

Un affare trovato alle 14:00 e visto in dashboard alle 19:00 è un affare
perso: questo modulo notifica su Telegram, al termine di ogni giro dello
sniper, le opportunità NUOVE con margine sopra soglia e i CALI di prezzo
rilevanti sugli annunci già tracciati.

- Un bot unico, due chat separate (tech / auto) → ognuno riceve solo il suo
  verticale (TELEGRAM_CHAT_ID_TECH / TELEGRAM_CHAT_ID_AUTO in .env).
- Dedup persistente su ``sent_alerts`` (unique listing_id+alert_type): lo
  stesso annuncio non viene mai rinotificato per lo stesso motivo, anche se
  lo sniper lo rivede a ogni giro.
- Config assente → no-op silenzioso: lo sniper funziona anche senza bot.
"""

from __future__ import annotations

import asyncio
import html
import logging
from typing import Any

import httpx
from backend.core.database import Client

from backend.core.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

ALERT_NEW = "new_deal"
ALERT_DROP = "price_drop"


# ---------------------------------------------------------- alert di sistema

async def notify_system_alert(text: str) -> bool:
    """Alert operativo (scraper down/ripristino) alla chat ops (o ai verticali).

    No-op se il bot non è configurato.
    """
    token = settings.telegram_bot_token
    if not token:
        return False
    chat = (
        settings.telegram_chat_ops
        or settings.telegram_chat_tech
        or settings.telegram_chat_auto
    )
    if not chat:
        return False
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        return await _send_telegram(client, chat, text)


# ------------------------------------------------------------------ invio

async def _send_telegram(
    client: httpx.AsyncClient,
    chat_id: str,
    text: str,
    photo_url: str | None = None,
) -> bool:
    """Invia un messaggio (con foto se disponibile). True se accettato."""
    token = settings.telegram_bot_token
    if not token:
        return False
    try:
        if photo_url:
            response = await client.post(
                f"{TELEGRAM_API}/bot{token}/sendPhoto",
                json={
                    "chat_id": chat_id,
                    "photo": photo_url,
                    "caption": text,
                    "parse_mode": "HTML",
                },
            )
        else:
            response = await client.post(
                f"{TELEGRAM_API}/bot{token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
            )
        if response.status_code != 200:
            logger.warning(
                "Telegram ha rifiutato la notifica (%s): %s",
                response.status_code,
                response.text[:200],
            )
            return False
        return True
    except httpx.HTTPError as exc:
        logger.warning("Invio Telegram fallito: %s", exc)
        return False


# ------------------------------------------------------------- formatting

def _fmt_eur(value: float | int | None) -> str:
    if value is None:
        return "—"
    return f"{int(round(value)):,}".replace(",", ".") + " €"


_DEAL_HEAD = {
    "affare": "🎯 <b>AFFARE</b>",
    "in-linea": "✅ <b>In linea</b>",
    "caro": "💸 <b>Caro</b>",
    "sospetto": "⚠️ <b>Sospetto</b>",
}


def _fmt_smart_deal(item: dict[str, Any], category: str) -> str:
    """Messaggio ricco da un'opportunità GIÀ arricchita (valore equo per
    variante, Deal Score, offerta consigliata, radar riparazioni, motivo AI):
    la stessa intelligence della dashboard, dritta sul telefono."""
    title = html.escape(str(item.get("title") or "Annuncio"))
    score = int(round(item.get("score") or 0))
    head = _DEAL_HEAD.get(str(item.get("dealClass")), "🎯 <b>OPPORTUNITÀ</b>")
    lines = [f"{head} · Score {score}/100", f"<b>{title}</b>"]

    asking = item.get("askingPrice")
    fair = item.get("fairValue")
    if fair:
        m_eur = item.get("marginVsFairEur")
        m_pct = item.get("marginVsFairPct")
        extra = ""
        if m_eur is not None and m_pct is not None:
            sign = "+" if m_eur >= 0 else ""
            extra = f" ({sign}{_fmt_eur(m_eur)} / {sign}{m_pct:.0f}%)"
        lines.append(f"💰 Chiede {_fmt_eur(asking)} · valore equo {_fmt_eur(fair)}{extra}")
    else:
        lines.append(f"💰 Chiede {_fmt_eur(asking)}")

    offer = item.get("suggestedOffer")
    if offer:
        lines.append(f"🤝 Offerta consigliata: {_fmt_eur(offer)}")

    if category == "automobile":
        detail = " · ".join(
            str(x)
            for x in (
                item.get("year"),
                f"{item.get('km'):,} km".replace(",", ".") if item.get("km") else None,
                item.get("transmission"),
                item.get("fuel"),
            )
            if x
        )
        if detail:
            lines.append(f"🚗 {html.escape(detail)}")
    else:
        detail = " · ".join(
            x
            for x in (
                f"{item.get('storageGb')} GB" if item.get("storageGb") else None,
                f"🔋 {item.get('batteryPct')}%" if item.get("batteryPct") else None,
                html.escape(str(item.get("color"))) if item.get("color") else None,
            )
            if x
        )
        if detail:
            lines.append(f"📱 {detail}")

    place = item.get("location")
    seller = item.get("sellerType")
    seller_label = {
        "privato": "privato",
        "finto_privato": "⚠️ finto privato",
        "dealer": "concessionario",
    }.get(str(seller), None)
    info = " · ".join(x for x in (place, seller_label) if x)
    if info:
        lines.append(f"📍 {html.escape(info)}")

    ai = item.get("ai") or {}
    motivo = ai.get("motivo_prezzo")
    if motivo and ai.get("categoria_motivo") not in (None, "nessuno"):
        lines.append(f"🤖 {html.escape(str(motivo))}")
    if ai.get("riparabile"):
        nota = ai.get("nota_riparazione")
        lines.append("🔧 Riparabile" + (f": {html.escape(str(nota))}" if nota else ""))

    repair = item.get("repair") or {}
    if repair.get("netMarginEur") is not None:
        lines.append(f"🛠️ Margine post-riparazione: {_fmt_eur(repair['netMarginEur'])}")

    defects = item.get("defects") or []
    if defects:
        lines.append(f"⚠️ Difetti: {html.escape(', '.join(map(str, defects)))}")
    urgency = item.get("urgencyFlags") or []
    if urgency:
        lines.append(f"🔥 Urgenza: {html.escape(', '.join(map(str, urgency)))} → tratta!")

    lines.append(str(item.get("url") or ""))
    return "\n".join(lines)


def _fmt_price_drop(event: dict[str, Any], market_avg: float | None) -> str:
    title = html.escape(str(event.get("title") or "Annuncio"))
    old = event["old_price"]
    new = event["new_price"]
    drop_pct = (old - new) / old * 100 if old else 0
    lines = [
        f"📉 <b>CALO DI PREZZO −{drop_pct:.0f}%</b>",
        f"<b>{title}</b>",
        f"💰 {_fmt_eur(old)} → <b>{_fmt_eur(new)}</b>"
        + (f" · media {_fmt_eur(market_avg)}" if market_avg else ""),
        "Il venditore sta scendendo: momento buono per trattare.",
        str(event.get("listing_url") or ""),
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- dedup DB

def _claim_alerts(
    db: Client, candidates: list[dict[str, Any]]
) -> set[tuple[str, str]]:
    """Registra i candidati in sent_alerts e ritorna le chiavi VINTE.

    Upsert con ignore_duplicates: PostgREST ritorna solo le righe realmente
    inserite → quelle già notificate in passato spariscono dal set. Se la
    tabella sent_alerts non esiste ancora (migrazione 13 non applicata),
    ritorna tutte le chiavi: meglio un doppione che nessuna notifica.
    """
    if not candidates:
        return set()
    try:
        inserted = (
            db.table("sent_alerts")
            .upsert(
                candidates,
                on_conflict="listing_id,alert_type",
                ignore_duplicates=True,
            )
            .execute()
        )
        return {
            (row["listing_id"], row["alert_type"]) for row in inserted.data or []
        }
    except Exception:
        logger.warning(
            "sent_alerts non disponibile: dedup notifiche disattivata "
            "(applica la migrazione 13)."
        )
        return {(c["listing_id"], c["alert_type"]) for c in candidates}


# ------------------------------------------------------------------ hook

async def notify_deals(
    db: Client,
    category: str,
    deal_items: list[dict[str, Any]],
    drop_events: list[dict[str, Any]],
) -> dict[str, int]:
    """Notifica gli affari di un giro sniper, con l'intelligence completa.

    - ``deal_items``: opportunità GIÀ arricchite e filtrate dal chiamante
      (classe "affare" + Deal Score sopra soglia). Il messaggio riporta valore
      equo, offerta consigliata, score, radar riparazioni e motivo AI — così si
      notifica solo ciò che la BI considera un vero affare, non il margine
      grezzo contro una media (meno falsi positivi).
    - ``drop_events``: cali di prezzo su annunci già tracciati → alert se il
      calo ≥ ALERT_MIN_DROP_PCT.
    Dedup persistente su ``sent_alerts``. No-op se il bot non è configurato.
    """
    from backend.services import settings_store  # lazy: evita import circolare

    cfg = settings_store.get_all()
    chat_id = settings.telegram_chat_for(category)
    # Override chat da Impostazioni UI (solo se il bot ha un token configurato).
    key = "telegram_chat_auto" if category == "automobile" else "telegram_chat_tech"
    if cfg.get(key) and settings.telegram_bot_token:
        chat_id = cfg[key]
    if not chat_id:
        return {"sent": 0, "skipped": len(deal_items) + len(drop_events)}

    to_send: list[tuple[str, str, str, str | None]] = []  # (lid, type, text, photo)

    for item in deal_items:
        lid = item.get("id")
        if not lid:
            continue
        images = item.get("images") or []
        to_send.append(
            (
                str(lid),
                ALERT_NEW,
                _fmt_smart_deal(item, category),
                images[0] if images else None,
            )
        )

    for event in drop_events:
        old, new = event.get("old_price"), event.get("new_price")
        drop_pct = (old - new) / old * 100 if old else 0
        if drop_pct < cfg["alert_min_drop_pct"]:
            continue
        to_send.append(
            (
                str(event["listing_id"]),
                ALERT_DROP,
                _fmt_price_drop(event, None),
                None,
            )
        )

    if not to_send:
        return {"sent": 0, "skipped": 0}

    # Dedup persistente prima dell'invio (mai rinotificare lo stesso motivo).
    keys = {(lid, atype) for lid, atype, _, _ in to_send}
    claimed = await asyncio.to_thread(
        _claim_alerts,
        db,
        [
            {"listing_id": lid, "alert_type": atype, "category": category}
            for (lid, atype) in keys
        ],
    )

    sent = 0
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        for lid, atype, text, photo in to_send:
            if (lid, atype) not in claimed:
                continue
            if await _send_telegram(client, chat_id, text, photo):
                sent += 1

    logger.info(
        "Telegram (%s): %d affari notificati su %d candidati.",
        category,
        sent,
        len(to_send),
    )
    return {"sent": sent, "skipped": len(to_send) - sent}
