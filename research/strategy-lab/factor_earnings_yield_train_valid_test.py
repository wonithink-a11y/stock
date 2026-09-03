#!/usr/bin/env python
"""factor_earnings_yield_train_valid_test.py — earnings_yield의 IC/decile slope를
TRAIN/VALID/TEST로 쪼개서 재계산한다.

배경: factor-earnings-yield-portfolio-validation-2026-08.md가 "Periods: TRAIN
46063, VALID 13713, TEST 23312"라고 구간 개수만 적어두고, IC t=6.10·decile
slope 0.867 같은 핵심 통계는 전체기간 풀링값이었다 - TEST(진짜 out-of-sample)
구간만 따로 봤을 때도 신호가 살아있는지 이 프로젝트 표준 검증(REV20·Opening
Fade·PBR이 반복해서 요구해 온 것)이 빠져 있었다.

factor_discovery_kr.py의 decile_analysis()를 그대로 재사용한다(새 계산식을
안 만든다 - 같은 함수를 쓰면 전체기간 수치와 자동으로 비교 가능해진다).
base 구성도 그 파일의 로직을 그대로 따르되, earnings_yield에 필요 없는
A3 성장·품질 팩터 루프는 건너뛴다(속도 - per만 있으면 된다).
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import factor_discovery_kr as fd  # noqa: E402

OUT_DIR = os.path.join(fd.LAB, "reports", "2026-09-02-earnings-yield-oos-split")


def build_base():
    t0 = time.time()
    print("loading A4 ...", flush=True)
    df = pd.read_parquet(fd.A4_PATH, columns=["ticker", "date", "close", "total_amount"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers", flush=True)

    g = df.groupby("ticker", sort=False)
    df["dv20"] = g["total_amount"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["liquid"] = df["dv20"] >= fd.LIQUID_THRESHOLD

    all_dates = sorted(df["date"].unique())
    months = fd.monthly_reb(all_dates)
    base = df[df["date"].isin(months)].copy()
    print(f"base rows {len(base)}, months {len(months)}", flush=True)

    # forward 1-month return: signal at sd close, entry next trading day close,
    # exit next month first trading day close (factor_discovery_kr.py와 동일 규약).
    close_wide = df.pivot_table(index="date", columns="ticker", values="close")
    next_date = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}
    exit_map = {months[i]: months[i + 1] for i in range(len(months) - 1)}
    fwd = pd.Series(np.nan, index=base.index, dtype=float)
    for i, sd in enumerate(months[:-1]):
        rows = base.index[base["date"] == sd]
        if len(rows) == 0:
            continue
        exit_d = months[i + 1]
        entry_d = next_date[sd]
        try:
            ec = close_wide.loc[entry_d]
            xc = close_wide.loc[exit_d]
        except KeyError:
            continue
        tks = base.loc[rows, "ticker"]
        vals = (xc.reindex(ec.index) / ec - 1.0)
        fwd.loc[rows] = tks.map(vals).to_numpy(dtype=float)
    base["fwd1m"] = fwd
    base = base.dropna(subset=["fwd1m"])
    base = base[base["fwd1m"] > -1].copy()
    print(f"  with fwd1m {len(base)} rows ({time.time()-t0:.0f}s)", flush=True)

    market_map = fd.load_market_map()
    base["market"] = base["ticker"].map(market_map)
    base["period"] = base["date"].map(fd.period_of)
    n_pre = len(base)
    base = base[base["liquid"]].copy()
    print(f"  liquidity gate dv20>=1e8: {n_pre} -> {len(base)} rows", flush=True)

    print("loading valuation-panel (per) ...", flush=True)
    vdf = fd.load_panel(fd.VALUATION_PANEL, ["per"])
    base["per"] = [fd.panel_lookup(vdf, t, d, "per") for t, d in zip(base["ticker"], base["date"])]
    base["earnings_yield"] = np.where((base["per"].notna()) & (base["per"] > 0), 1.0 / base["per"], np.nan)
    print(f"  base ready ({time.time()-t0:.0f}s)", flush=True)
    return base


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    base = build_base()

    sub_all = base.dropna(subset=["earnings_yield"]).copy()
    print(f"earnings_yield coverage: {len(sub_all)}/{len(base)} "
          f"({len(sub_all) / len(base) * 100:.1f}%)", flush=True)

    results = {"factor": "earnings_yield", "generatedAt": pd.Timestamp.utcnow().isoformat(),
               "purpose": "TRAIN/VALID/TEST를 나눠 IC·decile slope가 TEST(진짜 OOS)에서도 유지되는지 확인",
               "trainEnd": "2022-06-30", "validEnd": "2024-01-01", "splits": {}}

    for split in ["ALL", "TRAIN", "VALID", "TEST"]:
        sub = sub_all if split == "ALL" else sub_all[sub_all["period"] == split]
        res = fd.decile_analysis(sub, "earnings_yield")
        if res is None:
            results["splits"][split] = None
            print(f"[{split}] no data", flush=True)
            continue
        results["splits"][split] = res
        spr = res.get("spread") or {}
        print(f"[{split}] n={res['n']} months={res['nMonths']} "
              f"decileSlope={res['decileSlopeSpearman']} "
              f"spread_t={spr.get('t')} spread_mean={spr.get('mean')} "
              f"hitRate={spr.get('hitRate')} posYearRatio={spr.get('posYearRatio')}", flush=True)

    out_path = os.path.join(OUT_DIR, "earnings-yield-train-valid-test.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1, default=str)
    print(f"\nSaved: {out_path}", flush=True)


if __name__ == "__main__":
    main()
