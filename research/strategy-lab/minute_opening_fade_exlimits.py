#!/usr/bin/env python
"""오더닝 페이드 - 상하한가(±29%) 도달 종목 제외 민감도 ([RESEARCH HYPOTHESIS]).

minute-opening-fade 첫 실행의 자기 명시 한계("상하한가 도달 종목 미제외")를 점검한다.
한국 주식 가격제한폭 ±30% 기준, 그날 시가 대비 **±29% 이상 도달**한 종목-일을
제외하고 동일한 5분위 사다리를 다시 그려 제외 전/후 스프레드 변화를 나란히 본다.
threshold 튜닝 없음(29%는 30% 제한폭에 대한 단일 고정 관례값).

정의:
  - dayHi/dayLo = 그날 전 분봉 high 최대 / low 최소
  - up29 = dayHi/P0900 - 1 >= 0.29, down29 = dayLo/P0900 - 1 <= -0.29
  - 제외 = up29 또는 down29 (제외 통계도 상하 각각 보고)
  - 그 외 정의·측정은 minute_opening_fade_study.py와 동일

  python minute_opening_fade_exlimits.py
"""
import glob
import json
import os
import sys
import time

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MINUTE_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "minute_raw")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "minute-opening-fade-exlimits")
LIMIT_MOVE = 0.29


def day_frame(date_dir, date_str):
    frames = []
    for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
        frames.append(pd.read_parquet(part, columns=["ticker", "ts", "open", "high", "low", "close"]))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    s = df["ts"]
    hhmm = s.astype(str).str.slice(11, 16) if not hasattr(s, "dt") else s.dt.strftime("%H:%M")
    keep = hhmm.isin(["09:00", "09:05", "10:00", "11:00", "15:30"])
    df = df[keep]
    df = df[(df["open"] > 0) & (df["close"] > 0)].assign(hhmm=hhmm[keep][df.index])

    def at(hhmm_val, col):
        sub = df.loc[df["hhmm"] == hhmm_val, ["ticker", col]].copy()
        name = "p0900" if col == "open" else f"p{hhmm_val.replace(':', '')}"
        sub.columns = ["ticker", name]
        return sub

    out = at("09:00", "open").merge(at("09:05", "close"), on="ticker", how="inner") \
                             .merge(at("10:00", "close"), on="ticker", how="left") \
                             .merge(at("11:00", "close"), on="ticker", how="left") \
                             .merge(at("15:30", "close"), on="ticker", how="left")

    # 일중 최고/최저(전 분봉 대상)
    s_all = None
    highs, lows = [], []
    for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
        d = pd.read_parquet(part, columns=["ticker", "high", "low"])
        highs.append(d.groupby("ticker", sort=False)["high"].max())
        lows.append(d.groupby("ticker", sort=False)["low"].min())
    hi = pd.concat(highs).groupby(level=0).max()
    lo = pd.concat(lows).groupby(level=0).min()
    out = out.merge(hi.rename("dayHi"), on="ticker", how="left").merge(lo.rename("dayLo"), on="ticker", how="left")
    out.insert(0, "date", date_str)
    return out


def quintile_ladder(base, col_map):
    """col_map: horizon label -> outcome column. base에 q 컬럼 있다고 가정."""
    res = {}
    for h_label, col in col_map.items():
        d = base[base[col].notna()]
        bench = d.groupby("date")[col].mean().rename("bench")
        dq = d.merge(bench, on="date")
        dq["excess"] = dq[col] - dq["bench"]
        gmean = dq.groupby(["date", "q"])["excess"].mean().groupby("q").mean()
        res[h_label] = {
            "excessByQuintile": {f"Q{q}": round(float(gmean.get(q, float('nan'))) * 100, 4) for q in range(1, 6)},
            "spreadQ5mQ1": round(float(gmean.get(5, float('nan')) - gmean.get(1, float('nan'))) * 100, 4),
        }
    return res


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
    print(f"ticker-days={len(df)}, days={n_days} ({time.time()-t0:.0f}s)", flush=True)

    base = df[df["p0900"].notna() & df["p0905"].notna()].copy()
    base = base.sort_values(["date", "ticker"]).reset_index(drop=True)
    base["r05"] = base["p0905"] / base["p0900"] - 1
    for key, col in (("r1000", "p1000"), ("r1100", "p1100"), ("rclose", "p1530")):
        base[key] = base[col] / base["p0905"] - 1
    base["q"] = base.groupby("date")["r05"].transform(
        lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 5), 5).astype(int))

    base["up29"] = base["dayHi"] / base["p0900"] - 1 >= LIMIT_MOVE
    base["down29"] = base["dayLo"] / base["p0900"] - 1 <= -LIMIT_MOVE
    base["limitHit"] = base["up29"] | base["down29"]

    diag = {
        "days": int(n_days),
        "tickerDaysFull": int(len(base)),
        "up29Count": int(base["up29"].sum()),
        "down29Count": int(base["down29"].sum()),
        "limitHitCount": int(base["limitHit"].sum()),
        "limitHitSharePct": round(float(base["limitHit"].mean()) * 100, 3),
    }
    print("diag:", diag, flush=True)

    col_map = {"→10:00": "r1000", "→11:00": "r1100", "→close": "rclose"}
    results = {
        "before_fullSample": quintile_ladder(base, col_map),
        "after_exLimitHit": quintile_ladder(base[~base["limitHit"]], col_map),
    }
    for k, v in results.items():
        print(k, json.dumps(v.get("→close")), flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "label": "[RESEARCH HYPOTHESIS]",
            "purpose": "상하한가(시가 대비 ±29% 도달) 종목 제외가 오더닝 페이드 사다리를 얼마나 "
                       "줄이는지 - 제외 전/후 나란히 비교",
            "definitions": {
                "limitMove": "dayHi/P0900-1>=0.29 또는 dayLo/P0900-1<=-0.29 (30% 제한폭 대비 "
                             "단일 고정 관례값)",
                "rest": "minute_opening_fade_study.py와 동일",
            },
            "diagnostics": diag,
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
