"""Validazione a mano delle ripubblicazioni (G12 della release).

Il programma fonde due annunci quando li ritiene lo stesso telefono rimesso
online (``services/republish.py`` e ``tasks.republish_match``):
- stessa prima foto (pHash) E stesso venditore;
- oppure stesso venditore + stessa variante + prezzo ±15%, se il venditore
  non ha due pezzi uguali online insieme (negozio).

Sbagliare in un senso conta vendite inesistenti (ripubblicazione non vista),
nell'altro cancella vendite vere (pezzi diversi fusi). Qui si estraggono
coppie candidate, si scrive cosa deciderebbe il programma e una persona
guarda i due annunci (foto, testo) e segna se sono lo stesso telefono.

  python scripts/sample_republish.py             # crea il CSV da compilare
  python scripts/sample_republish.py --eval FILE # precisione / richiamo

Nella colonna ``stesso`` scrivi "si" o "no" (lascia vuoto se non si capisce).
Meglio farlo dopo una settimana di inventari: ci sono più coppie "uno
sparito, uno nuovo", il caso che conta davvero.
"""

import csv
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DATA_DIR = Path(__file__).resolve().parent / "data"
TABLE = "live_opportunities_tech"
COLS = ("id, listing_url, title, description, asking_price, seller_id, variant_key, "
        "image_hash, status, published_at, found_at, updated_at")


def _program_says(category: str, a: dict, b: dict, active_by_identity: dict) -> str:
    """Decisione del programma sulla coppia, con le regole correnti."""
    from backend.services.republish import identity, _close_price  # noqa: PLC0415
    from backend.services.variants import model_text  # noqa: PLC0415

    same_seller = a.get("seller_id") and str(a["seller_id"]) == str(b.get("seller_id"))
    if a.get("image_hash") and a["image_hash"] == b.get("image_hash"):
        return "fonde (foto)" if same_seller else "separa (foto uguale, venditore diverso)"
    key = identity(category, a.get("seller_id"), a.get("variant_key"),
                   model_text(a.get("title"), a.get("description")))
    if not key or not _close_price(a.get("asking_price"), b.get("asking_price")):
        return "separa"
    if active_by_identity.get(key, 0) >= 2:
        return "separa (negozio)"
    return "fonde (venditore+variante)"


def extract(n_photo: int = 30, n_seller: int = 40) -> Path:
    from backend.core.database import _get_pool  # noqa: PLC0415
    from backend.services.republish import identity  # noqa: PLC0415
    from backend.services.variants import model_text  # noqa: PLC0415

    with _get_pool().connection() as conn:
        rows = conn.execute(
            f"select {COLS} from public.{TABLE} where seller_id is not null or image_hash is not null"
        ).fetchall()
    rows = [dict(r) for r in rows]

    by_hash: dict[str, list[dict]] = {}
    by_identity: dict[tuple, list[dict]] = {}
    active_by_identity: dict[tuple, int] = {}
    for r in rows:
        if r.get("image_hash"):
            by_hash.setdefault(r["image_hash"], []).append(r)
        key = identity("smartphone", r.get("seller_id"), r.get("variant_key"),
                       model_text(r.get("title"), r.get("description")))
        if key:
            by_identity.setdefault(key, []).append(r)
            if r["status"] in ("nuovo", "visto"):
                active_by_identity[key] = active_by_identity.get(key, 0) + 1

    def pairs_of(groups):
        out = []
        for group in groups.values():
            if len(group) >= 2:
                a, b = random.sample(group, 2)
                out.append((a, b))
        return out

    random.seed()
    photo_pairs = random.sample(pairs_of(by_hash), min(n_photo, len(pairs_of(by_hash))))
    seller_all = pairs_of(by_identity)
    seller_pairs = random.sample(seller_all, min(n_seller, len(seller_all)))

    DATA_DIR.mkdir(exist_ok=True)
    out = DATA_DIR / f"validazione_ripubblicazioni_{datetime.now(timezone.utc):%Y%m%d}.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["tipo", "url_a", "url_b", "titolo_a", "titolo_b", "prezzo_a", "prezzo_b",
                    "stato_a", "stato_b", "programma", "stesso"])
        for kind, pairs in (("foto", photo_pairs), ("venditore", seller_pairs)):
            for a, b in pairs:
                w.writerow([kind, a["listing_url"], b["listing_url"], a["title"], b["title"],
                            a["asking_price"], b["asking_price"], a["status"], b["status"],
                            _program_says("smartphone", a, b, active_by_identity), ""])
    print(f"{len(photo_pairs)} coppie con la stessa foto + {len(seller_pairs)} stesso "
          f"venditore/variante → {out}")
    print("Apri le due URL di ogni riga e scrivi si/no in 'stesso', poi: --eval", out.name)
    return out


def evaluate(path: Path) -> None:
    rows = [r for r in csv.DictReader(path.open(encoding="utf-8"))
            if r["stesso"].strip().lower() in ("si", "sì", "no")]
    if not rows:
        sys.exit("Nessuna riga compilata.")

    def same(r):
        return r["stesso"].strip().lower() in ("si", "sì")

    def merges(r):
        return r["programma"].startswith("fonde")

    tp = sum(1 for r in rows if merges(r) and same(r))
    fp = [r for r in rows if merges(r) and not same(r)]
    fn = [r for r in rows if not merges(r) and same(r)]
    print(f"Compilate {len(rows)}")
    if tp + len(fp):
        print(f"Precisione (fusioni giuste): {tp / (tp + len(fp)):.0%}  → sotto: vendite vere cancellate")
    if tp + len(fn):
        print(f"Richiamo (ripubblicazioni viste): {tp / (tp + len(fn)):.0%}  → sotto: vendite inventate")
    for r in fp:
        print("  fusi ma diversi:", r["programma"], r["url_a"], r["url_b"])
    for r in fn:
        print("  stesso telefono non riconosciuto:", r["programma"], r["url_a"], r["url_b"])
    print("\nObiettivo v1: precisione ≥ 95% e richiamo ≥ 80%.")


if __name__ == "__main__":
    if "--eval" in sys.argv:
        arg = sys.argv[sys.argv.index("--eval") + 1]
        evaluate(Path(arg) if Path(arg).exists() else DATA_DIR / arg)
    else:
        extract()
