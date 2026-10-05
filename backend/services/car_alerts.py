"""Alert Telegram per le auto, sui criteri di chi compra (Impostazioni).

Con tutte le auto di Subito il criterio "classe affare + Deal Score" degli
iPhone manderebbe decine di messaggi l'ora. Qui conta il margine VERO e i
criteri del compratore:
- margine netto dopo passaggio e costi ≥ ``car_alert_min_net_margin_eur``;
- prezzo ≤ ``car_alert_max_price`` (0 = nessun tetto);
- marca tra ``car_alert_brands`` (vuoto = tutte);
- località che contiene una delle ``car_alert_zones`` (province o regioni,
  vuoto = ovunque);
- sempre: valore equo da un modello affidabile, rischio non alto, auto sana;
- sempre: margine oltre il rumore del modello (``car_alert_min_err_multiple``
  × errore tipico in euro). Con errori del 25–35% un "margine" di 800 € su
  un'auto da 10.000 € è un errore del modello, non un affare;
- almeno UN criterio del compratore (marca, zona, raggio o budget): su tutta
  Italia senza criteri erano ~2.500 "affari" al giorno (misurato il 5/10).
Funzione pura (niente DB) → testabile.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

DEFAULTS: dict[str, Any] = {
    "car_alert_min_net_margin_eur": 800,
    "car_alert_max_price": 0,
    "car_alert_brands": [],
    "car_alert_zones": [],
    "car_alert_radius_km": 0,   # 0 = nessun limite; serve il comune di casa
    "car_alert_min_err_multiple": 1.0,  # margine ≥ N × errore tipico del modello (€)
}


def has_buyer_criteria(cfg: dict[str, Any]) -> bool:
    """Almeno un criterio del compratore impostato (marca, zona, raggio, budget)."""
    return bool([b for b in cfg.get("car_alert_brands") or [] if b]
                or [z for z in cfg.get("car_alert_zones") or [] if z]
                or float(cfg.get("car_alert_radius_km") or 0)
                or float(cfg.get("car_alert_max_price") or 0))


def _norm(text: str | None) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def matches(item: dict[str, Any], cfg: dict[str, Any]) -> bool:
    if not has_buyer_criteria(cfg):
        return False
    net = item.get("netMarginAfterCostsEur")
    if net is None or net < float(cfg.get("car_alert_min_net_margin_eur") or 0):
        return False
    if not item.get("carModel") or (item.get("risk") or {}).get("level") == "alto":
        return False
    err_pct, expected = (item.get("carModel") or {}).get("errPct"), item.get("expectedPrice")
    multiple = float(cfg.get("car_alert_min_err_multiple", DEFAULTS["car_alert_min_err_multiple"]) or 0)
    if multiple and err_pct is not None and expected and net < multiple * err_pct / 100 * expected:
        return False
    if item.get("conditionTier") not in (None, "buono", "come-nuovo"):
        return False
    max_price = float(cfg.get("car_alert_max_price") or 0)
    if max_price and (item.get("askingPrice") or 0) > max_price:
        return False
    brands = [_norm(b) for b in cfg.get("car_alert_brands") or [] if b]
    if brands and not any((item.get("variantKey") or "").startswith(b + "-") for b in brands):
        return False
    radius = float(cfg.get("car_alert_radius_km") or 0)
    if radius and (item.get("distanceKm") is None or item["distanceKm"] > radius):
        return False
    zones = [_norm(z) for z in cfg.get("car_alert_zones") or [] if z]
    where = "-".join(_norm(item.get(k)) for k in ("location", "province", "region"))
    if zones and not any(z in where for z in zones):
        return False
    return True


def select_car_alerts(items: list[dict[str, Any]], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Le auto da notificare, dal margine netto più alto."""
    chosen = [it for it in items if matches(it, cfg)]
    return sorted(chosen, key=lambda it: -(it.get("netMarginAfterCostsEur") or 0))
