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


def _fmt_new_deal(
    row: dict[str, Any],
    category: str,
    market_avg: float,
    margin_eur: float,
    margin_pct: float,
) -> str:
    title = html.escape(str(row.get("title") or "Annuncio"))
    lines = [
        f"🎯 <b>NUOVA OPPORTUNITÀ +{margin_pct:.0f}%</b>",
        f"<b>{title}</b>",
        f"💰 Chiede {_fmt_eur(row.get('asking_price'))} · "
        f"media mercato {_fmt_eur(market_avg)}",
        f"📈 Margine stimato: +{_fmt_eur(margin_eur)} (+{margin_pct:.0f}%)",
    ]

    place = row.get("location")
    seller = row.get("seller_type")
    seller_label = {
        "privato": "privato",
        "finto_privato": "⚠️ finto privato",
        "dealer": "concessionario",
    }.get(str(seller), None)
    info = " · ".join(x for x in (place, seller_label) if x)
    if info:
        lines.append(f"📍 {html.escape(info)}")

    if category == "automobile":
        detail = " · ".join(
            str(x)
            for x in (
                row.get("year"),
                f"{row.get('km'):,} km".replace(",", ".") if row.get("km") else None,
                row.get("transmission"),
                row.get("fuel"),
            )
            if x
        )
        if detail:
            lines.append(f"🚗 {html.escape(detail)}")
    else:
        detail = " · ".join(
            x
            for x in (
                f"{row.get('storage_gb')} GB" if row.get("storage_gb") else None,
                f"🔋 {row.get('battery_pct')}%" if row.get("battery_pct") else None,
            )
            if x
        )
        if detail:
            lines.append(f"📱 {detail}")

    defects = row.get("defects_noted") or []
    if defects:
        lines.append(f"⚠️ Difetti: {html.escape(', '.join(defects))}")
    urgency = row.get("urgency_flags") or []
    if urgency:
        lines.append(f"🔥 Urgenza: {html.escape(', '.join(urgency))} → tratta!")

    lines.append(str(row.get("listing_url") or ""))
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

async def notify_round(
    db: Client,
    category: str,
    new_rows: list[dict[str, Any]],
    drop_events: list[dict[str, Any]],
    market_avg: float | None,
) -> dict[str, int]:
    """Notifica l'esito di un giro sniper per UN target.

    - ``new_rows``: righe appena inserite → alert se margine ≥ soglia.
    - ``drop_events``: cali di prezzo su annunci esistenti → alert se il calo
      ≥ ALERT_MIN_DROP_PCT oppure il nuovo margine ≥ soglia.
    Ritorna {"sent": n, "skipped": m}. No-op se il bot non è configurato.
    """
    chat_id = settings.telegram_chat_for(category)
    if not chat_id:
        return {"sent": 0, "skipped": len(new_rows) + len(drop_events)}

    to_send: list[tuple[str, str, str, str | None]] = []  # (lid, type, text, photo)

    if market_avg is not None:
        for row in new_rows:
            asking = row.get("asking_price")
            if asking is None or float(asking) <= 0:
                continue
            margin_eur = market_avg - float(asking)
            margin_pct = margin_eur / float(asking) * 100
            if margin_pct < settings.alert_min_margin_pct:
                continue
            # Annunci esclusi dall'IQR (rotti/incidentati): il margine contro la
            # media del funzionante è fittizio — niente alert automatico.
            defects = set(row.get("defects_noted") or [])
            if defects & {"incidentata", "fuso", "icloud-bloccato", "per-ricambi"}:
                continue
            images = row.get("image_urls") or []
            to_send.append(
                (
                    str(row["id"]),
                    ALERT_NEW,
                    _fmt_new_deal(row, category, market_avg, margin_eur, margin_pct),
                    images[0] if images else None,
                )
            )

    for event in drop_events:
        old, new = event["old_price"], event["new_price"]
        drop_pct = (old - new) / old * 100 if old else 0
        margin_ok = (
            market_avg is not None
            and new > 0
            and (market_avg - new) / new * 100 >= settings.alert_min_margin_pct
        )
        if drop_pct < settings.alert_min_drop_pct and not margin_ok:
            continue
        to_send.append(
            (
                str(event["listing_id"]),
                ALERT_DROP,
                _fmt_price_drop(event, market_avg),
                None,
            )
        )

    if not to_send:
        return {"sent": 0, "skipped": 0}

    # Dedup persistente prima dell'invio (mai rinotificare lo stesso motivo).
    margin_by_key = {(lid, atype): None for lid, atype, _, _ in to_send}
    claimed = await asyncio.to_thread(
        _claim_alerts,
        db,
        [
            {"listing_id": lid, "alert_type": atype, "category": category}
            for (lid, atype) in margin_by_key
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
        "Telegram (%s): %d notifiche inviate su %d candidate.",
        category,
        sent,
        len(to_send),
    )
    return {"sent": sent, "skipped": len(to_send) - sent}
