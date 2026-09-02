#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 0 - 섹터 주도권(Sector Leadership) 신호가 존재하는가.

백테스트를 만들기 전에 IC 로만 판정한다. 이 프로젝트가 반복해서 겪은 순서
문제(전략 먼저 만들고 나서 "이게 모멘텀이랑 같은 거였네"를 발견) 때문에
신호 존재 확인이 먼저다. 게이트 셋을 전부 건다:

  1. 난수 바닥선 - 정답(fwd1m)을 월 내부에서 섞어 같은 절차를 N회 재실행
                   (함정 1: 난수 팩터로 4,845조합을 돌리면 최고가 t=3.21)
  2. TRAIN/VALID/TEST - 패널이 이미 갖고 있는 period 컬럼 그대로
  3. Newey-West t - 월별 IC 계열의 자기상관 보정(naive t 금지)

양방향으로 잰다. KR 은 이 프로젝트 실측상 모멘텀 리버셜 시장이라
("주도섹터 안에서 가장 강한 종목"보다 "아직 안 간 종목"이 나을 수 있다)
부호를 가정하지 않는다.

  python sector_step0.py            # 전체
  python sector_step0.py --selftest # 패널 없이 로직만
"""
import argparse
import json
import os

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(LAB))
PANEL_PATH = os.path.join(LAB, "data", "factor-panel", "kr-monthly-v1.parquet")
ROLLUP_PATH = os.path.join(REPO_ROOT, "config", "sectorGroups.json")
OUT_DIR = os.path.join(LAB, "reports", "2026-09-03-sector-step0")

PERIODS = ["TRAIN", "VALID", "TEST"]
N_SHUFFLE = 20
NW_LAG = 3
MIN_MEMBERS = 5          # 이 미만인 (달, 그룹)은 집계에서 뺀다


def load_rollup():
    with open(ROLLUP_PATH, encoding="utf-8") as f:
        groups = json.load(f)["groups"]
    return {ksic: g for g, ks in groups.items() for ksic in ks}


def nw_tstat(x, lag=NW_LAG):
    """Newey-West 보정 t. 월별 IC 계열처럼 자기상관이 있는 평균에 쓴다."""
    x = np.asarray([v for v in x if np.isfinite(v)], dtype=float)
    n = len(x)
    if n < 3:
        return np.nan
    mu = x.mean()
    e = x - mu
    var = (e @ e) / n
    for lg in range(1, min(lag, n - 1) + 1):
        cov = (e[lg:] @ e[:-lg]) / n
        var += 2.0 * (1.0 - lg / (lag + 1.0)) * cov
    if var <= 0:
        return np.nan
    return mu / np.sqrt(var / n)


def zscore(s):
    sd = s.std(ddof=0)
    return (s - s.mean()) / sd if sd and np.isfinite(sd) and sd > 0 else s * 0.0


def monthly_ic(df, signal, target, by="date"):
    """달마다 Spearman(signal, target) -> 월별 IC 계열."""
    out = {}
    for d, g in df.groupby(by, sort=True):
        g = g[[signal, target]].dropna()
        if len(g) < 5 or g[signal].nunique() < 3:
            continue
        out[d] = g[signal].corr(g[target], method="spearman")
    return pd.Series(out).sort_index()


def evaluate(df, signals, target, label):
    """신호별 x 구간별 mean IC / NW t / 월수."""
    rows = []
    for sig in signals:
        for per in PERIODS:
            ics = monthly_ic(df[df["period"] == per], sig, target)
            if len(ics) < 6:
                continue
            rows.append({"layer": label, "signal": sig, "period": per,
                         "months": int(len(ics)), "meanIC": float(ics.mean()),
                         "t": float(nw_tstat(ics.values))})
    return pd.DataFrame(rows)


def random_floor(df, signals, target, n=N_SHUFFLE, seed=0):
    """정답을 월 내부에서 섞고 같은 절차를 n회 재실행 -> |t| 최댓값의 분포.

    '평가 횟수 보정'이 아니라 절차 전체 재실행이다(함정 2: 빔서치가 전수보다
    바닥선이 높았던 이유 - 탐색 절차 자체가 과최적화 효율을 만든다).
    """
    rng = np.random.default_rng(seed)
    maxima = []
    for _ in range(n):
        d = df.copy()
        d[target] = d.groupby("date")[target].transform(
            lambda s: s.to_numpy()[rng.permutation(len(s))])
        best = 0.0
        for sig in signals:
            for per in PERIODS:
                ics = monthly_ic(d[d["period"] == per], sig, target)
                if len(ics) < 6:
                    continue
                t = nw_tstat(ics.values)
                if np.isfinite(t):
                    best = max(best, abs(t))
        maxima.append(best)
    a = np.array(maxima)
    return {"runs": n, "mean": float(a.mean()), "p50": float(np.percentile(a, 50)),
            "p95": float(np.percentile(a, 95)), "max": float(a.max())}


def build_sector_panel(panel, k2g):
    """종목 패널 -> (달, 그룹) 집계 패널."""
    p = panel.copy()
    p["group"] = p["sector"].map(k2g)
    p = p[p["group"].notna()]
    p["above20"] = (p["ma20_pos"] > 0).astype(float)
    p["above60"] = (p["ma60_pos"] > 0).astype(float)

    agg = p.groupby(["date", "group"]).agg(
        n=("ticker", "size"), period=("period", "first"),
        ret1m=("rev1m", "mean"), ret3m=("mom3m", "mean"), ret6m=("mom6m", "mean"),
        breadth20=("above20", "mean"), breadth60=("above60", "mean"),
        fwd1m=("fwd1m", "mean"),
    ).reset_index()
    agg = agg[agg["n"] >= MIN_MEMBERS].copy()

    # 가속 = 단기 - 장기 (같은 달 안에서 표준화한 뒤 뺀다)
    for a, b, name in [("ret1m", "ret6m", "accel_1m6m"),
                       ("ret1m", "ret3m", "accel_1m3m"),
                       ("breadth20", "breadth60", "breadth_accel")]:
        agg[name] = (agg.groupby("date")[a].transform(zscore)
                     - agg.groupby("date")[b].transform(zscore))
    return agg


def build_stock_signals(panel, k2g):
    p = panel.copy()
    p["group"] = p["sector"].map(k2g)
    p = p[p["group"].notna() & p["fwd1m"].notna()].copy()
    # 시장 전체 기준 가속
    p["accel_mkt"] = (p.groupby("date")["rev1m"].transform(zscore)
                      - p.groupby("date")["mom6m"].transform(zscore))
    # 섹터 내부 기준 가속 (= 업종 등락을 뺀 초과 가속)
    gk = ["date", "group"]
    p["accel_sec"] = (p.groupby(gk)["rev1m"].transform(zscore)
                      - p.groupby(gk)["mom6m"].transform(zscore))
    # 섹터 내부 상대 모멘텀/1개월 (비교 기준선)
    p["sec_rel_mom6m_z"] = p.groupby(gk)["mom6m"].transform(zscore)
    p["sec_rel_rev1m_z"] = p.groupby(gk)["rev1m"].transform(zscore)
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--shuffles", type=int, default=N_SHUFFLE)
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    os.makedirs(OUT_DIR, exist_ok=True)
    k2g = load_rollup()
    panel = pd.read_parquet(PANEL_PATH)
    print("패널 {:,}행 · {}종목 · {}~{}".format(
        panel.shape[0], panel["ticker"].nunique(), panel["date"].min(), panel["date"].max()))

    mapped = panel["sector"].map(k2g)
    cov = {
        "panelRows": int(len(panel)), "panelTickers": int(panel["ticker"].nunique()),
        "rowsWithGroup": int(mapped.notna().sum()),
        "tickersWithGroup": int(panel.loc[mapped.notna(), "ticker"].nunique()),
        "a1bDelistedTickers": 1223, "a1bWithSector": 0,
        "note": "A1b(폐지 1,223종목)에는 sector 필드 자체가 없다 - 섹터 층은 "
                "구조적으로 A1A_ONLY 이고 생존편향을 제거할 방법이 현재 없다.",
    }
    print("그룹 매핑: {:,}행 / {}종목".format(cov["rowsWithGroup"], cov["tickersWithGroup"]))

    sec = build_sector_panel(panel, k2g)
    gpm = sec.groupby("date")["group"].size()
    print("섹터 패널 {:,}행 · 월당 그룹 {}~{}개(중앙 {}) · {}개월".format(
        len(sec), gpm.min(), gpm.max(), int(gpm.median()), sec["date"].nunique()))

    sec_signals = ["ret1m", "ret3m", "ret6m", "accel_1m6m", "accel_1m3m",
                   "breadth20", "breadth_accel"]
    sec_res = evaluate(sec, sec_signals, "fwd1m", "sector")
    print("\n=== 섹터 층: 다음달 섹터 수익률 예측 (NW t) ===")
    print(sec_res.pivot(index="signal", columns="period", values="t")[PERIODS].round(2).to_string())

    print("\n난수 바닥선 ({}회 x 절차 전체 재실행)...".format(args.shuffles))
    sec_floor = random_floor(sec, sec_signals, "fwd1m", n=args.shuffles, seed=11)
    print("섹터 바닥선 |t| : 중앙 {:.2f} · p95 {:.2f} · 최대 {:.2f}".format(
        sec_floor["p50"], sec_floor["p95"], sec_floor["max"]))

    stk = build_stock_signals(panel, k2g)
    stk_signals = ["accel_sec", "accel_mkt", "sec_rel_mom6m_z", "sec_rel_rev1m_z",
                   "mom6m", "rev1m", "dist_52w_high"]
    stk_res = evaluate(stk, stk_signals, "fwd1m", "stock")
    print("\n=== 종목 층: 다음달 종목 수익률 예측 (NW t) ===")
    print(stk_res.pivot(index="signal", columns="period", values="t")[PERIODS].round(2).to_string())

    print("\n난수 바닥선 ({}회)...".format(args.shuffles))
    stk_floor = random_floor(stk, stk_signals, "fwd1m", n=args.shuffles, seed=23)
    print("종목 바닥선 |t| : 중앙 {:.2f} · p95 {:.2f} · 최대 {:.2f}".format(
        stk_floor["p50"], stk_floor["p95"], stk_floor["max"]))

    out = {
        "generatedAt": pd.Timestamp.now().isoformat(timespec="seconds"),
        "coverage": cov,
        "sectorPanel": {"rows": int(len(sec)), "months": int(sec["date"].nunique()),
                        "groupsPerMonthMin": int(gpm.min()), "groupsPerMonthMax": int(gpm.max()),
                        "minMembers": MIN_MEMBERS},
        "sector": {"results": sec_res.to_dict("records"), "randomFloor": sec_floor},
        "stock": {"results": stk_res.to_dict("records"), "randomFloor": stk_floor},
        "method": {"ic": "월별 Spearman", "t": "Newey-West lag={}".format(NW_LAG),
                   "shuffles": args.shuffles,
                   "randomFloor": "fwd1m 을 월 내부에서 섞어 절차 전체를 재실행, |t| 최댓값 분포"},
    }
    path = os.path.join(OUT_DIR, "sector-step0.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", path)


def selftest():
    assert np.isnan(nw_tstat([1.0, 1.0, 1.0]))
    rng = np.random.default_rng(0)
    assert abs(nw_tstat(rng.normal(0, 1, 400))) < 3.0
    assert nw_tstat(rng.normal(0.5, 0.1, 200)) > 10.0

    z = zscore(pd.Series([1.0, 2.0, 3.0]))
    assert abs(z.mean()) < 1e-12 and abs(z.std(ddof=0) - 1) < 1e-12
    assert (zscore(pd.Series([2.0, 2.0])) == 0).all()

    df = pd.DataFrame({"date": ["A"] * 6, "s": list(range(6)), "y": list(range(6))})
    assert abs(monthly_ic(df, "s", "y").iloc[0] - 1.0) < 1e-12
    df2 = df.copy()
    df2["y"] = list(range(6))[::-1]
    assert abs(monthly_ic(df2, "s", "y").iloc[0] + 1.0) < 1e-12
    assert len(monthly_ic(df.head(4), "s", "y")) == 0

    k2g = load_rollup()
    assert len(k2g) == 159, len(k2g)

    ks = list(k2g)[:2]
    rows = []
    for i in range(MIN_MEMBERS + 1):
        rows.append({"date": "2020-01-01", "sector": ks[0], "period": "TRAIN", "ticker": "A%d" % i,
                     "rev1m": 0.1, "mom3m": 0.2, "mom6m": 0.3, "ma20_pos": 1.0,
                     "ma60_pos": -1.0, "fwd1m": 0.05})
    rows.append({"date": "2020-01-01", "sector": ks[1], "period": "TRAIN", "ticker": "B0",
                 "rev1m": 0.1, "mom3m": 0.2, "mom6m": 0.3, "ma20_pos": 1.0,
                 "ma60_pos": 1.0, "fwd1m": 0.05})
    sec = build_sector_panel(pd.DataFrame(rows), k2g)
    assert len(sec) == 1, sec
    assert sec.iloc[0]["breadth20"] == 1.0 and sec.iloc[0]["breadth60"] == 0.0
    assert {"accel_1m6m", "accel_1m3m", "breadth_accel"} <= set(sec.columns)
    print("selftest ok (12건)")


if __name__ == "__main__":
    main()
