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
# Opportunità di riparazione: rotto che, riparato, rende sopra soglia.
ALERT_REPAIR = "repair_deal"
# Calo su un annuncio SALVATO (⭐). Il tipo include il nuovo prezzo: il vincolo
# di unicità è (listing_id, alert_type), quindi ogni ribasso successivo è una
# chiave diversa e ti arriva. Sui salvati vuoi seguire tutta la discesa, non
# solo il primo gradino.
ALERT_SAVED_DROP = "saved_drop"


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
        return await _send_telegram(client, chat, text) is not None


# ------------------------------------------------------------------ invio

# Telegram accetta didascalie di foto fino a 1.024 caratteri: oltre, rifiuta
# l'intero messaggio. I nostri alert ricchi possono superarla.
CAPTION_MAX = 1024


def _public_photo(item: dict[str, Any]) -> str | None:
    """Una foto che i server di Telegram possano scaricare: il link pubblico
    del CDN di Subito. Le nostre copie su disco hanno URL locali
    (``localhost``/LAN) irraggiungibili da Telegram: passarle faceva rifiutare
    TUTTO l'alert (bug fino al 2026-10-05)."""
    for url in [*(item.get("remoteImages") or []), *(item.get("images") or [])]:
        u = str(url)
        if u.startswith("https://") and not any(h in u for h in ("localhost", "127.0.0.1", "192.168.")):
            return u
    return None


async def _send_telegram(
    client: httpx.AsyncClient,
    chat_id: str,
    text: str,
    photo_url: str | None = None,
    reply_markup: dict[str, Any] | None = None,
) -> int | None:
    """Invia un messaggio (con foto se possibile). Ritorna l'id del messaggio
    o None se Telegram lo ha rifiutato. Se la foto non va (URL non
    scaricabile, didascalia troppo lunga) ripiega sul solo testo: un alert
    senza foto vale infinitamente più di un alert perso."""
    token = settings.telegram_bot_token
    if not token:
        return None
    extra = {"reply_markup": reply_markup} if reply_markup else {}
    try:
        if photo_url and len(text) <= CAPTION_MAX:
            response = await client.post(
                f"{TELEGRAM_API}/bot{token}/sendPhoto",
                json={"chat_id": chat_id, "photo": photo_url, "caption": text,
                      "parse_mode": "HTML", **extra},
            )
            if response.status_code == 200:
                return (response.json().get("result") or {}).get("message_id")
            logger.warning("Telegram ha rifiutato la foto (%s), invio solo testo: %s",
                           response.status_code, response.text[:160])
        response = await client.post(
            f"{TELEGRAM_API}/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": False, **extra},
        )
        if response.status_code != 200:
            logger.warning(
                "Telegram ha rifiutato la notifica (%s): %s",
                response.status_code,
                response.text[:200],
            )
            return None
        return (response.json().get("result") or {}).get("message_id")
    except httpx.HTTPError as exc:
        logger.warning("Invio Telegram fallito: %s", exc)
        return None


def chat_for(category: str) -> str | None:
    """Chat effettiva per categoria ("smartphone", "automobile", "ops"):
    Impostazioni UI se c'è il token, altrimenti il .env."""
    from backend.services import settings_store  # noqa: PLC0415

    if not settings.telegram_bot_token:
        return None
    key = {"automobile": "telegram_chat_auto", "ops": "telegram_chat_ops"}.get(category, "telegram_chat_tech")
    fallback = settings.telegram_chat_ops if category == "ops" else settings.telegram_chat_for(category)
    return settings_store.get_all().get(key) or fallback


async def send_test_alert(category: str) -> dict[str, Any]:
    """Alert di prova per verificare token, chat e bottoni in un clic.

    iPhone/auto: il primo affare del feed, formattato come un alert vero (foto
    dal CDN, offerta da copiare, bottoni funzionanti su quell'annuncio).
    Sistema: un messaggio semplice. Ritorna l'esito con la descrizione esatta
    di Telegram in caso di rifiuto (mai il token).
    """
    token = settings.telegram_bot_token
    if not token:
        return {"ok": False, "detail": "TELEGRAM_BOT_TOKEN mancante in backend/.env (poi riavvia backend e collector)"}
    chat = chat_for(category)
    if not chat:
        return {"ok": False, "detail": "Nessuna chat impostata per questa categoria: scrivi l'ID e salva"}
    text = "🧪 <b>Prova FlipRadar</b>: il bot raggiunge questa chat."
    photo: str | None = None
    keyboard: dict[str, Any] | None = None
    if category in ("smartphone", "automobile"):
        from backend.services.reads import list_opportunities  # noqa: PLC0415

        try:
            items = (await asyncio.to_thread(list_opportunities, category, sort="score", limit=1))["items"]
        except Exception:
            logger.exception("Alert di prova: feed non disponibile")
            items = []
        if items:
            item = items[0]
            text = ("🧪 <b>PROVA</b>: così arriveranno gli alert (i bottoni agiscono davvero su "
                    "questo annuncio)\n\n" + _fmt_smart_deal(item, category))
            photo, keyboard = _public_photo(item), action_keyboard(str(item["id"]), category)
    extra = {"reply_markup": keyboard} if keyboard else {}
    try:
        async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
            if photo and len(text) <= CAPTION_MAX:
                r = await client.post(f"{TELEGRAM_API}/bot{token}/sendPhoto",
                                      json={"chat_id": chat, "photo": photo, "caption": text,
                                            "parse_mode": "HTML", **extra})
                if r.status_code == 200:
                    return {"ok": True, "detail": "Arrivato, con foto e bottoni"}
            r = await client.post(f"{TELEGRAM_API}/bot{token}/sendMessage",
                                  json={"chat_id": chat, "text": text, "parse_mode": "HTML", **extra})
    except httpx.HTTPError:
        # Il messaggio dell'eccezione contiene l'URL col token: mai restituirlo.
        return {"ok": False, "detail": "api.telegram.org non raggiungibile da questo computer"}
    if r.status_code == 200:
        return {"ok": True, "detail": "Arrivato" + (" (senza foto)" if photo else "")}
    try:
        description = r.json().get("description")
    except ValueError:
        description = None
    return {"ok": False, "detail": f"Telegram ha rifiutato: {description or 'HTTP ' + str(r.status_code)}"}


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


def offer_message(item: dict[str, Any], category: str, repair: bool = False) -> str | None:
    """Primo messaggio al venditore, da toccare e copiare (Goal Version §3.5):
    la gara si vince al primo messaggio credibile, non alla notifica.

    Cifra = offerta consigliata (come nella riga sopra), altrimenti il 90% del
    tetto; arrotondata a 5 € (iPhone) o 100 € (auto), mai sopra il prezzo chiesto.
    """
    asking = item.get("askingPrice")
    amount = item.get("suggestedOffer")
    if not amount and item.get("maxBid"):
        amount = item["maxBid"] * 0.9
    if not amount:
        return None
    step = 100 if category == "automobile" else 5
    amount = int(round(amount / step) * step)
    if amount <= 0:
        return None
    at_asking = bool(asking) and amount >= asking
    eur = f"{amount:,}".replace(",", ".") + " €"
    if category == "automobile":
        price = "il prezzo richiesto mi va bene" if at_asking else f"offrirei {eur}"
        return ("Buongiorno, l'auto è ancora disponibile? Posso venire a vederla a breve: "
                f"se è come descritta {price}.")
    how = "anche così com'è" if repair else "subito"
    price = "al prezzo indicato" if at_asking else f"a {eur}"
    return f"Ciao! È ancora disponibile? Lo prendo {how} {price} e passo a ritirarlo anche oggi."


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
        # Il numero che conta per un flip: margine netto dopo passaggio e costi.
        net = item.get("netMarginAfterCostsEur")
        costs = (item.get("acquisitionCosts") or {}).get("total")
        if net is not None:
            lines.append(f"✅ <b>Margine netto {_fmt_eur(net)}</b> (passaggio e costi {_fmt_eur(costs)})"
                         + (f" · tetto {_fmt_eur(item.get('maxBid'))}" if item.get("maxBid") else ""))
        model = item.get("carModel") or {}
        if model.get("errPct") is not None:
            lines.append(f"📊 Stima da {model.get('n')} auto simili, errore tipico ±{model['errPct']}%")
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
    # "concessionario" ha senso solo per le auto; per il tech è un "negozio".
    dealer_label = "concessionario" if category == "automobile" else "negozio"
    seller_label = {
        "privato": "privato",
        "finto_privato": "⚠️ finto privato",
        "dealer": dealer_label,
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

    message = offer_message(item, category)
    if message:
        lines.append(f"✉️ <code>{html.escape(message)}</code>")
    lines.append(str(item.get("url") or ""))
    return "\n".join(lines)


def _fmt_repair_deal(item: dict[str, Any]) -> str:
    """Rotto da riparare: i conti del business, non il margine da "sano"."""
    title = html.escape(str(item.get("title") or "Annuncio"))
    repair = item.get("repair") or {}
    lines = ["🔧 <b>DA RIPARARE</b>", f"<b>{title}</b>",
             f"💰 Chiede {_fmt_eur(item.get('askingPrice'))}"
             + (f" · tetto d'acquisto {_fmt_eur(item.get('maxBid'))}" if item.get("maxBid") else "")]
    for part in repair.get("items") or []:
        cols = []
        if part.get("aftermarket"):
            cols.append(f"aftermarket {_fmt_eur(part['aftermarket']['price'])} ({part['aftermarket']['grade']})")
        if part.get("apple"):
            cols.append(f"Apple {_fmt_eur(part['apple']['net'])}")
        used = "Apple" if part.get("source") == "apple" else "aftermarket"
        lines.append(f"🛠️ {html.escape(str(part.get('label')))}: {' · '.join(cols)} → conti con {used}")
    if repair.get("resaleAfterRepair"):
        factor = repair.get("resaleFactor") or 1
        note = f" (−{round((1 - factor) * 100)}% per ricambi non originali)" if factor < 1 else ""
        lines.append(f"📈 Rivendita riparato ≈ {_fmt_eur(repair['resaleAfterRepair'])}{note}")
    lines.append(f"✅ <b>Margine netto {_fmt_eur(repair.get('netMarginEur'))}</b>"
                 + (f" ({repair['netMarginPct']:.0f}%)" if repair.get("netMarginPct") is not None else ""))
    other = [d for d in (item.get("defects") or [])
             if d not in {p.get("defect") for p in repair.get("items") or []} and d != "graffi"]
    if other:
        lines.append(f"⚠️ Altri difetti dichiarati: {html.escape(', '.join(map(str, other)))}")
    risk = item.get("risk") or {}
    if risk.get("level") == "medio":
        lines.append(f"⚠️ {html.escape('; '.join(risk.get('reasons') or []))}")
    place = item.get("location")
    if place:
        lines.append(f"📍 {html.escape(str(place))}")
    message = offer_message(item, "smartphone", repair=True)
    if message:
        lines.append(f"✉️ <code>{html.escape(message)}</code>")
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


def _fmt_saved_drop(event: dict[str, Any]) -> str:
    """Ribasso su un annuncio che hai messo tra i salvati: sempre notificato."""
    title = html.escape(str(event.get("title") or "Annuncio"))
    old = event["old_price"]
    new = event["new_price"]
    drop_pct = (old - new) / old * 100 if old else 0
    return "\n".join(
        [
            f"⭐ <b>UN TUO SALVATO È CALATO −{drop_pct:.0f}%</b>",
            f"<b>{title}</b>",
            f"💰 {_fmt_eur(old)} → <b>{_fmt_eur(new)}</b>",
            "Lo stavi seguendo: il venditore si sta muovendo.",
            str(event.get("listing_url") or ""),
        ]
    )


def _saved_listing_ids(db: Client, table: str, ids: list[str]) -> set[str]:
    """Quali fra questi annunci sono marcati ⭐ salvato (triage)."""
    if not ids:
        return set()
    try:
        rows = (
            db.table(table)
            .select("id")
            .in_("id", ids)
            .eq("triage", "salvato")
            .execute()
            .data
            or []
        )
    except Exception:
        logger.warning("triage non leggibile: alert sui salvati saltati.")
        return set()
    return {str(r["id"]) for r in rows}


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


def action_keyboard(listing_id: str, category: str) -> dict[str, Any]:
    """Bottoni sotto l'alert: registrare l'esito costa due tocchi, quindi si
    fa davvero (Goal Version §1.6). Il callback lo gestisce
    services/telegram_bot.py; ``t``/``a`` = verticale."""
    cat = "a" if category == "automobile" else "t"
    def btn(label: str, action: str) -> dict[str, str]:
        return {"text": label, "callback_data": f"fr:{action}:{cat}:{listing_id}"}
    return {"inline_keyboard": [
        [btn("⭐ Salva", "s"), btn("📞 Contattato", "c"), btn("🗑 Scarta", "x")],
        [btn("💶 Ho offerto…", "o"), btn("✅ Comprato a…", "b")],
    ]}


def _mark_delivery(db: Client, rows: list[dict[str, Any]]) -> None:
    """Esito reale di ogni invio in sent_alerts (migrazione 25): consegnato o
    no, id del messaggio per bottoni e risposte. Senza colonne: niente."""
    for r in rows:
        try:
            db.table("sent_alerts").update({
                "delivered": r["delivered"], "telegram_msg_id": r.get("msg_id"), "chat_id": r["chat_id"],
            }).eq("listing_id", r["listing_id"]).eq("alert_type", r["alert_type"]).execute()
        except Exception:
            logger.debug("sent_alerts senza colonne di consegna (migrazione 25)", exc_info=True)
            return


# ------------------------------------------------------------------ hook

async def notify_deals(
    db: Client,
    category: str,
    deal_items: list[dict[str, Any]],
    drop_events: list[dict[str, Any]],
    repair_items: list[dict[str, Any]] | None = None,
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
        # Senza Telegram i candidati si registrano comunque (delivered resta
        # NULL = mai tentato): servono al ricontrollo, che misura quanto dura
        # un affare (services/deal_watch.py), e alla galleria completa delle auto.
        recorded = [
            {"listing_id": str(it["id"]), "alert_type": atype, "category": category}
            for atype, items in ((ALERT_NEW, deal_items), (ALERT_REPAIR, repair_items or []))
            for it in items if it.get("id")
        ]
        if recorded:
            await asyncio.to_thread(_claim_alerts, db, recorded)
        return {"sent": 0, "recorded": len(recorded),
                "skipped": len(deal_items) + len(drop_events) + len(repair_items or [])}

    # (lid, tipo, testo, foto pubblica, bottoni)
    to_send: list[tuple[str, str, str, str | None, dict[str, Any] | None]] = []

    for item in deal_items:
        lid = item.get("id")
        if not lid:
            continue
        to_send.append((str(lid), ALERT_NEW, _fmt_smart_deal(item, category),
                        _public_photo(item), action_keyboard(str(lid), category)))

    for item in repair_items or []:
        lid = item.get("id")
        if not lid:
            continue
        to_send.append((str(lid), ALERT_REPAIR, _fmt_repair_deal(item),
                        _public_photo(item), action_keyboard(str(lid), category)))

    # Annunci ⭐ salvati fra quelli che hanno cambiato prezzo: su questi il calo
    # si notifica SEMPRE, anche sotto la soglia minima — li stai seguendo apposta.
    from backend.services.reads import _opportunities_table  # lazy: import circolare

    saved = await asyncio.to_thread(
        _saved_listing_ids,
        db,
        _opportunities_table(category),
        [str(e["listing_id"]) for e in drop_events if e.get("listing_id")],
    )

    for event in drop_events:
        old, new = event.get("old_price"), event.get("new_price")
        drop_pct = (old - new) / old * 100 if old else 0
        listing_id = str(event["listing_id"])
        if listing_id in saved:
            to_send.append(
                (
                    listing_id,
                    # Il nuovo prezzo nella chiave: ogni ribasso è un alert.
                    f"{ALERT_SAVED_DROP}:{new}",
                    _fmt_saved_drop(event),
                    None,
                    None,
                )
            )
            continue
        if category == "automobile":
            continue  # auto: ribassi solo sulle ⭐ salvate (mezzo milione di annunci = spam)
        if drop_pct < cfg["alert_min_drop_pct"]:
            continue
        to_send.append(
            (
                listing_id,
                ALERT_DROP,
                _fmt_price_drop(event, None),
                None,
                None,
            )
        )

    if not to_send:
        return {"sent": 0, "skipped": 0}

    # Dedup persistente prima dell'invio (mai rinotificare lo stesso motivo).
    keys = {(lid, atype) for lid, atype, _, _, _ in to_send}
    claimed = await asyncio.to_thread(
        _claim_alerts,
        db,
        [
            {"listing_id": lid, "alert_type": atype, "category": category}
            for (lid, atype) in keys
        ],
    )

    sent = 0
    outcome: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        for lid, atype, text, photo, keyboard in to_send:
            if (lid, atype) not in claimed:
                continue
            msg_id = await _send_telegram(client, chat_id, text, photo, keyboard)
            outcome.append({"listing_id": lid, "alert_type": atype, "chat_id": str(chat_id),
                            "delivered": msg_id is not None, "msg_id": msg_id})
            if msg_id is not None:
                sent += 1
    await asyncio.to_thread(_mark_delivery, db, outcome)
    if len(outcome) > sent:
        logger.error("Telegram (%s): %d alert NON consegnati su %d", category, len(outcome) - sent, len(outcome))

    logger.info(
        "Telegram (%s): %d affari notificati su %d candidati.",
        category,
        sent,
        len(to_send),
    )
    return {"sent": sent, "skipped": len(to_send) - sent}
