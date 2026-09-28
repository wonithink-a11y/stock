#!/usr/bin/env python3
"""거래량 급증 + 20일선 회복 — 1차 판정 (사전등록 findings/volume-ma20-reclaim-preregistration-2026-09.md).

자료 적재·특징·비용·판정은 close_open_phase5 / structure_phase4 를 import 한다(재구현 금지).
  python research/strategy-lab/futures/volume_ma20_study.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from close_open_phase5 import FIXED_BP, LIQ_MIN, load, split  # noqa: E402
from structure_phase4 import family, tick_bp  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

SEED = 20260929
H = 5


def prep(a: pd.DataFrame) -> pd.DataFrame:
    g = a.groupby("ticker")
    ok = lambda n: g.k.shift(-n) == a.k + n
    a["volr_prev"] = np.where(g.k.shift(1) == a.k - 1, g.volr.shift(1), np.nan)
    a["ma20"] = g.close.transform(lambda s: s.rolling(20, min_periods=20).mean())
    a["ma20_prev"] = g.ma20.shift(1)
    a["close_prev"] = g.close.shift(1)
    tr = np.maximum(a.high - a.low, np.maximum((a.high - a.close_prev).abs(), (a.low - a.close_prev).abs()))
    a["atr14"] = tr.groupby(a.ticker).transform(lambda s: s.rolling(14, min_periods=14).mean())
    a["o1"] = np.where(ok(1), g.open.shift(-1), np.nan)
    for h in (1, H, 20):
        a[f"c{h}"] = np.where(ok(h), g.close.shift(-h), np.nan)
    for i in range(1, H + 1):
        a[f"lo{i}"], a[f"op{i}"] = g.low.shift(-i), g.open.shift(-i)
    for h in (1, H, 20):
        a[f"r{h}"] = (a[f"c{h}"] / a.o1 - 1) * 1e4
        a.loc[a[f"r{h}"].abs() > 5000, f"r{h}"] = np.nan
    # 2×ATR 손절 변형(기록 전용): 저가가 닿으면 손절가(갭이면 시가), 아니면 T+5 종가
    stop = a.o1 - 2 * a.atr14
    out = a[f"c{H}"].copy()
    hit = pd.Series(False, index=a.index)
    for i in range(1, H + 1):
        now = (~hit) & (a[f"lo{i}"] <= stop)
        px = np.where(a[f"op{i}"] <= stop, a[f"op{i}"], stop)
        out = out.where(~now, px)
        hit |= now
    a["rstop"] = np.where(ok(H), (out / a.o1 - 1) * 1e4, np.nan)
    return a


CELLS = {
    "A": lambda u: (u.volr >= 2.0) & (u.volr_prev < 1.5) & (u.ret >= 0.03),
    "B": lambda u: (u.close > u.ma20) & (u.close_prev <= u.ma20_prev),
    "C": lambda u: (u.volr >= 2.0) & (u.volr_prev < 1.5) & (u.ret >= 0.03) & (u.close > u.ma20) & (u.close_prev <= u.ma20_prev),
}


def events(u, cid, col):
    ev = u[CELLS[cid](u)].dropna(subset=[col, "o1"])
    mkt = u.dropna(subset=[col]).groupby("date")[col].mean()
    ev = ev.assign(info=ev[col] - ev["date"].map(mkt), g=ev[col], tk=tick_bp(ev["o1"]), blk=ev["k"] // H)
    b = ev.groupby("blk").agg(date=("date", "first"), i=("info", "mean"), g=("g", "mean"), tk=("tk", "mean"))
    return [(r.date, r.i, r.g, FIXED_BP, FIXED_BP + r.tk) for r in b.itertuples()], ev


def main():
    a = prep(load())
    u = a[a.liq >= LIQ_MIN].copy()
    cells, evs = {}, {}
    for cid in CELLS:
        cells[cid], evs[cid] = events(u, cid, f"r{H}")
    rng = np.random.default_rng(SEED)
    res = family(cells, split, rng, {c: {"long_only": True} for c in CELLS})
    for cid, r in res["cells"].items():
        ev = evs[cid]
        r["events"] = int(len(ev))
        r["names_per_day"] = round(len(ev) / max(1, ev["date"].nunique()), 2)
        if "TRAIN" in r:
            s = r["train_sign"]
            dts = [e[0] for e in cells[cid]]
            g = np.array([e[2] for e in cells[cid]])
            r["yearly_net_bp"] = {int(y): round(float(v), 1) for y, v in
                                  pd.Series(s * g - FIXED_BP, index=pd.to_datetime(dts)).groupby(lambda x: x.year).mean().items()}
            oos = np.array([split(d) != "TRAIN" for d in dts])
            r["oos_gross_bp"] = round(float((s * g[oos]).mean()), 2) if oos.any() else None
            r["breakeven_bp"] = r["oos_gross_bp"]
    rec = {}
    for cid in CELLS:
        rec[cid] = {}
        for col in ("r1", "r20", "rstop"):
            e, _ = events(u, cid, col)
            gg = np.array([x[2] for x in e]); ii = np.array([x[1] for x in e])
            rec[cid][col] = {"n_blocks": len(e), "gross_bp": round(float(gg.mean()), 1), "info_bp": round(float(ii.mean()), 1),
                             "t_info": round(tstat(ii), 2)}
    ca = pd.DataFrame(cells["C"], columns=["d", "i", "g", "c1", "c2"]).set_index("d")["i"]
    aa = pd.DataFrame(cells["A"], columns=["d", "i", "g", "c1", "c2"]).set_index("d")["i"]
    both = (ca - aa).dropna()
    rec["C_minus_A"] = {"n": len(both), "bp": round(float(both.mean()), 1), "t": round(tstat(both.to_numpy()), 2)}
    evA = evs["A"]
    fut = u.set_index(["ticker", "k"])["volume"]
    rec["A_split_like_share"] = None  # 사후 지표 — 아래에서 계산
    try:
        g = u.groupby("ticker")
        fwd20 = g.volume.transform(lambda s: s[::-1].rolling(20, min_periods=20).mean()[::-1].shift(-1))
        back20 = g.volume.transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
        ratio = (fwd20 / back20).reindex(evA.index)
        rec["A_split_like_share"] = round(float((ratio >= 3).mean()), 4)
    except Exception as e:  # noqa: BLE001
        rec["A_split_like_share"] = f"계산 실패: {e}"
    res["record"] = rec
    (HERE / "volume-ma20-results.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("bar", res["bar"], "cost", round(FIXED_BP, 2))
    for cid, r in res["cells"].items():
        if "TRAIN" not in r:
            print(cid, r["verdict"]); continue
        print(f"{cid} {r['verdict']:11s} s{r['train_sign']:+d} tTR {r['t_train']:6.2f} n {r['TRAIN']['n']}/{r['VALID']['n']}/{r['TEST']['n']} "
              f"info {r['TRAIN']['info_bp']}/{r['VALID']['info_bp']}/{r['TEST']['info_bp']} gross {r['TRAIN']['gross_bp']}/{r['VALID']['gross_bp']}/{r['TEST']['gross_bp']} "
              f"net {r['net1_oos_bp']} stress {r['net2_oos_bp']} ev {r['events']} names/d {r['names_per_day']}")
        print("   yearly", r["yearly_net_bp"])
    print("record", json.dumps(rec, ensure_ascii=False))


if __name__ == "__main__":
    main()
