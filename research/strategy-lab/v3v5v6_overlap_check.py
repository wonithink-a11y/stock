#!/usr/bin/env python
"""양(-)의 초과수익 후보 세 개(V3, V5 divA, V6 필터 적용) 간 신호 겹침 검사.

findings/v3-overlap-check/와 동일 방법론:
  - 같은 종목에서 상대 신호가 ±3거래일 이내에 있는 비율(양방향)
  - 정확 동일일 보조치
세 쌍(V3-V5, V3-V6, V5-V6) 전부 적용. V3는 저가/종가 두 변형을 나란히 보고한다
(v3-overlap-check 전례와 동일).

신호 소스(모두 기존 스터디 코드 경로 재사용):
  V3       : v3_bb_rsi_signal_study.find_signals_and_exit (entryLow / entryClose)
  V5 divA  : foreign_nb_5d > 0 AND inst_nb_5d < 0 (v5_divergence_signal_study 정의)
  V6 필터  : foreign_nb_5d>0 & inst_nb_5d>0 & close<=1.05*accPrice(5일 pooled VWAP)

  python v3v5v6_overlap_check.py
"""
import json
import os
import sys
import time
from bisect import bisect_left

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

OUT_DIR = os.path.join(HERE, "findings", "signal-correlation-v3v5v6")
TOL = 3


def covered(sorted_pos, p, tol=TOL):
    i = bisect_left(sorted_pos, p - tol)
    return i < len(sorted_pos) and sorted_pos[i] <= p + tol


def pair_stats(set_a, set_b, date_pos):
    """set_a/set_b: {(ticker,date)} -> 양방향 커버리지 + 동일일."""
    b_by_ticker = {}
    for tk, d in set_b:
        b_by_ticker.setdefault(tk, []).append(int(date_pos[(tk, d)]))
    for tk in b_by_ticker:
        b_by_ticker[tk].sort()

    cov_a = exact = 0
    a_by_ticker = {}
    for tk, d in set_a:
        p = int(date_pos[(tk, d)])
        a_by_ticker.setdefault(tk, []).append(p)
        arr = b_by_ticker.get(tk, [])
        if covered(arr, p):
            cov_a += 1
        if (tk, d) in set_b:
            exact += 1
    for tk in a_by_ticker:
        a_by_ticker[tk].sort()
    cov_b = sum(1 for tk, d in set_b
                if covered(a_by_ticker.get(tk, []), int(date_pos[(tk, d)])))
    return {
        "aSize": len(set_a),
        "bSize": len(set_b),
        "aCoveredWithin3d": cov_a,
        "aCoveragePct": round(100.0 * cov_a / max(1, len(set_a)), 2),
        "exactSameDay": exact,
        "exactPctOfA": round(100.0 * exact / max(1, len(set_a)), 2),
        "bCoveredWithin3d": cov_b,
        "bCoveragePct": round(100.0 * cov_b / max(1, len(set_b)), 2),
    }


def main():
    t0 = time.time()
    # --- 마스터 패널(위치 인덱스 기준) + V5/V6 신호
    from v6_acc_price_signal_study import PRICE_CAP, load_buy_flows, load_panel
    panel = load_panel()
    print(f"panel rows={len(panel)} ({time.time()-t0:.0f}s)")
    panel["posInTicker"] = panel.groupby("ticker").cumcount()
    date_pos = dict(zip(zip(panel["ticker"], panel["date"]),
                        panel["posInTicker"].astype(int)))

    v5_set = set(zip(panel.loc[(panel["foreign_nb_5d"] > 0) & (panel["inst_nb_5d"] < 0), "ticker"],
                     panel.loc[(panel["foreign_nb_5d"] > 0) & (panel["inst_nb_5d"] < 0), "date"]))
    print(f"V5 divA signals={len(v5_set)} ({time.time()-t0:.0f}s)")

    flows = load_buy_flows()
    df6 = panel.merge(flows, on=["ticker", "date"], how="left").sort_values(["ticker", "date"]).reset_index(drop=True)
    g6 = df6.groupby("ticker")
    amt5 = g6["buyAmt"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
    vol5 = g6["buyVol"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
    import numpy as np
    acc = np.where(vol5 > 0, amt5 / vol5, float("nan"))
    ratio = df6["close"] / acc
    m6 = ((df6["foreign_nb_5d"] > 0) & (df6["inst_nb_5d"] > 0)
          & ratio.notna() & (ratio <= PRICE_CAP))
    v6_set = set(zip(df6.loc[m6, "ticker"], df6.loc[m6, "date"]))
    print(f"V6 signals={len(v6_set)} ({time.time()-t0:.0f}s)")

    # --- V3 신호 (별도 로더 - a2a 캐시 기반, 같은 유니버스/기간)
    from v3_bb_rsi_signal_study import find_signals_and_exit, load_ohlc
    df3 = load_ohlc()
    missing = 0
    v3_sets = {}
    for basis, name in (("low", "entryLow"), ("close", "entryClose")):
        sig_pos = find_signals_and_exit(df3, basis)[0]
        rows = df3.iloc[sig_pos]
        pairs = []
        for tk, d in zip(rows["ticker"], rows["date"]):
            if (tk, d) in date_pos:
                pairs.append((tk, d))
            else:
                missing += 1
        v3_sets[name] = set(pairs)
        print(f"V3 {name}: {len(v3_sets[name])} (unmapped={missing}) ({time.time()-t0:.0f}s)")

    sets = {"V3_entryLow": v3_sets["entryLow"], "V3_entryClose": v3_sets["entryClose"],
            "V5_divA": v5_set, "V6_filtered": v6_set}

    pair_defs = [
        ("V3_entryLow", "V5_divA"),
        ("V3_entryClose", "V5_divA"),
        ("V3_entryLow", "V6_filtered"),
        ("V3_entryClose", "V6_filtered"),
        ("V5_divA", "V6_filtered"),
        ("V3_entryLow", "V3_entryClose"),  # 참고: V3 내부 두 변형
    ]
    results = {}
    for a, b in pair_defs:
        results[f"{a}--{b}"] = pair_stats(sets[a], sets[b], date_pos)
        print(f"{a} -- {b}", results[f"{a}--{b}"])

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "overlap_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "method": "±3거래일 겹침률(양방향) + 정확 동일일 - findings/v3-overlap-check와 동일",
            "toleranceTradingDays": TOL,
            "universe": "a4 패널 2,558종목, 2016-01-04~2026-08-03",
            "signalSources": {
                "V3": "v3_bb_rsi_signal_study (entryLow/entryClose)",
                "V5_divA": "foreign_nb_5d>0 & inst_nb_5d<0",
                "V6_filtered": "동시순매수 & close<=1.05*매집가(5일 pooled buy VWAP)",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
