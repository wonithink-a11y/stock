"""STINE-0 사건 수 탐침 — 수익률은 계산하지 않는다(결과 전 표본 규모만).
KR 일봉 A2a(상장) + A2b(폐지) → 주봉(금요일 마감). 변형 3개는 표본 민감도만 본다.
"""
import gzip, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\User\projects\stock\data\backfill\price")
rows = []
for sub in ("a2a", "a2b"):
    for p in sorted((ROOT / sub).glob("20*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                rows.append((r["ticker"], r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]))
d = pd.DataFrame(rows, columns=["t", "date", "o", "h", "l", "c", "v"])
del rows
d["date"] = pd.to_datetime(d["date"])
d = d[(d.v > 0) & (d.c > 0)].drop_duplicates(["t", "date"]).sort_values(["t", "date"])
d["val"] = d.c * d.v
d["wk"] = d.date.dt.to_period("W-FRI")
w = d.groupby(["t", "wk"]).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"),
                                v=("v", "sum"), val=("val", "sum"), end=("date", "last")).reset_index()
print("tickers", w.t.nunique(), "weekly rows", len(w), file=sys.stderr)

g = w.groupby("t", group_keys=False)
w["ma30"] = g.c.transform(lambda s: s.rolling(30).mean())
w["ma10"] = g.c.transform(lambda s: s.rolling(10).mean())
w["c1"] = g.c.shift(1)
w["ma30_1"] = g.ma30.shift(1)
w["hi12"] = g.h.transform(lambda s: s.shift(1).rolling(12).max())
w["lo12"] = g.l.transform(lambda s: s.shift(1).rolling(12).min())
w["v20"] = g.v.transform(lambda s: s.shift(1).rolling(20).mean())

VARIANTS = {  # (기준 폭 상한, 거래량 배수)
    "loose": (1.8, 3.0),
    "core": (1.6, 5.0),
    "strict": (1.4, 8.0),
}
MIN_VAL = 1e9  # 돌파 주 거래대금 10억 원


def split(y):
    return "TRAIN" if y <= 2020 else ("VALID" if y <= 2022 else "TEST")


out = {}
for name, (base_w, vmult) in VARIANTS.items():
    bo = ((w.c > w.ma30) & (w.c1 <= w.ma30_1) & (w.c > w.hi12) & (w.hi12 / w.lo12 <= base_w)
          & (w.v >= vmult * w.v20) & (w.val >= MIN_VAL))
    idx = np.flatnonzero(bo.values)
    tk, c, v, ma10, h = w.t.values, w.c.values, w.v.values, w.ma10.values, w.hi12.values
    ends = w.end.values
    ev = []
    for i in idx:
        entry = None
        for k in range(2, 7):  # 돌파 뒤 2~6주째(두 주 연속 좁은 종가 필요)
            j = i + k
            if j >= len(w) or tk[j] != tk[i]:
                break
            tight = abs(c[j] / c[j - 1] - 1) <= 0.03 and abs(c[j - 1] / c[j - 2] - 1) <= 0.03
            if (v[j] <= 0.4 * v[i] and tight and c[j] >= 0.95 * h[i]
                    and c[j] >= ma10[j] and c[j] <= 1.15 * ma10[j]):
                entry = j
                break
        ev.append((tk[i], pd.Timestamp(ends[i]).year, entry is not None))
    e = pd.DataFrame(ev, columns=["t", "y", "entry"])
    e["split"] = e.y.map(split)
    out[name] = e
    by = e.groupby("split").agg(breakouts=("t", "size"), entries=("entry", "sum"),
                                tickers=("t", "nunique")).reindex(["TRAIN", "VALID", "TEST"])
    print(f"\n== {name} (base<= {base_w}, vol>= {vmult}x)")
    print(by.to_string())
    print(e.groupby("y").entry.agg(["size", "sum"]).T.to_string())
