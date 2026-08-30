#!/usr/bin/env python
"""분봉 시간대별 거래량 프로파일 x 종목 규모 tercile - 인프라 진단 ([RESEARCH HYPOTHESIS] 아님,
데이터 관측치). 첫 실행, threshold 튜닝 없음.

질문: 하루 거래량이 09:00-10:00 / 10:00-14:00 / 14:00-15:30 에 어떻게 나뉘는가,
그리고 그 분할이 거래대금 상위/중위/하위 tercile마다 다른가.
목적은 엔진 실행 계약(signal t -> t+1 시가 체결, 단일 시점 체결 가정)의 현실성
진단 자료 제공 - 숫자만 보고하고 실행 설계 제안은 하지 않는다.

정의 고정:
  - 구간: 봉 타임스탬프(분 시작) 기준 S1=09:00..09:59 / S2=10:00..13:59 / S3=14:00..15:30
  - 종목-일 거래대금 프록시 = sum(close * volume) (당일, 분봉 합)
  - tercile = 같은 날 유니버스 내 거래대금 프록시 순위(method='first', 결정적)
  - 보고: 날짜 동일가중 평균 점유율(%)

  python minute_volume_profile.py
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "minute-volume-profile")


def day_frame(date_dir, date_str):
    frames = []
    for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
        frames.append(pd.read_parquet(part, columns=["ticker", "ts", "close", "volume"]))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    s = df["ts"]
    hhmm = s.astype(str).str.slice(11, 16) if not hasattr(s, "dt") else s.dt.strftime("%H:%M")
    df = df.assign(hhmm=hhmm)
    hh = df["hhmm"].str.slice(0, 2).astype(int)
    mm = df["hhmm"].str.slice(3, 5).astype(int)
    mins = hh * 60 + mm
    seg = np.select([mins < 600, mins < 840], ["S1", "S2"], default="S3")
    df = df[(df["close"] > 0) & (df["volume"] >= 0)].assign(seg=seg)
    df["turnover"] = df["close"] * df["volume"]

    pv = df.pivot_table(index="ticker", columns="seg", values="volume", aggfunc="sum").fillna(0.0)
    for c in ("S1", "S2", "S3"):
        if c not in pv.columns:
            pv[c] = 0.0
    turn = df.groupby("ticker", sort=False)["turnover"].sum()
    out = pv[["S1", "S2", "S3"]].copy()
    out["total"] = out.sum(axis=1)
    out["dayTurnover"] = turn.reindex(out.index)
    out = out[out["total"] > 0].reset_index()
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
    print(f"ticker-days={len(df)}, days={n_days}, avg/day={len(df)/max(1,n_days):.0f} ({time.time()-t0:.0f}s)", flush=True)

    # 규모 tercile (날짜 내 거래대금 프록시 순위)
    base = df.sort_values(["date", "ticker"]).reset_index(drop=True)
    base["tercile"] = base.groupby("date")["dayTurnover"].transform(
        lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 3), 3).astype(int))
    for c in ("S1", "S2", "S3"):
        base[f"share_{c}"] = base[c] / base["total"]

    labels = {"tercile": {1: "하위(소형)", 2: "중위", 3: "상위(대형)"},
              "seg": ("S1 09:00-10:00", "S2 10:00-14:00", "S3 14:00-15:30")}
    results = {}
    groups = [("전체", base)] + [(labels["tercile"][k], base[base["tercile"] == k]) for k in (1, 2, 3)]
    for name, gsub in groups:
        means = gsub[[f"share_{c}" for c in ("S1", "S2", "S3")]].mean() * 100
        medians = gsub[[f"share_{c}" for c in ("S1", "S2", "S3")]].median() * 100
        results[name] = {
            "tickerDays": int(len(gsub)),
            "meanSharePct": {s: round(float(means[f"share_{s}"]), 2) for s in ("S1", "S2", "S3")},
            "medianSharePct": {s: round(float(medians[f"share_{s}"]), 2) for s in ("S1", "S2", "S3")},
        }
        print(name, results[name], flush=True)

    diag = {"days": int(n_days), "avgTickersPerDay": round(len(base) / max(1, n_days), 1)}
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "purpose": "인프라 진단 - 시간대별 거래량 점유율 x 규모 tercile (숫자만 보고)",
            "dataSources": ["engine/data/minuteProvider.py 미러 .cache/minute_raw"],
            "definitions": {
                "segments": "S1=09:00-09:59 / S2=10:00-13:59 / S3=14:00-15:30 (봉 타임스탬프 기준)",
                "sizeTercile": "같은 날 당일 거래대금 프록시 sum(close*volume) 순위 3분위",
                "aggregation": "날짜 동일가중 평균/중앙값",
            },
            "diagnostics": diag,
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
