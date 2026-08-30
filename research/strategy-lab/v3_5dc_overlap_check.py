#!/usr/bin/env python
"""V3(Bollinger+RSI) vs 5dc_v1a_p LONG 진입 신호 겹침 검사.

- V3 신호: research/strategy-lab/v3_bb_rsi_signal_study.py가 만든 신호를 그대로
  재사용(entryLow / entryClose 두 변형 모두).
- 5dc_v1a_p 신호: strategies/5dc_v1a_p/rule.py의 compute_features()+generate_signals()
  을 엔진 그대로 호출(재구현 금지). 유니버스·기간은 V3와 동일(a4 ticker 집합,
  A2a 캐시 2016~2026).
- 겹침률: 같은 종목에서 상대 신호가 ±3거래일 이내에 있는 비율(양방향) + 정확 동일일 보조치.

  python v3_5dc_overlap_check.py
"""
import importlib.util
import json
import os
import sys
import time
from bisect import bisect_left

import pandas as pd  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from v3_bb_rsi_signal_study import load_ohlc, find_signals_and_exit  # noqa: E402

REPO_ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(HERE, "findings", "v3-overlap-check")
TOL = 3

spec = importlib.util.spec_from_file_location(
    "five_dc_rule", os.path.join(HERE, "strategies", "5dc_v1a_p", "rule.py"))
rule5 = importlib.util.module_from_spec(spec)
sys.modules["five_dc_rule"] = rule5
spec.loader.exec_module(rule5)


def covered(sorted_pos, p, tol=TOL):
    """sorted_pos 내 p±tol 위치에 신호가 하나라도 있으면 True."""
    i = bisect_left(sorted_pos, p - tol)
    return i < len(sorted_pos) and sorted_pos[i] <= p + tol


def main():
    t0 = time.time()
    df = load_ohlc()
    print(f"panel rows={len(df)}, tickers={df['ticker'].nunique()}, "
          f"dates {df['date'].min()}~{df['date'].max()} ({time.time()-t0:.0f}s)")
    df["posInTicker"] = df.groupby("ticker").cumcount()

    # --- 5dc 진행용 open/volume 병합 (같은 캐시, 컬럼만 추가)
    frames = []
    for year in range(2016, 2027):
        p = os.path.join(HERE, ".cache", "a2a_parquet", f"{year}.parquet")
        if os.path.exists(p):
            d = pd_read_cols(p)
            frames.append(d)
    extra = pd.concat(frames, ignore_index=True).drop_duplicates(["ticker", "date"]).drop(columns=["open"])
    df = df.merge(extra, on=["ticker", "date"], how="left")
    print(f"open/volume merged ({time.time()-t0:.0f}s)")

    # --- 5dc_v1a_p 신호 (엔진 rule 재사용)
    five_dc = set()
    n_tk = 0
    for tk, sub in df.groupby("ticker", sort=False):
        bars = sub.set_index("date")[["open", "high", "low", "close", "volume"]]
        feats = rule5.compute_features(bars)
        for sig in rule5.generate_signals(tk, feats):
            five_dc.add((tk, str(sig.signal_date)))
        n_tk += 1
        if n_tk % 500 == 0:
            print(f"  5dc tickers {n_tk}, signals so far {len(five_dc)} ({time.time()-t0:.0f}s)")
    print(f"5dc signals={len(five_dc)} ({time.time()-t0:.0f}s)")

    # --- 위치 인덱스 (dict: (ticker, date) -> 티커 내 거래일 순번)
    date_pos = dict(zip(zip(df["ticker"], df["date"]),
                        df["posInTicker"].astype(int)))
    dc_by_ticker = {}
    for tk, d in five_dc:
        dc_by_ticker.setdefault(tk, []).append(int(date_pos[(tk, d)]))
    for tk in dc_by_ticker:
        dc_by_ticker[tk].sort()

    results = {}
    v3_sets = {}
    for basis, name in (("low", "entryLow"), ("close", "entryClose")):
        sig_pos = find_signals_and_exit(df, basis)[0]
        rows = df.iloc[sig_pos]
        pairs = list(zip(rows["ticker"], rows["date"]))
        v3_sets[name] = len(pairs)

        cov_v3 = 0
        exact = 0
        for tk, d in pairs:
            p = int(date_pos[(tk, d)])
            arr = dc_by_ticker.get(tk, [])
            if covered(arr, p):
                cov_v3 += 1
            if (tk, d) in five_dc:
                exact += 1
        pct_v3 = round(100.0 * cov_v3 / max(1, len(pairs)), 2)

        # 역방향: 5dc 중 ±3거래일 내 V3가 있는 비율
        v3_by_ticker = {}
        for tk, d in pairs:
            v3_by_ticker.setdefault(tk, []).append(int(date_pos[(tk, d)]))
        for tk in v3_by_ticker:
            v3_by_ticker[tk].sort()
        cov_dc = 0
        for tk, d in five_dc:
            p = int(date_pos[(tk, d)])
            if covered(v3_by_ticker.get(tk, []), p):
                cov_dc += 1
        pct_dc = round(100.0 * cov_dc / max(1, len(five_dc)), 2)

        results[name] = {
            "v3Signals": len(pairs),
            "fiveDcSignals": len(five_dc),
            "v3CoveredWithin3d": cov_v3,
            "v3CoveragePct": pct_v3,
            "exactSameDay": exact,
            "exactPctOfV3": round(100.0 * exact / max(1, len(pairs)), 2),
            "fiveDcCoveredWithin3d": cov_dc,
            "fiveDcCoveragePct": pct_dc,
        }
        print(name, results[name])

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "overlap_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "universe": f"a4 tickers, A2a cache 2016~2026 (panel rows={len(df)})",
            "toleranceTradingDays": TOL,
            "fiveDcEnginePath": "strategies/5dc_v1a_p/rule.py compute_features+generate_signals",
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


def pd_read_cols(p):
    import pandas as pd
    d = pd.read_parquet(p, columns=["ticker", "date", "open", "volume"])
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    return d


if __name__ == "__main__":
    main()
