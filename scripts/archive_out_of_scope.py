"""Ambito iPhone (dal 12 in su, IPHONE_MIN_GEN): sposta in archivio gli annunci
fuori ambito (modelli più vecchi, accessori, altri marchi). Non cancella niente.

Esegui (nel container del backend):
  python scripts/archive_out_of_scope.py                         # conta e basta
  python scripts/archive_out_of_scope.py --apply                 # sposta in archivio
  python scripts/archive_out_of_scope.py --restore               # rimette tutto
  python scripts/archive_out_of_scope.py --restore --reason sotto_ambito
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.scope import archive_out_of_scope, restore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="sposta davvero (senza: solo conteggio)")
    parser.add_argument("--restore", action="store_true", help="rimette gli archiviati nella tabella")
    parser.add_argument("--reason", choices=["sotto_ambito", "non_iphone"], help="solo questo motivo (con --restore)")
    args = parser.parse_args()
    if args.restore:
        print(f"Ripristinati {restore(args.reason)} annunci")
        return
    out = archive_out_of_scope(apply=args.apply)
    if out.get("error"):
        raise SystemExit(out["error"])
    verb = "Spostati" if out["applied"] else "Da spostare (prova: aggiungi --apply)"
    print(f"{verb}: {out['out']} su {out['total']} annunci iPhone")


if __name__ == "__main__":
    main()
