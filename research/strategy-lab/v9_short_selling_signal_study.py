#!/usr/bin/env python
"""V9 공매도 signal study - [RESEARCH HYPOTHESIS] (영상 출처 없음, 순수 연구 가설).

데이터: data/backfill/shortSelling/a8/*.jsonl.gz (A8 finalize, SS-1.1,
5,310,860행, 2016-06-30~2026-08-14). 필드: shortVolume(당일 공매도 거래량),
shortBalanceShares(공매도 잔고수량), shortValue, shortBalanceValue.

PIT 판정 (첫 단계):
  - A8 값은 '그 거래일 d에 발생한' 수치지만 공시는 익일이다 - 잔고는 2019-04-05부터
    상장법인이 매매영업일 다음 날까지 공시하는 의무 규칙, 거래량·잔고 집계 모두
    KRX가 다음 영업일 공표. 즉 d의 값이 시장에 알려지는 최소 시점은 d+1이다.
  - 따라서 신호일 s가 사용할 수 있는 최신 A8 값은 "직전 거래일 d=prev(s)"분이고,
    이는 engine 계약(signal s -> next open 체결)과 정합적이다. 구현: 병합된
    패널에서 특징을 계산한 뒤 티커별 shift(1)로 신호일에 올린다.
  - _diagnostics.json에는 공시 시점 명시가 없어 위 규칙 근거를 문서로 남긴다.

가설 ([RESEARCH HYPOTHESIS], threshold 없음 - 부호/배율만, 첫 실행 고정):
  H1 숏스퀴즈 vs 지속하락 방향 확인:
    surge[d] = shortVolume[d] >= 2 * mean(shortVolume[d-20..d-1])
    ("최근 20일 평균 대비 급증(예: 2배 이상)" - 지시문 예시 배율 그대로).
    신호일 s = d+1. 방향만 본다: 양(-) 평균이면 반등(숏스퀴즈) 쪽, 음(-)이면 지속하락.
  H2 잔고 5일 변화율 부호별:
    chg5[d] = shortBalanceShares[d] / shortBalanceShares[d-5] - 1 (기준>0)
    up(증가=비관 심화) / down(감소=숏커버링) 두 그룹을 나란히 보고.

측정: v1~v8 동일 관례 - 신호일 s 종가 기준 T+1/5/10/20 close-to-close(A2a),
같은 날 유니버스 전체 동일가중 벤치마크, 날짜별 초과수익의 날짜 동일가중 평균.
유니버스 = a4 패널 ticker(2,558종목).

  python v9_short_selling_signal_study.py
"""
import gzip
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(REPO_ROOT, "data", "backfill", "shortSelling", "a8")
CACHE_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "v9_shortselling")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "short-selling-signal")
HORIZONS = {"T+1": 1, "T+5": 5, "T+10": 10, "T+20": 20}
SURGE_MULTIPLE = 2.0
SURGE_WINDOW = 20


def extract_cache():
    """jsonl.gz -> 연도별 parquet 캐시(티커/날짜/거래량/잔고수량)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    total = 0
    for year in range(2016, 2027):
        out_path = os.path.join(CACHE_DIR, f"{year}.parquet")
        if os.path.exists(out_path):
            continue
        src = os.path.join(SRC_DIR, f"{year}.jsonl.gz")
        if not os.path.exists(src):
            continue
        rows = []
        with gzip.open(src, "rt", encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                rows.append((d["ticker"], d["date"], d["shortVolume"], d["shortBalanceShares"]))
        df = pd.DataFrame(rows, columns=["ticker", "date", "sv", "sb"])
        df.to_parquet(out_path, index=False)
        total += len(df)
        print(f"extract {year}: {len(df)} rows")
    return total


def load_a8():
    frames = []
    for year in range(2016, 2027):
        p = os.path.join(CACHE_DIR, f"{year}.parquet")
        if os.path.exists(p):
            frames.append(pd.read_parquet(p))
    df = pd.concat(frames, ignore_index=True)
    return df.sort_values(["ticker", "date"]).reset_index(drop=True)


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
    n_new = extract_cache()

    from v6_acc_price_signal_study import load_panel  # a4 패널(universe+fwd) 재사용
    panel = load_panel()
    print(f"panel rows={len(panel)}, tickers={panel['ticker'].nunique()} ({time.time()-t0:.0f}s)")

    a8 = load_a8()
    df = panel.merge(a8, on=["ticker", "date"], how="left").sort_values(["ticker", "date"]).reset_index(drop=True)
    cov = float(df["sv"].notna().mean())
    sb_changed = float((df.groupby("ticker")["sb"].transform(lambda s: s.ne(s.shift())))
                       .mean())
    print(f"a8 cache rows={len(a8)}, merged coverage={cov:.4f}, sb-changed-share={sb_changed:.4f} "
          f"(new extractions={n_new}) ({time.time()-t0:.0f}s)")

    g = df.groupby("ticker")
    # --- PIT(T+1 공시): 신호일 s는 직전 거래일 d의 A8 값을 쓴다 -> 아래에서 shift(1)
    sv_prev_avg = g["sv"].transform(lambda s: s.shift(1).rolling(SURGE_WINDOW, min_periods=SURGE_WINDOW).mean())
    surge_d = (df["sv"] > 0) & sv_prev_avg.notna() & (df["sv"] >= SURGE_MULTIPLE * sv_prev_avg)
    # PIT(T+1 공시): 신호일 s = 직전 거래일 d -> 티커별 shift(1)
    h1_sig = surge_d.groupby(df["ticker"]).shift(1).fillna(False).astype(bool)

    sb_base = g["sb"].shift(5)
    chg5_d = np.where(sb_base > 0, df["sb"] / sb_base.replace(0, np.nan) - 1, np.nan)
    chg5_s = pd.Series(chg5_d, index=df.index).groupby(df["ticker"]).shift(1)
    h2_up = (chg5_s > 0).fillna(False)
    h2_down = (chg5_s < 0).fillna(False)

    variants = {
        "H1_volumeSurge2x_vs20dAvg": h1_sig,
        "H2a_balanceRising5d_chgPositive": h2_up,
        "H2b_balanceFalling5d_chgNegative": h2_down,
    }

    diag = {
        "panelRowsWithA8": int(df["sv"].notna().sum()),
        "coverageShareOfPanel": round(cov, 4),
        "sbChangedShareVsPrevDay": round(sb_changed, 4),
        "surgeDaysRaw": int(surge_d.sum()),
        "h1SignalRows": int(h1_sig.sum()),
        "h2UpRows": int(h2_up.sum()),
        "h2DownRows": int(h2_down.sum()),
    }
    print("diag:", diag)

    results = {"diagnostics": diag}
    for name, mask in variants.items():
        sig_all = df[mask]
        block = {"signalRowsRaw": int(len(sig_all))}
        print(f"{name}: rows={len(sig_all)}")
        for h_name, h in HORIZONS.items():
            fwd_col = f"fwd_{h}"
            bench = df.dropna(subset=[fwd_col]).groupby("date")[fwd_col].mean()
            block[h_name] = stats_for(sig_all, bench, fwd_col)
            r = block[h_name]
            print(f"  {h_name}: n={r['n']}, mean={r.get('mean')}, median={r.get('median')}, "
                  f"win={r.get('winRate')}, excess={r.get('excessPerDateMatched')}")
        results[name] = block

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "signal_study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "label": "[RESEARCH HYPOTHESIS] - 영상 출처 없는 순수 연구 가설",
            "context": "V9 공매도 최소 signal study - 엔진 미연결 이벤트 스터디. 첫 실행 결과 그대로.",
            "pitVerdict": "A8 값은 거래일 d 기준이지만 공시는 익일(잔고는 2019-04-05부터 익영업일 "
                          "공시 의무). 신호일 s는 직전 거래일 분만 사용(shift(1)) - engine "
                          "signal s->next open 계약과 정합",
            "dataSources": ["data/backfill/shortSelling/a8/*.jsonl.gz (SS-1.1)",
                            ".cache/v9_shortselling (추출 캐시)",
                            "a4 패널(universe+fwd)"],
            "hypotheses": {
                "H1": "[RESEARCH HYPOTHESIS] shortVolume >= 2 * 직전 20거래일 평균(배율만, 예시값) "
                      "-> 다음 거래일 신호. 숏스퀴즈 vs 지속하락 방향 확인 목적",
                "H2": "[RESEARCH HYPOTHESIS] shortBalanceShares 5일 변화율 부호별(up=비관 심화 / "
                      "down=숏커버링), threshold 없음",
            },
            "forwardReturn": "s 종가 → s+h째 행 종가 (A2a adjusted, close-to-close)",
            "benchmark": "같은 날 패널 전체 종목 동일가중 (신호 종목 포함)",
            "pitNote": "실거래 계약은 signal s -> s+1 open 체결이므로 이벤트 스터디 근사치",
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
