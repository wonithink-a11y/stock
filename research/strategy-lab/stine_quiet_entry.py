"""Stine 조용한 재진입 — 계산 (사전등록 findings/stine-quiet-entry-preregistration-2026-09.md, 30b5b240).

    python research/strategy-lab/stine_quiet_entry.py run

사전등록과 이 파일이 커밋된 상태가 아니면 수익률을 계산하지 않는다.

구현에서 정한 세부(사전등록에 없는 것, 실행 전 커밋):
- 데이터 끝(2026-09)에 열려 있는 상장 종목 거래는 마지막 종가로 평가한다(중도절단, 건수 기록).
- 일봉은 거래량·시가·종가가 모두 양인 날만 주봉에 쓴다(시가 0 행은 정지 표시).
- 대조 종목 수익 = 거래 진입일 이상 첫 시가 → 거래 청산일 이상 첫 시가. 청산일 이후 거래가 없으면 마지막 종가.
- 5분위 경계 = 그 주 후보(거래대금 ≥10억, 그 주 해당 변형의 돌파 사건 없음) 거래대금의 20/40/60/80 백분위.
  거래 종목의 분위 = 신호 주 거래대금을 그 경계에 넣은 자리. 후보에서 거래 종목 자신은 뺀다. 후보가 5개 미만이면 복원 추출, 0 이면 거래 제외(건수 기록).
- 계수 급변 검사는 창 안에 A4 계수가 있는 주가 5개 이상일 때만 한다.
- 정지 창 = 주봉 행 t−20 의 주 시작(주 마감일 −6일) ~ 행 t+6 의 주 마감일.
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
PREREG = HERE / "findings" / "stine-quiet-entry-preregistration-2026-09.md"
OUT = HERE / "findings" / "stine-quiet-entry-results-2026-09.json"
C1, C2 = 23.54, 33.5          # 왕복 bp: 시가 단일가 · 연속 시장(스트레스)
VARIANTS = {"core": (1.6, 5.0), "loose": (1.8, 3.0), "strict": (1.4, 8.0)}
MIN_VAL = 1e9
SEED = 20260923
MAX_HOLD = 65


def committed_clean(p: Path) -> bool:
    rel = str(p.relative_to(REPO))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=REPO, capture_output=True).returncode == 0
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return tracked and not dirty


def split(d):
    return "TRAIN" if d.year <= 2020 else ("VALID" if d.year <= 2022 else "TEST")


def load():
    import numpy as np
    import pandas as pd
    P = REPO / "data" / "backfill"
    rows, delisted = [], set()
    for sub in ("a2a", "a2b"):
        for p in sorted((P / "price" / sub).glob("20*.jsonl.gz")):
            for line in gzip.open(p, "rt", encoding="utf-8"):
                r = json.loads(line)
                rows.append((r["ticker"], r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]))
                if sub == "a2b":
                    delisted.add(r["ticker"])
    d = pd.DataFrame(rows, columns=["t", "date", "o", "h", "l", "c", "v"])
    del rows
    d["date"] = pd.to_datetime(d["date"])
    d = d.drop_duplicates(["t", "date"]).sort_values(["t", "date"], ignore_index=True)
    halt = (d.o == 0) & (d.v == 0)
    prev = halt.groupby(d.t).shift(1, fill_value=False)
    hd = d.loc[halt & prev, ["t", "date"]]
    halts = {t: np.sort(g.date.values) for t, g in hd.groupby("t")}
    am = []
    for p in sorted((P / "supplyDemand" / "a4").glob("20*.jsonl.gz")):
        for line in gzip.open(p, "rt", encoding="utf-8"):
            r = json.loads(line)
            am.append((r["ticker"], r["date"], r["buyAmount"].get("전체")))
    a = pd.DataFrame(am, columns=["t", "date", "amt"])
    del am
    a["date"] = pd.to_datetime(a["date"])
    tr = d[(d.v > 0) & (d.c > 0) & (d.o > 0)].merge(a, on=["t", "date"], how="left")
    tr["f"] = np.where(tr.amt > 0, tr.amt / (tr.c * tr.v), np.nan)
    tr["val"] = tr.c * tr.v
    tr["wk"] = tr.date.dt.to_period("W-FRI")
    w = tr.groupby(["t", "wk"]).agg(o=("o", "first"), h=("h", "max"), l=("l", "min"), c=("c", "last"),
                                    v=("v", "sum"), val=("val", "sum"), od=("date", "first"), end=("date", "last"),
                                    f=("f", "median")).reset_index().sort_values(["t", "wk"], ignore_index=True)
    g = w.groupby("t", group_keys=False)
    w["ma30"] = g.c.transform(lambda s: s.rolling(30).mean())
    w["ma10"] = g.c.transform(lambda s: s.rolling(10).mean())
    w["c1"] = g.c.shift(1)
    w["ma30_1"] = g.ma30.shift(1)
    w["hi12"] = g.h.transform(lambda s: s.shift(1).rolling(12).max())
    w["lo12"] = g.l.transform(lambda s: s.shift(1).rolling(12).min())
    w["v20"] = g.v.transform(lambda s: s.shift(1).rolling(20).mean())
    O = tr.pivot(index="date", columns="t", values="o")
    Cl = tr.pivot(index="date", columns="t", values="c")
    return w, halts, delisted, O, Cl


def run_variant(name, base_w, vmult, w, halts, delisted, O, Cl):
    import numpy as np
    import pandas as pd
    bo = ((w.c > w.ma30) & (w.c1 <= w.ma30_1) & (w.c > w.hi12) & (w.hi12 / w.lo12 <= base_w)
          & (w.v >= vmult * w.v20) & (w.val >= MIN_VAL)).values
    T, o, c, v, ma10, hi, lo, f = (w[k].values for k in ("t", "o", "c", "v", "ma10", "hi12", "lo12", "f"))
    od, end = w.od.values, w.end.values
    starts = np.flatnonzero(np.r_[True, T[1:] != T[:-1]])
    bounds = list(zip(starts, np.r_[starts[1:], len(w)]))
    rec = Counter()

    def simulate(s, b, base_lo, tk):
        e = s + 1
        if e >= b:
            return None
        for k in range(e, b):
            why = ("stop" if c[k] < base_lo else "ma10" if c[k] < ma10[k]
                   else "max" if k - e + 1 >= MAX_HOLD else None)
            if why and k + 1 < b:
                return dict(e=e, x=k + 1, ed=od[e], xd=od[k + 1], g=o[k + 1] / o[e] - 1, why=why, wk=k + 1 - e)
            if why or k == b - 1:
                why = "delisted" if tk in delisted else "censored"
                return dict(e=e, x=k, ed=od[e], xd=end[k], g=c[k] / o[e] - 1, why=why, wk=k - e + 1)
        return None

    trades = {"A": [], "B": []}
    for a, b in bounds:
        tk = T[a]
        hdates = halts.get(tk)
        busy = {"A": -1, "B": -1}
        for i in np.flatnonzero(bo[a:b]) + a:
            lo_r, hi_r = max(a, i - 20), min(b - 1, i + 6)
            if hdates is not None:
                s0 = end[lo_r] - np.timedelta64(6, "D")
                j = np.searchsorted(hdates, s0)
                if j < len(hdates) and hdates[j] <= end[hi_r]:
                    rec["ca_halt"] += 1
                    continue
            fw = f[lo_r:hi_r + 1]
            fw = fw[~np.isnan(fw)]
            if len(fw) >= 5 and fw.max() / fw.min() > 1.5:
                rec["ca_factor"] += 1
                continue
            rec["breakouts"] += 1
            if i >= busy["A"]:
                tA = simulate(i, b, lo[i], tk)
                if tA:
                    trades["A"].append(dict(tA, t=tk, sig=i))
                    busy["A"] = tA["x"]
            if i >= busy["B"]:
                for k in range(2, 7):
                    j = i + k
                    if j >= b:
                        break
                    if (v[j] <= 0.4 * v[i] and abs(c[j] / c[j - 1] - 1) <= 0.03 and abs(c[j - 1] / c[j - 2] - 1) <= 0.03
                            and c[j] >= 0.95 * hi[i] and ma10[j] <= c[j] <= 1.15 * ma10[j]):
                        tB = simulate(j, b, lo[i], tk)
                        if tB:
                            trades["B"].append(dict(tB, t=tk, sig=j))
                            busy["B"] = tB["x"]
                        break

    # 대조 후보: 주별 거래대금 ≥10억 · 그 주 이 변형의 돌파 아님
    cand = w.loc[(w.val >= MIN_VAL) & ~bo, ["wk", "t", "val"]]
    pools = {wk: (gg.t.values, np.quantile(gg.val.values, [0.2, 0.4, 0.6, 0.8]), gg.val.values) for wk, gg in cand.groupby("wk")}
    dates = O.index.values
    Ov, Cv, cols = O.values, Cl.values, {t: i for i, t in enumerate(O.columns)}
    rng = np.random.default_rng(SEED)

    def ret(tk, ed, xd):
        ci = cols[tk]
        i0 = np.searchsorted(dates, ed)
        ok = np.flatnonzero(~np.isnan(Ov[i0:, ci]))
        if not len(ok):
            return np.nan
        p0 = Ov[i0 + ok[0], ci]
        i1 = np.searchsorted(dates, xd)
        ok1 = np.flatnonzero(~np.isnan(Ov[i1:, ci]))
        if len(ok1):
            return Ov[i1 + ok1[0], ci] / p0 - 1
        okc = np.flatnonzero(~np.isnan(Cv[:, ci]))
        return Cv[okc[-1], ci] / p0 - 1

    wk_arr = w.wk.values
    val_arr = w.val.values
    out = {}
    for cid, lst in trades.items():
        rows = []
        for tdct in lst:
            pool = pools.get(wk_arr[tdct["sig"]])
            if pool is None:
                rec[f"{cid}_no_control"] += 1
                continue
            tks, edges, _ = pool
            q = np.searchsorted(edges, val_arr[tdct["sig"]])
            vals = pools[wk_arr[tdct["sig"]]][2]
            qs = np.searchsorted(edges, vals)
            cands = tks[(qs == q) & (tks != tdct["t"])]
            if not len(cands):
                rec[f"{cid}_no_control"] += 1
                continue
            pick = rng.choice(cands, 5, replace=len(cands) < 5)
            cr = np.nanmean([ret(x, tdct["ed"], tdct["xd"]) for x in pick])
            if np.isnan(cr):
                rec[f"{cid}_no_control"] += 1
                continue
            rows.append(dict(t=tdct["t"], ed=pd.Timestamp(tdct["ed"]), g=tdct["g"] * 1e4, info=(tdct["g"] - cr) * 1e4,
                             why=tdct["why"], wk=tdct["wk"]))
        out[cid] = pd.DataFrame(rows)
    return out, dict(rec)


def monthly(df, stress_delisted=False):
    import pandas as pd
    df = df.copy()
    if stress_delisted:
        m = df.why == "delisted"
        df.loc[m, "info"] = df.loc[m, "info"] - df.loc[m, "g"] - 1e4
        df.loc[m, "g"] = -1e4
    df["m"] = df.ed.dt.to_period("M").dt.to_timestamp()
    return df.groupby("m").agg(info=("info", "mean"), g=("g", "mean"), n=("info", "size"))


def cmd_run() -> int:
    for p in (PREREG, Path(__file__).resolve()):
        if not committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률을 계산하지 않는다")
            return 2
    import numpy as np
    sys.path.insert(0, str(HERE / "futures"))
    from structure_phase4 import family
    from short_horizon_study import tstat

    w, halts, delisted, O, Cl = load()
    res = {"prereg": PREREG.name, "variants": {}}
    for name, (bw, vm) in VARIANTS.items():
        tr, rec = run_variant(name, bw, vm, w, halts, delisted, O, Cl)
        mo = {cid: monthly(df) for cid, df in tr.items()}
        cells = {cid: [(m, r["info"], r["g"], C1, C2) for m, r in mm.iterrows()] for cid, mm in mo.items()}
        fam = family(cells, split, np.random.default_rng(SEED), {"A": {"long_only": True}, "B": {"long_only": True}})
        stats = {}
        for cid, df in tr.items():
            mm = mo[cid]
            n = {k: int(sum(split(d) == k for d in mm.index)) for k in ("TRAIN", "VALID", "TEST")}
            if n["TRAIN"] < 36 or n["VALID"] < 12 or n["TEST"] < 20:
                fam["cells"][cid]["verdict"] = "INCONCLUSIVE(표본 부족)"
            oos = mm[[split(d) != "TRAIN" for d in mm.index]]
            rng = np.random.default_rng(7)
            boot = [rng.choice(oos.g.values, len(oos)).mean() for _ in range(2000)]
            st = monthly(df, stress_delisted=True)
            st_tr = st[[split(d) == "TRAIN" for d in st.index]].info.values
            st_oos = st[[split(d) != "TRAIN" for d in st.index]].info.values
            top5 = mm.n.sort_values(ascending=False).head(5).sum() / mm.n.sum()
            stats[cid] = {
                "trades": int(len(df)), "tickers": int(df.t.nunique()), "months": n,
                "max_trades_per_month": int(mm.n.max()), "top5_month_share": round(float(top5), 3),
                "trade_info_mean_bp": round(float(df["info"].mean()), 1), "trade_gross_mean_bp": round(float(df.g.mean()), 1),
                "trade_gross_median_bp": round(float(df.g.median()), 1),
                "oos_gross_month_bp": round(float(oos.g.mean()), 1),
                "oos_gross_ci95": [round(float(np.quantile(boot, q)), 1) for q in (0.025, 0.975)],
                "oos_net_month_bp": round(float(oos.g.mean() - C1), 1),
                "breakeven_cost_roundtrip_bp": round(float(oos.g.mean()), 1),
                "hold_weeks_mean": round(float(df.wk.mean()), 1), "hold_weeks_median": float(df.wk.median()),
                "exit_reasons": dict(Counter(df.why)),
                "yearly_info_bp": {int(y): round(float(x), 1) for y, x in mm.info.groupby(mm.index.year).mean().items()},
                "stress_delisted_minus100": {"t_train": round(tstat(st_tr), 2), "oos_info_bp": round(float(st_oos.mean()), 1)},
            }
        a, b = mo["A"].info, mo["B"].info
        both = (b - a).dropna()
        oosd = both[[split(d) != "TRAIN" for d in both.index]].values
        rng = np.random.default_rng(11)
        bd = [rng.choice(oosd, len(oosd)).mean() for _ in range(2000)] if len(oosd) else [np.nan]
        res["variants"][name] = {
            "params": {"base_width_max": bw, "volume_mult": vm}, "judged": name == "core",
            "bar": fam["bar"], "cells": fam["cells"], "stats": stats, "counts": rec,
            "B_minus_A": {"months_both": int(len(both)),
                          "train_bp": round(float(both[[split(d) == "TRAIN" for d in both.index]].mean()), 1),
                          "oos_bp": round(float(oosd.mean()), 1) if len(oosd) else None,
                          "oos_ci95": [round(float(np.quantile(bd, q)), 1) for q in (0.025, 0.975)]},
        }
        print(name, json.dumps({k: res["variants"][name][k] for k in ("bar", "cells", "B_minus_A", "counts")},
                               ensure_ascii=False, default=str))
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("저장", OUT.relative_to(REPO))
    return 0


if __name__ == "__main__":
    sys.exit({"run": cmd_run}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__) or 2)())
