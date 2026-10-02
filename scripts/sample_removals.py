"""Validazione a mano di "venduto" (G11 della release).

Il programma decide che un annuncio è sparito (inventario + verifica della
pagina) e poi, con un'euristica, se è venduto, ritirato o scaduto. Prima di
fidarsi dei tempi di vendita (C4) serve misurare quanto spesso sbaglia, con
un controllo indipendente: una persona che apre la pagina nel browser.

  python scripts/sample_removals.py            # crea il CSV da compilare
  python scripts/sample_removals.py --eval FILE  # misura sul CSV compilato

Il CSV (in scripts/data/) contiene annunci marcati spariti e, come controllo,
alcuni ancora attivi, mescolati e senza dire quale è quale. Nella colonna
``online_ora`` scrivi "si" se la pagina mostra ancora l'annuncio in vendita,
"no" se è rimosso / non disponibile. Da fare entro un giorno dall'estrazione:
dopo, anche gli attivi spariscono davvero.
"""

import csv
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA_DIR = Path(__file__).resolve().parent / "data"
TABLE = "live_opportunities_tech"


def extract(n_removed: int = 40, n_active: int = 15) -> Path:
    from backend.core.database import _get_pool  # noqa: PLC0415

    with _get_pool().connection() as conn:
        removed = conn.execute(
            f"select id, listing_url, title, asking_price, status from public.{TABLE} "
            f"where status in ('venduto_rimosso', 'scaduto') "
            f"and updated_at >= now() - interval '2 days' order by random() limit %s",
            (n_removed,),
        ).fetchall()
        active = conn.execute(
            f"select id, listing_url, title, asking_price, status from public.{TABLE} "
            f"where status in ('nuovo', 'visto') order by random() limit %s",
            (n_active,),
        ).fetchall()
    if not removed:
        sys.exit("Nessun annuncio marcato sparito negli ultimi 2 giorni: serve prima un inventario.")
    rows = [dict(r) for r in removed + active]
    random.shuffle(rows)
    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / f"validazione_venduti_{datetime.now(timezone.utc):%Y%m%d}.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "url", "titolo", "prezzo", "stato_programma", "online_ora"])
        for r in rows:
            w.writerow([r["id"], r["listing_url"], r["title"], r["asking_price"], r["status"], ""])
    print(f"{len(removed)} spariti + {len(active)} attivi di controllo → {out}")
    print("Apri ogni URL e scrivi si/no in 'online_ora', poi: --eval", out.name)
    return out


def evaluate(path: Path) -> None:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    done = [r for r in rows if r["online_ora"].strip().lower() in ("si", "sì", "no")]
    if not done:
        sys.exit("Nessuna riga compilata.")

    def online(r):
        return r["online_ora"].strip().lower() in ("si", "sì")

    removed = [r for r in done if r["stato_programma"] in ("venduto_rimosso", "scaduto")]
    active = [r for r in done if r["stato_programma"] not in ("venduto_rimosso", "scaduto")]
    false_removed = [r for r in removed if online(r)]
    false_active = [r for r in active if not online(r)]
    print(f"Compilate {len(done)}/{len(rows)}")
    if removed:
        prec = 1 - len(false_removed) / len(removed)
        print(f"Spariti davvero spariti: {prec:.0%} ({len(removed) - len(false_removed)}/{len(removed)})")
        for r in false_removed:
            print("  ancora online ma marcato sparito:", r["url"])
    if active:
        print(f"Attivi davvero online: {1 - len(false_active) / len(active):.0%} "
              f"({len(active) - len(false_active)}/{len(active)})")
        for r in false_active:
            print("  sparito ma ancora attivo per noi:", r["url"])
    print("\nObiettivo v1: ≥ 95% sugli spariti. Sotto, i tempi di vendita sono gonfiati da falsi venduti.")


if __name__ == "__main__":
    if "--eval" in sys.argv:
        evaluate(Path(sys.argv[sys.argv.index("--eval") + 1]).resolve()
                 if Path(sys.argv[sys.argv.index("--eval") + 1]).exists()
                 else DATA_DIR / sys.argv[sys.argv.index("--eval") + 1])
    else:
        extract()
