#!/usr/bin/env python
"""오더닝 페이드 세기의 국면 의존성 원인 대조 ([RESEARCH HYPOTHESIS]) - 실험4 후속.

2026-05~08 스프레드가 2025하반기의 3배였던 이유가 변동성 국세 때문인지 확인한다.
시장 변동성 프록시(KOSPI 지수 데이터 없음 -> 미러 유니버스로 구성):
  - rngEW : 그날 종목별 일중 레인지 (dayHi-dayLo)/P0900 의 동일가중 평균
  - xsStd : 그날 09:05->종가 수익률의 횡단면 표준편차
월별 평균과 월별 스프레드(Q5-Q1, 09:05->close)를 나란히 보고하고 상관계수만 계산.
원인 규명 해석은 하지 않는다(숫자만).

  python minute_fade_regime.py
"""
import glob
import json
import os
import sys
import time

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MINUTE_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "minute_raw")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "minute-fade-regime")


def day_frame(date_dir, date_str):
    frames = []
    for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
        frames.append(pd.read_parquet(part, columns=["ticker", "ts", "open", "high", "low", "close"]))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    s = df["ts"]
    hhmm = s.astype(str).str.slice(11, 16) if not hasattr(s, "dt") else s.dt.strftime("%H:%M")
    keep = hhmm.isin(["09:00", "09:05", "15:30"])
    df = df[keep]
    df = df[(df["open"] > 0) & (df["close"] > 0)].assign(hhmm=hhmm[keep][df.index])

    def at(hhmm_val, col):
        sub = df.loc[df["hhmm"] == hhmm_val, ["ticker", col]].copy()
        name = {"09:00": "p0900", "09:05": "p0905", "15:30": "p1530"}[hhmm_val] if col == "close" \
            else ("p0900" if col == "open" else f"h{hhmm_val.replace(':', '')}")
        return sub.rename(columns={col: name})[["ticker", name]]

    o900 = at("09:00", "open")
    c905 = at("09:05", "close")
    c1530 = at("15:30", "close")
    hi_all, lo_all = [], []
    for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
        d2 = pd.read_parquet(part, columns=["ticker", "high", "low"])
        hi_all.append(d2.groupby("ticker", sort=False)["high"].max())
        lo_all.append(d2.groupby("ticker", sort=False)["low"].min())
    hi = pd.concat(hi_all).groupby(level=0).max().rename("dayHi")
    lo = pd.concat(lo_all).groupby(level=0).min().rename("dayLo")
    out = o900.merge(c905, on="ticker", how="inner").merge(c1530, on="ticker", how="left") \
              .merge(hi, on="ticker", how="left").merge(lo, on="ticker", how="left")
    out.insert(0, "date", date_str)
    return out


def main():
    t0 = time.time()
    date_dirs = sorted(glob.glob(os.path.join(MINUTE_DIR, "date=*")))
    chunks, n_days = [], 0
    for dd in date_dirs:
        fr = day_frame(dd, dd.split("=")[-1])
        if fr is None or fr.empty:
            continue
        chunks.append(fr)
        n_days += 1
        if n_days % 50 == 0:
            print(f"  {n_days} days ({time.time()-t0:.0f}s)", flush=True)
    df = pd.concat(chunks, ignore_index=True)

    base = df[df["p0900"].notna() & df["p0905"].notna() & df["p1530"].notna()].copy()
    base = base.sort_values(["date", "ticker"]).reset_index(drop=True)
    base["r05"] = base["p0905"] / base["p0900"] - 1
    base["rclose"] = base["p1530"] / base["p0905"] - 1
    base["q"] = base.groupby("date")["r05"].transform(
        lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 5), 5).astype(int))
    base["rng"] = (base["dayHi"] - base["dayLo"]) / base["p0900"]
    base["month"] = base["date"].str[:7]

    bench = base.groupby("date")["rclose"].mean().rename("bench")
    dq = base.merge(bench, on="date")
    dq["excess"] = dq["rclose"] - dq["bench"]

    rows = []
    for month, gm in dq.groupby("month"):
        q1 = gm[gm["q"] == 1].groupby("date")["excess"].mean()
        q5 = gm[gm["q"] == 5].groupby("date")["excess"].mean()
        rng_m = gm.groupby("date")["rng"].mean()          # 일중 레인지 EW
        xs_std = gm.groupby("date")["rclose"].std()       # 횡단면 산포
        rows.append({
            "month": month,
            "nDates": int(len(q1)),
            "spreadQ5mQ1Bp": round(float((q5 - q1).mean()) * 100, 3),
            "rangeMeanBp": round(float(rng_m.mean()) * 1e4, 1),
            "xsStdBp": round(float(xs_std.mean()) * 1e4, 1),
            "mktDayRetAbsBp": round(float(gm.groupby("date")["rclose"].mean().abs().mean()) * 1e4, 1),
        })
    monthly = pd.DataFrame(rows).sort_values("month")
    corr_rng = float(monthly["spreadQ5mQ1Bp"].corr(monthly["rangeMeanBp"]))
    corr_xs = float(monthly["spreadQ5mQ1Bp"].corr(monthly["xsStdBp"]))
    corr_ret = float(monthly["spreadQ5mQ1Bp"].corr(monthly["mktDayRetAbsBp"]))
    print(monthly.to_string(index=False), flush=True)
    print(f"corr(spread, range)={corr_rng:.3f} corr(spread, xsStd)={corr_xs:.3f} "
          f"corr(spread, |mktRet|)={corr_ret:.3f}", flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "label": "[RESEARCH HYPOTHESIS]",
            "purpose": "페이드 스프레드 세기와 시장 변동성 프록시의 월별 대조 (숫자만)",
            "proxies": {
                "rangeMeanBp": "종목별 일중 레인지 (dayHi-dayLo)/P0900 의 날짜 EW 평균",
                "xsStdBp": "09:05->종가 수익률 횡단면 표준편차",
                "mktDayRetAbsBp": "날짜 등가중 평균 수익률의 절댓값",
            },
            "correlations": {"spreadVsRange": round(corr_rng, 3),
                             "spreadVsXsStd": round(corr_xs, 3),
                             "spreadVsMktDayRetAbs": round(corr_ret, 3)},
            "monthly": rows,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
