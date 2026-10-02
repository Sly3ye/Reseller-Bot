"""Recupero TOTALE dello stock attivo (una tantum): tutti gli iPhone su Subito.

La ricerca ampia schedulata vede solo ciò che esce da ora in poi. Questo
script sfoglia l'intero stock attivo (~68.000 annunci iPhone al 2026-10-02),
spezzando la query in fasce di prezzo sotto il tetto di 10.000 risultati di
hades. Senza immagini (le scarica lo Sweep quando rivede l'annuncio).

Costo: ~1 richiesta ogni 100 annunci + qualche conteggio, al ritmo del pacer
(SCRAPER_MIN_GAP_S): ~700 richieste ≈ 70-80 minuti a 6s. Se Subito blocca,
lo script si ferma e stampa da dove riprendere.

Esegui dalla root (meglio dentro il container, così scrive nel DB giusto):
  docker compose exec backend python scripts/deep_sweep.py
  docker compose exec backend python scripts/deep_sweep.py --from 420   # riprendi
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.scrapers.subito import ScraperBlockedError  # noqa: E402
from backend.services.sweep import deep_backfill  # noqa: E402

# Nota: dopo il primo recupero non serve rilanciarlo a mano, lo stesso giro
# d'inventario gira ogni notte (reconcile_inventory nello scheduler).


def main() -> int:
    min_price = None
    if "--from" in sys.argv:
        min_price = int(sys.argv[sys.argv.index("--from") + 1])
    try:
        asyncio.run(deep_backfill("smartphone", min_price=min_price))
    except ScraperBlockedError as exc:
        print(f"\n!! Bloccati da Subito ({exc}). Aspetta il cooldown e riprendi con "
              f"--from <prezzo della fascia in corso> (vedi sopra).")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
