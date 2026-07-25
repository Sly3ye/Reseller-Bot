"""Analisi AI locale (Ollama) delle descrizioni — lancio on-demand.

Consuma il backlog degli annunci attivi con descrizione e senza ai_analysis.
Gira anche schedulato ogni 10' nel backend; questo wrapper serve per spingere
un batch a mano (es. dopo un backfill).

Esegui dalla root (dentro il container per raggiungere Ollama/DB):
  docker compose exec backend python -m scripts.enrich_ai [limit] [category]
Oppure in locale:
  python scripts/enrich_ai.py [limit] [category]
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.ai_analysis import enrich_missing  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")


async def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    category = sys.argv[2] if len(sys.argv) > 2 else "smartphone"
    result = await enrich_missing(limit=limit, category=category)
    print(f"AI enrich: {result['ok']}/{result['processed']} analizzati ({category})")


if __name__ == "__main__":
    asyncio.run(main())
