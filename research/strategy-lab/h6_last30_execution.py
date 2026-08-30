#!/usr/bin/env python
"""H6 역활용(마감 급등 되돌림) 실행 프로토콜 - [RESEARCH HYPOTHESIS] (첫 정의만).

재정의:
  1) 신호 = r(15:00->15:20) = c1520/c1500 - 1   (15:20 이후 정보 배제)
  2) 체결 창 유동성 = 진입 의사결정 이후 봉(ts 15:21..15:30)의 거래량/거래대금,
     당일 점유율·절대값 분포(cand1_execution_microstructure 방식)
  3) 구조 = 15:20 종가 매도 -> 익일 시가 청산(A2a open, 문서화된 선택).
     숏손익 = -(익일 open/c1520 - 1), 같은 창 유니버스 EW 평균 대비 초과수익.
     날짜 내 5분위(Q5=급등 그룹이 숏 후보). threshold 튜닝 없음.

  python h6_last30_execution.py
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
A2A_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "a2a_parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "h6-last30-execution")
EXEC_STAMPS = [f"15:{m:02d}" for m in range(21, 31)]


def day_frame(date_dir, date_str):
    frames = []
    for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
        frames.append(pd.read_parquet(part, columns=["ticker", "ts", "close", "volume"]))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    s = df["ts"]
    df = df.assign(hhmm=s.astype(str).str.slice(11, 16))
    df = df[(df["close"] > 0) & (df["volume"] >= 0)]
    df["tv"] = df["close"] * df["volume"]

    m_exec = df["hhmm"].isin(EXEC_STAMPS)
    sub = df.loc[m_exec]
    g = df.groupby("ticker", sort=False)

    def fc(stamp):
        return df.loc[df["hhmm"] == stamp].groupby("ticker")["close"].first()

    agg = pd.DataFrame({
        "c1500": fc("15:00"), "c1520": fc("15:20"), "c1530": fc("15:30"),
        "vExec": sub.groupby("ticker")["volume"].sum(),
        "tExec": sub.groupby("ticker")["tv"].sum(),
        "vDay": g["volume"].sum(), "tDay": g["tv"].sum(),
    }).fillna(0.0).reset_index()
    agg.insert(0, "date", date_str)
    return agg


def pct_table(s, qs=(10, 25, 50, 75, 90)):
    s = pd.Series(s).dropna()
    if s.empty:
        return {}
    t = {f"p{q}": round(float(np.percentile(s, q)), 2) for q in qs}
    t["mean"] = round(float(s.mean()), 2)
    return t


def main():
    t0 = time.time()
    date_dirs = sorted(glob.glob(os.path.join(MINUTE_DIR, "date=*")))
    chunks, n_days = [], 0
    for dd in date_dirs:
        fr = day_frame(dd, dd.split("=")[-1])
        if fr is not None and fr.size:
            chunks.append(fr)
        n_days += 1
        if n_days % 50 == 0:
            print(f"  {n_days} ({time.time()-t0:.0f}s)", flush=True)
    m = pd.concat(chunks, ignore_index=True)
    print(f"ticker-days={len(m)}, days={n_days} ({time.time()-t0:.0f}s)", flush=True)

    # 익일 시가: A2a 일간 캐시(open 컬럼) 인접 매핑
    pxs = []
    for year in (2025, 2026):
        p = os.path.join(A2A_DIR, f"{year}.parquet")
        if os.path.exists(p):
            d = pd.read_parquet(p, columns=["ticker", "date", "open"])
            d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
            d = d[d["open"] > 0]
            pxs.append(d)
    px = pd.concat(pxs, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
    tk = px["ticker"].to_numpy()
    same = np.empty(len(tk), dtype=bool)
    same[:-1] = tk[:-1] == tk[1:]
    nxt = pd.DataFrame({
        "ticker": tk[same], "date": px["date"].to_numpy()[same],
        "nextOpen": px["open"].to_numpy()[np.where(same)[0] + 1]})
    m = m.merge(nxt, on=["ticker", "date"], how="left")

    base = m[(m["c1500"] > 0) & (m["c1520"] > 0) & m["nextOpen"].notna()].copy()
    base = base.sort_values(["date", "ticker"]).reset_index(drop=True)
    base["rsig"] = base["c1520"] / base["c1500"] - 1
    base["shortRet"] = -(base["nextOpen"] / base["c1520"] - 1)
    base["q"] = base.groupby("date")["rsig"].transform(
        lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 5), 5).astype(int))

    bench = base.groupby("date")["shortRet"].mean().rename("bench")
    dq = base.merge(bench, on="date")
    dq["excess"] = dq["shortRet"] - dq["bench"]
    gmean = dq.groupby(["date", "q"])["excess"].mean().groupby("q").mean()
    ladder = {f"Q{q}": round(float(gmean.get(q, np.nan)) * 100, 3) for q in range(1, 6)}

    liq = {
        "execWindowTurnoverKRW": pct_table(base["tExec"]),
        "execWindowVolumeShareOfDay": pct_table(base["vExec"] / base["vDay"]),
    }
    print("ladder(shortProfitExcess %p):", ladder, flush=True)
    print("liq:", json.dumps(liq, ensure_ascii=False)[:400], flush=True)

    diag = {"days": int(n_days), "tickerDaysValid": int(len(dq)),
            "avgTickersPerDay": round(len(dq) / max(1, n_days), 1)}
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "label": "[RESEARCH HYPOTHESIS] - H6 재정의 첫 정의만 테스트, 튜닝 없음",
            "redefinition": {
                "signal": "r(15:00->15:20) = c1520/c1500 - 1 (15:20 이후 정보 배제)",
                "structure": "15:20 종가 매도 진입 -> 익일 시가 청산(A2a open)",
                "outcome": "숏손익 = -(익일 open/c1520 - 1), 같은 창 유니버스 EW 평균 대비 초과수익",
                "executionWindow": "봉 ts 15:21..15:30",
            },
            "diagnostics": diag,
            "quintileShortProfitExcessPct": ladder,
            "liquidity": liq,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
