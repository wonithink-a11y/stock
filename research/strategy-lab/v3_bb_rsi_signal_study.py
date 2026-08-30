#!/usr/bin/env python
"""V3 Bollinger + RSI 최소 signal study (전략 엔진 미연결 — 이벤트 스터디만).

가설[V3, OBSERVED — 영상 문장 그대로]:
  - "캔들이 하단 밴드 이탈 + RSI<=30" -> 매수
  - "캔들이 상단 밴드 돌파" -> 청산
이 두 조건이 원본 규칙이다.

[UNSPECIFIED] -> 임시 채택 (첫 실행 고정, 튜닝 없음 — 이 구분을 문서에 그대로 남긴다):
  - BB 기간/표준편차: 20일, ±2 표준편차 (일반 기본값; 영상 확인분 아님)
  - RSI 기간: 14일 Wilder 평활 (일반 기본값)
  - 하단 이탈 기준(저가 vs 종가) 미상 → 두 가독을 변형으로 나란히 보고(v5의 divA/B처럼):
      entryLow   : low[k]   < lowerBand[k]
      entryClose : close[k] < lowerBand[k]
    공통 조건: rsi14[k] <= 30, 신호일 t = 조건 충족 행(연속 발화 그대로 카운트)
  - 상단 돌파 청산 기준도 미상 → 임시로 종가 확정 돌파 close[j] > upperBand[j].
    이벤트 스터디에서 관측 청산 규칙을 다음과 같이 반영: 신호일 t부터 최대 20거래일 내
    첫 상단 종가 돌파일 j에 청산(close[j]/close[t]-1), 없으면 T+20 강제 청산(censored).
    비교용 고정 홀딩 T+1/5/10/20 표는 v1/v2와 동일하게 함께 보고.

데이터: 유니버스 = a4 연구 패널 ticker 집합(V1/V2와 동일). OHLC는 A2a 백필 캐시
  (.cache/a2a_parquet/{year}.parquet, 읽기 전용)에서 로드.

측정: v1/v2와 동일 관례 — 신호일 t 종가 기준 T+1/5/10/20 close-to-close(A2a adjusted),
같은 날 유니버스 전체 동일가중 벤치마크, 날짜별 초과수익의 날짜 동일가중 평균.
실거래 계약(signal t → t+1 open)과의 차이는 근사치 한계. rule-exit 수치는 절대수익만.

  python v3_bb_rsi_signal_study.py
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "v3-bb-rsi")
HORIZONS = {"T+1": 1, "T+5": 5, "T+10": 10, "T+20": 20}
BB_PERIOD, BB_K = 20, 2.0
RSI_PERIOD = 14
EXIT_WINDOW = 20

ENTRY_VARIANTS = {
    "entryLow_lowBelowBand": ("low",),
    "entryClose_closeBelowBand": ("close",),
}


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
    mid = g.transform(lambda s: s.rolling(BB_PERIOD, min_periods=BB_PERIOD).mean())
    sd = g.transform(lambda s: s.rolling(BB_PERIOD, min_periods=BB_PERIOD).std())
    df["bbMid"] = mid
    df["bbLower"] = mid - BB_K * sd
    df["bbUpper"] = mid + BB_K * sd

    delta = g.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.groupby(df["ticker"]).transform(lambda s: s.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean())
    avg_loss = loss.groupby(df["ticker"]).transform(lambda s: s.ewm(alpha=1 / RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean())
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - 100 / (1 + rs)

    for h_name, h in HORIZONS.items():
        df[f"fwd_{h}"] = g.transform(lambda s: s.shift(-h) / s - 1)
    return df


def find_signals_and_exit(df, basis_col):
    """basis_col('low'|'close') < bbLower & rsi<=30 신호 + rule-exit 센서링."""
    lows = df[basis_col].to_numpy()
    closes = df["close"].to_numpy()
    lb = df["bbLower"].to_numpy()
    ub = df["bbUpper"].to_numpy()
    rsi = df["rsi"].to_numpy()

    sig_pos = []
    exit_ret = []
    exit_days = []
    censored = []
    for _, idx in df.groupby("ticker").indices.items():
        b, c = lows[idx], closes[idx]
        l, u, r = lb[idx], ub[idx], rsi[idx]
        n = len(idx)
        if n < max(BB_PERIOD, RSI_PERIOD) + 1:
            continue
        form = np.where((b < l) & (r <= 30))[0]
        for i in form:
            sig_pos.append(idx[i])
            hit = False
            end = min(i + EXIT_WINDOW, n - 1)
            for j in range(i + 1, end + 1):
                if c[j] > u[j]:
                    exit_ret.append(c[j] / c[i] - 1)
                    exit_days.append(j - i)
                    censored.append(False)
                    hit = True
                    break
            if not hit:
                exit_ret.append(c[end] / c[i] - 1)
                exit_days.append(end - i)
                censored.append(True)
    return (
        np.array(sig_pos, dtype=int),
        np.array(exit_ret),
        np.array(exit_days),
        np.array(censored),
    )


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

    results = {}
    for var_name, (basis_col,) in ENTRY_VARIANTS.items():
        sig_pos, exit_ret, exit_days, cens = find_signals_and_exit(df, basis_col)
        sig_all = df.iloc[sig_pos].copy()
        sig_all["exitRet"] = exit_ret
        print(f"{var_name}: signal rows={len(sig_all)} ({time.time()-t0:.0f}s)")
        block = {"signalRowsRaw": int(len(sig_all))}
        for h_name, h in HORIZONS.items():
            fwd_col = f"fwd_{h}"
            bench = df.dropna(subset=[fwd_col]).groupby("date")[fwd_col].mean()
            block[h_name] = stats_for(sig_all, bench, fwd_col)
            r = block[h_name]
            print(f"  {h_name}: n={r['n']}, mean={r.get('mean')}, median={r.get('median')}, "
                  f"win={r.get('winRate')}, bench={r.get('benchMean')}, excess={r.get('excessPerDateMatched')}")
        # OBSERVED 청산 규칙 반영(센서링): 절대수익만 보고
        block["ruleExitT20Censored"] = {
            "n": int(len(exit_ret)),
            "mean": round(float(np.mean(exit_ret)), 5),
            "median": round(float(np.median(exit_ret)), 5),
            "winRate": round(float((exit_ret > 0).mean()), 4),
            "avgExitDays": round(float(np.mean(exit_days)), 2),
            "medianExitDays": float(np.median(exit_days)),
            "censorRate": round(float(cens.mean()), 4),
        }
        re = block["ruleExitT20Censored"]
        print(f"  ruleExit: mean={re['mean']}, median={re['median']}, win={re['winRate']}, "
              f"exitDays(avg)={re['avgExitDays']}, censorRate={re['censorRate']}")
        results[var_name] = block

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "signal_study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "V3 Bollinger+RSI 최소 signal study — 엔진 미연결 이벤트 스터디. "
                       "[OBSERVED] 문장 그대로 구현, threshold 튜닝 없음, 첫 실행 결과 그대로.",
            "panelRows": int(len(df)),
            "conventions": {
                "observedEntry": "'캔들이 하단 밴드 이탈 + RSI<=30' -> 매수",
                "observedExit": "'캔들이 상단 밴드 돌파' -> 청산",
                "unspecifiedProvisional": {
                    "bbPeriodStd": "20일 ±2 표준편차 (pandas rolling std ddof=1)",
                    "rsiPeriod": "14일 Wilder ewm(alpha=1/14)",
                    "entryBasis": "미상 → 두 가독 병행: low<band(entryLow) / close<band(entryClose)",
                    "exitTrigger": "미상 → close>upperBand(종가 확정 돌파) 임시 채택",
                    "ruleExitStudy": "신호일부터 최대 20거래일 내 첫 상단 종가 돌파에 청산, "
                                     "없으면 T+20 강제 청산(censored). 절대수익만 산출.",
                },
                "data": "OHLC: A2a 백필 캐시 .cache/a2a_parquet (읽기 전용), 유니버스: a4 패널 ticker",
                "forwardReturn": "t 종가 → t+h째 행 종가 (A2a adjusted, close-to-close)",
                "benchmark": "같은 날 유니버스 전체 종목 동일가중 (신호 종목 포함) — 고정 홀딩 표만",
                "pitNote": "실거래 계약은 signal t → t+1 open 체결이므로 이벤트 스터디 근사치; "
                           "하단 이탈 연속일 중복 카운트 있음",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
