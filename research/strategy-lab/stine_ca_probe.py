"""분할·병합 오염 탐침: (1) 매매정지 규칙이 거르는 사건 수 (2) A4 거래대금으로 본 수정계수 급변을 규칙이 놓치는 비율. 수익률 없음."""
import gzip, json
from pathlib import Path
import numpy as np, pandas as pd
P = Path(r"C:\Users\User\projects\stock\data\backfill")
rows = []
for sub in ("a2a", "a2b"):
    for p in sorted((P / "price" / sub).glob("20*.jsonl.gz")):
        for l in gzip.open(p, "rt", encoding="utf-8"):
            r = json.loads(l); rows.append((r["ticker"], r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]))
d = pd.DataFrame(rows, columns=["t","date","o","h","l","c","v"]); del rows
d["date"] = pd.to_datetime(d["date"]); d = d.drop_duplicates(["t","date"]).sort_values(["t","date"])
d["halt"] = (d.o == 0) & (d.v == 0)
# 2일 이상 연속 정지
d["hrun"] = d.groupby("t").halt.transform(lambda s: s.rolling(2).sum() >= 2)
am = []
for p in sorted((P / "supplyDemand" / "a4").glob("20*.jsonl.gz")):
    for l in gzip.open(p, "rt", encoding="utf-8"):
        r = json.loads(l); am.append((r["ticker"], r["date"], r["buyAmount"].get("전체")))
a = pd.DataFrame(am, columns=["t","date","amt"]); del am
a["date"] = pd.to_datetime(a["date"])
d = d.merge(a, on=["t","date"], how="left")
d["f"] = np.where((d.v > 0) & (d.amt > 0), d.amt / (d.c * d.v), np.nan)  # ≈ 원주가/수정주가
t = d[(d.v > 0) & (d.c > 0)].copy()
t["val"] = t.c * t.v; t["wk"] = t.date.dt.to_period("W-FRI")
w = t.groupby(["t","wk"]).agg(h=("h","max"), l=("l","min"), c=("c","last"), v=("v","sum"), val=("val","sum"),
                              end=("date","last"), f=("f","median")).reset_index()
hw = d.assign(wk=d.date.dt.to_period("W-FRI")).groupby(["t","wk"]).hrun.max().rename("hw").reset_index()
w = w.merge(hw, on=["t","wk"], how="left").sort_values(["t","wk"]).reset_index(drop=True)
g = w.groupby("t", group_keys=False)
w["ma30"] = g.c.transform(lambda s: s.rolling(30).mean()); w["ma10"] = g.c.transform(lambda s: s.rolling(10).mean())
w["c1"] = g.c.shift(1); w["ma30_1"] = g.ma30.shift(1)
w["hi12"] = g.h.transform(lambda s: s.shift(1).rolling(12).max()); w["lo12"] = g.l.transform(lambda s: s.shift(1).rolling(12).min())
w["v20"] = g.v.transform(lambda s: s.shift(1).rolling(20).mean())
w["halt_win"] = g.hw.transform(lambda s: s.astype(float).rolling(27, min_periods=1).max().shift(-6))  # t-20..t+6
w["fmax"] = g.f.transform(lambda s: s.rolling(27, min_periods=5).max().shift(-6))
w["fmin"] = g.f.transform(lambda s: s.rolling(27, min_periods=5).min().shift(-6))
bo = ((w.c > w.ma30) & (w.c1 <= w.ma30_1) & (w.c > w.hi12) & (w.hi12 / w.lo12 <= 1.6) & (w.v >= 5 * w.v20) & (w.val >= 1e9))
e = w[bo].copy()
e["halt"] = e.halt_win.fillna(0) > 0
e["a4"] = e.fmax.notna()
e["jump"] = e.a4 & (e.fmax / e.fmin > 1.5)
print("core breakouts", len(e), "| halt-window", int(e.halt.sum()))
print("A4-covered", int(e.a4.sum()), "| factor jump>1.5x", int(e.jump.sum()),
      "| of which caught by halt rule", int((e.jump & e.halt).sum()), "| missed", int((e.jump & ~e.halt).sum()))
print(e[e.jump & ~e.halt][["t","end","fmin","fmax"]].head(15).to_string())
