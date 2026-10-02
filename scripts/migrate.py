"""Stato e applicazione manuale delle migrazioni (di norma le applica il backend
all'avvio, vedi backend/core/migrations.py).

Esegui dalla root (o nel container):
  python scripts/migrate.py           # mostra applicate / in attesa
  python scripts/migrate.py --apply   # applica quelle in attesa
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core import migrations  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if "--apply" in sys.argv:
        done = migrations.apply_pending()
        print(f"Applicate ora: {done or 'nessuna'}")
    state = migrations.status()
    print(f"Applicate: {len(state['applied'])} (ultima: {state['applied'][-1] if state['applied'] else '—'})")
    print(f"In attesa: {state['pending'] or 'nessuna'}")
    return 1 if state["pending"] else 0


if __name__ == "__main__":
    sys.exit(main())
