#!/usr/bin/env python
"""CAND1(PMCRASH_REVERSAL) 체결 미시구조 검증 - 인프라 진단(숫자만 보고).

신호 재구성은 run_strategy_validation.py의 코드 경로를 그대로 재사용한다
(load_frame + 동결 파라미터 thr=2%, vthr=1.5, mthr=None; 진입=익일 시가,
청산=익일 09:35 종가). 측정은 MinuteProvider 미러(.cache/minute_raw, 같은
252세션)의 진입일 분봉에서:

  - 갭: 익일 시가 / 신호일 종가 - 1
  - 진입 유동성: 진입일 누적 거래량/거래대금 (<=09:05, <=09:30, <=09:35),
    09:00-09:35 VWAP 대비 시가 괴리(진입 슬리피지 프록시)
  - 청산 유동성: 09:30-09:35 구간 거래대금, 09:35 종가 vs VWAP 괴리
  - 용량 맥락: 신호 표본의 09:00-09:35 거래대금 분포 vs 유니버스 전체 분포

판단·설계 제안 없이 숫자만 남긴다.

  python cand1_execution_microstructure.py
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
OUT_DIR = os.path.join(HERE, "findings", "cand1-execution-microstructure")

THR, VTHR = 0.02, 1.5  # 동결 파라미터 (findings/strategy-candidates)


def pct_table(s, qs=(5, 10, 25, 50, 75, 90, 95)):
    s = pd.Series(s).dropna()
    if s.empty:
        return {}
    return {f"p{q}": round(float(np.percentile(s, q)), 6) for q in qs} | \
           {"mean": round(float(s.mean()), 6)}


def main():
    t0 = time.time()
    from run_strategy_validation import load_frame
    f, _p, _g = load_frame()
    kr = f["reg_kospi_ret"]
    rv = f["rel_v_w1400_1500"]
    mask1 = ((f["r_1400_close"] <= -THR) & (rv < VTHR)).fillna(False)
    sigs = f[mask1][["ticker", "date", "day_close", "n_open", "n_close", "n_c0935", "market"]].copy()
    print(f"CAND1 signals={len(sigs)} ({time.time()-t0:.0f}s)", flush=True)

    # 진입일 = 신호일 다음 세션 (전체 세션 달력 기준 인접 매핑)
    all_dates = sorted(_p["date"].unique()) if "_p" in dir() else None
    if all_dates is None:
        all_dates = sorted(pd.read_parquet(
            os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "intraday_panel.parquet"),
            columns=["date"])["date"].unique())
    pos = {d: i for i, d in enumerate(all_dates)}
    sigs["entryDate"] = sigs["date"].map(lambda d: all_dates[pos[d] + 1] if pos[d] + 1 < len(all_dates) else None)

    need = sigs.dropna(subset=["entryDate"]).groupby("entryDate")["ticker"] \
               .agg(lambda s: set(s)).to_dict()

    rows = []
    for date_dir in sorted(glob.glob(os.path.join(MINUTE_DIR, "date=*"))):
        ds = date_dir.split("=")[-1]
        frames = []
        for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
            frames.append(pd.read_parquet(part, columns=["ticker", "ts", "close", "volume"]))
        df = pd.concat(frames, ignore_index=True)
        s = df["ts"]
        hhmm = s.astype(str).str.slice(11, 16) if not hasattr(s, "dt") else s.dt.strftime("%H:%M")
        mins = hhmm.str.slice(0, 2).astype(int) * 60 + hhmm.str.slice(3, 5).astype(int)
        df = df.assign(mins=mins, tv=df["close"] * df["volume"])
        df = df[(df["close"] > 0) & (df["volume"] >= 0)]

        m905, m930, m935 = df["mins"] <= 545, df["mins"] <= 570, df["mins"] <= 575
        gcol = "ticker"
        v0905 = df.loc[m905].groupby(gcol)["volume"].sum()
        v0930 = df.loc[m930].groupby(gcol)["volume"].sum()
        v0935 = df.loc[m935].groupby(gcol)["volume"].sum()
        t0935 = df.loc[m935].groupby(gcol)["tv"].sum()
        dv = df.groupby(gcol)["volume"].sum()
        dt = df.groupby(gcol)["tv"].sum()
        agg = pd.DataFrame({
            "v0905": v0905, "v0930": v0930, "v0935": v0935,
            "turn0935": t0935, "wapNum": t0935, "wapDen": v0935,
            "dayVol": dv, "dayTurn": dt,
        }).fillna(0.0).reset_index()
        agg.insert(0, "date", ds)
        rows.append(agg)
        if len(rows) % 50 == 0:
            print(f"  scanned {len(rows)} date partitions ({time.time()-t0:.0f}s)", flush=True)
    A = pd.concat(rows, ignore_index=True)
    print(f"minute aggregates rows={len(A)} ({time.time()-t0:.0f}s)", flush=True)

    sigs = sigs.merge(A, left_on=["entryDate", "ticker"], right_on=["date", "ticker"],
                      how="left", suffixes=("", "_m"))
    uni = A.copy()

    sigs["gapPct"] = sigs["n_open"] / sigs["day_close"] - 1
    sigs["vwap0935"] = np.where(sigs["wapDen"] > 0, sigs["wapNum"] / sigs["wapDen"], np.nan)
    sigs["openVsVwapBp"] = (sigs["n_open"] / sigs["vwap0935"] - 1) * 1e4
    sigs["exitVsVwapBp"] = (sigs["n_c0935"] / sigs["vwap0935"] - 1) * 1e4
    sigs["volShareBy0935"] = sigs["v0935"] / sigs["dayVol"]

    out = {
        "nSignals": int(len(sigs)),
        "entryGap": pct_table(sigs["gapPct"]),
        "firstBarsVolumeShare": {
            "le0905": pct_table(sigs["v0905"] / sigs["dayVol"]),
            "le0930": pct_table(sigs["v0930"] / sigs["dayVol"]),
            "le0935": pct_table(sigs["volShareBy0935"]),
        },
        "turnoverValueBy0935KRW": pct_table(sigs["turn0935"]),
        "openVsVwap0935Bp": pct_table(sigs["openVsVwapBp"]),
        "exitCloseVsVwap0935Bp": pct_table(sigs["exitVsVwapBp"]),
        "universeBaseline": {
            "turnoverValueBy0935KRW": pct_table(uni["turn0935"]),
            "volShareBy0935": pct_table(uni["v0935"] / uni["dayVol"]),
        },
    }
    print(json.dumps(out, ensure_ascii=False)[:1200], flush=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "purpose": "CAND1 체결 미시구조 검증 - 숫자만 보고(설계 제안 없음)",
            "signalReconstruction": "run_strategy_validation.load_frame 재사용 + 동결 파라미터 "
                                    "(thr=2%, vthr=1.5, mthr=None)",
            "definitions": {
                "windows": "누적 봉 타임스탬프 기준(분 시작): <=09:05, <=09:30, <=09:35",
                "vwap0935": "09:00-09:35 분봉 close*volume 가중 평균",
                "openVsVwapBp": "(익일 시가 / vwap0935 - 1)*1e4",
                "exitVsVwapBp": "(09:35 종가 / vwap0935 - 1)*1e4",
                "gapPct": "익일 시가 / 신호일 종가 - 1",
            },
            "results": out,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
