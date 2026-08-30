#!/usr/bin/env python
"""오프닝 페이드 롱숏 - 비용 반영 net 스프레드 (지시 1).

minute_opening_fade_study.py의 신호(r05 날짜 내 5분위)를 그대로 재사용.
페어 가정: Q1 롱 + Q5 숏. 왕복비용(RT) 20/30/40bp를 각 다리 진입·청산에 절반씩 ->
롱숏 총 드래그 = 2 x RT (두 다리). threshold 튜닝 없음 - 비용 세 값만.

호라이즌:
  당일: 09:05->10:00 / ->11:00 / ->종가 (미러 분봉)
  다일: 신호일 09:05 가격 -> T+1/5/10/20 거래일 A2a 종가 (패널 병합)
breakeven RT = gross 롱숏 스프레드(Q1-Q5) / 2.

  python minute_fade_cost_horizons.py
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
PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(HERE, "findings", "minute-opening-fade-cost")
COSTS = (20, 30, 40)


def day_frame(date_dir, date_str):
    frames = []
    for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
        frames.append(pd.read_parquet(part, columns=["ticker", "ts", "open", "close"]))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    s = df["ts"]
    hhmm = s.astype(str).str.slice(11, 16) if not hasattr(s, "dt") else s.dt.strftime("%H:%M")
    keep = hhmm.isin(["09:00", "09:05", "10:00", "11:00", "15:30"])
    df = df[keep]
    df = df[(df["open"] > 0) & (df["close"] > 0)].assign(hhmm=hhmm[keep][df.index])

    def at(v, col):
        sub = df.loc[df["hhmm"] == v, ["ticker", col]].copy()
        sub.columns = ["ticker", "p0900" if col == "open" else f"p{v.replace(':', '')}"]
        return sub

    out = at("09:00", "open").merge(at("09:05", "close"), on="ticker", how="inner") \
                             .merge(at("10:00", "close"), on="ticker", how="left") \
                             .merge(at("11:00", "close"), on="ticker", how="left") \
                             .merge(at("15:30", "close"), on="ticker", how="left")
    out.insert(0, "date", date_str)
    return out


def main():
    t0 = time.time()
    date_dirs = sorted(glob.glob(os.path.join(MINUTE_DIR, "date=*")))
    chunks = []
    for dd in date_dirs:
        fr = day_frame(dd, dd.split("=")[-1])
        if fr is not None and fr.size:
            chunks.append(fr)
    df = pd.concat(chunks, ignore_index=True)

    base = df[df["p0900"].notna() & df["p0905"].notna()].copy()
    base = base.sort_values(["date", "ticker"]).reset_index(drop=True)
    base["r05"] = base["p0905"] / base["p0900"] - 1
    base["q"] = base.groupby("date")["r05"].transform(
        lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 5), 5).astype(int))
    print(f"base={len(base)} ({time.time()-t0:.0f}s)", flush=True)

    # --- 다일 종가(A2a 패널): 티커별 shift(-h)
    px = pd.read_parquet(PANEL_PATH, columns=["ticker", "date", "close"])
    px = px.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = px.groupby("ticker")["close"]
    for h in (1, 5, 10, 20):
        px[f"c{h}"] = g.transform(lambda s, hh=h: s.shift(-hh))
    fwd = px[px["date"].isin(set(base["date"]))][["ticker", "date", "c1", "c5", "c10", "c20"]]
    base = base.merge(fwd, on=["ticker", "date"], how="left")

    horizons = {
        "intraday_to1000": "p1000",
        "intraday_to1100": "p1100",
        "intraday_toClose": "p1530",
        "T+1": "c1", "T+5": "c5", "T+10": "c10", "T+20": "c20",
    }
    results = {}
    for h_name, col in horizons.items():
        d = base[base[col].notna()].copy()
        d["out"] = d[col] / d["p0905"] - 1
        bench = d.groupby("date")["out"].mean().rename("bench")
        dq = d.merge(bench, on="date")
        dq["excess"] = dq["out"] - dq["bench"]
        gmean = dq.groupby(["date", "q"])["excess"].mean().groupby("q").mean()
        gross_ls = float(gmean.get(1, np.nan) - gmean.get(5, np.nan)) * 1e4  # Q1-Q5 이익(bp)
        block = {
            "rows": int(len(d)),
            "grossLongShortBp": round(gross_ls, 2),
            "quintileExcessBp": {f"Q{q}": round(float(gmean.get(q, np.nan)) * 1e4, 2)
                                 for q in range(1, 6)},
            "netByCostBp": {f"cost{c}": round(gross_ls - 2 * c, 2) for c in COSTS},
            "breakevenRTbp": round(gross_ls / 2.0, 2),
        }
        results[h_name] = block
        print(h_name, json.dumps(block, ensure_ascii=False)[:220], flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "label": "[RESEARCH HYPOTHESIS]",
            "purpose": "오더닝 페이드 롱숏 net - 비용 20/30/40bp, 드래그=2xRT(두 다리), "
                       "호라이즌=당일 3개 + 다일 T+1/5/10/20",
            "definitions": {
                "signal": "minute_opening_fade_study.py와 동일(r05 날짜 내 5분위)",
                "multiDayOutcome": "신호일 09:05 가격 -> T+h 거래일 A2a 종가",
                "costSplit": "왕복비용 RT를 각 다리 진입/청산 절반씩 -> 페어 총 드래그 2xRT",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
