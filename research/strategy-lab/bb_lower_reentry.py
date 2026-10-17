"""볼린저 하단 재진입 · Williams %R 과매도 탈출 — 계산 (사전등록 findings/bb-lower-reentry-preregistration-2026-10.md).

    python research/strategy-lab/bb_lower_reentry.py selftest
    python research/strategy-lab/bb_lower_reentry.py count    # 사건 수·V3/5DC 겹침만(수익률 없음)
    python research/strategy-lab/bb_lower_reentry.py run      # 사전등록·이 파일이 커밋된 상태에서만

사전등록에 없는 구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다):
- 일봉 = A2a+A2b, 시가·종가·거래량이 모두 양인 행만(정지 행은 밴드·평균에서 빠진다). 밴드는 그 종목 유효 행 20개(당일 포함).
- 표준편차는 모집단(ddof=0, 통상 볼린저 정의). V3 연구는 ddof=1 이었다 — 밴드 폭 차이 √(20/19) ≈ 2.6%.
- 직전 5일 수익률 = c_t / c_{t−5 행} − 1. 시총 3분위·5일 수익률 5분위 = 그날 적격 종목 순위 백분위(rank pct).
- 군집 제거는 적격 사건에만: 같은 종목에서 마지막으로 센 사건 행 + 20 행 안의 새 사건은 세지 않는다.
- 신호 4개: B1 재진입 · B2 = B1 ∧ c_t > 200행 이평 · W1 = %R(14) t−1 ≤ −80 ∧ t > −80 · W2 = W1 ∧ c_t > 200행 이평.
  %R = −100 × (14행 최고 고가 − 종가) / (14행 최고 고가 − 14행 최저 저가), 고가 = 저가면 결측. 이평 = 유효 행 200개 종가 평균(모자라면 결측 → B2·W2 아님).
- 대조 후보 = 같은 날·같은 시총 3분위·같은 5일 수익률 5분위의 적격 종목 중 그날 **그 셀의 신호 조건**을 만족하지 않는 종목(자기 제외).
  5개 초과면 무작위 5개, 3개 미만이면 사건 제외. 대조 수익이 없는 후보는 빼고 3개 미만이면 사건 제외.
- 진입·청산 = supply_mcap_flow.fwd (신호일 다음 유효 행 시가 → h−1 행 뒤 종가; 상장 종목 중도절단은 뺀다, 폐지는 마지막 종가).
- 월 = 진입월. 판정은 structure_phase4.family(long_only=True), 공식 셀 {B1,B2,W1,W2}×{h5,h10,h20} 12개 · 바닥선 하나, 비용 c1 = c2 = 33.5bp.
- gross 신뢰구간 = 월 평균 gross 를 월 단위로 부트스트랩(2,000회) — 같은 날 사건끼리의 상관을 월 묶음으로 흡수.
- CCI(5DC 겹침 점검용) = 전형가 (H+L+C)/3, 20행 단순평균, 평균절대편차, 상수 0.015. RSI = 14행 Wilder.
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))

PREREG = HERE / "findings" / "bb-lower-reentry-preregistration-2026-10.md"
OUT = HERE / "findings" / "bb-lower-reentry-results-2026-10.json"
COST, COST_REF = 33.5, 23.54
SEED = 20261017
N, K = 20, 2.0
DEDUP_ROWS = 20
MIN_DV, MIN_PX = 5e8, 1000
START = 20160104                       # A4(시총) 첫날
HS = (5, 10, 20)
SIGNALS = ("B1", "B2", "W1", "W2")
ERAS = (("2016~23", 2016, 2023), ("2024", 2024, 2024), ("2025~", 2025, 2100))


def split(d):
    return "TRAIN" if d.year <= 2020 else ("VALID" if d.year <= 2022 else "TEST")


def committed_clean(p: Path) -> bool:
    from supply_mcap_flow import committed_clean as cc
    return cc(p)


def features(d):
    """d: t,di,o,h,l,c,v (종목·날짜 정렬). 밴드·재진입·5일 수익률·거래대금·RSI·CCI 열을 붙인다."""
    import numpy as np
    g = d.groupby("t", sort=False)
    d["mid"] = g.c.transform(lambda s: s.rolling(N).mean())
    d["sd"] = g.c.transform(lambda s: s.rolling(N).std(ddof=0))
    d["L"] = d.mid - K * d.sd
    below = d.c < d.L
    prev_below = below.groupby(d.t, sort=False).shift(1, fill_value=False)
    d["re"] = prev_below & (d.c >= d.L) & d.L.notna()
    hh = g.h.transform(lambda s: s.rolling(14).max())
    ll = g.l.transform(lambda s: s.rolling(14).min())
    wr = -100 * (hh - d.c) / (hh - ll).replace(0, np.nan)
    wr1 = wr.groupby(d.t, sort=False).shift(1)
    up200 = d.c > g.c.transform(lambda s: s.rolling(200).mean())
    d["B1"] = d.re
    d["B2"] = d.re & up200
    d["W1"] = (wr1 <= -80) & (wr > -80)
    d["W2"] = d.W1 & up200
    d["r5"] = d.c / g.c.shift(5) - 1
    d["dv20"] = (d.c * d.v).groupby(d.t, sort=False).transform(lambda s: s.shift(1).rolling(20).mean())
    # V3: low < L ∧ RSI14 ≤ 30
    diff = g.c.diff()
    up = diff.clip(lower=0).groupby(d.t, sort=False).transform(lambda s: s.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean())
    dn = (-diff).clip(lower=0).groupby(d.t, sort=False).transform(lambda s: s.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean())
    rsi = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    rsi = rsi.where(dn > 0, 100.0)
    d["v3"] = (d.l < d.L) & (rsi <= 30)
    # 5DC: c > mid ∧ CCI_{t−1} ≤ −100 ∧ CCI_t > −100
    tp = (d.h + d.l + d.c) / 3
    sma = tp.groupby(d.t, sort=False).transform(lambda s: s.rolling(20).mean())
    from numpy.lib.stride_tricks import sliding_window_view
    md = np.full(len(d), np.nan)
    tpv = tp.values
    starts = np.flatnonzero(np.r_[True, d.t.values[1:] != d.t.values[:-1]])
    for a, b in zip(starts, np.r_[starts[1:], len(d)]):
        if b - a >= 20:
            w = sliding_window_view(tpv[a:b], 20)
            md[a + 19:b] = np.abs(w - w.mean(axis=1, keepdims=True)).mean(axis=1)
    cci = (tp - sma) / (0.015 * md)
    cci1 = cci.groupby(d.t, sort=False).shift(1)
    d["dc5"] = (d.c > d.mid) & (cci1 <= -100) & (cci > -100)
    return d


def load_panel():
    import numpy as np
    import pandas as pd
    P = REPO / "data" / "backfill" / "price"
    rows, delisted = [], set()
    for sub in ("a2a", "a2b"):
        for p in sorted((P / sub).glob("20*.jsonl.gz")):
            for line in gzip.open(p, "rt", encoding="utf-8"):
                r = json.loads(line)
                rows.append((r["ticker"], r["date"], r["open"], r["high"], r["low"], r["close"], r["volume"]))
                if sub == "a2b":
                    delisted.add(r["ticker"])
    d = pd.DataFrame(rows, columns=["t", "date", "o", "h", "l", "c", "v"])
    del rows
    d = d[(d.o > 0) & (d.c > 0) & (d.v > 0)].drop_duplicates(["t", "date"])
    d["di"] = d["date"].str.replace("-", "", regex=False).astype(int)
    d = d.sort_values(["t", "di"], ignore_index=True)
    for k in ("o", "h", "l", "c", "v"):
        d[k] = d[k].astype(float)
    d = features(d)
    import supply_mcap_probe as pr
    m = pr.panel()[["ticker", "di", "mcap", "px", "ca"]].rename(columns={"ticker": "t"})
    d = d.merge(m, on=["t", "di"], how="left")
    base = (d.di >= START) & d.r5.notna() & (d.dv20 >= MIN_DV)
    d["elig_p"] = base & d.mcap.notna() & (d.px >= MIN_PX) & (d.ca == False)   # noqa: E712 (NaN → False)
    d["elig_r"] = base                                                          # 기록용: 폐지 포함, 시총 없이
    d["di_"] = d.di
    for tag, size_col in (("p", "mcap"), ("r", "dv20")):
        e = d[d[f"elig_{tag}"]]
        s3 = np.minimum((e.groupby("di")[size_col].rank(pct=True) * 3).astype(int), 2)
        q5 = np.minimum((e.groupby("di")["r5"].rank(pct=True) * 5).astype(int), 4)
        d[f"s3_{tag}"], d[f"q5_{tag}"] = -1, -1
        d.loc[e.index, f"s3_{tag}"] = s3
        d.loc[e.index, f"q5_{tag}"] = q5
    arr = {t: (x.di.values, x.o.values, x.c.values) for t, x in d.groupby("t", sort=False)}
    return d, arr, delisted


def events(d, sig, tag, rec):
    """적격 신호 사건 행 번호(군집 제거 뒤)."""
    import numpy as np
    T = d.t.values
    out, last_t, last_i = [], None, -10**9
    for i in np.flatnonzero((d[sig] & d[f"elig_{tag}"]).values):
        if T[i] == last_t and i - last_i < DEDUP_ROWS:
            rec[f"cluster_{sig}_{tag}"] += 1
            continue
        out.append(int(i))
        last_t, last_i = T[i], i
    return out


def overlap(d, evs):
    """V3·5DC·B1·W1 과의 겹침(수익률 없음). 같은 종목 행 기준."""
    T, v3, dc, b1, w1 = d.t.values, d.v3.values, d.dc5.values, d.B1.values, d.W1.values
    n = len(evs)
    c = Counter()
    for i in evs:
        c["v3_prev1"] += bool(i >= 1 and T[i - 1] == T[i] and v3[i - 1])
        c["v3_prev5"] += any(T[j] == T[i] and v3[j] for j in range(max(0, i - 5), i))
        c["dc5_same"] += bool(dc[i])
        c["dc5_next20"] += any(T[j] == T[i] and dc[j] for j in range(i + 1, min(len(T), i + 21)))
        c["B1_same"] += bool(b1[i])
        c["W1_same"] += bool(w1[i])
    return {"events": n, **{k: f"{v} ({v / max(n, 1):.1%})" for k, v in c.items()}}


def returns(d, arr, delisted, evs, sig, tag, rec):
    import numpy as np
    from supply_mcap_flow import fwd
    rng = np.random.default_rng(SEED)
    di_a, tk_a = d.di.values, d.t.values
    s3, q5 = d[f"s3_{tag}"].values, d[f"q5_{tag}"].values
    key = defaultdict(list)
    for i in np.flatnonzero((d[f"elig_{tag}"] & ~d[sig]).values):
        key[(di_a[i], s3[i], q5[i])].append(i)
    rows = []
    for i in evs:
        pool = [j for j in key.get((di_a[i], s3[i], q5[i]), []) if tk_a[j] != tk_a[i]]
        if len(pool) < 3:
            rec[f"no_match_{sig}_{tag}"] += 1
            continue
        pick = list(rng.choice(pool, 5, replace=False)) if len(pool) > 5 else pool
        for h in HS:
            fe = fwd(arr, delisted, tk_a[i], di_a[i], h)
            if fe is None:
                rec[f"censored_{sig}_{tag}_h{h}"] += 1
                continue
            cg = [x[0] for j in pick if (x := fwd(arr, delisted, tk_a[j], di_a[i], h)) is not None]
            if len(cg) < 3:
                rec[f"no_match_{sig}_{tag}_h{h}"] += 1
                continue
            rows.append({"sig": sig, "h": h, "di": fe[1], "tk": tk_a[i], "g": fe[0] * 1e4, "info": (fe[0] - float(np.mean(cg))) * 1e4,
                         "hit": float(fe[0] > 0), "chit": float(np.mean([x > 0 for x in cg])), "delisted": fe[3] == "delisted"})
    import pandas as pd
    return pd.DataFrame(rows)


def monthly(df):
    import pandas as pd
    x = df.copy()
    x["m"] = pd.to_datetime(x.di.astype(str), format="%Y%m%d").dt.to_period("M").dt.to_timestamp()
    return x.groupby("m").agg(info=("info", "mean"), g=("g", "mean"), n=("g", "size"))


def era_table(df):
    import numpy as np
    from short_horizon_study import tstat
    mm = monthly(df) if len(df) else None
    out = {}
    for name, a, b in ERAS:
        if mm is None:
            out[name] = None
            continue
        s = mm[(mm.index.year >= a) & (mm.index.year <= b)]
        out[name] = {"events": int(s.n.sum()), "months": int(len(s)), "info_bp": round(float(s["info"].mean()), 1) if len(s) else None,
                     "t_info": round(float(tstat(s["info"].values)), 2), "gross_bp": round(float(s.g.mean()), 1) if len(s) else None,
                     "net_bp": round(float(s.g.mean() - COST), 1) if len(s) else None}
    return out


def boot_ci(x, seed=7):
    import numpy as np
    rng = np.random.default_rng(seed)
    b = [rng.choice(x, len(x)).mean() for _ in range(2000)]
    return [round(float(np.quantile(b, q)), 1) for q in (0.025, 0.975)]


def summarize(dfp, dfr, semi):
    import numpy as np
    from structure_phase4 import family
    from short_horizon_study import tstat
    keys = [(s, h) for s in SIGNALS for h in HS]
    sub_of = lambda df, s, h: df[(df.sig == s) & (df.h == h)] if len(df) else df
    mo = {k: monthly(sub_of(dfp, *k)) for k in keys}
    cells = {f"{s}_h{h}": [(m, r["info"], r["g"], COST, COST) for m, r in mo[(s, h)].iterrows()] for s, h in keys}
    fam = family(cells, split, np.random.default_rng(SEED), {c: {"long_only": True} for c in cells})
    out = {"bar": fam["bar"], "cells": {}}
    for s, h in keys:
        c = f"{s}_h{h}"
        v = dict(fam["cells"][c])
        sub, mm = sub_of(dfp, s, h), mo[(s, h)]
        oos = mm[[split(x) != "TRAIN" for x in mm.index]]
        ev_n = {k: int(mm.n[[split(x) == k for x in mm.index]].sum()) for k in ("TRAIN", "VALID", "TEST")}
        if min(ev_n.values()) < 100:
            v["verdict"] = "INCONCLUSIVE(표본 부족)"
        sx = sub[~sub.tk.isin(semi)]
        rr = sub_of(dfr, s, h)
        mr = monthly(rr) if len(rr) else None
        by = lambda m, col, f=lambda x: round(float(x.mean()), 1): {k: f(m[col][[split(x) == k for x in m.index]]) for k in ("TRAIN", "VALID", "TEST")}
        tby = lambda m: {k: round(float(tstat(m["info"][[split(x) == k for x in m.index]].values)), 2) for k in ("TRAIN", "VALID", "TEST")}
        v["stats"] = {
            "events": int(len(sub)), "tickers": int(sub.tk.nunique()), "events_by_split": ev_n,
            "months_by_split": {k: int(sum(split(x) == k for x in mm.index)) for k in ("TRAIN", "VALID", "TEST")},
            "gross_month_bp": round(float(mm.g.mean()), 1), "gross_month_ci95": boot_ci(mm.g.values),
            "oos_gross_month_bp": round(float(oos.g.mean()), 1), "oos_gross_ci95": boot_ci(oos.g.values),
            "oos_net_bp_33.5": round(float(oos.g.mean() - COST), 1), "oos_net_bp_23.54_ref": round(float(oos.g.mean() - COST_REF), 1),
            "breakeven_cost_bp": round(float(oos.g.mean()), 1),
            "info_mean_month_bp": round(float(mm["info"].mean()), 1), "info_ci95": boot_ci(mm["info"].values),
            "info_by_split_bp": by(mm, "info"), "t_by_split": tby(mm), "gross_by_split_bp": by(mm, "g"),
            "yearly_info_bp": {int(y): round(float(x), 1) for y, x in mm["info"].groupby(mm.index.year).mean().items()},
            "hit_rate": {"event": round(float(sub.hit.mean()), 3), "control": round(float(sub.chit.mean()), 3)},
            "eras": era_table(sub), "eras_ex_semis": era_table(sx), "ex_semis_events": int(len(sx)),
            "record_delisted_incl": {"events": int(len(rr)), "delisted_exits": int(rr.delisted.sum()) if len(rr) else 0,
                                     "info_by_split_bp": by(mr, "info") if mr is not None else None,
                                     "t_by_split": tby(mr) if mr is not None else None, "eras": era_table(rr)},
        }
        out["cells"][c] = v
    return out


def semi_set():
    import pandas as pd
    from diag_regime_semis import semi_set as ss
    return ss(pd.read_parquet(HERE / "data" / "factor-panel" / "kr-monthly-v1.parquet", columns=["ticker", "sector"]))


def cmd_count():
    d, arr, delisted = load_panel()
    rec = Counter()
    for s in SIGNALS:
        ep, er = events(d, s, "p", rec), events(d, s, "r", rec)
        yr = Counter(int(d.di.values[i] // 10000) for i in ep)
        print(s, "primary", len(ep), "tickers", len(set(d.t.values[ep])), dict(sorted(yr.items())))
        print(s, "record(delisted incl.)", len(er), "delisted tickers", len({d.t.values[i] for i in er} & delisted))
        print(s, "overlap", json.dumps(overlap(d, ep), ensure_ascii=False))
    print("rec", dict(rec))
    print("rows v3", int(d.v3.sum()), "dc5", int(d.dc5.sum()), "B1", int(d.B1.sum()), "W1", int(d.W1.sum()))
    return 0


def cmd_run():
    for p in (PREREG, Path(__file__).resolve()):
        if not committed_clean(p):
            print(f"중단: {p.name} 이 커밋되지 않았거나 수정됐다 — 사전등록·코드 커밋 뒤에만 계산한다")
            return 2
    import pandas as pd
    d, arr, delisted = load_panel()
    rec = Counter()
    dfp, dfr, ov = [], [], {}
    for s in SIGNALS:
        ep, er = events(d, s, "p", rec), events(d, s, "r", rec)
        ov[s] = overlap(d, ep)
        dfp.append(returns(d, arr, delisted, ep, s, "p", rec))
        dfr.append(returns(d, arr, delisted, er, s, "r", rec))
    out = summarize(pd.concat(dfp, ignore_index=True), pd.concat(dfr, ignore_index=True), semi_set())
    out["rec"], out["overlap"], out["prereg"] = dict(rec), ov, PREREG.name
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("bar", out["bar"])
    for c, v in out["cells"].items():
        s = v["stats"]
        print(c, v["verdict"], "events", s["events"], "oos gross", s["oos_gross_month_bp"], s["oos_gross_ci95"],
              "net33.5", s["oos_net_bp_33.5"], "t", s["t_by_split"], "info", s["info_by_split_bp"])
    print("저장", OUT.relative_to(REPO))
    return 0


def selftest():
    import numpy as np
    import pandas as pd
    n = 60
    c = np.full(n, 100.0) + np.sin(np.arange(n)) * 0.5      # 잔잔한 진동
    c[30] = 90.0                                            # 하단 아래로
    c[31] = 99.5                                            # 다음 날 안으로 → 재진입
    c[33] = 90.0                                            # 2 행 뒤 다시 이탈
    c[34] = 99.5                                            # 재진입이지만 20 행 안 → 군집 제거
    d = pd.DataFrame({"t": "X", "di": np.arange(20200101, 20200101 + n), "o": c, "h": c + 0.5, "l": c - 0.5, "c": c, "v": 1e7})
    d = features(d)
    re = list(np.flatnonzero(d.re.values))
    assert re == [31, 34], re
    assert d.c[30] < d.L[30] and d.c[31] >= d.L[31]
    assert not d.re[30] and not d.re[32]
    d["elig_x"] = True
    rec = Counter()
    assert events(d, "B1", "x", rec) == [31] and rec["cluster_B1_x"] == 1
    assert d.W1[31] and not d.W1[30] and not d.B2.any()        # %R 탈출 · 200행 이평 없으면 B2 아님
    # 밴드 = 모집단 표준편차
    w = c[11:31]
    assert abs(d.L[30] - (w.mean() - 2 * w.std(ddof=0))) < 1e-9
    print("selftest ok")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit({"selftest": selftest, "count": cmd_count, "run": cmd_run}.get(cmd, lambda: print(__doc__) or 1)())
