"""시총대비 수급 — 계산 (사전등록 findings/supply-mcap-flow-preregistration-2026-10.md).

    python research/strategy-lab/supply_mcap_flow.py selftest
    python research/strategy-lab/supply_mcap_flow.py run

사전등록·이 파일·탐침이 커밋된 상태가 아니면 수익률을 계산하지 않는다.

구현에서 정한 세부(사전등록에 없는 것, 실행 전 커밋):
- 시가총액 3분위·당일 수익률 5분위 = 그날 적격 종목의 순위 백분위(rank pct)로 자른다(경계 20/40/60/80 과 같은 뜻, 동률은 평균 순위).
- 사건도 당일 수익률(직전 행 필요)이 없으면 매칭 불가 — 사건에서 뺀다(건수 기록).
- 대조 후보는 '그 변형의 비사건'이고 사건 종목 자신은 뺀다. 3개 미만이면 사건 제외. 5개 초과면 무작위 5개(비복원), 3~5개면 전부.
- 셀마다 사건 수익이 없으면(상장 종목 중도절단) 그 셀에서 사건을 뺀다. 대조 수익이 없는 후보는 대조에서 뺀다(3개 미만이면 사건 제외).
- 갭 = 진입 시가 ÷ 신호일 수정종가 − 1(A4 close). 신호일 종가가 없으면 갭 기록에서 뺀다.
"""
from __future__ import annotations

import gzip
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PREREG = HERE / "findings" / "supply-mcap-flow-preregistration-2026-10.md"
PROBE = HERE / "supply_mcap_probe.py"
OUT = HERE / "findings" / "supply-mcap-flow-results-2026-10.json"
C1, C2 = 23.54, 33.5
SEED = 20261001
THR = 0.009
HS = {"A": 1, "B": 3, "C": 20}
VARIANTS = {            # (이름, 사건 열, 임계) — 첫째만 판정
    "core": ("S", 0.009), "th0.5": ("S", 0.005), "th1.5": ("S", 0.015),
    "foreign0.9": ("Sf", 0.009), "inst0.9": ("Si", 0.009),
}


def committed_clean(p: Path) -> bool:
    rel = str(p.relative_to(REPO))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=REPO, capture_output=True).returncode == 0
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return tracked and not dirty


def split(d):
    return "TRAIN" if d.year <= 2020 else ("VALID" if d.year <= 2022 else "TEST")


def load_prices():
    import numpy as np
    import pandas as pd
    P = REPO / "data" / "backfill" / "price"
    rows, delisted = [], set()
    for sub in ("a2a", "a2b"):
        for p in sorted((P / sub).glob("20*.jsonl.gz")):
            for line in gzip.open(p, "rt", encoding="utf-8"):
                r = json.loads(line)
                rows.append((r["ticker"], r["date"], r["open"], r["close"], r["volume"]))
                if sub == "a2b":
                    delisted.add(r["ticker"])
    d = pd.DataFrame(rows, columns=["t", "date", "o", "c", "v"])
    del rows
    d = d[(d.o > 0) & (d.c > 0) & (d.v > 0)].drop_duplicates(["t", "date"])
    d["di"] = d["date"].str.replace("-", "", regex=False).astype(int)
    d = d.sort_values(["t", "di"])
    arr = {t: (g.di.values, g.o.values.astype(float), g.c.values.astype(float)) for t, g in d.groupby("t", sort=False)}
    return arr, delisted


def fwd(arr, delisted, tk, t_di, h):
    """(수익, 진입일 di, 진입 시가, 상태) — 신호일 다음 유효 행 시가 → h−1 행 뒤 종가. 없으면 None."""
    a = arr.get(tk)
    if a is None:
        return None
    di, o, c = a
    i = int(di.searchsorted(t_di, side="right"))
    if i >= len(di):
        return None
    x = i + h - 1
    why = "ok"
    if x >= len(di):
        if tk not in delisted:
            return None
        x, why = len(di) - 1, "delisted"
    return c[x] / o[i] - 1, int(di[i]), float(o[i]), why


def selftest():
    import numpy as np
    arr = {"X": (np.array([20200102, 20200103, 20200106, 20200107]), np.array([10., 11., 12., 13.]), np.array([10.5, 11.5, 12.5, 13.5]))}
    g, e, o, why = fwd(arr, set(), "X", 20200102, 1)
    assert (e, o, why) == (20200103, 11.0, "ok") and abs(g - (11.5 / 11 - 1)) < 1e-12
    g3, *_ = fwd(arr, set(), "X", 20200102, 3)
    assert abs(g3 - (13.5 / 11 - 1)) < 1e-12
    assert fwd(arr, set(), "X", 20200102, 20) is None                       # 상장 종목 중도절단은 뺀다
    g20, _, _, why = fwd(arr, {"X"}, "X", 20200102, 20)
    assert why == "delisted" and abs(g20 - (13.5 / 11 - 1)) < 1e-12         # 폐지는 마지막 종가
    assert fwd(arr, set(), "X", 20200107, 1) is None and fwd(arr, set(), "Y", 20200102, 1) is None
    print("selftest ok")
    return 0


def build_panel():
    import numpy as np
    sys.path.insert(0, str(HERE))
    import supply_mcap_probe as pr
    d = pr.panel()
    d["ret"] = d["close"] / d.groupby("ticker", sort=False)["close"].shift(1) - 1
    d["elig"] = d.shares.notna() & (d.mcap >= 1e11) & (d.px >= 1000) & ~d.ca
    e = d[d.elig]
    pm = e.groupby("date")["mcap"].rank(pct=True)
    pr_ = e.groupby("date")["ret"].rank(pct=True)
    d["mc3"] = -1
    d["rq5"] = -1
    d.loc[e.index, "mc3"] = np.minimum((pm * 3).astype(int), 2)
    d.loc[e.index, "rq5"] = np.where(e.ret.isna(), -1, np.minimum((pr_.fillna(0) * 5).astype(int), 4))
    return d


def run_variant(name, col, thr, d, arr, delisted):
    import numpy as np
    rng = np.random.default_rng(SEED)
    d_elig = d[d.elig]
    isev = (d[col] >= thr).values & d.elig.values
    cand_ok = d.elig.values & ~isev
    key_full, key_size = {}, {}
    for i in np.flatnonzero(cand_ok):
        r_ = d.mc3.values[i]
        if r_ < 0:
            continue
        key_size.setdefault((d.di.values[i], r_), []).append(i)
        q = d.rq5.values[i]
        if q >= 0:
            key_full.setdefault((d.di.values[i], r_, q), []).append(i)
    di_a, tk_a, mc_a, rq_a, cl_a = d.di.values, d.ticker.values, d.mc3.values, d.rq5.values, d.close.values
    rec = Counter()
    rows = []
    for i in np.flatnonzero(isev):
        if rq_a[i] < 0 or mc_a[i] < 0:
            rec["no_ret_event"] += 1
            continue
        pools = {"full": key_full.get((di_a[i], mc_a[i], rq_a[i]), []), "size": key_size.get((di_a[i], mc_a[i]), [])}
        picks = {}
        for m, pool in pools.items():
            pool = [j for j in pool if tk_a[j] != tk_a[i]]
            if len(pool) < 3:
                picks[m] = None
                continue
            picks[m] = list(rng.choice(pool, 5, replace=False)) if len(pool) > 5 else pool
        if picks["full"] is None:
            rec["no_match_full"] += 1
        for h_name, h in HS.items():
            fe = fwd(arr, delisted, tk_a[i], di_a[i], h)
            if fe is None:
                rec[f"event_censored_{h_name}"] += 1
                continue
            if fe[3] == "delisted":
                rec[f"event_delisted_{h_name}"] += 1
            rec_row = {"cell": h_name, "di": fe[1], "g": fe[0] * 1e4, "tk": tk_a[i],
                       "gap": (fe[2] / cl_a[i] - 1) * 1e4 if cl_a[i] > 0 else np.nan, "hit": float(fe[0] > 0)}
            for m, pk in picks.items():
                if pk is None:
                    rec_row[f"info_{m}"] = np.nan
                    continue
                cg = [(x, j) for j in pk if (x := fwd(arr, delisted, tk_a[j], di_a[i], h)) is not None]
                if len(cg) < 3:
                    rec_row[f"info_{m}"] = np.nan
                    continue
                rec_row[f"info_{m}"] = (fe[0] - np.mean([x[0] for x, _ in cg])) * 1e4
                if m == "full":
                    rec_row["cgap"] = np.nanmean([(x[2] / cl_a[j] - 1) * 1e4 for x, j in cg if cl_a[j] > 0])
                    rec_row["chit"] = float(np.mean([x[0] > 0 for x, _ in cg]))
            rows.append(rec_row)
    import pandas as pd
    return pd.DataFrame(rows), rec


def monthly(df, info_col):
    import pandas as pd
    x = df.dropna(subset=[info_col]).copy()
    x["m"] = pd.to_datetime(x.di.astype(str), format="%Y%m%d").dt.to_period("M").dt.to_timestamp()
    return x.groupby("m").agg(info=(info_col, "mean"), g=("g", "mean"), n=("g", "size"))


def cmd_run():
    for p in (PREREG, Path(__file__).resolve(), PROBE):
        if not committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률을 계산하지 않는다")
            return 2
    import numpy as np
    sys.path.insert(0, str(HERE / "futures"))
    from structure_phase4 import family
    from short_horizon_study import tstat

    d = build_panel()
    arr, delisted = load_prices()
    print(f"패널 {len(d):,}행 · 적격 {int(d.elig.sum()):,} · 가격 종목 {len(arr):,}")
    res = {"prereg": PREREG.name, "variants": {}}
    for name, (col, thr) in VARIANTS.items():
        df, rec = run_variant(name, col, thr, d, arr, delisted)
        out = {"params": {"col": col, "thr": thr}, "events_by_cell": {c: int((df.cell == c).sum()) for c in HS}, "counts": dict(rec)}
        mo = {c: monthly(df[df.cell == c], "info_full") for c in HS}
        mo_size = {c: monthly(df[df.cell == c], "info_size") for c in HS}
        if name == "core":
            cells = {c: [(m, r["info"], r["g"], C1, C2) for m, r in mm.iterrows()] for c, mm in mo.items()}
            fam = family(cells, split, np.random.default_rng(SEED), {c: {"long_only": True} for c in HS})
            out["bar"], out["cells"], out["stats"] = fam["bar"], fam["cells"], {}
            for c, mm in mo.items():
                n = {k: int(sum(split(x) == k for x in mm.index)) for k in ("TRAIN", "VALID", "TEST")}
                if n["TRAIN"] < 36 or n["VALID"] < 12 or n["TEST"] < 20:
                    out["cells"][c]["verdict"] = "INCONCLUSIVE(표본 부족)"
                oos = mm[[split(x) != "TRAIN" for x in mm.index]]
                rng = np.random.default_rng(7)
                boot = [rng.choice(oos.g.values, len(oos)).mean() for _ in range(2000)]
                sub = df[df.cell == c]
                out["stats"][c] = {
                    "events": int(len(sub)), "tickers": int(sub.tk.nunique()), "months": n,
                    "event_gross_mean_bp": round(float(sub.g.mean()), 1), "event_info_mean_bp": round(float(sub.info_full.mean()), 1),
                    "oos_gross_month_bp": round(float(oos.g.mean()), 1),
                    "oos_gross_ci95": [round(float(np.quantile(boot, q)), 1) for q in (0.025, 0.975)],
                    "oos_net_month_bp": round(float(oos.g.mean() - C1), 1),
                    "breakeven_cost_roundtrip_bp": round(float(oos.g.mean()), 1),
                    "max_events_per_month": int(mm.n.max()), "top5_month_share": round(float(mm.n.nlargest(5).sum() / mm.n.sum()), 3),
                    "yearly_info_bp": {int(y): round(float(x), 1) for y, x in mm["info"].groupby(mm.index.year).mean().items()},
                    "overnight_gap_bp": {"event": round(float(sub.gap.mean()), 1), "control": round(float(sub.cgap.mean()), 1)},
                    "hit_rate": {"event": round(float(sub.hit.mean()), 3), "control": round(float(sub.chit.mean()), 3)},
                    "date_size_only_control": {k: {"info_bp": round(float(mo_size[c]["info"][[split(x) == k for x in mo_size[c].index]].mean()), 1),
                                                   "t": round(float(tstat(mo_size[c]["info"][[split(x) == k for x in mo_size[c].index]].values)), 2)}
                                               for k in ("TRAIN", "VALID", "TEST")},
                }
        else:                                    # 민감도 — 판정 없이 분할별 평균 정보와 t
            out["record_only"] = {c: {k: {"info_bp": round(float(mm["info"][[split(x) == k for x in mm.index]].mean()), 1),
                                          "t": round(float(tstat(mm["info"][[split(x) == k for x in mm.index]].values)), 2),
                                          "gross_bp": round(float(mm["g"][[split(x) == k for x in mm.index]].mean()), 1)}
                                      for k in ("TRAIN", "VALID", "TEST")} for c, mm in mo.items()}
        res["variants"][name] = out
        print(name, json.dumps({k: out[k] for k in out if k in ("events_by_cell", "counts", "bar", "cells", "record_only")}, ensure_ascii=False, default=str))
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("저장", OUT.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit({"run": cmd_run, "selftest": selftest}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__) or 2)())
