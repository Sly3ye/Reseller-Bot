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
import time
from typing import Any

import httpx

from backend.core.config import settings
from backend.scrapers.nlp_parser import _extract_color
from backend.services.defects import GUASTO_CLASSE, PROMPT_V2, coerce_ai_v2, merge_ai_defects

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

# Versione dell'analisi tech. v3 = guasti per tipo (tassonomia di
# services/defects.py, B3/B4) + i campi di prima, in UNA chiamata. Le righe con
# una versione più vecchia tornano in coda (dopo quelle mai analizzate).
AI_VERSION = 3

# Tech: il prompt dei guasti misurato con scripts/eval_guasti.py, più i campi
# che servono a feed e valutazione. Lo stesso testo lo usa il banco di prova.
# "riparabile" e "nota_riparazione" non li scrive il modello: si ricavano dai
# guasti (coerce_analysis). Ogni token in uscita costa ~0,08 s sul Mac.
_TECH_V3_EXTRA = """- "categoria_motivo": uno tra "legittimo" (vendita urgente, regalo non gradito, upgrade, doppione, cambio operatore...), "difetto" (rotto/problema tecnico), "sospetto" (poco chiaro o possibile truffa), "nessuno"
- "sintesi": UNA frase in italiano di massimo 15 parole per chi compra per rivendere
""" + _TECH_EXTRA

PROMPT_TECH = PROMPT_V2.replace("\n\nATTENZIONE", "\n" + _TECH_V3_EXTRA + "\n\nATTENZIONE", 1)
assert PROMPT_TECH != PROMPT_V2, "PROMPT_V2 cambiato: aggiorna l'innesto dei campi tech"

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

    template = _PROMPT_AUTO if category == "automobile" else PROMPT_TECH
    prompt = template.format(title=(title or "").strip(), description=desc[:2000])
    try:
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            resp = await client.post(
                f"{settings.ollama_url}/api/generate", json=ollama_payload(prompt)
            )
            resp.raise_for_status()
            content = resp.json().get("response", "")
        raw = json.loads(content)
        if not isinstance(raw, dict):
            return None
        return {"analysis": coerce_analysis(raw, category), "fields": _coerce_fields(raw, category)}
    except Exception as exc:
        logger.warning("Analisi AI fallita (Ollama): %s", str(exc)[:150])
        return None


def ollama_payload(prompt: str, model: str | None = None) -> dict[str, Any]:
    """Richiesta a Ollama: JSON, deterministica, senza "ragionamento" (i modelli
    che pensano diventano 5-10 volte più lenti senza leggere meglio un annuncio),
    contesto ridotto per la memoria del Mac. Usata anche dal banco di prova."""
    return {
        "model": model or settings.ollama_model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "think": False,
        "keep_alive": "15m",
        "options": {"temperature": 0, "num_ctx": settings.ollama_num_ctx},
    }


def coerce_analysis(raw: dict[str, Any], category: str = "smartphone") -> dict[str, Any]:
    """ai_analysis da salvare: i 6 campi di sempre e, per il tech, i guasti per
    tipo (v3) validati sulla tassonomia."""
    analysis = _coerce(raw)
    if category == "automobile":
        return analysis
    v2 = coerce_ai_v2(raw)
    analysis.update({k: v2[k] for k in ("guasti", "parti_non_originali", "segni_estetici", "per_ricambi")})
    fixable = [g for g in v2["guasti"] if GUASTO_CLASSE.get(g) == "riparabile"]
    analysis["riparabile"] = bool(fixable) and not v2["per_ricambi"]
    analysis["nota_riparazione"] = ", ".join(fixable)
    analysis["v"] = AI_VERSION
    return analysis


def _field_writeback(
    row: dict[str, Any], fields: dict[str, Any], title: str | None,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Costruisce l'update dei campi strutturati mancanti (solo tech), SENZA mai
    sovrascrivere ciò che le regex hanno già estratto (più precise): memoria,
    colore, batteria, e i guasti dell'AI AGGIUNTI a quelli delle regex. Se
    cambia la memoria o i guasti, ri-risolve variante e condizione."""
    update: dict[str, Any] = {}
    if analysis:
        defects, features = merge_ai_defects(row.get("defects_noted"), row.get("features"), analysis)
        if defects != list(row.get("defects_noted") or []):
            update["defects_noted"] = defects
        if features != list(row.get("features") or []):
            update["features"] = features
    if row.get("storage_gb") is None and fields.get("storage_gb"):
        update["storage_gb"] = fields["storage_gb"]
    if not row.get("color") and fields.get("color"):
        update["color"] = fields["color"]
    if row.get("battery_pct") is None and fields.get("battery_pct"):
        update["battery_pct"] = fields["battery_pct"]

    if update.keys() & {"storage_gb", "defects_noted", "features"}:
        from backend.services.variants import resolve_variant  # noqa: PLC0415

        meta = {
            "storage_gb": update.get("storage_gb", row.get("storage_gb")),
            "defects_noted": update.get("defects_noted", row.get("defects_noted") or []),
            "features": update.get("features", row.get("features") or []),
        }
        resolved = resolve_variant("smartphone", title, meta, description=row.get("description"))
        if resolved["variant_key"] != row.get("variant_key"):
            update["variant_key"] = resolved["variant_key"]
        if resolved["condition_tier"] != row.get("condition_tier"):
            update["condition_tier"] = resolved["condition_tier"]
    return update


# Sotto questa quota della mediana del modello un annuncio è o un affare o un
# guasto non dichiarato: è lì che leggere la descrizione cambia la decisione.
AI_CHEAP_RATIO = 0.8


def ai_queue(table: str, limit: int) -> list[dict[str, Any]]:
    """Annunci da analizzare, in ordine di utilità (Goal Version §4.7):
    1. candidati: segnalati come affare, salvati, in pipeline;
    2. prezzo sotto l'80% della mediana del modello: affare vero o guasto non
       dichiarato (le regole riconoscono solo il 48% dei guasti, verifica del 5/10);
    3. modello non riconosciuto (o raro): l'AI lo legge dalla descrizione;
    4. il resto. A parità, i più recenti. Prima l'ordine era casuale su ~49.000
    attivi: un affare poteva aspettare giorni l'analisi.
    Le righe analizzate con una versione vecchia del prompt (senza guasti per
    tipo) tornano in coda, dopo tutte quelle mai analizzate."""
    from backend.core.database import _get_pool  # noqa: PLC0415

    with _get_pool().connection() as conn:
        rows = conn.execute(
            f"""
            with med as (
              select variant_key, percentile_cont(0.5) within group (order by asking_price) as m
              from public.{table}
              where status in ('nuovo', 'visto') and asking_price > 0
              group by variant_key having count(*) >= 6
            )
            select t.id, t.title, t.description, t.storage_gb, t.color, t.battery_pct,
                   t.defects_noted, t.features, t.variant_key, t.condition_tier
            from public.{table} t
            left join med on med.variant_key = t.variant_key
            where t.status in ('nuovo', 'visto') and t.description is not null
              and (t.ai_analysis is null or coalesce(t.ai_analysis->>'v', '') <> %s)
            order by t.ai_analysis is not null,
                     case
                       when t.triage = 'salvato'
                            or exists (select 1 from public.sent_alerts s where s.listing_id = t.id)
                            or exists (select 1 from public.deals d where d.listing_id = t.id) then 0
                       when t.asking_price < %s * med.m then 1
                       when med.m is null then 2
                       else 3
                     end,
                     t.found_at desc
            limit %s
            """,
            (str(AI_VERSION), AI_CHEAP_RATIO, limit),
        ).fetchall()
    return [dict(r) for r in rows]


async def enrich_missing(
    limit: int = 30, category: str = "smartphone", run_seconds: float | None = None
) -> dict[str, int]:
    """Analizza gli annunci attivi CON descrizione e senza analisi aggiornata.

    Oltre all'analisi semantica (ai_analysis), per il tech aggiunge i guasti
    letti dall'AI a quelli delle regex (condizione ricalcolata) e riempie i
    campi strutturati mancanti (memoria/colore/batteria), ri-risolvendo la
    variante.

    Sequenziale (l'LLM è locale): lotti da ``limit`` uno dopo l'altro finché
    restano annunci in coda e c'è tempo (``run_seconds``, default
    AI_RUN_SECONDS), con AI_PAUSE_S di respiro tra due annunci. Si ferma dopo 3
    errori di fila (Ollama spento o modello assente): riprova al giro dopo.
    No-op se l'AI è disabilitata.
    """
    empty = {"processed": 0, "ok": 0, "fields_filled": 0}
    if not settings.ai_enabled or category == "automobile":   # le auto non hanno ai_analysis
        return empty

    from backend.core.database import get_db  # noqa: PLC0415 (lazy by design)

    table = "live_opportunities_tech"
    db = get_db()
    budget = settings.ai_run_seconds if run_seconds is None else run_seconds
    deadline = time.monotonic() + budget
    processed = ok = fields_filled = failures = 0
    while time.monotonic() < deadline and failures < 3:
        try:
            rows = await asyncio.to_thread(ai_queue, table, limit)
        except Exception:
            logger.warning("enrich_missing: query non riuscita")
            break
        if not rows:
            break
        for row in rows:
            if time.monotonic() >= deadline or failures >= 3:
                break
            processed += 1
            result = await analyze_listing(row.get("title"), row.get("description"), category)
            if result is None:
                failures += 1
                continue
            failures = 0
            update: dict[str, Any] = {"ai_analysis": result["analysis"]}
            writeback = _field_writeback(
                row, result.get("fields") or {}, row.get("title"), result["analysis"]
            )
            if writeback:
                update.update(writeback)
                fields_filled += 1
            try:
                await asyncio.to_thread(
                    lambda r=row, u=update: db.table(table).update(u).eq("id", r["id"]).execute()
                )
                ok += 1
            except Exception:
                logger.warning("enrich_missing: update fallito per %s", row.get("id"))
            if settings.ai_pause_s > 0:
                await asyncio.sleep(settings.ai_pause_s)
    if processed:
        logger.info(
            "AI enrich (%s, %s): %d/%d analizzati, %d con campi o guasti aggiornati",
            category, settings.ollama_model, ok, processed, fields_filled,
        )
    return {"processed": processed, "ok": ok, "fields_filled": fields_filled}
