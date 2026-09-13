#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""RV20 sizing 규칙(동결, futures-rv20-sizing-rule-freeze-2026-09-13.md)을
KOSPI200 선물 모의투자에 시험 적용하기 위한 **순수 계산** 계층. 네트워크·
KIS 호출 없음 - 오늘의 목표 익스포저(1.0x/0.0x)와 그에 맞는 계약 수만
계산한다. 실제 주문은 `kis_vts_futures_order.py`(별도, 이 스크립트의
출력을 받아서만 동작)가 한다 - 신호 계산과 주문 실행을 분리해 신호
쪽은 계좌 없이도, 언제든 재현 가능하게 둔다.

**동결 규칙 재사용 원칙**: 이 파일은 stage5_1/stage5_3의 함수를 그대로
import한다 - 재구현하지 않는다. 재구현하면 그 자체가 동결 위반이자
새로운 회귀 위험이다(동결 메모 §1.3).

사용법:
    python rv20_sizing_paper_signal.py --capital 250000000
    (계좌 중 이 실험에 배정한 자본 - "50%만 적용"의 50%는 호출부가
    이미 계산해서 넘긴다. 이 스크립트는 배정된 자본 자체를 안다고
    가정하고 그 안에서 0x/1x만 결정한다 - "50%가 뭘 뜻하는지"는
    사용자 확인사항이었지 이 스크립트가 다시 판단할 문제가 아니다.)
"""
import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage5_1_volatility_event_study import load, front_series, process
from stage5_3_sizing_backtest import target_weight, Q5_CUT, MULT

STATE_DIR = Path(__file__).resolve().parents[1] / "data" / "paper-futures"
RULE = "defensive"  # Rule B(Q5->0x) - 사용자 확정(2026-09-13)
FREEZE_DOC = "research/strategy-lab/futures/futures-rv20-sizing-rule-freeze-2026-09-13.md"


def compute_today_signal():
    """가장 최근 거래일 기준 pct_rv20_rol과 목표 weight를 계산한다.
    반환: dict(asOfDate, rv20, pct, targetWeight, lastClose)."""
    df = load()
    fr = front_series(df)
    d, _, _ = process(fr)
    pct = d["pct_rv20_rol"].dropna()
    if len(pct) == 0:
        raise RuntimeError("pct_rv20_rol이 전부 NaN - warmup(252관측) 미달이거나 데이터 문제")
    last_date = pct.index[-1]
    last_pct = float(pct.iloc[-1])
    last_rv20 = float(d["rv20"].loc[last_date])
    w = target_weight(last_pct, RULE)
    cts = fr[~fr["roll"]]
    last_close = float(cts["TDD_CLSPRC"].reindex([last_date]).iloc[0]) if last_date in cts.index else None
    return {
        "asOfDate": str(last_date.date()),
        "rv20": round(last_rv20, 4),
        "pctRv20Rolling252": round(last_pct, 4),
        "q5Cut": Q5_CUT,
        "rule": "B (Q5->0x, defensive)",
        "targetWeight": w,
        "lastClose": last_close,
        "freezeDoc": FREEZE_DOC,
    }


def target_contracts(signal: dict, capital_krw: float) -> dict:
    """배정 자본과 목표 weight로 계약 수를 계산한다. 레버리지 없음(노출
    weight <= 1.0x, 명목가치를 자본으로 전액 커버) - 동결 메모·futures
    Stage 5-3 원문과 동일 원칙."""
    if signal["lastClose"] is None:
        raise RuntimeError(f"{signal['asOfDate']} 종가를 못 찾음 - 롤봉이었을 수 있음")
    notional_per_contract = signal["lastClose"] * MULT
    target_notional = capital_krw * signal["targetWeight"]
    contracts = int(round(target_notional / notional_per_contract)) if notional_per_contract > 0 else 0
    return {
        **signal,
        "capitalKrw": capital_krw,
        "notionalPerContractKrw": round(notional_per_contract, 0),
        "targetContracts": contracts,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, required=True,
                     help="이 실험에 배정한 자본(원) - 계좌 전체가 아니라 이미 50% 등으로 나눈 값을 넣는다")
    args = ap.parse_args()

    signal = compute_today_signal()
    result = target_contracts(signal, args.capital)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = STATE_DIR / "rv20_sizing_signal_latest.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"기준일: {result['asOfDate']}  (동결 규칙: {FREEZE_DOC})")
    print(f"RV20={result['rv20']:.3f}  rolling252 percentile={result['pctRv20Rolling252']:.3f}"
          f"  (Q5 cut={result['q5Cut']})")
    print(f"규칙: {result['rule']}  ->  목표 익스포저 {result['targetWeight']}x")
    print(f"배정자본 {result['capitalKrw']:,.0f}원 / 계약당 명목가치 {result['notionalPerContractKrw']:,.0f}원"
          f"  ->  목표 계약수 {result['targetContracts']}")
    print(f"\n저장: {out_path}")
    if result["asOfDate"] < pd.Timestamp.now().strftime("%Y-%m-%d"):
        print(f"\n주의: 기준일이 오늘이 아니다 - .cache/kospi200_daily 갱신 필요할 수 있음"
              f"(collect_kospi200_daily_krx.py 재실행).")


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    sig = compute_today_signal()
    ck("asOfDate 존재", bool(sig["asOfDate"]))
    ck("targetWeight는 0.0 또는 1.0(Rule B, 레버리지 없음)", sig["targetWeight"] in (0.0, 1.0))
    ck("pctRv20Rolling252가 [0,1] 범위", 0.0 <= sig["pctRv20Rolling252"] <= 1.0)

    result = target_contracts(sig, 250_000_000)
    ck("targetContracts는 0 이상 정수", isinstance(result["targetContracts"], int) and result["targetContracts"] >= 0)
    ck("weight=0이면 계약수 0", sig["targetWeight"] != 0.0 or result["targetContracts"] == 0)

    total = 5
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    main()
