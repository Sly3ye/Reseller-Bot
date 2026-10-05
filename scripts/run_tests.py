"""Lancia tutti i test (funzioni pure, nessun DB) e riassume l'esito.

Esegui dalla root:  python scripts/run_tests.py
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Test che non richiedono DB né rete (gli altri script test_* toccano il DB).
TESTS = ["intelligence", "variants", "republish", "survival", "valuation",
         "repair_feedback", "depreciation", "car_costs", "car_alerts", "telegram_bot", "deal_watch", "governor", "time_value", "verify_queue", "goals"]

env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
sys.stdout.reconfigure(encoding="utf-8")
failed = []
for name in TESTS:
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / f"test_{name}.py")],
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=ROOT)
    last = (proc.stdout.strip().splitlines() or ["(nessun output)"])[-1]
    print(f"{'OK  ' if proc.returncode == 0 else 'FAIL'} {name:<16} {last}")
    if proc.returncode != 0:
        failed.append(name)
        print(proc.stdout[-1500:], proc.stderr[-1500:])
print(f"\n{len(TESTS) - len(failed)}/{len(TESTS)} file di test verdi")
sys.exit(1 if failed else 0)
