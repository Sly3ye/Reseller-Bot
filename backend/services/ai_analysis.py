"""Analisi semantica delle descrizioni con un LLM LOCALE (Ollama).

Le regex dell'NLP colgono keyword; un LLM capisce il *contesto*. Qui, per ogni
annuncio, un modello locale (nessun costo per-token, dati in casa) estrae:

- **motivo del prezzo** e la sua natura (legittimo / difetto / sospetto): così
  un prezzo basso ben spiegato ("vendo causa upgrade") NON viene bollato come
  truffa dalla Fase 2, e uno poco chiaro sì.
- **riparabilità**: se il difetto (schermo/batteria/scocca) è sistemabile con
  profitto → l'annuncio è ancora più un affare (potenzia il radar riparazioni).
- **rischio truffa** e una sintesi leggibile.

Tutto fail-safe: se Ollama non è raggiungibile o l'output non è JSON valido,
ritorna None e il resto del sistema continua a funzionare (degrada, non rompe).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from backend.core.config import settings

logger = logging.getLogger(__name__)

_PROMPT = """Sei un esperto di compravendita di iPhone usati su Subito.it.
Analizza questo annuncio e rispondi SOLO con un oggetto JSON valido, senza testo
attorno, con ESATTAMENTE questi campi:
- "motivo_prezzo": stringa breve sul perché il prezzo può essere basso o alto (o "" se non emerge)
- "categoria_motivo": uno tra "legittimo" (vendita urgente, regalo non gradito, upgrade, doppione, cambio operatore...), "difetto" (rotto/problema tecnico), "sospetto" (poco chiaro o possibile truffa), "nessuno"
- "riparabile": true o false (true solo se c'è un difetto sistemabile con profitto: schermo, batteria, vetro posteriore)
- "nota_riparazione": stringa breve su cosa riparare (o "")
- "rischio_truffa": uno tra "basso", "medio", "alto"
- "sintesi": UNA frase in italiano che riassume l'annuncio per chi compra per rivendere

Titolo: {title}
Descrizione: {description}"""

_VALID_CATEGORIES = {"legittimo", "difetto", "sospetto", "nessuno"}
_VALID_RISK = {"basso", "medio", "alto"}


def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalizza e valida l'output del modello (difensivo su tipi/valori)."""
    cat = str(raw.get("categoria_motivo", "nessuno")).strip().lower()
    risk = str(raw.get("rischio_truffa", "basso")).strip().lower()
    repairable = raw.get("riparabile")
    if isinstance(repairable, str):
        repairable = repairable.strip().lower() in ("true", "vero", "si", "sì", "1")
    return {
        "motivo_prezzo": str(raw.get("motivo_prezzo") or "")[:300],
        "categoria_motivo": cat if cat in _VALID_CATEGORIES else "nessuno",
        "riparabile": bool(repairable),
        "nota_riparazione": str(raw.get("nota_riparazione") or "")[:200],
        "rischio_truffa": risk if risk in _VALID_RISK else "basso",
        "sintesi": str(raw.get("sintesi") or "")[:400],
    }


async def analyze_listing(
    title: str | None, description: str | None
) -> dict[str, Any] | None:
    """Analizza titolo+descrizione con Ollama. None se disabilitato/errore/vuoto."""
    if not settings.ai_enabled:
        return None
    desc = (description or "").strip()
    if not desc:
        return None  # senza descrizione l'LLM non aggiunge nulla di affidabile

    prompt = _PROMPT.format(title=(title or "").strip(), description=desc[:2000])
    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            resp = await client.post(
                f"{settings.ollama_url}/api/generate",
                json={
                    "model": settings.ollama_model,
                    "prompt": prompt,
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
            )
            resp.raise_for_status()
            content = resp.json().get("response", "")
        raw = json.loads(content)
        if not isinstance(raw, dict):
            return None
        return _coerce(raw)
    except Exception as exc:
        logger.warning("Analisi AI fallita (Ollama): %s", str(exc)[:150])
        return None


async def enrich_missing(limit: int = 30, category: str = "smartphone") -> dict[str, int]:
    """Analizza in blocco gli annunci attivi CON descrizione e SENZA ai_analysis.

    Sequenziale (l'LLM è lento e locale): pensato per un giro schedulato che
    consuma il backlog un po' alla volta. No-op se l'AI è disabilitata.
    """
    if not settings.ai_enabled:
        return {"processed": 0, "ok": 0}

    from backend.core.database import get_db  # noqa: PLC0415 (lazy by design)

    table = (
        "live_opportunities_auto" if category == "automobile" else "live_opportunities_tech"
    )
    db = get_db()
    try:
        rows = (
            db.table(table)
            .select("id, title, description")
            .in_("status", ["nuovo", "visto"])
            .is_("ai_analysis", "null")
            .not_.is_("description", "null")
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception:
        logger.warning("enrich_missing: query non riuscita")
        return {"processed": 0, "ok": 0}

    ok = 0
    for row in rows:
        analysis = await analyze_listing(row.get("title"), row.get("description"))
        if analysis is None:
            continue
        try:
            await asyncio.to_thread(
                lambda r=row, a=analysis: db.table(table)
                .update({"ai_analysis": a})
                .eq("id", r["id"])
                .execute()
            )
            ok += 1
        except Exception:
            logger.warning("enrich_missing: update fallito per %s", row.get("id"))
    logger.info("AI enrich (%s): %d/%d analizzati", category, ok, len(rows))
    return {"processed": len(rows), "ok": ok}
