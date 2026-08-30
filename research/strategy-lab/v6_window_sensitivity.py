#!/usr/bin/env python
"""V6 매집가 창 민감도 스터디 - 튜닝이 아니라 민감도 확인(세 버전 전부 보고).

audit 지적: "매집가=5일 총매수VWAP"이라는 [UNSPECIFIED] 임시 정의 하나가 V6 결과를
지배할 수 있다. 창을 3일/5일(기존)/10일로 바꿔 같은 V6 신호 스터디(+5% 필터,
[OBSERVED] 그대로)를 각각 돌려 결과의 흔들림을 측정한다.

- 데이터: 기존 추출 캐시 .cache/v6_acc_price/{year}.parquet 재사용.
  v6_extract_buy_vwap.py는 일별 금액/수량 추출 단계(창 개념 없음)이므로 창은
  이 스크립트의 집계 단계에서 파라미터화된다.
- min_periods=1 관례도 기존과 동일하게 고정(창 외 요소 불변).
- threshold 튜닝 없음: PRICE_CAP=1.05([OBSERVED]) 고정, 세 창 전부 보고.

  python v6_window_sensitivity.py
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402

from v6_acc_price_signal_study import (  # noqa: E402
    PRICE_CAP,
    load_buy_flows,
    load_panel,
    stats_for,
)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "findings", "v6-window-sensitivity")
HORIZONS = {"T+1": 1, "T+5": 5, "T+10": 10, "T+20": 20}
WINDOWS = (3, 5, 10)


def main():
    t0 = time.time()
    panel = load_panel()
    flows = load_buy_flows()
    df = panel.merge(flows, on=["ticker", "date"], how="left")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"panel rows={len(df)}, tickers={df['ticker'].nunique()} ({time.time()-t0:.0f}s)")

    both = (df["foreign_nb_5d"] > 0) & (df["inst_nb_5d"] > 0)
    results = {}
    for win in WINDOWS:
        g = df.groupby("ticker")
        amt = g["buyAmt"].transform(lambda s, w=win: s.fillna(0).rolling(w, min_periods=1).sum())
        vol = g["buyVol"].transform(lambda s, w=win: s.fillna(0).rolling(w, min_periods=1).sum())
        acc = np.where(vol > 0, amt / vol, float("nan"))
        ratio = df["close"] / acc
        mask = both & ratio.notna() & (ratio <= PRICE_CAP)
        sig_all = df[mask]
        r_ratio = ratio[mask]

        block = {
            "signalRowsRaw": int(len(sig_all)),
            "passRatePlus5AmongDivBoth": round(float((both & ratio.notna() & (ratio <= PRICE_CAP)).sum()
                                                     / max(1, int((both & ratio.notna()).sum()))), 4),
            "ratioMedian": round(float(r_ratio.median()), 4),
            "accPriceCoverageRows": int(np.isfinite(acc).sum()),
        }
        print(f"window={win}: signals={len(sig_all)} ({time.time()-t0:.0f}s)")
        for h_name, h in HORIZONS.items():
            fwd_col = f"fwd_{h}"
            bench = df.dropna(subset=[fwd_col]).groupby("date")[fwd_col].mean()
            block[h_name] = stats_for(sig_all, bench, fwd_col)
            r = block[h_name]
            print(f"  {h_name}: n={r['n']}, mean={r.get('mean')}, median={r.get('median')}, "
                  f"win={r.get('winRate')}, bench={r.get('benchMean')}, excess={r.get('excessPerDateMatched')}")
        results[f"w{win}"] = block

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "window_sensitivity_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "purpose": "V6 매집가 창(3/5/10일) 민감도 확인 - 튜닝 아님, 세 버전 전부 보고",
            "conventions": {
                "observed": "[OBSERVED] 동시 순매수 + 매집가 대비 +5% 이내 (PRICE_CAP=1.05 고정)",
                "accPriceDefinition": "직전 W거래일 외국인+기관 총매수금액 합/총매수수량 합, "
                                      "min_periods=1 (기존 관례 유지)",
                "dataGapVerdictAndCache": ".cache/v6_acc_price (원본 백필에서 추출, 읽기 전용)",
                "benchmark": "같은 날 패널 전체 종목 동일가중",
            },
            "windows": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
