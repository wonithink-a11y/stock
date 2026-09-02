#!/usr/bin/env python
"""sector_neutral_pbr_growth 전략 디렉터리 생성 — Tier 2(실제 엔진) 검증용.

sweep_combos 로 검증한 조합(sector_rel_pbr + sector_rel_growth_accel)을
pbr_value_v1 과 **완전히 같은 패턴**(오프라인 selection.json + 엔진 무변경)으로
strategies/ 에 만든다. 새 엔진 기능을 쓰지 않는다.

종목선택은 sweep_combos.build_matrices 를 그대로 재사용한다 - 랭킹 규약이
어긋나면 검증한 것과 다른 전략을 엔진에 태우게 된다.

★ 슬롯 수 주의
검증한 것은 '상위 decile 전체 동일가중'(월 66~95종목)이다. pbr_value_v1 처럼
maxPositions=30 으로 두면 엔진이 티커 오름차순으로 잘라내 **다른 전략**이 된다.
그래서 두 판을 만든다:
  decile 판 (--top-n 0) : maxPositions=120, 검증한 것을 충실히 재현
  top30 판 (--top-n 30) : 개인 계좌에 현실적인 축약판, 별도 검증 대상

사용법
------
  python build_sector_neutral_selection.py                  # decile 판
  python build_sector_neutral_selection.py --top-n 30       # top30 판
  python build_sector_neutral_selection.py --selftest
"""
import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(LAB))
PANEL = os.path.join(LAB, "data", "factor-panel", "kr-monthly-v1.parquet")
MANIFEST = os.path.join(LAB, "data", "factor-panel", "_manifest_kr_monthly.json")

FACTORS = ["sector_rel_pbr", "sector_rel_growth_accel"]
TOP_QUANTILE = 0.9
MIN_NAMES = 30
FALLBACK_HOLD = 21

sys.path.insert(0, LAB)


def build(top_n=0):
    import sweep_combos as sw
    from engine.data.calendar import TradingCalendar

    catalog = json.load(open(MANIFEST, encoding="utf-8"))["factors"]
    panel = pd.read_parquet(PANEL)
    # period=None -> 전 구간. 엔진은 2016~2026 을 한 번에 돈다.
    R, FWD, TICK, months, M, W, names = sw.build_matrices(panel, catalog, FACTORS, None)
    comp = R[[0, 1]].sum(axis=0)

    picks = {}          # signal_date -> [ticker]
    for mi in range(M):
        row = comp[mi]
        v = ~np.isnan(row)
        if v.sum() < MIN_NAMES:
            continue
        idx = np.flatnonzero(v)
        if top_n:
            order = idx[np.argsort(-row[idx], kind="stable")][:top_n]
        else:
            thr = np.nanquantile(row[idx], TOP_QUANTILE)
            order = idx[row[idx] >= thr]
        sel = [names[c] for c in TICK[mi][order] if c >= 0]
        if sel:
            picks[months[mi]] = sel

    # holdSessions: 다음 리밸런싱일의 '다음 거래일'까지 (build_composite_selection.py 와 동일)
    cal = TradingCalendar(repo_root=REPO_ROOT)
    reb = sorted(picks)
    hold = {}
    for i, d in enumerate(reb):
        if i + 1 >= len(reb):
            hold[d] = FALLBACK_HOLD
            continue
        entry = cal.next_session(d)
        exit_target = cal.next_session(reb[i + 1])
        if entry is None or exit_target is None:
            hold[d] = FALLBACK_HOLD
            continue
        hold[d] = len(cal.sessions_between(entry, exit_target))

    selection = {}
    for d, tickers in picks.items():
        for t in tickers:
            selection.setdefault(t, []).append({"date": d, "holdSessions": hold[d]})
    for t in selection:
        selection[t].sort(key=lambda e: e["date"])

    counts = [len(v) for v in picks.values()]
    return selection, picks, counts, reb


def emit(strategy_id, selection, picks, counts, top_n):
    out_dir = os.path.join(LAB, "strategies", strategy_id)
    os.makedirs(out_dir, exist_ok=True)
    max_names = max(counts)
    max_positions = 30 if top_n else int(np.ceil(max_names / 10.0) * 10)

    with open(os.path.join(out_dir, "selection.json"), "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_sector_neutral_selection.py",
            "factors": FACTORS,
            "rankingConvention": "sweep_combos.build_matrices - 팩터별 월내 pct-rank 후 "
                                 "선택 팩터가 전부 있는 종목만(교집합), 방향 반영 랭크합",
            "selectionRule": (f"랭크합 상위 {top_n}개" if top_n
                              else f"랭크합 상위 {(1 - TOP_QUANTILE) * 100:.0f}% (decile)"),
            "sourcePanel": "data/factor-panel/kr-monthly-v1.parquet",
            "rebalanceMonths": len(picks),
            "avgSelectedPerMonth": round(float(np.mean(counts)), 1),
            "maxSelectedPerMonth": max_names,
            "tickersEverSelected": len(selection),
            "selection": selection,
        }, f, ensure_ascii=False, indent=1)

    policy = {
        "strategyId": strategy_id,
        "version": "0.1",
        "note": "업종중립 PBR + 성장가속. findings/sector-neutral-pbr-growth-2026-09.md 의 "
                "HOLD 후보를 실제 엔진에 연결한 것 - 그 검증 설계를 재구현하는 것이지 "
                "새로 발명하는 게 아니다. 오프라인 랭킹 + 엔진 무변경(pbr_value_v1 패턴).",
        "direction": "LONG_ONLY",
        "factor": {
            "note": "이 블록은 build_sector_neutral_selection.py 가 오프라인으로 읽는 설정이다 - "
                    "engine/runner.py 는 모른다(선택이 selection.json 에 이미 구워져 있다).",
            "metrics": FACTORS,
            "transform": "같은 달·같은 업종 내 백분위(업종 표본 5종목 미만 유보). "
                         "업종은 A1a 현재 분류라 엄밀히 PIT 아님",
            "rankDirection": "sector_rel_pbr 낮을수록 / sector_rel_growth_accel 높을수록 좋음",
            "selectionRule": (f"랭크합 상위 {top_n}개" if top_n else "랭크합 상위 decile"),
            "rebalanceFrequency": "monthly",
            "minTurnover20": 100000000,
            "minTurnoverNote": "절대 임계값 - 상대 tercile 아님(2026-08-21 사고 회피)",
            "sourcePanel": "research/strategy-lab/data/factor-panel/kr-monthly-v1.parquet",
        },
        "signal": {
            "expression": "그 달 dv20>=1억 유니버스 안에서 두 업종중립 팩터의 랭크합 상위 - "
                          "오프라인 계산, selection.json 에 (ticker, date) 목록으로 저장",
            "evaluatedAfter": "월별 리밸런싱일(패널의 각 월 첫 거래일)",
        },
        "entry": {
            "timing": "next_tradable_session_open",
            "signalDateField": "그 달 리밸런싱일",
            "entryDateField": "next_session(t)",
            "entryPriceField": "Open[entry_date]",
        },
        "risk": {
            "note": "가격 기반 stop/target 없음 - 순수 시간 기반 청산. stop_distance 를 "
                    "entry_price 대비 극단적으로 크게 잡아 STOP/TARGET 이 절대 안 걸리게 하고 "
                    "maxHoldingSessions 만으로 TIME_EXIT 을 강제한다(pbr_value_v1 과 동일).",
            "stopDistanceFormula": "entry_price * 100 (사실상 도달 불가)",
            "rewardRisk": 1.0,
            "maxHoldingSessions": FALLBACK_HOLD,
            "maxHoldingSessionsNote": "다음 리밸런싱일이 없는 마지막 달 폴백. 그 외 모든 신호는 "
                                      "selection.json 의 정확한 세션수를 쓴다.",
            "timeExitRule": "close of the Nth tradable session counting entry_date as session 1",
        },
        "sameBarRule": "STOP_FIRST",
        "gapRule": "fill at session Open if Open already through stop_price",
        "entryDaySameBarCheck": True,
        "cost": {"entryCostBps": 15, "exitCostBps": 15, "roundTripBps": 30, "slippageBps": 0},
        "portfolio": {
            "initialCapital": 100000000, "currency": "KRW",
            "maxPositions": max_positions,
            "maxPositionsNote": (
                "검증한 것은 '상위 decile 전체 동일가중'(월 최대 "
                f"{max_names}종목)이다. 슬롯을 30 으로 두면 엔진이 티커 오름차순으로 "
                "잘라내 다른 전략이 되므로 최대 선택수 이상으로 잡았다."
                if not top_n else
                "상위 30개만 고르는 축약판이라 슬롯 30 으로 충분하다."),
            "equalWeight": True, "fractionalShares": False,
            "sameDayCashReuse": False, "tieBreak": "ticker_ascending",
        },
        "universe": {"mode": "A1A_ONLY", "runClassAllowed": ["SMOKE"],
                     "primaryRequires": "A1A_A1B_MERGED universe with full A2a+A2b coverage"},
        "scheduling": {
            "continuousHoldOnRenewal": True,
            "note": "다음 리밸런싱에도 같은 종목이 선택되면 청산-재진입 없이 계속 보유 "
                    "(runner.py _merge_continuous_same_symbol_holds). pbr_value_v1 이 "
                    "2026-08-21 현금타이밍 진단에서 이 방식을 채택한 것과 동일.",
        },
        "warmup": {"note": "기술적 지표 없음 - compute_features 는 원본 bars 를 그대로 통과."},
    }
    with open(os.path.join(out_dir, "policy.json"), "w", encoding="utf-8") as f:
        json.dump(policy, f, ensure_ascii=False, indent=1)

    rule = '''"""업종중립 PBR + 성장가속. 선택은 selection.json 에 이미 구워져 있다.

build_sector_neutral_selection.py 가 생성한다 - 직접 고치지 말 것.
pbr_value_v1/rule.py 와 같은 구조(오프라인 선택 + 정확한 holdSessions 전달).
"""
import json
import os

import pandas as pd

from engine.signals.schema import RiskSpec, Signal

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_THIS_DIR, "policy.json"), encoding="utf-8") as _f:
    PARAMS = json.load(_f)

with open(os.path.join(_THIS_DIR, "selection.json"), encoding="utf-8") as _f:
    _SELECTION = {t: {e["date"]: e["holdSessions"] for e in entries}
                  for t, entries in json.load(_f)["selection"].items()}

TIE_BREAK = PARAMS["portfolio"]["tieBreak"]
_HOLD_COL = "holdSessions"
_STOP_MULTIPLE = 100.0
_REWARD_RISK = PARAMS["risk"]["rewardRisk"]
_FALLBACK_MAX_HOLDING = PARAMS["risk"]["maxHoldingSessions"]


def compute_features(bars: pd.DataFrame) -> pd.DataFrame:
    features = bars.copy()
    features[_HOLD_COL] = float("nan")
    return features


def generate_signals(symbol: str, features: pd.DataFrame) -> list:
    out = []
    for d, hold_sessions in _SELECTION.get(symbol, {}).items():
        ts = pd.Timestamp(d)
        if ts in features.index:
            features.loc[ts, _HOLD_COL] = hold_sessions
            out.append(Signal(symbol=symbol, signal_date=d, direction="LONG"))
    return out


def risk_spec_for(features_row) -> RiskSpec:
    close = float(features_row["close"])
    hold = features_row.get(_HOLD_COL)
    max_holding = int(hold) if hold is not None and not pd.isna(hold) else _FALLBACK_MAX_HOLDING
    return RiskSpec(stop_distance=close * _STOP_MULTIPLE, reward_risk=_REWARD_RISK,
                    max_holding_sessions=max_holding)


def evaluate_at(pit_features, symbol: str, date: str, prev_date):
    if date not in _SELECTION.get(symbol, {}):
        return None
    if pit_features.at(date) is None:
        return None
    return Signal(symbol=symbol, signal_date=date, direction="LONG")
'''
    with open(os.path.join(out_dir, "rule.py"), "w", encoding="utf-8") as f:
        f.write(rule)
    return out_dir, max_positions, max_names


def selftest():
    """selection.json 의 형태 계약만 검사한다(엔진이 읽는 모양)."""
    sel = {"005930": [{"date": "2016-01-04", "holdSessions": 20}]}
    assert all(isinstance(v, list) for v in sel.values())
    for entries in sel.values():
        for e in entries:
            assert set(e) == {"date", "holdSessions"}
            assert isinstance(e["holdSessions"], int) and e["holdSessions"] > 0
            assert len(e["date"]) == 10 and e["date"][4] == "-"
    assert FACTORS == ["sector_rel_pbr", "sector_rel_growth_accel"]
    print("selftest OK (selection 형태 계약 4건)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-n", type=int, default=0, help="0 이면 상위 decile 전체")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return 0
    selftest()
    sid = f"sector_neutral_pbr_growth_v1{'_top' + str(a.top_n) if a.top_n else ''}"
    selection, picks, counts, reb = build(a.top_n)
    out_dir, max_pos, max_names = emit(sid, selection, picks, counts, a.top_n)
    print(f"저장: {out_dir}")
    print(f"  리밸런스 {len(picks)}개월 ({reb[0]} ~ {reb[-1]})")
    print(f"  월평균 {np.mean(counts):.1f}종목 · 최대 {max_names}종목 · "
          f"연인원 {sum(counts):,}건 · 종목수 {len(selection):,}")
    print(f"  maxPositions = {max_pos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
