import json
from pathlib import Path

import numpy as np
from scipy.stats import pearsonr

BASE = Path(r"research/strategy-lab/reports/2026-08-16-sl2-sequential")

with open(BASE / "slim_trades.json", encoding="utf-8") as f:
    slim = json.load(f)
with open(BASE / "mfe_mae_2154_trades.json", encoding="utf-8") as f:
    mfe = json.load(f)

mfe_by_key = {(t["symbol"], t["entry_date"]): t for t in mfe}
print("mfe unique keys:", len(mfe_by_key), "of", len(mfe))

rows = []
dropped = 0
for t in slim:
    key = (t["symbol"], t["entry_date"])
    m = mfe_by_key.get(key)
    if m is None:
        dropped += 1
        continue
    atr = t["stop_distance"] / 2.0
    atr_pct = atr / t["entry"]["price"] * 100.0
    rows.append((atr_pct, m["mae_pct"], m["exit_type"]))

print("joined:", len(rows), "dropped:", dropped)

atr_all = np.array([r[0] for r in rows])
mae_all = np.array([r[1] for r in rows])

r_all, p_all = pearsonr(atr_all, mae_all)
print(f"ALL  n={len(rows)}  r={r_all:.6f}  p={p_all:.6e}")

stops = [r for r in rows if r[2] == "STOP"]
atr_stop = np.array([r[0] for r in stops])
mae_stop = np.array([r[1] for r in stops])
r_stop, p_stop = pearsonr(atr_stop, mae_stop)
print(f"STOP n={len(stops)}  r={r_stop:.6f}  p={p_stop:.6e}")

from collections import Counter
print("exit_type counts:", Counter(r[2] for r in rows))
