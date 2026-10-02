"""Sonda del rate limit di Subito/Akamai in connessione DIRETTA (senza proxy).

Serve a scegliere il ritmo dello Sniper sui numeri, non a occhio: il limite
dipende dall'IP di uscita, quindi va rilanciata su ogni macchina che scrapa
(PC, Mac, VPS).

Modalità:
  --once   una richiesta, stampa esito e campi utili dell'annuncio più recente.
  --ramp   scende per gradini di intervallo (es. 60s → 1s), N richieste per
           gradino; al PRIMO blocco (403/429/risposta non-JSON) si ferma e
           misura quanto dura il blocco riprovando ogni --recovery-step secondi.

Ogni richiesta finisce in un CSV (ts, gradino, status, latenza, esito), così
lo stesso file si può confrontare tra macchine/giorni.

Esegui dalla root:
  python scripts/probe_rate_limit.py --once
  python scripts/probe_rate_limit.py --ramp --gaps 60,30,15,8,4,2,1 --per-step 8
"""

import argparse
import asyncio
import csv
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import CurlError

HADES_URL = "https://hades.subito.it/v1/search/items"
# Query realistiche e diverse fra loro: la stessa ricerca ripetuta è un
# pattern più sospetto di quello che fa davvero lo Sniper.
QUERIES = ["iphone 13", "iphone 14 pro", "iphone 15", "iphone 12", "iphone 11"]
IMPERSONATE = ["safari", "firefox"]


async def one_request(query: str) -> dict:
    params = {"q": query, "t": "s", "sort": "datedesc", "lim": "100", "start": "0"}
    started = time.perf_counter()
    try:
        async with AsyncSession(
            impersonate=random.choice(IMPERSONATE),
            timeout=20,
            headers={"Accept": "application/json"},
        ) as client:
            resp = await client.get(HADES_URL, params=params)
        latency = time.perf_counter() - started
        try:
            payload = resp.json()
            n_ads = len(payload.get("ads") or [])
        except Exception:
            payload, n_ads = None, None
        ok = resp.status_code == 200 and payload is not None
        outcome = "ok" if ok else ("blocked" if resp.status_code in (403, 429) or payload is None else "error")
        return {
            "status": resp.status_code, "latency": round(latency, 2),
            "outcome": outcome, "n_ads": n_ads, "payload": payload,
            "snippet": "" if ok else resp.text[:200].replace("\n", " "),
        }
    except CurlError as exc:
        return {
            "status": None, "latency": round(time.perf_counter() - started, 2),
            "outcome": "neterr", "n_ads": None, "payload": None, "snippet": str(exc)[:200],
        }


def log_row(writer, fh, step_gap, query, res) -> None:
    writer.writerow([
        datetime.now(timezone.utc).isoformat(timespec="seconds"), step_gap, query,
        res["status"], res["latency"], res["outcome"], res["n_ads"], res["snippet"],
    ])
    fh.flush()


async def run_once() -> int:
    res = await one_request("iphone 13")
    print(f"status={res['status']} esito={res['outcome']} latenza={res['latency']}s annunci={res['n_ads']}")
    if res["snippet"]:
        print("risposta:", res["snippet"])
    if res["payload"] and res["payload"].get("ads"):
        ad = res["payload"]["ads"][0]
        print("count_all:", res["payload"].get("count_all"))
        print("chiavi annuncio:", sorted(ad.keys()))
        print("dates:", ad.get("dates"))
    return 0 if res["outcome"] == "ok" else 1


async def run_ramp(gaps: list[float], per_step: int, recovery_step: int,
                   recovery_max: int, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if fh.tell() == 0:
            writer.writerow(["ts", "gap_s", "query", "status", "latency_s", "outcome", "n_ads", "snippet"])

        for gap in gaps:
            print(f"\n--- gradino: 1 richiesta ogni ~{gap}s ({per_step} richieste)")
            for i in range(per_step):
                query = random.choice(QUERIES)
                res = await one_request(query)
                log_row(writer, fh, gap, query, res)
                print(f"  [{i + 1}/{per_step}] {query!r:18} status={res['status']} "
                      f"{res['outcome']} {res['latency']}s")
                if res["outcome"] == "blocked":
                    print(f"\n!! BLOCCO al gradino {gap}s (richiesta {i + 1}). Misuro la durata…")
                    blocked_at = time.monotonic()
                    while time.monotonic() - blocked_at < recovery_max:
                        await asyncio.sleep(recovery_step)
                        res = await one_request(random.choice(QUERIES))
                        log_row(writer, fh, f"recovery+{int(time.monotonic() - blocked_at)}", "-", res)
                        print(f"  recovery +{int(time.monotonic() - blocked_at)}s → {res['outcome']}")
                        if res["outcome"] == "ok":
                            print(f"Sbloccato dopo ~{int(time.monotonic() - blocked_at)}s.")
                            return 2
                    print(f"Ancora bloccato dopo {recovery_max}s.")
                    return 3
                # Jitter ±25%: un intervallo perfettamente regolare è a sua volta una firma.
                await asyncio.sleep(gap * random.uniform(0.75, 1.25))
    print("\nNessun blocco su tutti i gradini.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--ramp", action="store_true")
    parser.add_argument("--gaps", default="60,30,15,8,4,2,1")
    parser.add_argument("--per-step", type=int, default=8)
    parser.add_argument("--recovery-step", type=int, default=60)
    parser.add_argument("--recovery-max", type=int, default=1800)
    parser.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "backups" / "probe_rate_limit.csv"))
    args = parser.parse_args()

    if args.once:
        return asyncio.run(run_once())
    gaps = [float(g) for g in args.gaps.split(",") if g.strip()]
    return asyncio.run(run_ramp(gaps, args.per_step, args.recovery_step, args.recovery_max, Path(args.out)))


if __name__ == "__main__":
    sys.exit(main())
