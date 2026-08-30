#!/usr/bin/env python
"""V6 외국인+기관 동시 순매수 + 매집가 +5% 최소 signal study (엔진 미연결 — 이벤트 스터디만).

가설[V6, OBSERVED]:
  - 5일 누적 외국인+기관 동시 순매수 종목 중
  - "현재가가 매집가(평균 매수단가) 대비 +5% 이내"인 경우만 유효 진입
    (+5%는 영상에 실제로 나온 수치)

DATA GAP 검증 결과 (이 후보의 핵심 질문):
  - A4 연구 패널에는 카테고리별 '순매수 금액'만 있고 수량이 없다.
  - 그러나 원본 백필(data/backfill/supplyDemand/a4/*.jsonl.gz, 읽기 전용)에는
    투자자별 매수 금액(buyAmount)과 매수 수량(buyVolume)이 모두 있다.
    -> DATA GAP 아님. v6_extract_buy_vwap.py로 외국인(외국인+기타외국인)+
       기관(8카테고리)의 일별 총매수 금액/수량을 추출해 재현했다.

[UNSPECIFIED] -> 임시 채택 (첫 실행 고정, 튜닝 없음):
  - "매집가" = 직전 5거래일 동안 외국인+기관의 총매수금액 합 / 총매수수량 합
    (= pooled gross buy VWAP). 영상 정의 미상이므로 '그들이 실제로 산 가격'의
    가장 직접적인 근사로 총매수 VWAP을 채택 (순매수 기준은 수량 부호·0 문제).
  - 창 = rolling(5, min_periods=1) — 패널 nb_5d 컬럼과 동일 관례.
  - "+5% 이내" = 상한만 적용: close <= 1.05 * 매집가 (하한 조건 없음;
    매집가 아래 가격은 더 유리한 진입으로 보는 해석).
  - 비교용 baseline: 동시 순매수만(foreign_nb_5d>0 AND inst_nb_5d>0), 가격 필터 없음.

데이터: a4 패널(유니버스·nb_5d·fwd 수익률) + .cache/v6_acc_price/{year}.parquet
  (원본 백필에서 추출한 일별 외국인/기관 총매수 금액·수량).

측정: v5와 동일 관례 — T+1/5/10/20 close-to-close(A2a), 같은 날 패널 전체
동일가중 벤치마크, 날짜별 초과수익의 날짜 동일가중 평균.

  python v6_acc_price_signal_study.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from v5_divergence_signal_study import load_panel, HORIZONS  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "v6_acc_price")
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "v6-accrual-price")
PRICE_CAP = 1.05


def load_buy_flows():
    frames = []
    for year in range(2016, 2027):
        p = os.path.join(CACHE_DIR, f"{year}.parquet")
        if os.path.exists(p):
            frames.append(pd.read_parquet(p))
    df = pd.concat(frames, ignore_index=True)
    df["buyAmt"] = df["fBuyAmt"] + df["iBuyAmt"]
    df["buyVol"] = df["fBuyVol"] + df["iBuyVol"]
    return df.groupby(["ticker", "date"])[["buyAmt", "buyVol"]].sum().reset_index()


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
    panel = load_panel()
    print(f"panel rows={len(panel)}, tickers={panel['ticker'].nunique()} ({time.time()-t0:.0f}s)")

    flows = load_buy_flows()
    df = panel.merge(flows, on=["ticker", "date"], how="left")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")
    amt5 = g["buyAmt"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
    vol5 = g["buyVol"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
    df["accPrice"] = np.where(vol5 > 0, amt5 / vol5, np.nan)
    df["priceRatio"] = df["close"] / df["accPrice"]
    print(f"merged: rows with accPrice={df['accPrice'].notna().sum()} ({time.time()-t0:.0f}s)")

    both = (df["foreign_nb_5d"] > 0) & (df["inst_nb_5d"] > 0)
    variants = {
        "baseline_divBoth_noFilter": both,
        "v6_divBoth_plus5pctCap": both & (df["priceRatio"] <= PRICE_CAP),
    }

    # 진단: 동시 순매수 행들의 priceRatio 분포
    r = df.loc[both & df["priceRatio"].notna(), "priceRatio"]
    diag = {
        "divBothRowsWithAccPrice": int(len(r)),
        "passRatePlus5": round(float((r <= PRICE_CAP).mean()), 4),
        "quantiles": {q: round(float(r.quantile(q)), 4) for q in (0.1, 0.25, 0.5, 0.75, 0.9)},
    }
    print("diag:", diag)

    results = {"diagnostics": diag}
    for name, mask in variants.items():
        sig_all = df[mask]
        block = {"signalRowsRaw": int(len(sig_all))}
        print(f"{name}: signal rows={len(sig_all)}")
        for h_name, h in HORIZONS.items():
            fwd_col = f"fwd_{h}"
            bench = panel.dropna(subset=[fwd_col]).groupby("date")[fwd_col].mean()
            block[h_name] = stats_for(sig_all, bench, fwd_col)
            rr = block[h_name]
            print(f"  {h_name}: n={rr['n']}, mean={rr.get('mean')}, median={rr.get('median')}, "
                  f"win={rr.get('winRate')}, bench={rr.get('benchMean')}, excess={rr.get('excessPerDateMatched')}")
        results[name] = block

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "signal_study_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "V6 외국인+기관 동시 순매수 + 매집가+5% 최소 signal study — 엔진 미연결 "
                       "이벤트 스터디. 첫 실행 결과 그대로.",
            "panelRows": int(len(panel)),
            "conventions": {
                "observed": "5일 누적 외국인+기관 동시 순매수 중 현재가가 매집가 대비 +5% 이내인 "
                            "경우만 유효 진입",
                "dataGapVerdict": "DATA GAP 없음 — A4 패널엔 금액만 있으나 원본 백필(jsonl.gz)에 "
                                  "투자자별 매수 금액·수량 모두 존재. .cache/v6_acc_price로 추출해 사용.",
                "unspecifiedProvisional": {
                    "accPriceDefinition": "직전 5거래일 외국인+기관 총매수금액 합 / 총매수수량 합 "
                                          "(pooled gross buy VWAP)",
                    "window": "rolling(5, min_periods=1)",
                    "plus5Rule": "상한만: close <= 1.05*accPrice (하한 없음)",
                },
                "forwardReturn": "t 종가 → t+h째 행 종가 (A2a adjusted, close-to-close)",
                "benchmark": "같은 날 패널 전체 종목 동일가중 (신호 종목 포함)",
                "pitNote": "실거래 계약은 signal t → t+1 open 체결이므로 이벤트 스터디 근사치",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
