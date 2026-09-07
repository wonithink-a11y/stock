#!/usr/bin/env python
"""06 — Quality Composite Factor OOS (2026-09).

실험 설계 (research/strategy-lab/findings/06_quality_composite_oos_2026-09.md)
-------------------------------------------------------------------------
단일 ROE 필터가 아니라 여러 quality 신호를 **사전 정의된 방식**으로 묶었을 때
한국 주식의 횡단면 예측력이 독립적으로 유지되는지 검증한다. 실험 결과를 보고
좋은 quality 변수를 사후 선택하지 않는다.

사전 정의 (성과 계산 **전에** 고정)
------------------------------------
QCOMP = 7개 quality 팩터의 월별 횡단면 pct-rank (각 팩터 자기 non-NaN 집합 안에서,
        sweep_combos.py 랭킹 규약) 방향 적용 후 동일가중 평균:
          roe(high) · op_margin(high) · net_margin(high) · debt_ratio(low)
          · current_ratio(high) · roe_consistency(high) · op_margin_trend(high)
        retention 은 제외 - 데이터 커버리지 60.7%(2026-09-06 probe)로 교집합을
        46%(TRAIN)로 붕괴시켜 월 최소 종목수 게이트가 위험해진다. 성과가 아니라
        커버리지 기준 사전 결정이다.
적격 종목 = 7개 팩터가 전부 non-null 인 liquid 종목 (합에서 NaN 전파).

매개변수 (3구간 고정)
----------------------
- 리밸런스: 월 첫 세션, 다음 영업일 종가 진입 / 익월 첫 세션 종가 청산 (패널 fwd1m)
- 유동성: dv20 >= 1e8 KRW 절대 게이트 (상대 tercile 금지)
- 선택: 랭크합 상위 decile (top 10%), 롱온리, 동일가중
- 최소 종목수: 30 (MIN_NAMES)

비교
-----
1. ROE 단독        — 동일 파이프라인
2. QCOMP (사전정의) — 상위 decile 롱온리 백테스트
3. QCOMP decile spread (D10 - D1, 월별 평균 fwd1m 차) — 통계적 구성물. 이 프로젝트는
   공매도를 production 으로 안 쓰므로 실현 전략이 아니라 진단이다.
4. TEST 오염 확인   — 규칙이 TRAIN 선택이 아니라 사전 정의라 매개변수 고정 그 자체가
   고정. 또한 난수 귀무분포(월내 fwd1m shuffle)로 같은 규칙의 t 운분포를 실측한다.

산출물
-------
  research/strategy-lab/findings/06_quality_composite_oos_2026-09.md
"""
import json
import math
import os

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
PANEL_PATH = os.path.join(LAB, "data", "factor-panel", "kr-monthly-v1.parquet")
MANIFEST_PATH = os.path.join(LAB, "data", "factor-panel", "_manifest_kr_monthly.json")

MIN_NAMES = 30
TOP_QUANTILE = 0.90
ROUNDTRIP_BPS = 30.0          # 랩 표준 왕복비용 (편도 15bp) — 진단용 기준

# 사전 정의된 composite 멤버 (방향 포함)
QCOMP_MEMBERS = [("roe", 1.0), ("op_margin", 1.0), ("net_margin", 1.0),
                 ("debt_ratio", -1.0), ("current_ratio", 1.0),
                 ("roe_consistency", 1.0), ("op_margin_trend", 1.0)]
ROE_ALONE = [("roe", 1.0)]


def build_ranked(panel, members, period):
    """월별 pct-rank(팩터 자기 non-NaN 내) 후 방향 적용, 동일가중 평균.
    반환: DataFrame[ticker, date, fwd1m, score]. score = composite 랭크(양=좋음)."""
    sub = panel[panel["period"] == period].sort_values(["date", "ticker"]).copy()
    rows = []
    for _, g in sub.groupby("date"):
        sc = None
        for f, sign in members:
            r = g[f].rank(pct=True) * sign
            sc = r if sc is None else sc + r
        sc = sc / len(members)
        tmp = pd.DataFrame({
            "ticker": g["ticker"].to_numpy(), "date": g["date"].to_numpy(),
            "fwd1m": g["fwd1m"].to_numpy(), "score": sc.to_numpy(),
        })
        tmp = tmp.dropna(subset=["score", "fwd1m"])
        if len(tmp) >= MIN_NAMES:
            rows.append(tmp)
    out = pd.concat(rows, ignore_index=True)
    return out


def monthly_ic(d):
    ics = []
    for _, g in d.groupby("date"):
        if len(g) >= MIN_NAMES:
            ics.append(g["score"].corr(g["fwd1m"], method="spearman"))
    ics = np.array(ics, dtype=float)
    ics = ics[np.isfinite(ics)]
    t = float(ics.mean() / (ics.std(ddof=1) / math.sqrt(len(ics)))) if len(ics) > 1 else 0.0
    return {"nMonths": len(ics), "meanIC": round(float(ics.mean()), 4),
            "t": round(t, 3)}


def monthly_excess_top_decile(d, topq=TOP_QUANTILE):
    """월별 상위 decile 롱온리 EW 수익과 같은 적격집합 EW 벤치마크와의 차이."""
    gross, bench, months, held = [], [], [], []
    for date, g in d.groupby("date"):
        thr = g["score"].quantile(topq)
        sel = g[g["score"] >= thr]
        if len(sel) == 0 or len(g) == 0:
            continue
        gross.append(float(sel["fwd1m"].mean()))
        bench.append(float(g["fwd1m"].mean()))
        months.append(date)
        held.append(len(sel))
    return {"monthly_gross": np.array(gross), "monthly_bench": np.array(bench),
            "months": months, "avg_held": round(float(np.mean(held)), 1)}


def decile_spread(d):
    """D10 - D1: 월별로 score 를 10개 decile 로 나눈 뒤 평균 fwd1m 차."""
    spreads = []
    for _, g in d.groupby("date"):
        try:
            q = pd.qcut(g["score"].rank(method="first"), 10, labels=False)
        except ValueError:
            continue
        g = g.assign(dec=q)
        g1 = g[g["dec"] == 0]
        g10 = g[g["dec"] == 9]
        if len(g1) == 0 or len(g10) == 0:
            continue
        spreads.append(float(g10["fwd1m"].mean() - g1["fwd1m"].mean()))
    spreads = np.array(spreads, dtype=float)
    spreads = spreads[np.isfinite(spreads)]
    t = float(spreads.mean() / (spreads.std(ddof=1) / math.sqrt(len(spreads)))) if len(spreads) > 1 else 0.0
    return {"nMonths": len(spreads), "spread": round(float(spreads.mean()), 6),
            "t": round(t, 3)}


def turnover_of(d, topq=TOP_QUANTILE):
    rates = []
    prev = None
    for date, g in d.groupby("date"):
        thr = g["score"].quantile(topq)
        cur = set(g.loc[g["score"] >= thr, "ticker"])
        if prev is not None and cur and prev:
            rates.append(1.0 - len(cur & prev) / len(cur))
        prev = cur
    return round(float(np.mean(rates)), 3) if rates else None


def strategy_stats(gross, bench, months, roundtrip_bps=None):
    net = gross - (roundtrip_bps or 0.0) / 10000.0 if roundtrip_bps else gross
    excess = gross - bench
    n = len(net)
    esd = float(excess.std(ddof=1))
    t = float(excess.mean() / (esd / math.sqrt(n))) if esd > 0 else 0.0
    sd = float(net.std(ddof=1))
    eq_tot = float(np.prod(1.0 + net))
    span = n / 12.0
    cagr = eq_tot ** (1.0 / span) - 1.0 if eq_tot > 0 else float("nan")
    sharpe = float(net.mean() / sd * math.sqrt(12)) if sd > 0 else 0.0
    peak, cum, mdd = 1.0, 1.0, 0.0
    for r in net:
        cum *= (1.0 + r)
        peak = max(peak, cum)
        mdd = min(mdd, cum / peak - 1.0)
    years = np.array([m[:4] for m in months])
    tot = float(excess.sum())
    max_year_pct = None
    if tot > 0:
        by = {y: float(excess[years == y].sum()) for y in np.unique(years)}
        max_year_pct = round(100.0 * max(by.values()) / tot, 1)
    return {"nMonths": n, "excessT": round(t, 3),
            "meanExcessPct": round(float(excess.mean()) * 100, 3),
            "meanNetPct": round(float(net.mean()) * 100, 3),
            "cagr": round(cagr * 100, 2), "sharpe": round(sharpe, 3),
            "mdd": round(mdd * 100, 1), "winRate": round(float((net > 0).mean()) * 100, 1),
            "maxSingleYearPct": max_year_pct,
            "totalReturn": round((eq_tot - 1.0) * 100, 2)}


def null_excess_t(panel, members, periods, reps=200, seed=20260906):
    """월 내부 fwd1m shuffle 후 같은 규칙의 상위 decile 초과 t — '이 규칙을 그대로 썼을 때
    운으로 나올 수 있는 t' 분포. 팩터 랭크 구조는 보존, 정답만 섞는다."""
    rng = np.random.default_rng(seed)
    res = {}
    for period in periods:
        sub = panel[panel["period"] == period].sort_values(["date", "ticker"]).copy()
        score = []
        for _, g in sub.groupby("date"):
            sc = None
            for f, sign in members:
                r = g[f].rank(pct=True) * sign
                sc = r if sc is None else sc + r
            score.append((sc / len(members)).to_numpy())
        rank_valid = np.concatenate(score)
        orig_fwd = sub["fwd1m"].to_numpy(copy=True)
        date_groups = sub.groupby("date", sort=True).indices
        dates = sorted(date_groups.keys())
        ts = []
        for rep in range(reps):
            shuffled = orig_fwd.copy()
            for d in dates:
                idx = date_groups[d]
                if len(idx) > 1:
                    shuffled[idx] = shuffled[idx[rng.permutation(len(idx))]]
            ts.append(_topdecile_t(rank_valid, shuffled, date_groups, dates))
        res[period] = {"nullT": ts,
                       "median": round(float(np.median(ts)), 3),
                       "p95": round(float(np.quantile(ts, 0.95)), 3),
                       "max": round(float(np.max(ts)), 3)}
    return res


def _topdecile_t(score, fwd, date_groups, dates):
    gross, bench = [], []
    for d in dates:
        idx = date_groups[d]
        s = score[idx]
        f = fwd[idx]
        v = ~np.isnan(s) & ~np.isnan(f)
        if v.sum() < MIN_NAMES:
            continue
        s, f = s[v], f[v]
        thr = np.quantile(s, TOP_QUANTILE)
        sel = s >= thr
        if sel.sum() == 0:
            continue
        gross.append(float(f[sel].mean()))
        bench.append(float(f.mean()))
    gross, bench = np.array(gross), np.array(bench)
    n = len(gross)
    exc = gross - bench
    if n < 2 or exc.std(ddof=1) == 0:
        return 0.0
    return float(exc.mean() / (exc.std(ddof=1) / math.sqrt(n)))


def main():
    panel = pd.read_parquet(PANEL_PATH)
    panel = panel[panel["liquid"]].copy()
    manifest = json.load(open(MANIFEST_PATH, encoding="utf-8"))
    print(f"패널 {len(panel):,}행 (liquid), {manifest['panelVersion']}", flush=True)

    out = {"experiment": "QUALITY-COMPOSITE-OOS-KR",
           "panelVersion": manifest["panelVersion"],
           "date": "2026-09-06",
           "members": [f"{f}({'high' if s > 0 else 'low'})" for f, s in QCOMP_MEMBERS],
           "preSpecified": "composite 멤버·가중·decile·3구간 분할 전부 성과 계산 전 고정. "
                           "retention 은 커버리지 60.7% 로 교집합 붕괴(46% TRAIN)우려라 제외 - "
                           "성과 기준 아님.",
           "conventions": "포털 scan_combos와 동일: 팩터별 자기 non-NaN 내 pct-rank, "
                          "동일가중 평균, 적격=전 팩터 존재, dv20>=1e8 절대 게이트, "
                          "월 리밸런스, top decile 롱온리, min_names=30"}

    print("\n=== 1/2. IC + backtest: ROE 단독 vs QCOMP ===")
    for label, members in (("ROE", ROE_ALONE), ("QCOMP", QCOMP_MEMBERS)):
        row = {"label": label, "periods": {}}
        print(f"\n--- {label} ---")
        for period in ["TRAIN", "VALID", "TEST"]:
            d = build_ranked(panel, members, period)
            ic = monthly_ic(d)
            ex = monthly_excess_top_decile(d)
            spr = decile_spread(d)
            tv = turnover_of(d)
            st = strategy_stats(ex["monthly_gross"], ex["monthly_bench"], ex["months"],
                                roundtrip_bps=ROUNDTRIP_BPS)
            st["turnover"] = tv
            row["periods"][period] = {
                "ic": ic, "spreadD10D1": spr, "strategy": st,
                "avgHeld": ex["avg_held"]}
            print(f"  {period:>5} IC {ic['meanIC']:+.4f} (t {ic['t']:+.2f}) | "
                  f"spread(D10-D1) {spr['spread']*100:+.3f}% (t {spr['t']:+.2f}) | "
                  f"top-decile: 초과 {st['meanExcessPct']:+.3f}%/월(t {st['excessT']:+.2f}) | "
                  f"CAGR {st['cagr']:+.2f}% Sharpe {st['sharpe']:.2f} MDD {st['mdd']:.1f}% "
                  f"승률 {st['winRate']:.0f}% n {st['nMonths']} | turnover {tv}")
        out["rows"].append(row) if "rows" in out else out.update(rows=[row])

    print("\n=== 3. QCOMP 난수 귀무분포 (월내 fwd1m shuffle, 같은 규칙, 200회) ===")
    nulls = null_excess_t(panel, QCOMP_MEMBERS, ["TRAIN", "VALID", "TEST"],
                          reps=200, seed=20260906)
    for period, nr in nulls.items():
        print(f"  {period}: null t 중앙 {nr['median']:+.2f} / p95 {nr['p95']:+.2f} / max {nr['max']:+.2f}")
    out["nullShuffle"] = nulls

    summary = {p: out["rows"][1]["periods"][p] for p in ["TRAIN", "VALID", "TEST"]}

    # verdict 저장은 findings 파일에서 사람이, 여기는 json 만
    out_path = os.path.join(LAB, "reports", "2026-09-06-quality-composite-oos",
                            "quality-composite-oos.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {out_path}")


if __name__ == "__main__":
    main()