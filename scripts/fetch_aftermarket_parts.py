"""Listino ricambi AFTERMARKET (Italia) dal catalogo pubblico di brotech.it.

Rivenditore italiano di ricambi per laboratori: prezzi IVA inclusa (verificato
sulla scheda prodotto). Tre categorie: display, batterie, back cover. Per
ogni modello si tengono TUTTE le qualità trovate, più una scelta consigliata
per la colonna "aftermarket" del calcolo margini:

- schermo: Soft OLED (il miglior aftermarket) sui modelli nati OLED; sui
  modelli nati LCD (11, XR, SE, 8...) un Incell/LCD è equivalente. Il
  "pulled" (originale usato, spesso con flat per la calibrazione True Tone) è
  una terza via: costa di più ma non degrada il telefono.
- batteria: Deji (quella che usi), altrimenti chip Texas Instruments.
- back cover: la più economica disponibile.

⚠️ Dall'iPhone 11 in poi una batteria/schermo non originale fa comparire
l'avviso "parte non originale" in Impostazioni (salvo trasferire il chip): va
detto all'acquirente e pesa sul prezzo di rivendita.

Scrive ``backend/data/aftermarket_parts_it.json``. Rilancialo per aggiornarlo.
Esegui dalla root:  python scripts/fetch_aftermarket_parts.py
"""

import html as H
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

from curl_cffi import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.services.variants import iphone_model_key  # noqa: E402

SHOP = "https://brotech.it"
CATEGORIES = {
    "schermo": "170-display-per-apple",
    "batteria": "171-batterie-per-apple",
    "scocca": "258-back-cover-per-apple",
}
OUT = ROOT / "backend" / "data" / "aftermarket_parts_it.json"
# Modelli nati con display LCD: per loro un Incell non è un declassamento.
LCD_MODELS = {"iphone-11", "iphone-xr", "iphone-se", "iphone-8", "iphone-8-plus",
              "iphone-7", "iphone-7-plus", "iphone-6s", "iphone-6s-plus", "iphone-6", "iphone-6-plus"}
_ITEM = re.compile(
    r'<h\d[^>]*class="[^"]*product-title[^"]*"[^>]*>\s*<a[^>]*>(.*?)</a>.*?'
    r'<span[^>]*class="[^"]*price[^"]*"[^>]*>(.*?)</span>',
    re.S,
)
# Parole che chiudono il nome del modello nel titolo prodotto.
_STOP = re.compile(
    r"\b(INCELL|SOFT|HARD|OLED|PULLED|FOG|LG|SHARP|TOSHIBA|GX|JK|ZY|DD|YK|DEJI|CHIP|HIGH|NO|NEW|"
    r"CONFIGURABILE|BLACK|WHITE|BLU|ROSSO|\+|CON|SENZA|COLORE|ORIGINALE|PARTE|LCD|A-SI)\b"
)


def grade(part: str, name: str) -> str:
    n = name.upper()
    if part == "schermo":
        for g in ("PULLED", "SOFT OLED", "HARD OLED", "INCELL", "HIGH-END"):
            if g in n:
                return {"HIGH-END": "lcd"}.get(g, g.lower())
        return "altro"
    if part == "batteria":
        if "DEJI" in n:
            return "deji"
        if "TEXAS" in n:
            return "chip-ti"
        if "HIGH CAPACITY" in n:
            return "alta-capacita"
        if "NO FLAT" in n or "CONFIGURABILE" in n:
            return "cella-da-programmare"
        return "generica"
    return "standard"


def models_in(name: str) -> list[str]:
    """'DISPLAY IPHONE 12 / 12 PRO SOFT OLED' → ['iphone-12', 'iphone-12-pro']."""
    m = re.search(r"IPHONE\s+(.*)", name.upper())
    if not m:
        return []
    stop = _STOP.search(m.group(1))
    seg = m.group(1)[: stop.start()] if stop else m.group(1)
    keys = []
    for piece in seg.split("/"):
        key = iphone_model_key("iphone " + piece.strip())
        if key and key not in keys:
            keys.append(key)
    return keys


def fetch(session, cat: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for page in range(1, 30):
        r = session.get(f"{SHOP}/{cat}?page={page}", timeout=30)
        items = _ITEM.findall(r.text) if r.status_code == 200 else []
        if not items:
            break
        page_rows = []
        for name, price in items:
            name = H.unescape(re.sub(r"\s+", " ", name)).strip()
            value = float(re.sub(r"[^\d,]", "", H.unescape(price)).replace(",", "."))
            page_rows.append((name, value))
        if out and page_rows[0] in out:  # pagina ripetuta: fine catalogo
            break
        out += page_rows
        time.sleep(2)
    return out


def recommend(part: str, key: str, options: list[dict]) -> dict | None:
    by_grade: dict[str, list[dict]] = {}
    for o in options:
        by_grade.setdefault(o["grade"], []).append(o)
    if part == "schermo":
        order = ["incell", "lcd", "soft oled", "hard oled"] if key in LCD_MODELS else ["soft oled", "hard oled", "incell"]
    elif part == "batteria":
        order = ["deji", "chip-ti", "alta-capacita", "generica"]
    else:
        order = ["standard"]
    for g in order:
        if g in by_grade:
            return min(by_grade[g], key=lambda o: o["priceEur"])
    return None


def main() -> int:
    session = requests.Session(impersonate="safari")
    catalog: dict[str, dict] = {}
    for part, cat in CATEGORIES.items():
        rows = fetch(session, cat)
        print(f"{part}: {len(rows)} prodotti")
        for name, price in rows:
            if "IPHONE" not in name.upper():
                continue
            for key in models_in(name):
                entry = catalog.setdefault(key, {})
                entry.setdefault(part, {"options": []})["options"].append(
                    {"name": name, "priceEur": price, "grade": grade(part, name)}
                )
    for key, entry in catalog.items():
        for part, data in entry.items():
            data["recommended"] = recommend(part, key, data["options"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": f"{SHOP} (catalogo pubblico), prezzi IVA inclusa",
        "fetchedAt": date.today().isoformat(),
        "models": dict(sorted(catalog.items())),
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n{'modello':18} {'schermo consigliato':42} {'batteria':26} scocca")
    for key in sorted(catalog):
        e = catalog[key]
        def fmt(p):
            r = (e.get(p) or {}).get("recommended")
            return f"{r['priceEur']:.2f}€ {r['grade']}" if r else "—"
        print(f"{key:18} {fmt('schermo'):42} {fmt('batteria'):26} {fmt('scocca')}")
    print(f"\nScritto {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
