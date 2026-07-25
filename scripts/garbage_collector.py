"""Garbage Collector — wrapper CLI del servizio schedulato.

La logica vive in backend/services/garbage_collector.py (gira anche ogni
notte nello scheduler del backend, alimentando il time-to-sale). Questo
script permette di lanciarla a mano dalla riga di comando.

Esegui dalla root:
  python scripts/garbage_collector.py [category]
  es. python scripts/garbage_collector.py automobile
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.garbage_collector import (  # noqa: E402
    TABLES,
    run_garbage_collector,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")


async def main() -> None:
    category = sys.argv[1] if len(sys.argv) > 1 else None
    if category and category not in TABLES:
        print(f"Categoria sconosciuta '{category}'. Usa: {', '.join(TABLES)}")
        return

    grand = await run_garbage_collector(category)
    print(
        f"\n=== GC COMPLETATO === verificati {grand['checked']}, "
        f"rimossi (venduto_rimosso) {grand['removed']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
