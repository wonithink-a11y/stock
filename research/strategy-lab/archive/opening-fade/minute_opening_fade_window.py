#!/usr/bin/env python
"""오더닝 페이드 - 신호 창(1/5/15분) 민감도 ([RESEARCH HYPOTHESIS]) - 실험 5.

"09:00→09:05"라는 5분 창은 첫 실행에서 임의로 고른 값이다. 1분·15분 창으로 바꿔
같은 5분위 사다리를 다시 그려 Q5−Q1 스프레드가 창 선택에 얼마나 민감한지 본다.
민감도 확인이므로 세 값 전부 보고한다(선택하지 않음).

창별 정의(결과 구간은 그 창 끝부터 종가까지로 맞춰 비교 가능하게):
  W=1 : 신호=P(09:01)/P(09:00)-1, 결과=P(close)/P(09:01)-1
  W=5 : 신호=P(09:05)/P(09:00)-1, 결과=P(close)/P(09:05)-1  (첫 실행 재현)
  W=15: 신호=P(09:15)/P(09:00)-1, 결과=P(close)/P(09:15)-1
그 외(5분위 경계 결정적 처리, 날짜 동일가중 벤치마크/초과수익)는 첫 실행과 동일.

  python minute_opening_fade_window.py
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "minute-opening-fade-window")
WINDOWS = {"W1": "09:01", "W5": "09:05", "W15": "09:15"}


def day_frame(date_dir, date_str):
    frames = []
    for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
        frames.append(pd.read_parquet(part, columns=["ticker", "ts", "open", "close"]))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    s = df["ts"]
    hhmm = s.astype(str).str.slice(11, 16) if not hasattr(s, "dt") else s.dt.strftime("%H:%M")
    keep = hhmm.isin(["09:00", "09:01", "09:05", "09:15", "15:30"])
    df = df[keep]
    df = df[(df["open"] > 0) & (df["close"] > 0)].assign(hhmm=hhmm[keep][df.index])

    def at(hhmm_val, col):
        sub = df.loc[df["hhmm"] == hhmm_val, ["ticker", col]].copy()
        name = "p0900" if col == "open" else f"p{hhmm_val.replace(':', '')}"
        sub.columns = ["ticker", name]
        return sub

    out = at("09:00", "open").merge(at("09:01", "close"), on="ticker", how="left") \
                             .merge(at("09:05", "close"), on="ticker", how="left") \
                             .merge(at("09:15", "close"), on="ticker", how="left") \
                             .merge(at("15:30", "close"), on="ticker", how="left")
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
    print(f"ticker-days={len(df)}, days={n_days} ({time.time()-t0:.0f}s)", flush=True)

    base = df[df["p0900"].notna()].copy().sort_values(["date", "ticker"]).reset_index(drop=True)
    results = {}
    for w_name, stamp in WINDOWS.items():
        pcol = f"p{stamp.replace(':', '')}"
        d = base[base[pcol].notna()].copy()
        d["rsig"] = d[pcol] / d["p0900"] - 1
        d["rout"] = d["p1530"] / d[pcol] - 1
        d["q"] = d.groupby("date")["rsig"].transform(
            lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 5), 5).astype(int))
        dd = d[d["rout"].notna()]
        bench = dd.groupby("date")["rout"].mean().rename("bench")
        dq = dd.merge(bench, on="date")
        dq["excess"] = dq["rout"] - dq["bench"]
        gmean = dq.groupby(["date", "q"])["excess"].mean().groupby("q").mean()
        block = {
            "signalRows": int(len(d)),
            "excessByQuintileBp": {f"Q{q}": round(float(gmean.get(q, float('nan'))) * 1e4, 2)
                                   for q in range(1, 6)},
            "spreadQ5mQ1Bp": round(float(gmean.get(5, float('nan')) - gmean.get(1, float('nan'))) * 1e4, 2),
            "medianAbsSignalBp": round(float(d["rsig"].abs().median()) * 1e4, 1),
        }
        results[w_name] = block
        print(w_name, json.dumps(block, ensure_ascii=False), flush=True)

    diag = {"days": int(n_days), "tickerDays": int(len(base))}
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "label": "[RESEARCH HYPOTHESIS]",
            "purpose": "오더닝 페이드 스프레드의 신호 창(1/5/15분) 민감도 - 세 값 전부 보고",
            "definitions": {
                "perWindow": "신호=P(tw)/P(09:00)-1, 결과=P(15:30 close)/P(tw)-1 "
                             "(결과 구간은 창 끝->종가로 정렬)",
                "rest": "minute_opening_fade_study.py와 동일",
            },
            "diagnostics": diag,
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
