#!/usr/bin/env python
"""V4 Fibonacci 38.2/61.8 + 지지/저항 최소 signal study (엔진 미연결 — 이벤트 스터디만).

가설[V4, OBSERVED]: swing high-low 사이 되돌림 38.2%/61.8% 구간 + 기존 지지/저항
겹침에서 반전 진입.

핵심 리스크[UNSPECIFIED]: swing point 탐지 방법 미상 — 사람이 사후에 고르면
look-ahead가 된다. 본 스터디는 **인과적(causal) 탐지**로만 대응한다:
  - pivot high at k: high[k] == max(high[k-L .. k+L]) (대칭 창, L=3 임시)
  - 이 swing은 **k+L 봉이 종가로 닫힌 뒤에야 알려진 것**으로 취급한다.
    신호 판정은 확정 시점 이후 데이터만 사용 — 사후 선택 없음.
그 외 [UNSPECIFIED] -> 임시 채택 (첫 실행 고정, 튜닝 없음):
  - leg: 교대(zigzag) 수용한 확정 swing low -> 다음 확정 swing high (상승 다리).
    같은 유형 연속 후보는 더 극단값만 갱신. 새 swing high 확정 시 기존 세팅 대체.
  - fib zone: top = SH - 0.382*(SH-SL), bottom = SH - 0.618*(SH-SL)
  - 지지 겹침: 과거 확정 swing low 중 현재 leg의 SL 제외하고 가격이
    [zone_bottom, zone_top] 안에 있는 것이 하나라도 존재 (tolerance 없음)
  - 되돌림 깊이: 조건 없음 — zone 상단 터치만 요구 (V2와 동일 최소 해석)
  - 반전 트리거: SH 확정 후 최대 20거래일 내 first day with
    low[t] <= zone_top AND close[t] > zone_top, leg당 1회 발화
  - 무효화: 트리거 전 close < swing low면 leg 소멸 (최소 무효화)

데이터: 유니버스 = a4 연구 패널 ticker 집합(V1~V3와 동일). OHLC는 A2a 백필 캐시
(.cache/a2a_parquet/{year}.parquet, 읽기 전용)에서 로드.

측정: v1/v2/v3와 동일 관례 — 신호일 t 종가 기준 T+1/5/10/20 close-to-close(A2a),
같은 날 유니버스 전체 동일가중 벤치마크, 날짜별 초과수익의 날짜 동일가중 평균.

  python v4_fib_confluence_signal_study.py
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
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "v4-fib-sr")
HORIZONS = {"T+1": 1, "T+5": 5, "T+10": 10, "T+20": 20}
PIVOT_L = 3          # pivot 확인용 좌우 창 (임시)
SETUP_WINDOW = 20    # SH 확정 후 트리거 대기 한도 (임시)
FIB_LO, FIB_HI = 0.382, 0.618


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
    for h_name, h in HORIZONS.items():
        df[f"fwd_{h}"] = g.transform(lambda s: s.shift(-h) / s - 1)
    return df


def find_signals(df):
    """인과적 pivot -> zigzag leg -> fib zone x 지지 겹침 반등 신호."""
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()

    sig_pos = []
    diag = {"legs": 0, "triggered": 0, "invalidated": 0, "expired": 0,
            "noConfluence": 0}
    win_ = 2 * PIVOT_L + 1
    for _, idx in df.groupby("ticker").indices.items():
        h, l, c = highs[idx], lows[idx], closes[idx]
        n = len(idx)
        if n < win_ + SETUP_WINDOW:
            continue

        # --- 인과적 pivot 후보: k가 k-L..k+L 창의 극값. '확정'은 k+L 시점.
        hs, ls = pd.Series(h), pd.Series(l)
        rmax = hs.rolling(win_, center=True, min_periods=win_).max().to_numpy()
        rmin = ls.rolling(win_, center=True, min_periods=win_).min().to_numpy()
        events = []
        for k in range(PIVOT_L, n - PIVOT_L):
            conf = k + PIVOT_L
            if h[k] >= rmax[k]:
                events.append((conf, 0, "H", float(h[k]), k))
            if l[k] <= rmin[k]:
                events.append((conf, 1, "L", float(l[k]), k))
        events.sort()

        # --- zigzag식 교대 수용 (확정 시점 순서, 연속 동형은 극단값 갱신)
        swings = []  # (typ, price, orig_k, confirm_idx)
        for conf, _, typ, price, k in events:
            if swings and swings[-1][0] == typ:
                last_price = swings[-1][1]
                if (typ == "H" and price >= last_price) or (typ == "L" and price <= last_price):
                    swings[-1] = (typ, price, k, conf)
                continue
            swings.append((typ, price, k, conf))

        # --- 상승 leg(SL->SH 연쌍)마다 세팅. 유효 구간은 SH 확정 다음 날부터
        #     다음 H 확정 전까지(새 leg가 대체), 최대 SETUP_WINDOW 거래일.
        h_confs = [s[3] for s in swings if s[0] == "H"]
        for i in range(1, len(swings)):
            typ_l, p_l, k_l, c_l = swings[i - 1]
            typ_h, p_h, _k_h, c_h = swings[i]
            if typ_l != "L" or typ_h != "H":
                continue
            span = p_h - p_l
            if span <= 0:
                continue
            z_top = p_h - FIB_LO * span
            z_bot = p_h - FIB_HI * span
            next_h = min([hc for hc in h_confs if hc > c_h], default=None)
            end = n - 1
            if next_h is not None:
                end = min(end, next_h - 1)
            end = min(end, c_h + SETUP_WINDOW)
            diag["legs"] += 1

            outcome = "expired"
            for t in range(c_h + 1, end + 1):
                if c[t] < p_l:
                    diag["invalidated"] += 1
                    outcome = None
                    break
                if l[t] <= z_top and c[t] > z_top:
                    # 지지 겹침: 신호일 t까지 확정된 과거 swing low 중 현재 leg의
                    # SL 제외하고 가격이 zone 안에 있는 것 (모두 t 이전 확정분)
                    ok = any(z_bot <= p <= z_top
                             for (tp, p, kk, _cc) in swings[:i - 1] + [
                                 s for s in swings[i + 1:]
                                 if s[0] == "L" and s[3] <= t]
                             if tp == "L" and kk != k_l)
                    if not ok:
                        diag["noConfluence"] += 1
                        outcome = None
                        break
                    sig_pos.append(idx[t])
                    diag["triggered"] += 1
                    outcome = None
                    break
            if outcome == "expired":
                diag["expired"] += 1
    return np.array(sig_pos, dtype=int), diag


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

    sig_pos, diag = find_signals(df)
    print(f"legs={diag['legs']}, triggered={diag['triggered']}, "
          f"invalidated={diag['invalidated']}, noConfluence={diag['noConfluence']} ({time.time()-t0:.0f}s)")

    sig_all = df.iloc[sig_pos]
    results = {"signalRowsRaw": int(len(sig_all)), "diagnostics": diag}
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
            "context": "V4 Fibonacci 38.2/61.8 + 지지저항 최소 signal study — 엔진 미연결 "
                       "이벤트 스터디. [OBSERVED] 규칙만 구현, threshold 튜닝 없음, 첫 실행 결과 그대로.",
            "panelRows": int(len(df)),
            "conventions": {
                "observed": "swing high-low 되돌림 38.2/61.8% 구간 + 기존 지지 겹침에서 반전 진입",
                "unspecifiedProvisional": {
                    "swingDetectionCoreRisk": "look-ahead 방지 위해 인과적 pivot: high[k]==max("
                                              "high[k-L..k+L]) (L=3), 확정 시점=k+L. 신호는 확정 "
                                              "이후 데이터만 사용",
                    "legSelection": "zigzag 교대 수용(연속 동형은 극단값 갱신), 최근 SL->SH 상승 다리",
                    "fibZone": "top=SH-0.382*span, bottom=SH-0.618*span",
                    "srOverlap": "과거 확정 swing low 중 leg SL 제외하고 가격이 zone 내 존재 "
                                 "(tolerance 없음)",
                    "bounceTrigger": "SH 확정 후 최대 20거래일 내 first day with low<=zone_top "
                                     "AND close>zone_top, leg당 1회",
                    "invalidation": "트리거 전 close<SL이면 leg 소멸",
                    "setupWindowDays": SETUP_WINDOW,
                },
                "data": "OHLC: A2a 백필 캐시 .cache/a2a_parquet (읽기 전용), 유니버스: a4 패널 ticker",
                "forwardReturn": "t 종가 → t+h째 행 종가 (A2a adjusted, close-to-close)",
                "benchmark": "같은 날 유니버스 전체 종목 동일가중 (신호 종목 포함)",
                "pitNote": "실거래 계약은 signal t → t+1 open 체결이므로 이벤트 스터디 근사치",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
