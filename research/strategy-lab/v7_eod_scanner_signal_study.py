#!/usr/bin/env python
"""V7 종가베팅 EOD 스캐너 최소 signal study (엔진 미연결 — 단계별 feature 스태킹).

가설[V7, OBSERVED]: 장마감 시점에 거래량·거래대금·외국인/기관/개인 수급·가격위치를
종합해 종목 선정, T+1 이후 성과 추적. 1차 익절 +10% / 2차 익절 +20%(영상 표시)는
RiskSpec/execution 연결(다음 단계) 항목 — 본 스터디 범위 밖.

[UNSPECIFIED]: 정확한 필터 threshold 미공개 -> 정확한 재현 대신 지시대로
feature를 하나씩 추가하며 각 단계의 T+1/5/10 초과수익을 측정한다.
각 feature의 임시 정의 (첫 실행 고정, 튜닝 없음 — 문서에 그대로 남긴다):
  - 거래대금: 당일 거래대금이 같은 날 패널 내 상위 30%(백분위 >= 0.7)
    (연도별 물가 상승을 피하기 위해 절대 금액 대신 당일 내 분위 사용)
  - +외국인: foreign_nb_1d > 0 (당일 외국인+기타외국인 순매수)
  - +기관:   inst_nb_1d   > 0 (당일 8카테고리 순매수)
  - +개인:   indiv_nb_1d  > 0 (당일 개인 순매수 — 동시순매수와 양립 여부 자체가
    관측 대상; '개인 역방향' 해석은 본 문서에서 검증하지 않음)
  - +가격위치: pos20 = (close - min20) / (max20 - min20) >= 0.5
    (직전 20거래일 고저 범위에서 중간 이상; 방향·기간 모두 임시 선택)

데이터: a4 패널(수급 1d·거래대금·fwd 수익률) + A2a OHLC 캐시(.cache/a2a_parquet,
읽기 전용)에서 pos20 산출.

측정: v1~v6와 동일 관례 — 신호일 t 종가 기준 close-to-close(A2a), 같은 날 패널 전체
동일가중 벤치마크, 날짜별 초과수익의 날짜 동일가중 평균. 실거래 계약(signal t →
t+1 open)과의 차이는 근사치 한계.

  python v7_eod_scanner_signal_study.py
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "v7-eod-scanner")
HORIZONS = {"T+1": 1, "T+5": 5, "T+10": 10}
AMT_Q = 0.70
POS_WINDOW = 20
POS_MIN = 0.50


def load_panel_full():
    cols = ["ticker", "date", "close", "total_amount",
            "foreign_nb_1d", "inst_nb_1d", "indiv_nb_1d"]
    df = pd.read_parquet(A4_PANEL_PATH, columns=cols)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")["close"]
    for h_name, h in HORIZONS.items():
        df[f"fwd_{h}"] = g.transform(lambda s: s.shift(-h) / s - 1)
    return df


def load_pos20():
    frames = []
    for year in range(2016, 2027):
        p = os.path.join(A2A_CACHE_DIR, f"{year}.parquet")
        if not os.path.exists(p):
            continue
        d = pd.read_parquet(p, columns=["ticker", "date", "high", "low", "close"])
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        g = d.groupby("ticker")
        hi = g["high"].transform(lambda s: s.rolling(POS_WINDOW, min_periods=POS_WINDOW).max())
        lo = g["low"].transform(lambda s: s.rolling(POS_WINDOW, min_periods=POS_WINDOW).min())
        span = hi - lo
        d["pos20"] = np.where(span > 0, (d["close"] - lo) / span, np.nan)
        frames.append(d[["ticker", "date", "pos20"]])
    out = pd.concat(frames, ignore_index=True)
    return out.drop_duplicates(["ticker", "date"])


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
    panel = load_panel_full()
    print(f"panel rows={len(panel)}, tickers={panel['ticker'].nunique()} ({time.time()-t0:.0f}s)")

    pos = load_pos20()
    df = panel.merge(pos, on=["ticker", "date"], how="left")
    print(f"pos20 merged rows={df['pos20'].notna().sum()} ({time.time()-t0:.0f}s)")

    amt_rank = df.groupby("date")["total_amount"].rank(pct=True)
    stages = {
        "S1_amtTop30": amt_rank >= AMT_Q,
        "S2_plusForeign": None,
        "S3_plusInst": None,
        "S4_plusIndiv": None,
        "S5_plusPos20half": None,
    }
    mask = stages["S1_amtTop30"]
    stages["S2_plusForeign"] = mask & (df["foreign_nb_1d"] > 0)
    stages["S3_plusInst"] = stages["S2_plusForeign"] & (df["inst_nb_1d"] > 0)
    stages["S4_plusIndiv"] = stages["S3_plusInst"] & (df["indiv_nb_1d"] > 0)
    stages["S5_plusPos20half"] = stages["S4_plusIndiv"] & (df["pos20"] >= POS_MIN)

    # '개인 순매수' 해석이 공집합(외국인+기관 동시매수 시 개인은 대략 반대편)이면
    # 대안 가독 '개인 순매도'를 명시적 변형으로 추가한다 (V3 entryLow/entryClose,
    # V5 divA/divB와 같은 다중 가독 처리 — 어느 쪽이 영상 원본인지는 미상).
    if int(stages["S4_plusIndiv"].sum()) == 0:
        stages["S4alt_plusIndivSell"] = stages["S3_plusInst"] & (df["indiv_nb_1d"] < 0)
        stages["S5alt_plusPos20half"] = stages["S4alt_plusIndivSell"] & (df["pos20"] >= POS_MIN)

    results = {}
    for name, m in stages.items():
        sig_all = df[m]
        block = {"signalRowsRaw": int(len(sig_all))}
        print(f"{name}: rows={len(sig_all)}")
        for h_name, h in HORIZONS.items():
            fwd_col = f"fwd_{h}"
            bench = df.dropna(subset=[fwd_col]).groupby("date")[fwd_col].mean()
            block[h_name] = stats_for(sig_all, bench, fwd_col)
            r = block[h_name]
            print(f"  {h_name}: n={r['n']}, mean={r.get('mean')}, median={r.get('median')}, "
                  f"win={r.get('winRate')}, bench={r.get('benchMean')}, excess={r.get('excessPerDateMatched')}")
        results[name] = block

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "signal_study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "V7 종가베팅 EOD 스캐너 단계별 feature 스태킹 signal study — 엔진 미연결 "
                       "이벤트 스터디. threshold 미공개라 각 feature 임시 정의로 한계 기여 측정.",
            "panelRows": int(len(df)),
            "conventions": {
                "observed": "장마감 시점 거래량·거래대금·외국인/기관/개인 수급·가격위치 종합 선정, "
                            "T+1 이후 성과 추적. 1차 익절 +10%/2차 익절 +20%는 RiskSpec 연결 항목.",
                "unspecifiedProvisional": {
                    "amtFilter": "당일 거래대금 패널 내 백분위 >= 0.70",
                    "foreign": "foreign_nb_1d > 0",
                    "inst": "inst_nb_1d > 0",
                    "indiv": "indiv_nb_1d > 0 (관측 결과 공집합 — 외국인+기관 동시매수와 양립 불가) "
                             "-> 대안 가독 indiv_nb_1d < 0 (개인 순매도)를 S4alt/S5alt로 병행",
                    "pricePosition": "pos20=(close-min20)/(max20-min20) >= 0.5, 창 20거래일",
                },
                "stacking": "단계별 누적 AND (지시서 순서 그대로)",
                "data": "a4 패널 + A2a OHLC 캐시(읽기 전용)",
                "forwardReturn": "t 종가 → t+h째 행 종가 (A2a adjusted, close-to-close)",
                "benchmark": "같은 날 패널 전체 종목 동일가중 (신호 종목 포함)",
                "pitNote": "실거래 계약은 signal t → t+1 open 체결이므로 이벤트 스터디 근사치",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
