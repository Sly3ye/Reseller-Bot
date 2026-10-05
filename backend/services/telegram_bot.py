"""Bot Telegram: registrare l'esito di un affare in due tocchi (Goal Version §1.6).

Il vantaggio che nessuno può copiare sono i propri dati di transazione (a
quanto hai offerto, a quanto hai comprato e venduto, cosa è sfumato). Dalla
dashboard nessuno li registra; dal telefono, sotto l'alert, sì:

- bottoni sotto ogni alert (``notifications.action_keyboard``):
  ⭐ salva · 📞 contattato · 🗑 scarta · 💶 ho offerto… · ✅ comprato a…
  ("offerto"/"comprato" chiedono la cifra: si risponde col numero);
- risposta libera all'alert: "comprato 230", "offerto 250", "venduto 400",
  "sfumato".

Tutto finisce nella pipeline (tabella ``deals``), con la stima del bot
fotografata alla creazione come fa la dashboard. Long polling di getUpdates
(niente webhook: in casa non c'è un indirizzo pubblico). Si accettano comandi
solo dalle chat configurate.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from backend.core.config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
TABLES = {"t": "live_opportunities_tech", "a": "live_opportunities_auto"}
CATEGORIES = {"t": "smartphone", "a": "automobile"}
ACTIONS = {"s", "c", "x", "o", "b"}

# offset di getUpdates e domande in attesa di cifra: {id_domanda: (annuncio, cat, azione)}
_state: dict[str, Any] = {"offset": None, "pending": {}}

_REPLY_RE = re.compile(
    r"(?P<kw>offert[oa]|offro|comprat[oa]|pres[oa]|vendut[oa]|sfumat[oa]|pers[oa])?\D*"
    r"(?P<num>\d+(?:[.,]\d{1,2})?)?",
    re.IGNORECASE,
)
_KW_ACTION = {"offert": "o", "offro": "o", "comprat": "b", "pres": "b", "vendut": "v",
              "sfumat": "f", "pers": "f"}


def parse_callback(data: str | None) -> tuple[str, str, str] | None:
    """"fr:<azione>:<t|a>:<id annuncio>" → (azione, verticale, id) o None."""
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[0] != "fr" or parts[1] not in ACTIONS or parts[2] not in TABLES:
        return None
    return parts[1], parts[2], parts[3]


def parse_reply(text: str | None) -> tuple[str | None, float | None] | None:
    """Risposta scritta → (azione o None, cifra o None). None se non dice nulla
    di utile. "230" → (None, 230); "comprato 230 €" → ("b", 230); "sfumato" → ("f", None)."""
    m = _REPLY_RE.search((text or "").strip())
    if not m or not (m.group("kw") or m.group("num")):
        return None
    action = None
    if m.group("kw"):
        kw = m.group("kw").lower()
        action = next(v for k, v in _KW_ACTION.items() if kw.startswith(k))
    num = float(m.group("num").replace(",", ".")) if m.group("num") else None
    return action, num


def _allowed_chats() -> set[str]:
    from backend.services import settings_store  # noqa: PLC0415

    cfg = settings_store.get_all()
    chats = {cfg.get("telegram_chat_tech"), cfg.get("telegram_chat_auto"), cfg.get("telegram_chat_ops"),
             settings.telegram_chat_tech, settings.telegram_chat_auto, settings.telegram_chat_ops}
    return {str(c) for c in chats if c}


# ------------------------------------------------------------------ pipeline

def _estimate(item: dict[str, Any]) -> dict[str, Any]:
    """La stima del bot fotografata all'aggancio (stessa forma della dashboard)."""
    repair = item.get("repair")
    if repair:
        return {"kind": "riparazione", "marginEur": repair.get("netMarginEur"),
                "repairItems": [{"part": r.get("part"), "source": r.get("source"), "cost": r.get("cost"),
                                 "partCost": r.get("partCost")} for r in repair.get("items") or []],
                "resaleAfterRepair": repair.get("resaleAfterRepair"), "maxBid": item.get("maxBid")}
    margin = item.get("netMarginAfterCostsEur")
    if margin is None and item.get("marketAvg") is not None and item.get("askingPrice") is not None:
        margin = item["marketAvg"] - item["askingPrice"]
    return {"kind": "rivendita", "marginEur": margin, "maxBid": item.get("maxBid"),
            "acquisition": item.get("acquisitionCosts")}


def _ensure_deal(db: Any, cat: str, listing_id: str) -> dict[str, Any] | None:
    rows = (db.table("deals").select("*").eq("listing_id", listing_id)
            .order("created_at", desc=True).limit(1).execute().data or [])
    if rows:
        return rows[0]
    found = db.table(TABLES[cat]).select("*").eq("id", listing_id).limit(1).execute().data or []
    if not found:
        return None
    row = found[0]
    try:
        from backend.services.reads import enrich_for_alerts  # noqa: PLC0415

        item = enrich_for_alerts(CATEGORIES[cat], [row], db)[0]
    except Exception:
        logger.exception("Stima per la pipeline non disponibile")
        item = {}
    created = db.table("deals").insert({
        "listing_id": listing_id, "category": CATEGORIES[cat], "title": row.get("title"),
        "listing_url": row.get("listing_url"), "asking_price": row.get("asking_price"),
        "market_avg": item.get("fairValue") or item.get("marketAvg"),
        "offer_price": item.get("suggestedOffer"), "estimate": _estimate(item) if item else None,
    }).execute().data or []
    return created[0] if created else None


def apply_action(db: Any, cat: str, listing_id: str, action: str, amount: float | None = None) -> str:
    """Esegue l'azione e ritorna la conferma da mostrare."""
    if action in ("s", "x"):
        triage = "salvato" if action == "s" else "scartato"
        db.table(TABLES[cat]).update({"triage": triage}).eq("id", listing_id).execute()
        if action == "x":
            return "🗑 Scartato: non lo vedrai più nel feed"
        _ensure_deal(db, cat, listing_id)
        return "⭐ Salvato e in pipeline (interessante); i ribassi ti arriveranno"
    deal = _ensure_deal(db, cat, listing_id)
    if not deal:
        return "Annuncio non trovato"
    patch: dict[str, Any] = {}
    if action == "c":
        patch["stage"] = "contattato"
    elif action == "o":
        patch = {"stage": "offerta", **({"offer_price": amount} if amount else {})}
    elif action == "b":
        patch = {"stage": "comprato", **({"buy_price": amount} if amount else {})}
    elif action == "v":
        patch = {"stage": "venduto", **({"sell_price": amount} if amount else {})}
    elif action == "f":
        patch["stage"] = "sfumato"
    if not patch:
        return "Niente da registrare"
    db.table("deals").update(patch).eq("id", deal["id"]).execute()
    labels = {"c": "📞 Contattato", "o": "💶 Offerta", "b": "✅ Comprato", "v": "💰 Venduto", "f": "❌ Sfumato"}
    return f"{labels[action]}" + (f" a {amount:,.0f} €".replace(",", ".") if amount else "") + " — in pipeline"


# -------------------------------------------------------------------- polling

async def _api(client: httpx.AsyncClient, method: str, **payload: Any) -> dict[str, Any]:
    r = await client.post(f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/{method}", json=payload)
    return r.json() if r.status_code == 200 else {}


def _listing_from_alert(db: Any, chat_id: str, msg_id: int) -> tuple[str, str] | None:
    rows = (db.table("sent_alerts").select("listing_id, category").eq("chat_id", str(chat_id))
            .eq("telegram_msg_id", msg_id).limit(1).execute().data or [])
    if not rows:
        return None
    return str(rows[0]["listing_id"]), ("a" if rows[0].get("category") == "automobile" else "t")


async def poll_telegram(timeout: int = 25) -> dict[str, int]:
    """Un giro di long polling: gestisce bottoni e risposte agli alert."""
    import asyncio  # noqa: PLC0415

    from backend.core.database import get_db  # noqa: PLC0415

    if not settings.telegram_bot_token:
        return {"handled": 0}
    allowed = _allowed_chats()
    handled = 0
    async with httpx.AsyncClient(timeout=timeout + 10, trust_env=False) as client:
        params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["callback_query", "message"]}
        if _state["offset"] is not None:
            params["offset"] = _state["offset"]
        data = await _api(client, "getUpdates", **params)
        db = get_db()
        for upd in data.get("result") or []:
            _state["offset"] = upd["update_id"] + 1
            try:
                if cq := upd.get("callback_query"):
                    chat = str(((cq.get("message") or {}).get("chat") or {}).get("id"))
                    parsed = parse_callback(cq.get("data"))
                    if chat not in allowed or not parsed:
                        continue
                    action, cat, lid = parsed
                    if action in ("o", "b"):
                        ask = "Quanto hai offerto?" if action == "o" else "A quanto l'hai comprato?"
                        sent = await _api(client, "sendMessage", chat_id=chat,
                                          text=f"{ask} Rispondi a questo messaggio con la cifra.",
                                          reply_to_message_id=(cq.get("message") or {}).get("message_id"),
                                          reply_markup={"force_reply": True, "selective": True})
                        if (sent.get("result") or {}).get("message_id"):
                            _state["pending"][sent["result"]["message_id"]] = (lid, cat, action)
                        await _api(client, "answerCallbackQuery", callback_query_id=cq["id"])
                    else:
                        text = await asyncio.to_thread(apply_action, db, cat, lid, action)
                        await _api(client, "answerCallbackQuery", callback_query_id=cq["id"], text=text)
                    handled += 1
                elif (msg := upd.get("message")) and msg.get("reply_to_message"):
                    chat = str((msg.get("chat") or {}).get("id"))
                    if chat not in allowed:
                        continue
                    parsed = parse_reply(msg.get("text"))
                    if not parsed:
                        continue
                    action, amount = parsed
                    rid = msg["reply_to_message"]["message_id"]
                    if rid in _state["pending"]:
                        lid, cat, pending_action = _state["pending"].pop(rid)
                        action = action or pending_action
                    else:
                        found = await asyncio.to_thread(_listing_from_alert, db, chat, rid)
                        if not found or not action:
                            continue
                        lid, cat = found
                    text = await asyncio.to_thread(apply_action, db, cat, lid, action, amount)
                    await _api(client, "sendMessage", chat_id=chat, text=text,
                               reply_to_message_id=msg.get("message_id"))
                    handled += 1
            except Exception:
                logger.exception("Aggiornamento Telegram non gestito: %s", str(upd)[:200])
    return {"handled": handled}
