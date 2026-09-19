#!/usr/bin/env python3
"""CAND1(PMCRASH_REVERSAL) forward OOS — 연구창(2025-08-08~2026-08-21) 이후 신규 분봉 구간.

    python research/strategy-lab/cand1_forward_oos.py            # 패널: .cache/fwd_oos/
    python research/strategy-lab/cand1_forward_oos.py --selftest

★ 이 스크립트는 **결과를 보기 전에** 커밋한다. 아래 사전 선언은 결과 뒤에 바꾸지 않는다.

파라미터는 전부 동결값이다(신호·체결·비용 무변경): thr=2%, vthr=1.5, mthr=None, 진입=익일 시가(n_open),
청산=익일 09:35 종가(n_c0935), 비용 20bp. 신호·체결 함수는 `analyze_cand1_regime_conditional` 것을 import 한다.

사전 선언 (판정 규칙):
  - 신규 신호일 = 08-21 이후 패널의 날짜 중 **다음 세션이 달력상 실제 다음 거래일**인 날만.
    (VM 에 08-24~26 원본이 없어 08-21 신호는 진입일 자료가 없다 — 패널의 '다음 행' 인접 규칙이
    그 날을 08-27 로 잘못 이어 붙이므로 명시적으로 제외한다.)
  - 지표: 일별 동일가중 순수익(bp) 평균, 일자 클러스터 t, 거래당 적중률, 같은 창 유니버스 EW 대비 초과.
  - 기준선: 같은 코드로 같은 패널에서 잰 **연구창 TEST(마지막 63일)** 값.
  - 판정: CONSISTENT = 신규 일별 순평균 > 0 이고 t ≥ 1.0 ;
          CONTRADICTS = 신규 일별 순평균 < 0 이고 t ≤ -1.0 ;
          그 밖은 INCONCLUSIVE (약 16일 표본이라 대부분 이쪽일 것이다 — 미리 인정한다).
  - CONSISTENT 라도 채택 근거가 아니다(표본 16일). 연구 후보 유지 여부의 참고일 뿐이다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FWD_DIR = HERE / ".cache" / "fwd_oos"
STUDY_END = "2026-08-21"


def cluster_stats(daily: pd.Series) -> dict:
    """일별 순수익(소수) 시계열 -> 평균 bp·t·일수."""
    d = daily.dropna()
    n = len(d)
    if n < 2:
        return {"days": n, "meanBp": float("nan"), "t": float("nan")}
    m, sd = d.mean(), d.std(ddof=1)
    return {"days": n, "meanBp": float(m * 1e4), "t": float(m / (sd / np.sqrt(n))) if sd > 0 else float("nan")}


def verdict(mean_bp: float, t: float) -> str:
    if mean_bp > 0 and t >= 1.0:
        return "CONSISTENT"
    if mean_bp < 0 and t <= -1.0:
        return "CONTRADICTS"
    return "INCONCLUSIVE"


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    ck("양의 표본은 CONSISTENT", verdict(30.0, 1.5) == "CONSISTENT")
    ck("음의 표본은 CONTRADICTS", verdict(-30.0, -1.5) == "CONTRADICTS")
    ck("약한 표본은 INCONCLUSIVE", verdict(30.0, 0.5) == "INCONCLUSIVE" and verdict(-5.0, -0.2) == "INCONCLUSIVE")
    s = cluster_stats(pd.Series([0.01, 0.02, 0.03, np.nan]))
    ck("클러스터 통계(NaN 제외)", s["days"] == 3 and abs(s["meanBp"] - 200.0) < 1e-9 and s["t"] > 0)
    print(f"\nselftest {4 - len(fails)}/4" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    import run_strategy_validation as rsv
    import analyze_cand1_regime_conditional as A

    rsv.PANEL_PATH = str(FWD_DIR / "intraday_panel.parquet")
    rsv.GRID_PATH = str(FWD_DIR / "intraday_grid5m.parquet")
    f, p, _g = rsv.load_frame()

    cal = json.loads(A.CALENDAR_PATH.read_text(encoding="utf-8"))["tradingDays"]
    nxt_cal = {cal[i]: cal[i + 1] for i in range(len(cal) - 1)}
    p_dates = sorted(p["date"].unique())
    dd = pd.Series(p_dates)
    # 패널의 다음 날짜가 달력상 다음 거래일인 신호일만 유효
    valid_sig = {d for i, d in enumerate(p_dates[:-1]) if nxt_cal.get(d) == p_dates[i + 1]}

    trades = A.build_signal_trades(f)
    trades = trades[trades["signalDate"].isin(valid_sig)]
    daily = trades.groupby("signalDate")["pnlNet"].mean()

    with np.errstate(all="ignore"):
        uni = (f["n_c0935"] / f["n_open"] - 1.0).dropna().groupby(f["date"]).mean()
    uni = uni[uni.index.isin(valid_sig)]

    old_dates = [d for d in p_dates if d <= STUDY_END]
    test_dates = set(old_dates[-63:])
    new_dates = {d for d in valid_sig if d > STUDY_END}

    def block(dates):
        s = daily[daily.index.isin(dates)]
        tr = trades[trades["signalDate"].isin(dates)]
        u = uni[uni.index.isin(dates)]
        st = cluster_stats(s)
        st.update({"trades": int(len(tr)), "hitRate": float((tr["pnlNet"] > 0).mean()) if len(tr) else float("nan"),
                   "univEwGrossBp": float(u.mean() * 1e4) if len(u) else float("nan"),
                   "signalDays": int(s.notna().sum())})
        return st

    ref, fwd = block(test_dates), block(new_dates)
    fwd["verdict"] = verdict(fwd["meanBp"], fwd["t"])
    res = {"params": {"thr": A.THR, "vthr": A.VTHR, "entry": A.ENTRY_COL, "exit": A.EXIT_COL, "costBps": A.COST_BPS},
           "studyEnd": STUDY_END, "newSignalDays": sorted(new_dates), "referenceTest63": ref, "forward": fwd}
    (HERE / "findings" / "cand1-forward-oos-2026-09.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else main())
