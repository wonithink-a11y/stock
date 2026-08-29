#!/usr/bin/env python
"""KR foreign-flow x 52-week low distance x PER combination analysis.

버그 수정판(2026-08-30, Claude) - OpenCode(Nemotron 3.5 Lightning) 원본이
foreign_net/total_amount를 A2a(가격, 그런 컬럼 없음)에서 읽으려다 실패한 것을
A4(data/backfill/supplyDemand/a4/, buyAmount/sellAmount의 '외국인'/'전체' 키)로
바로잡았다. 로직(버킷 정의·IC/t 계산·판정 기준)은 원본 그대로 재사용.
"""
import glob
import gzip
import json
import os
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A2A_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2a")
A4_DIR = os.path.join(REPO_ROOT, "data", "backfill", "supplyDemand", "a4")
VAL_PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                               "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")

TRAIN_END = "2022-06-30"
VALID_END = "2023-12-31"
MIN_NAMES = 30


def load_valuation_panel():
    rows = [json.loads(line) for line in open(VAL_PANEL_PATH, encoding="utf-8")]
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["per"])
    df = df[df["per"] > 0]
    return df.set_index(["ticker", "asOf"])["per"].to_dict()


def load_a2a_price():
    frames = []
    for path in sorted(glob.glob(os.path.join(A2A_DIR, "*.jsonl.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            recs = [json.loads(line) for line in f]
        df = pd.DataFrame(recs, columns=["ticker", "date", "close", "low"])
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["low"] = pd.to_numeric(df["low"], errors="coerce")
    return df


def load_a4_flow():
    frames = []
    for path in sorted(glob.glob(os.path.join(A4_DIR, "*.jsonl.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            recs = []
            for line in f:
                o = json.loads(line)
                recs.append({
                    "ticker": o["ticker"],
                    "date": o["date"],
                    "foreign_net": o["buyAmount"].get("외국인", 0) - o["sellAmount"].get("외국인", 0),
                    "total_amount": o["buyAmount"].get("전체", np.nan),
                })
        frames.append(pd.DataFrame(recs))
    df = pd.concat(frames, ignore_index=True)
    df["foreign_net"] = pd.to_numeric(df["foreign_net"], errors="coerce")
    df["total_amount"] = pd.to_numeric(df["total_amount"], errors="coerce")
    return df


def newey_west_t(x, lag=4):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 5:
        return None
    e = x - x.mean()
    g0 = float(np.sum(e * e)) / n
    s = g0
    for l in range(1, min(lag, n - 1) + 1):
        w = 1.0 - l / (lag + 1.0)
        s += 2.0 * w * float(np.sum(e[l:] * e[:-l])) / n
    se = np.sqrt(max(s, 0.0) / n)
    return round(float(x.mean() / se), 3) if se > 0 else None


def period_of(d):
    if d <= TRAIN_END:
        return "TRAIN"
    if d <= VALID_END:
        return "VALID"
    return "TEST"


def compute_ic_t(sub_df):
    if len(sub_df) < MIN_NAMES:
        return None, None, None
    sp = spearmanr(sub_df["foreign_flow_ratio"].to_numpy(), sub_df["fwd5"].to_numpy())
    if np.isnan(sp.statistic):
        return None, None, None
    mr = float(sub_df["fwd5"].mean())
    t = newey_west_t(sub_df["fwd5"].to_numpy())
    return mr, t, len(sub_df)


def bucket_ffr(v):
    if v <= 0.20: return "0-20%"
    if v <= 0.40: return "20-40%"
    if v <= 0.60: return "40-60%"
    if v <= 0.80: return "60-80%"
    return "80-100%"


def bucket_l2w(v):
    if v <= 0.10: return "0-10%"
    if v <= 0.20: return "10-20%"
    if v <= 0.40: return "20-40%"
    return "40%+"


def main():
    t0 = time.time()
    print("Loading data...")

    per_lookup = load_valuation_panel()
    print(f"  valuation panel: {len(per_lookup)} rows")

    price = load_a2a_price()
    print(f"  A2A price: {len(price)} rows, {price['ticker'].nunique()} tickers")

    flow = load_a4_flow()
    print(f"  A4 flow: {len(flow)} rows, {flow['ticker'].nunique()} tickers")

    df = price.merge(flow, on=["ticker", "date"], how="inner")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  Merged: {len(df)} rows, {df['ticker'].nunique()} tickers")

    ta = df["total_amount"].replace(0, np.nan)
    df["foreign_flow_ratio"] = df["foreign_net"] / ta

    df["_252d_low"] = df.groupby("ticker")["low"].transform(
        lambda s: s.rolling(window=252, min_periods=252).min()
    )
    df["_52w_low_dist"] = (df["close"] - df["_252d_low"]) / df["_252d_low"]

    df["per"] = df.set_index(["ticker", "date"]).index.to_series().map(per_lookup).values

    cg = df.groupby("ticker", sort=False)["close"]
    df["fwd5"] = cg.shift(-5) / df["close"] - 1.0

    df = df.dropna(subset=["foreign_flow_ratio", "_52w_low_dist", "per", "fwd5"])
    print(f"  After drop NaN: {len(df)} rows, {df['ticker'].nunique()} tickers")

    df["period"] = df["date"].apply(period_of)
    print(f"  Periods: TRAIN={sum(df['period']=='TRAIN')}, VALID={sum(df['period']=='VALID')}, TEST={sum(df['period']=='TEST')}")

    p25, p66 = df["per"].quantile(0.33), df["per"].quantile(0.66)

    def bucket_per(v):
        if v <= p25: return "low"
        if v <= p66: return "mid"
        return "high"

    df["ff_bucket"] = df["foreign_flow_ratio"].apply(bucket_ffr)
    df["l2w_bucket"] = df["_52w_low_dist"].apply(bucket_l2w)
    df["per_bucket"] = df["per"].apply(bucket_per)

    print("\n=== Step 2: 52w low dist / foreign flow single-axis 5D forward return by period ===")
    step2 = {}
    for pname in ["TRAIN", "VALID", "TEST"]:
        sub = df[df["period"] == pname]
        mr, t, n = compute_ic_t(sub)
        step2[pname] = {"mean_ret": round(mr, 5) if mr else None, "t": t, "n": n}
        print(f"  {pname}: mean_5D_ret={mr}, t={t}, n={n}")

    print("\n=== Step 3: foreign_flow_ratio x 52w_low_dist 2-way (TRAIN) ===")
    step3 = []
    for ff_b in ["0-20%", "40-60%", "80-100%"]:
        for l2w_b in ["0-10%", "10-20%", "40%+"]:
            sub = df[(df["period"] == "TRAIN") & (df["ff_bucket"] == ff_b) & (df["l2w_bucket"] == l2w_b)]
            mr, t, n = compute_ic_t(sub)
            if mr is not None:
                step3.append({"ff": ff_b, "l2w": l2w_b, "mean_ret": round(mr, 5), "t": t, "n": n})
                print(f"  {ff_b} x {l2w_b}: ret={mr:.5f}, t={t}, n={n}")

    print("\n=== Step 4: foreign_flow_ratio x PER 2-way (TRAIN) ===")
    step4 = []
    for ff_b in ["0-20%", "40-60%", "80-100%"]:
        for per_b in ["low", "mid", "high"]:
            sub = df[(df["period"] == "TRAIN") & (df["ff_bucket"] == ff_b) & (df["per_bucket"] == per_b)]
            mr, t, n = compute_ic_t(sub)
            if mr is not None:
                step4.append({"ff": ff_b, "per": per_b, "mean_ret": round(mr, 5), "t": t, "n": n})
                print(f"  {ff_b} x {per_b}: ret={mr:.5f}, t={t}, n={n}")

    print("\n=== Step 5: 3-way candidate (TRAIN only) ===")
    step5 = []
    for ff_b in ["0-20%", "20-40%", "40-60%"]:
        for per_b in ["low", "mid", "high"]:
            for l2w_b in ["0-10%", "10-20%"]:
                sub = df[(df["period"] == "TRAIN") & (df["ff_bucket"] == ff_b)
                         & (df["per_bucket"] == per_b) & (df["l2w_bucket"] == l2w_b)]
                mr, t, n = compute_ic_t(sub)
                if mr is not None:
                    step5.append({"ff": ff_b, "per": per_b, "l2w": l2w_b, "mean_ret": round(mr, 5), "t": t, "n": n})
    step5.sort(key=lambda x: (x["t"] or 0), reverse=True)
    print(f"  Found {len(step5)} combos with n>=30 (TRAIN)")
    for r in step5[:5]:
        print(f"    {r['ff']} x {r['per']} x {r['l2w']}: ret={r['mean_ret']:.5f}, t={r['t']}, n={r['n']}")

    # 최고 후보의 VALID/TEST 재확인 - 부호일관성 검사 (원본 스크립트가 빠뜨린 부분)
    valid_test_check = {}
    if step5:
        best = step5[0]
        for pname in ["VALID", "TEST"]:
            sub = df[(df["period"] == pname) & (df["ff_bucket"] == best["ff"])
                     & (df["per_bucket"] == best["per"]) & (df["l2w_bucket"] == best["l2w"])]
            mr, t, n = compute_ic_t(sub)
            valid_test_check[pname] = {"mean_ret": mr, "t": t, "n": n}
            print(f"  Best combo re-check {pname}: ret={mr}, t={t}, n={n}")

    print("\n=== Applying rule discovery criteria ===")
    verdict = "HOLD"
    conditions = []
    max_year_pct = 0.0

    if step5:
        best = step5[0]
        best_sub = df[(df["period"] == "TRAIN") & (df["ff_bucket"] == best["ff"])
                      & (df["per_bucket"] == best["per"]) & (df["l2w_bucket"] == best["l2w"])]
        year_pcts = best_sub["date"].str[:4].value_counts()
        max_year_pct = float(year_pcts.iloc[0] / len(best_sub) * 100) if len(best_sub) else 0.0

        train_t_ok = best["t"] is not None and best["t"] >= 2.0
        sample_ok = best["n"] >= 30
        conc_ok = max_year_pct < 70
        sign_consistent = True
        for pname in ["VALID", "TEST"]:
            vt = valid_test_check.get(pname, {})
            if vt.get("mean_ret") is not None and best["mean_ret"] is not None:
                if (vt["mean_ret"] > 0) != (best["mean_ret"] > 0):
                    sign_consistent = False

        print(f"  Best 3-way TRAIN: ret={best['mean_ret']:.5f}, t={best['t']}, n={best['n']}")
        print(f"  max_single_year_pct={max_year_pct:.1f}%, train_t>=2.0:{train_t_ok}, "
              f"sample>=30:{sample_ok}, conc<70:{conc_ok}, sign_consistent:{sign_consistent}")

        if not sample_ok:
            verdict = "HOLD"
        elif not conc_ok:
            verdict = "REJECT"
        elif not train_t_ok:
            verdict = "HOLD"
        elif not sign_consistent:
            verdict = "HOLD"
        else:
            verdict = "KEEP"
        conditions = [f"ff_bucket={best['ff']}", f"l2w_bucket={best['l2w']}", f"per_bucket={best['per']}"]
        best_n, best_t = best["n"], best["t"]
    else:
        verdict = "HOLD"
        conditions = ["foreign_flow_ratio_bucket", "52w_low_dist_bucket", "PER_bucket"]
        best_n, best_t = None, None

    out_path = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings",
                             "kr-foreign-flow-52wlow-per-2026-08.md")

    def fmt_row(r):
        return f"| {r['ff']} | {r.get('l2w', r.get('per',''))} | {r['mean_ret']:.5f} | {r['t']} | {r['n']} |"

    md = f"""---
track: kr
factor: foreign-flow-52wlow-per
date: {time.strftime("%Y-%m-%d")}
verdict: {verdict}
criteria_version: v1
conditions: {json.dumps(conditions, ensure_ascii=False)}
n: {best_n if best_n is not None else 0}
t_stat: {best_t if best_t is not None else "null"}
---

# KR 실험 결과 - 외국인수급5D x 52주저점거리 x PER

- 검증일: {time.strftime("%Y-%m-%d")}
- 스크립트: `kr_foreign_flow_52wlow_per.py` (OpenCode Nemotron 3.5 Lightning 초안,
  A4 경로/필드 오류를 Claude가 수정 - `foreign_net`/`total_amount`는 A2a가 아니라
  `data/backfill/supplyDemand/a4/`의 buyAmount/sellAmount '외국인'/'전체' 키에서 옴)
- 재사용: findings/flow-basic-effect-2026-08.md의 foreign_flow_ratio 정의(5D, KEEP 확정)
- 데이터: A2a(가격) + A4(수급) + valuation-panel(PER), merged rows={len(df)}

## 1. 단일축 (foreign_flow_ratio, 5D forward return)

| 구간 | mean 5D ret | t | n |
|---|---:|---:|---:|
| TRAIN | {step2['TRAIN']['mean_ret']} | {step2['TRAIN']['t']} | {step2['TRAIN']['n']} |
| VALID | {step2['VALID']['mean_ret']} | {step2['VALID']['t']} | {step2['VALID']['n']} |
| TEST | {step2['TEST']['mean_ret']} | {step2['TEST']['t']} | {step2['TEST']['n']} |

## 2. foreign_flow_ratio x 52주저점거리 2-way (TRAIN)

| ff_bucket | l2w_bucket | mean_ret | t | n |
|---|---|---:|---:|---:|
{chr(10).join(fmt_row(r) for r in step3)}

## 3. foreign_flow_ratio x PER 2-way (TRAIN)

| ff_bucket | per_bucket | mean_ret | t | n |
|---|---|---:|---:|---:|
{chr(10).join(fmt_row(r) for r in step4)}

## 4. 3-way 후보 (TRAIN, t 내림차순 상위 5)

| ff_bucket | per_bucket | l2w_bucket | mean_ret | t | n |
|---|---|---|---:|---:|---:|
{chr(10).join(f"| {r['ff']} | {r['per']} | {r['l2w']} | {r['mean_ret']:.5f} | {r['t']} | {r['n']} |" for r in step5[:5])}

## 5. 최고 후보 VALID/TEST 재확인 (부호일관성)

| 구간 | mean_ret | t | n |
|---|---:|---:|---:|
{chr(10).join(f"| {p} | {v.get('mean_ret')} | {v.get('t')} | {v.get('n')} |" for p, v in valid_test_check.items())}

## 6. 판정

- 최대 단일 연도 집중도: {max_year_pct:.1f}%
- 판정 기준(rule_discovery_criteria.json v1): TRAIN t>=2.0 · 표본>=30 · 연도집중도<70% · VALID/TEST 부호일관성

### 판정: **{verdict}**

---
*forward-return 조건부 분석만 수행(engine 백테스트 아님). KEEP 판정이 나면 Claude가 별도로 엔진 연결.*
"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\nFinding saved: {out_path}")
    print(f"Verdict: {verdict}")
    print(f"Execution time: {round(time.time() - t0, 1)}s")


if __name__ == "__main__":
    main()
