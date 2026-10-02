"""Listino ricambi ORIGINALI Apple dal Self Service Repair Store (Italia).

Il negozio (selfservicerepair.eu) incorpora nella pagina di ogni riparazione
un blocco JSON ``bootstrap-data`` con i ricambi e, paese per paese, il prezzo
e il CREDITO che Apple rimborsa se le rispedisci la parte sostituita (per la
batteria ~metà del prezzo). I valori sono IVA ESCLUSA: qui si riportano al
prezzo italiano IVA inclusa (×1,22), verificato sul listino pubblico (batteria
iPhone 13: 81,15 + IVA = 99€).

Pezzo principale = la voce "661-…" della riparazione (le altre sono viti,
adesivi e attrezzi da pochi euro). Il kit attrezzi a noleggio (59,95€) non è
compreso: è un costo per sessione, non per pezzo.

Scrive ``backend/data/apple_parts_it.json`` (versionato: il listino cambia di
rado e così il backend non dipende dal sito). Rilancialo per aggiornarlo.

Esegui dalla root:  python scripts/fetch_apple_parts.py
"""

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

STORE = "https://selfservicerepair.eu"
VAT_IT = 1.22
# Riparazione nello store → nostra chiave di ricambio.
REPAIRS = {"batteria": "batteria", "schermo": "schermo", "fotocamera": "fotocamera"}
OUT = ROOT / "backend" / "data" / "apple_parts_it.json"
_BOOT_RE = re.compile(r'<script[^>]*id="bootstrap-data"[^>]*>(.*?)</script>', re.S)


def main_part(spares: list[dict]) -> dict | None:
    """La parte vera della riparazione: 661-… con prezzo più alto."""
    best = None
    for sp in spares:
        if not str(sp.get("partnumber", "")).startswith("661-") or not sp.get("part"):
            continue
        it = next((c for c in sp["country_specific_attributes"] if c["id_countries"] == "IT"), None)
        if not it or not it.get("price"):
            continue
        if best is None or it["price"] > best[1]["price"]:
            best = (sp, it)
    if best is None:
        return None
    sp, it = best
    return {
        "partNumber": sp["partnumber"],
        "priceEur": round(it["price"] * VAT_IT, 2),
        "returnCreditEur": round((it.get("creditamount") or 0) * VAT_IT, 2),
    }


def main() -> int:
    session = requests.Session(impersonate="safari")
    types = session.get(f"{STORE}/api/DeviceTypes", headers={"Accept": "application/json"}, timeout=30).json()
    models = []
    for group in types:
        for m in group.get("devicemodels") or []:
            slug = next((a["slug"] for a in m["language_specific_attributes"] if a["id_languages"] == "it"), None)
            key = iphone_model_key(m.get("model"))
            if slug and key:
                models.append((key, m["model"], slug))
    print(f"{len(models)} modelli iPhone nello store")

    catalog: dict[str, dict] = {}
    for key, name, slug in sorted(models):
        entry: dict = {"name": name}
        for repair, ours in REPAIRS.items():
            html = session.get(f"{STORE}/it-IT/{slug}/{repair}", timeout=30).text
            boot = _BOOT_RE.search(html)
            spares = []
            if boot:
                data = json.loads(boot.group(1))
                for k, v in (data.get("spares") or {}).items():
                    spares.extend(v or [])
            part = main_part(spares)
            if part:
                entry[ours] = part
            time.sleep(1.5)  # gentilezza verso lo store
        catalog[key] = entry
        parts = ", ".join(f"{p} {entry[p]['priceEur']}€ (reso -{entry[p]['returnCreditEur']}€)"
                          for p in REPAIRS.values() if p in entry)
        print(f"  {name:20} {parts or '— nessun ricambio'}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": f"{STORE}/it-IT (Self Service Repair Store), prezzi IVA inclusa",
        "fetchedAt": date.today().isoformat(),
        "vat": VAT_IT,
        "models": catalog,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nScritto {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
