#!/usr/bin/env python3
"""drop-events-v2b: vix30-fall3 의 VIX>=30 국면 매칭 대조. 사전등록 findings/drop-events-v2b-preregistration-2026-11.md.
    python research/strategy-lab/run_dropevents_v2b.py"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_dropevents_v2 as V  # noqa: E402
import tech_timing_3x as B  # noqa: E402


def main():
    vix = B.load("^VIX")["Close"]
    per, base_info = {}, {}
    for tk, us in [("^GSPC", True), ("^NDX", True), ("^SOX", True), ("^RUT", True), ("^N225", False), ("^GDAXI", False), ("^KS11", False), ("^KQ11", False), ("^HSI", False)]:
        s = V.load(tk)
        a = V.fw(s.values, 63)
        v = (vix if us else vix.shift(1)).reindex(s.index).ffill().values
        reg = (v >= 30) & ~np.isnan(a)
        base = float(a[reg].mean()) if reg.sum() >= 30 else np.nan
        uncond = float(np.nanmean(a))
        ev = [i for i in V.ev_vix30(s, vix, us) if not np.isnan(a[i])]
        per[tk] = [(str(s.index[i].date()), float(a[i] - base)) for i in ev] if base == base else []
        base_info[tk] = dict(VIX30날=int(reg.sum()), 국면평균63=round(base, 2) if base == base else None, 무조건평균63=round(uncond, 2),
                             사건=len(ev), 사건평균=round(float(np.mean([a[i] for i in ev])), 2) if ev else None)
    rows = V.study("vix30-fall3-events(VIX≥30 날 대조)", 63, {"VIX≥30·3일 연속 하락 vs VIX≥30 모든 날": per}, "INCONCLUSIVE(2/9)")
    out = dict(요약=rows, 시장별=base_info)
    (V.F / "drop-events-v2b-results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        print({k: r.get(k) for k in ["유효시장", "시장당부호일치", "지역", "지역평균", "사건", "군집", "평균초과", "ci95", "ci95_14일", "ci95_60일", "구간0제외"]})
    for k, v in base_info.items():
        print(k, v)


if __name__ == "__main__":
    main()
