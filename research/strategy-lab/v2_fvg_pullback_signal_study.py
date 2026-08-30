#!/usr/bin/env python
"""V2 FVG Pullback 최소 signal study (전략 엔진 미연결 — 이벤트 스터디만).

가설[V2, OBSERVED]: 상승 추세 중 발생한 3-candle Fair Value Gap(FVG)으로 가격이
되돌림 → FVG 구간에서 반등 시 매수. 익절 = 손절폭 × 2(2R)는 RiskSpec/execution
연결(다음 단계)에서 다룬다 — 본 스터디 범위 밖.

[UNSPECIFIED] → 임시 채택 (첫 실행 고정, 튜닝 없음 — 이 구분을 문서에 그대로 남긴다):
  - FVG 정의: bullish 3봉 갭 low[k] > high[k-2], zone = [high[k-2], low[k]]
    (영상에서 정의 미상 → 일반적 3봉 갭 최소 정의)
  - "상승 추세" = MA5 > MA25 > MA75, FVG 형성일 k에만 요구 (V1과 동일 최소 정의)
  - 되돌림 깊이(상단/50%/하단): 조건 없음 — 구간 터치만 요구
  - 반등 confirmation: 형성 후 최대 20거래일 내 첫날 중
    low[j] <= zone_top AND close[j] > zone_top (갭 상단을 저가로 터치하고 종가로 회복).
    대기 기간 20거래일도 임시 선택. 같은 FVG는 첫 발화 한 번만.
  - 신호일 j 추세 조건은 재요구하지 않음 (규칙 문언: 갭 발생 시점의 상승 추세)

데이터: 유니버스 = a4 연구 패널 ticker 집합(V1/V5와 동일). OHLC는 A2a 백필 캐시
  (.cache/a2a_parquet/{year}.parquet, 읽기 전용)에서 로드.

측정: v1/v5와 동일 관례 — 신호일 t 종가 기준 T+1/5/10/20 close-to-close(A2a adjusted),
같은 날 유니버스 전체 동일가중 벤치마크, 날짜별 초과수익의 날짜 동일가중 평균.
실거래 계약(signal t → t+1 open)과의 차이는 v1/v5와 같은 근사치 한계.

  python v2_fvg_pullback_signal_study.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A4_PANEL_PATH = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
A2A_CACHE_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "a2a_parquet")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "v2-fvg-pullback")
HORIZONS = {"T+1": 1, "T+5": 5, "T+10": 10, "T+20": 20}
MA_FAST, MA_MID, MA_SLOW = 5, 25, 75
PULLBACK_WINDOW = 20


def load_ohlc():
    uni = set(pd.read_parquet(A4_PANEL_PATH, columns=["ticker"])["ticker"].unique())
    frames = []
    for year in range(2016, 2027):
        path = os.path.join(A2A_CACHE_DIR, f"{year}.parquet")
        if not os.path.exists(path):
            continue
        d = pd.read_parquet(path, columns=["ticker", "date", "open", "high", "low", "close"])
        d = d[d["ticker"].isin(uni)]
        frames.append(d)
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")["close"]
    for n in (MA_FAST, MA_MID, MA_SLOW):
        df[f"ma{n}"] = g.transform(lambda s: s.rolling(n, min_periods=n).mean())
    for h_name, h in HORIZONS.items():
        df[f"fwd_{h}"] = g.transform(lambda s: s.shift(-h) / s - 1)
    return df


def find_signals(df):
    """FVG 형성 → 되돌림 터치 + 종가 회복 첫 발화일 위치 배열 반환."""
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    ma5 = df["ma5"].to_numpy()
    ma25 = df["ma25"].to_numpy()
    ma75 = df["ma75"].to_numpy()
    uptrend = (ma5 > ma25) & (ma25 > ma75)

    sig_pos = []
    formation_rows = 0
    gap_to_signal_days = []
    for _, idx in df.groupby("ticker").indices.items():
        h, l, c = highs[idx], lows[idx], closes[idx]
        up = uptrend[idx]
        n = len(idx)
        if n < MA_SLOW:
            continue
        # bullish FVG at i: l[i] > h[i-2], 상승 추세(형성일)
        prev2_high = np.empty(n)
        prev2_high[:2] = np.nan
        prev2_high[2:] = h[:-2]
        form = np.where((l > prev2_high) & up)[0]
        formation_rows += len(form)
        for i in form:
            zone_top = l[i]
            end = min(i + PULLBACK_WINDOW, n - 1)
            for j in range(i + 1, end + 1):
                if l[j] <= zone_top and c[j] > zone_top:
                    sig_pos.append(idx[j])
                    gap_to_signal_days.append(j - i)
                    break
    return np.array(sig_pos, dtype=int), formation_rows, np.array(gap_to_signal_days)


def stats_for(sig, bench_by_date, fwd_col):
    d = sig.dropna(subset=[fwd_col])
    if d.empty:
        return {"n": 0}
    joined = d.set_index("date")[fwd_col].rename("sig").to_frame().join(bench_by_date.rename("bench"))
    daily_excess = joined["sig"] - joined["bench"]
    years = d["date"].str[:4]
    yearly = {}
    for y in sorted(years.unique()):
        m = (years == y).values
        yearly[y] = {
            "n": int(m.sum()),
            "excessMean": round(float(daily_excess[m].mean()), 5),
            "sigMean": round(float(d.loc[m, fwd_col].mean()), 5),
        }
    return {
        "n": int(len(d)),
        "nDates": int(d["date"].nunique()),
        "avgPerDay": round(len(d) / max(1, d["date"].nunique()), 1),
        "mean": round(float(d[fwd_col].mean()), 5),
        "median": round(float(d[fwd_col].median()), 5),
        "winRate": round(float((d[fwd_col] > 0).mean()), 4),
        "benchMean": round(float(joined["bench"].mean()), 5),
        "excessPerDateMatched": round(float(daily_excess.mean()), 5),
        "yearly": yearly,
    }


def main():
    t0 = time.time()
    df = load_ohlc()
    print(f"panel rows={len(df)}, tickers={df['ticker'].nunique()}, "
          f"dates={df['date'].nunique()} ({df['date'].min()}~{df['date'].max()}) ({time.time()-t0:.0f}s)")

    sig_pos, formation_rows, gap_days = find_signals(df)
    print(f"fvg formations={formation_rows}, signal rows={len(sig_pos)} "
          f"(median gap→signal {int(np.median(gap_days)) if len(gap_days) else '-'}d) ({time.time()-t0:.0f}s)")

    sig_all = df.iloc[sig_pos]
    results = {
        "formationRowsRaw": int(formation_rows),
        "signalRowsRaw": int(len(sig_all)),
        "uniqueTickerDateRows": int(sig_all.drop_duplicates(["ticker", "date"]).shape[0]),
        "medianGapToSignalDays": int(np.median(gap_days)) if len(gap_days) else None,
    }
    for h_name, h in HORIZONS.items():
        fwd_col = f"fwd_{h}"
        bench = df.dropna(subset=[fwd_col]).groupby("date")[fwd_col].mean()
        results[h_name] = stats_for(sig_all, bench, fwd_col)
        r = results[h_name]
        print(f"  {h_name}: n={r['n']}, mean={r.get('mean')}, median={r.get('median')}, "
              f"win={r.get('winRate')}, bench={r.get('benchMean')}, excess={r.get('excessPerDateMatched')}")

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "signal_study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "V2 FVG Pullback 최소 signal study — 엔진 미연결 이벤트 스터디. "
                       "[OBSERVED] 규칙만 구현, threshold 튜닝 없음, 첫 실행 결과 그대로.",
            "panelRows": int(len(df)),
            "conventions": {
                "observed": "상승 추세 중 발생한 3-candle FVG 되돌림 → FVG 구간 반등 시 매수",
                "unspecifiedProvisional": {
                    "fvgDefinition": "bullish low[k]>high[k-2], zone=[high[k-2],low[k]]",
                    "uptrend": "MA5>MA25>MA75 (FVG 형성일에만 요구)",
                    "pullbackDepth": "조건 없음 — zone 터치만 요구",
                    "bounceConfirmation": "형성 후 최대 20거래일 내 first day with "
                                          "low<=zone_top AND close>zone_top; 같은 FVG 1회 발화",
                    "pullbackWindowDays": PULLBACK_WINDOW,
                },
                "rewardRisk12R": "RiskSpec 연결 단계 항목 — 본 스터디 범위 밖",
                "data": "OHLC: A2a 백필 캐시 .cache/a2a_parquet (읽기 전용), 유니버스: a4 패널 ticker",
                "forwardReturn": "t 종가 → t+h째 행 종가 (A2a adjusted, close-to-close)",
                "benchmark": "같은 날 유니버스 전체 종목 동일가중 (신호 종목 포함)",
                "pitNote": "실거래 계약은 signal t → t+1 open 체결이므로 이벤트 스터디 근사치; "
                           "겹치는 FVG·신호 중복 카운트 있음",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
