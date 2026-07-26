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
from backend.scrapers.nlp_parser import _extract_color

logger = logging.getLogger(__name__)

# Campi comuni ai due verticali: motivo/riparabilità/rischio/sintesi.
_COMMON_FIELDS = """- "motivo_prezzo": stringa breve sul perché il prezzo può essere basso o alto (o "" se non emerge)
- "categoria_motivo": uno tra "legittimo" (vendita urgente, regalo non gradito, upgrade, doppione, cambio operatore...), "difetto" (rotto/problema tecnico), "sospetto" (poco chiaro o possibile truffa), "nessuno"
- "riparabile": true o false (true solo se c'è un difetto sistemabile con profitto: schermo, batteria, vetro posteriore)
- "nota_riparazione": stringa breve su cosa riparare (o "")
- "rischio_truffa": uno tra "basso", "medio", "alto"
- "sintesi": UNA frase in italiano che riassume l'annuncio per chi compra per rivendere"""

# Solo tech: estrazione dei campi strutturati che le regex spesso non colgono
# (spesso finiscono in descrizione, non nel titolo). Ricchiscono la variante.
_TECH_EXTRA = """- "storage_gb": memoria in GB come numero intero tra 64, 128, 256, 512, 1024 se emerge dal testo, altrimenti null (1 TB = 1024)
- "color": colore dell'iPhone in italiano minuscolo (es. mezzanotte, galassia, nero, bianco, blu, rosso, verde, viola, rosa, giallo, grafite, oro, argento, "verde acqua", "titanio naturale", "titanio blu", "titanio nero", "titanio bianco") se emerge, altrimenti null
- "battery_pct": salute/capacità batteria in percentuale (numero intero 1-100) se emerge, altrimenti null"""

_PROMPT_TECH = f"""Sei un esperto di compravendita di iPhone usati su Subito.it.
Analizza questo annuncio e rispondi SOLO con un oggetto JSON valido, senza testo
attorno, con ESATTAMENTE questi campi:
{_COMMON_FIELDS}
{_TECH_EXTRA}

Titolo: {{title}}
Descrizione: {{description}}"""

_PROMPT_AUTO = f"""Sei un esperto di compravendita di auto usate su Subito.it.
Analizza questo annuncio e rispondi SOLO con un oggetto JSON valido, senza testo
attorno, con ESATTAMENTE questi campi:
{_COMMON_FIELDS}

Titolo: {{title}}
Descrizione: {{description}}"""

_VALID_CATEGORIES = {"legittimo", "difetto", "sospetto", "nessuno"}
_VALID_RISK = {"basso", "medio", "alto"}
_VALID_STORAGE = {32, 64, 128, 256, 512, 1024}


def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalizza e valida l'analisi semantica (i 6 campi salvati in ai_analysis)."""
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


def _coerce_int(value: Any) -> int | None:
    """Estrae un intero da valori sporchi ("256GB", "91%", 256.0, None)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        import re

        match = re.search(r"\d+", str(value))
        return int(match.group()) if match else None


def _coerce_fields(raw: dict[str, Any], category: str) -> dict[str, Any]:
    """Solo tech: campi strutturati estratti dall'AI (memoria/colore/batteria),
    validati e canonicalizzati come farebbe l'NLP. {} per gli altri verticali."""
    if category != "smartphone":
        return {}
    storage = _coerce_int(raw.get("storage_gb"))
    if storage == 1:  # il modello a volte scrive "1" per 1 TB
        storage = 1024
    if storage not in _VALID_STORAGE:
        storage = None
    battery = _coerce_int(raw.get("battery_pct"))
    if battery is not None and not (1 <= battery <= 100):
        battery = None
    color_raw = str(raw.get("color") or "").strip().lower()
    color = _extract_color(color_raw) if color_raw and color_raw != "null" else None
    return {"storage_gb": storage, "color": color, "battery_pct": battery}


async def analyze_listing(
    title: str | None, description: str | None, category: str = "smartphone"
) -> dict[str, Any] | None:
    """Analizza titolo+descrizione con Ollama.

    Ritorna ``{"analysis": {...6 campi...}, "fields": {...tech...}}`` oppure None
    se disabilitato/errore/vuoto. ``analysis`` va in ai_analysis; ``fields`` sono
    i campi strutturati (memoria/colore/batteria) da riscrivere sulle colonne.
    """
    if not settings.ai_enabled:
        return None
    desc = (description or "").strip()
    if not desc:
        return None  # senza descrizione l'LLM non aggiunge nulla di affidabile

    template = _PROMPT_AUTO if category == "automobile" else _PROMPT_TECH
    prompt = template.format(title=(title or "").strip(), description=desc[:2000])
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
        return {"analysis": _coerce(raw), "fields": _coerce_fields(raw, category)}
    except Exception as exc:
        logger.warning("Analisi AI fallita (Ollama): %s", str(exc)[:150])
        return None


def _field_writeback(
    row: dict[str, Any], fields: dict[str, Any], title: str | None
) -> dict[str, Any]:
    """Costruisce l'update dei campi strutturati mancanti (solo tech), SENZA mai
    sovrascrivere ciò che le regex hanno già estratto (più precise). Se aggiunge
    la memoria, ri-risolve la variante canonica (granularità per-memoria)."""
    update: dict[str, Any] = {}
    if row.get("storage_gb") is None and fields.get("storage_gb"):
        update["storage_gb"] = fields["storage_gb"]
    if not row.get("color") and fields.get("color"):
        update["color"] = fields["color"]
    if row.get("battery_pct") is None and fields.get("battery_pct"):
        update["battery_pct"] = fields["battery_pct"]

    if "storage_gb" in update:
        from backend.services.variants import resolve_variant  # noqa: PLC0415

        meta = {
            "storage_gb": update["storage_gb"],
            "defects_noted": row.get("defects_noted") or [],
            "features": row.get("features") or [],
        }
        resolved = resolve_variant("smartphone", title, meta)
        update["variant_key"] = resolved["variant_key"]
    return update


async def enrich_missing(limit: int = 30, category: str = "smartphone") -> dict[str, int]:
    """Analizza in blocco gli annunci attivi CON descrizione e SENZA ai_analysis.

    Oltre all'analisi semantica (ai_analysis), per il tech riempie i campi
    strutturati mancanti (memoria/colore/batteria) leggendoli dalla descrizione
    e ri-risolve la variante — così i margini per-memoria diventano più fini.

    Sequenziale (l'LLM è lento e locale): pensato per un giro schedulato che
    consuma il backlog un po' alla volta. No-op se l'AI è disabilitata.
    """
    if not settings.ai_enabled:
        return {"processed": 0, "ok": 0, "fields_filled": 0}

    from backend.core.database import get_db  # noqa: PLC0415 (lazy by design)

    table = (
        "live_opportunities_auto" if category == "automobile" else "live_opportunities_tech"
    )
    db = get_db()
    try:
        rows = (
            db.table(table)
            .select(
                "id, title, description, storage_gb, color, battery_pct, "
                "defects_noted, features, variant_key"
            )
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
        return {"processed": 0, "ok": 0, "fields_filled": 0}

    ok = 0
    fields_filled = 0
    for row in rows:
        result = await analyze_listing(
            row.get("title"), row.get("description"), category
        )
        if result is None:
            continue
        update: dict[str, Any] = {"ai_analysis": result["analysis"]}
        writeback = _field_writeback(row, result.get("fields") or {}, row.get("title"))
        if writeback:
            update.update(writeback)
            fields_filled += 1
        try:
            await asyncio.to_thread(
                lambda r=row, u=update: db.table(table)
                .update(u)
                .eq("id", r["id"])
                .execute()
            )
            ok += 1
        except Exception:
            logger.warning("enrich_missing: update fallito per %s", row.get("id"))
    logger.info(
        "AI enrich (%s): %d/%d analizzati, %d con campi riempiti",
        category, ok, len(rows), fields_filled,
    )
    return {"processed": len(rows), "ok": ok, "fields_filled": fields_filled}
