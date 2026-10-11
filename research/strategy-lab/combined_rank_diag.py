"""결합 순위 모델 — 사후 점검(판정 불변, 진단 전용). 결과 파일: findings/combined-rank-model-diag-2026-10.json

    python research/strategy-lab/combined_rank_diag.py

1) 특징 미래 누수: 데이터를 신호일 t 까지 자른 뒤 다시 계산한 특징이 전체 데이터 특징과 같은지(3개 날짜).
2) 점수 재현 + 선택 종목 구성: 다음 날 무거래·평탄봉, 폐지 직전(10거래일), 당일 ±25%, 저가, 거래대금 구간.
3) 같은 점수로 유니버스·제외 조건만 바꾼 재선택(거래대금 ≥ 50억·100억, 평탄봉·폐지 직전 제외).
4) 원자료(jsonl) 에서 독립 경로로 3개 날짜 h=1 상위 20 초과를 다시 계산해 대조.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import combined_rank_model as crm  # noqa: E402

OUT = HERE / "findings" / "combined-rank-model-diag-2026-10.json"
SPOT = ["2019-06-14", "2022-03-10", "2025-08-20"]


def leak_test(P_full, meta):
    dates = np.array(meta["dates"])
    full_load = crm.load_dense
    out = {}
    base = full_load()
    for d in SPOT:
        t = int(np.searchsorted(dates, d))

        def trunc():
            dts, tks, C, O, H, L, V, common, isdel = base
            cut = lambda a: np.vstack([a[:t + 1], np.full((1, a.shape[1]), np.nan)])  # noqa: E731
            return np.r_[dts[:t + 1], ["9999-12-31"]], tks, cut(C), cut(O), cut(H), cut(L), cut(V), common, isdel
        crm.load_dense = trunc
        Pt, _ = crm.build_panel()
        crm.load_dense = full_load
        a = P_full[P_full.t == t].set_index("tj")[crm.FEATS]
        b = Pt[Pt.t == t].set_index("tj")[crm.FEATS]
        same_rows = a.index.equals(b.index)
        diff = (a - b.reindex(a.index)).abs()
        both_nan = a.isna() & b.reindex(a.index).isna()
        mism = ((diff > 1e-5) | (a.isna() ^ b.reindex(a.index).isna())) & ~both_nan
        out[d] = {"rows": int(len(a)), "same_rows": bool(same_rows), "max_abs_diff": float(np.nanmax(diff.to_numpy())),
                  "mismatch_cells": int(mism.to_numpy().sum()),
                  "mismatch_by_feature": {k: int(v) for k, v in mism.sum().items() if v}}
        crm.log(f"누수 점검 {d}: 행 {len(a)} · 불일치 {out[d]['mismatch_cells']}")
    return out, base


def stats(series, years, months):
    s = crm.summarize(series, years, months, np.random.default_rng(1))
    return {k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in s["splits"][k].items() if kk in ("days", "mean_bp", "t")}
            for k in ("TRAIN-WF", "VALID", "TEST")} | {"2025~": {kk: round(vv, 2) if isinstance(vv, float) else vv
                                                              for kk, vv in s["periods"]["2025~"].items() if kk in ("days", "mean_bp", "t")}}


def main():
    P, meta = crm.get_panel()
    years, months = np.array(meta["years"]), np.array(meta["months"])
    res = {}
    res["leak"], base = leak_test(P, meta)
    dts, tks, C, O, H, L, V, common, isdel = base
    D, T = C.shape
    valid = ~np.isnan(C)
    last = np.where(valid.any(0), D - 1 - np.argmax(valid[::-1], axis=0), -1)
    med20 = crm.rolling(C * V, 20, 15, "median")
    t = P["t"].to_numpy()
    tj = P["tj"].to_numpy()
    e = np.minimum(t + 1, D - 1)
    flags = pd.DataFrame({
        "v0_next": V[e, tj] == 0,
        "flat_next": (O[e, tj] == H[e, tj]) & (H[e, tj] == L[e, tj]) & (L[e, tj] == C[e, tj]),
        "near_delist": isdel[tj] & (last[tj] - t <= 10),
        "r1_le_m25": P["r1_raw"].to_numpy() <= -0.25,
        "r1_ge_25": P["r1_raw"].to_numpy() >= 0.25,
        "px_lt_1000": C[t, tj] < 1000,
    })
    tv = med20[t, tj]
    flags["tv_10_30"] = tv < 3e9
    flags["tv_30_100"] = (tv >= 3e9) & (tv < 1e10)
    flags["tv_ge_100"] = tv >= 1e10
    cc1 = C[e, tj] / C[t, tj] - 1
    res["universe_flag_share"] = {k: round(float(flags[k][years[t] >= 2018].mean()), 4) for k in flags}
    res["cells"] = {}
    for h in crm.HS:
        cache = crm.CACHE / f"score_h{h}.npy"
        if cache.exists():
            score = np.load(cache)
        else:
            score, _ = crm.walk_forward(P, years, crm.FEATS, h, tag="재현")
            np.save(cache, score)
        top = crm.pick(P, score)
        s, _ = crm.daily_values(P, top, h)
        r = {"reproduced": stats(s, years, months)}
        f = flags.iloc[top]
        exc = P[f"exc{h}"].to_numpy()[top]
        trd = P[f"trd{h}"].to_numpy()[top]
        r["pick_flag_share"] = {k: round(float(f[k].mean()), 4) for k in flags}
        r["pick_excess_by_flag_bp"] = {k: [int(f[k].sum()), round(float(np.nanmean(np.where(trd & f[k].to_numpy(), exc, np.nan))) * 1e4, 1)
                                           if (trd & f[k].to_numpy()).any() else None] for k in flags}
        sel = trd & (years[t[top]] >= 2023)
        x = exc[sel]
        lo, hi = np.percentile(x, [1, 99])
        r["test_per_pick_bp"] = {"n": int(sel.sum()), "mean": round(float(x.mean()) * 1e4, 1), "median": round(float(np.median(x)) * 1e4, 1),
                                 "trim1_mean": round(float(x[(x >= lo) & (x <= hi)].mean()) * 1e4, 1),
                                 "win_rate": round(float((x > 0).mean()), 3)}
        if h == 1:
            mk = P["mkt1"].to_numpy()
            r["picks_test_bp"] = {
                "close_to_close": round(float(np.nanmean(cc1[top][sel])) * 1e4, 1),
                "overnight_gap": round(float(np.nanmean((O[e, tj][top] / C[t, tj][top] - 1)[sel])) * 1e4, 1),
                "open_to_close": round(float(np.nanmean(P["ret1"].to_numpy()[top][sel])) * 1e4, 1),
                "market_open_to_close": round(float(np.nanmean(mk[top][sel])) * 1e4, 1)}
        variants = {
            "tv_ge_50": tv >= 5e9,
            "tv_ge_100": tv >= 1e10,
            "ex_flat_v0_next": ~(flags.flat_next | flags.v0_next).to_numpy(),
            "ex_near_delist": ~flags.near_delist.to_numpy(),
            "ex_both": ~(flags.flat_next | flags.v0_next | flags.near_delist).to_numpy(),
        }
        r["variants"] = {}
        for k, m in variants.items():
            Q = P[m].copy()
            g = Q.groupby("t", sort=False)
            Q[f"exc{h}"] = Q[f"ret{h}"] - g[f"ret{h}"].transform("mean")
            Q = Q.reset_index(drop=True)
            v, _ = crm.daily_values(Q, crm.pick(Q, score[m]), h)
            r["variants"][k] = stats(v, years, months)
            ab, _ = crm.daily_values(Q, crm.pick(Q, score[m]), h, col="ret")
            r["variants"][k]["absolute_TEST_bp"] = stats(ab, years, months)["TEST"]["mean_bp"]
        res["cells"][f"h{h}"] = r
        crm.log(f"h={h} 구성 점검 완료")
    res["spot"] = spot_check(P, meta, np.load(crm.CACHE / "score_h1.npy"))
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    crm.log(f"→ {OUT.name}")
    print(json.dumps(res, ensure_ascii=False, indent=1))


def spot_check(P, meta, score):
    """원자료에서 직접: 적격(20일 거래대금 중앙값 ≥ 10억, 유효 15일) · t+1 시가→종가 · 시장 등가중 · 상위 20 초과."""
    dates = meta["dates"]
    tickers = np.array(meta["tickers"])
    top = crm.pick(P, score)
    out = {}
    need = set()
    idx = {}
    for d in SPOT[1:] + ["2024-11-05"]:
        t = dates.index(d)
        idx[d] = t
        need.update(dates[t - 25:t + 2])
    rows = {}
    for sub in ("a2a", "a2b"):
        for y in sorted({x[:4] for x in need}):
            p = crm.PRICE / sub / f"{y}.jsonl.gz"
            for line in gzip.open(p, "rt", encoding="utf-8"):
                r = json.loads(line)
                if r["date"] in need:
                    rows.setdefault((r["ticker"], r["date"]), r) if sub == "a2b" else rows.__setitem__((r["ticker"], r["date"]), r)
    for d, t in idx.items():
        win = dates[t - 19:t + 1]
        nxt = dates[t + 1]
        tk_all = {k[0] for k in rows if k[1] == d}
        elig, ret = [], {}
        for tk in tk_all:
            vals = [rows[(tk, x)]["close"] * rows[(tk, x)]["volume"] for x in win if (tk, x) in rows and rows[(tk, x)]["close"] > 0]
            if len(vals) >= 15 and np.median(vals) >= 1e9 and rows[(tk, d)]["close"] > 0:
                elig.append(tk)
                n = rows.get((tk, nxt))
                if n and n["open"] > 0 and n["close"] > 0:
                    ret[tk] = n["close"] / n["open"] - 1
        mkt = np.mean(list(ret.values()))
        sel = [i for i in top if P["t"].iat[i] == t]
        picks = tickers[P["tj"].to_numpy()[sel]]
        lim = [tk for tk in picks if tk in ret and rows[(tk, nxt)]["open"] >= rows[(tk, d)]["close"] * crm.LIMIT_OPEN]
        ex = [ret[tk] - mkt for tk in picks if tk in ret and tk not in lim]
        pipe = P.iloc[sel]
        pipe_v = float(pipe.loc[pipe.trd1, "exc1"].mean())
        out[d] = {"eligible_raw": len(elig), "eligible_pipeline": int((P["t"] == t).sum()), "market_raw_bp": round(mkt * 1e4, 2),
                  "market_pipeline_bp": round(float(pipe["mkt1"].iloc[0]) * 1e4, 2) if len(pipe) else None,
                  "top20_excess_raw_bp": round(float(np.mean(ex)) * 1e4, 2), "top20_excess_pipeline_bp": round(pipe_v * 1e4, 2),
                  "picks": picks.tolist()}
        crm.log(f"원자료 대조 {d}: 원자료 {out[d]['top20_excess_raw_bp']} vs 파이프라인 {out[d]['top20_excess_pipeline_bp']}")
    return out


if __name__ == "__main__":
    main()
