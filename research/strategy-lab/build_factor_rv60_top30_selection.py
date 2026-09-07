#!/usr/bin/env python
"""factor_rv60_v1_top30 selection builder — Low-vol 단독 long-only 30종목 판.

독립 실험(05_lowvol_factor_oos)의 최소 비교 중 'top-30 portfolio' 항목을 위해
기존 decile 판(factor_rv60_v1)과 **완전히 같은 A4 파이프라인**으로 만든다.
같은 PIT / 유니버스 / 유동성 게이트 / 월별 리밸런스 / holdSessions 규약을 쓰되,
선택 규칙만 'rv60_pct 하위 30종목'으로 바꾼다. 기존 코드는 읽기 전용으로
재사용하고(수정 금지) 이 스크립트는 연구 산출물로만 존재한다.

  python build_factor_rv60_top30_selection.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAB = os.path.join(REPO_ROOT, "research", "strategy-lab")
A4_PATH = os.path.join(LAB, "data", "a4", "a4-research-dataset.parquet")
OUT_DIR = os.path.join(LAB, "strategies", "factor_rv60_v1_top30")

START = "2016-01-01"
END = "2026-09-03"
MIN_TURNOVER = 100_000_000.0
TOP_N = 30
MIN_NAMES = 30

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.data.calendar import TradingCalendar  # noqa: E402


def monthly_reb(dates):
    out, seen = [], set()
    for d in sorted(dates):
        if d[:7] not in seen:
            seen.add(d[:7])
            out.append(d)
    return out


def main():
    print("Loading A4 ...", flush=True)
    df = pd.read_parquet(A4_PATH, columns=["ticker", "date", "close", "total_amount", "total_volume"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    df["date"] = df["date"].astype(str)
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(df)} rows, {df['ticker'].nunique()} tickers", flush=True)

    g = df.groupby("ticker", sort=False)
    df["logret"] = np.log(df["close"] / df["close"].shift(1))
    df["rv60_pct"] = g["logret"].transform(lambda s: s.rolling(60, min_periods=20).std()) * 100
    df["dv20"] = g["total_amount"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    df["liquid"] = df["dv20"] >= MIN_TURNOVER

    all_dates = sorted(df["date"].unique())
    months = monthly_reb(all_dates)
    base = df[df["date"].isin(months)].copy()

    close_wide = df.pivot_table(index="date", columns="ticker", values="close")
    next_date = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}
    exit_map = {months[i]: months[i + 1] for i in range(len(months) - 1)}
    base["entry_t"] = base["date"].map(next_date)
    base["exit_t"] = base["date"].map(exit_map)
    fwd = pd.Series(np.nan, index=base.index, dtype=float)
    for i, sd in enumerate(months[:-1]):
        rows = base.index[base["date"] == sd]
        if len(rows) == 0:
            continue
        exit_d = months[i + 1]
        entry_d = next_date[sd]
        try:
            ec = close_wide.loc[entry_d]
            xc = close_wide.loc[exit_d]
        except KeyError:
            continue
        tks = base.loc[rows, "ticker"]
        vals = (xc.reindex(ec.index) / ec - 1.0)
        fwd.loc[rows] = tks.map(vals).to_numpy(dtype=float)
    base["fwd1m"] = fwd
    # build_factor_selection.py 와 동일: 마지막 리밸런싱월은 fwd1m 이 없어도 면제
    base = base[(base["fwd1m"] > -1) | (base["date"] == months[-1])].copy()

    base = base[base["liquid"]].copy()
    print(f"  after liquid gate: {len(base)} rows", flush=True)

    sub = base[["ticker", "date", "rv60_pct", "fwd1m"]].dropna(subset=["rv60_pct"])
    sub = sub[sub["fwd1m"].notna() | (sub["date"] == months[-1])]

    calendar = TradingCalendar(repo_root=REPO_ROOT)
    picks = {}
    monthly_counts = {}
    for t, gsub in sub.groupby("date"):
        if len(gsub) < MIN_NAMES:
            continue
        g2 = gsub.sort_values(["rv60_pct", "ticker"], ascending=[True, True])
        selected = g2.head(TOP_N)["ticker"].tolist()
        picks[t] = selected
        monthly_counts[t] = len(selected)

    hold_sessions_by_date = {}
    for k, t in enumerate(months[:-1]):
        if t not in monthly_counts:
            continue
        entry_date = calendar.next_session(t)
        next_rebal = months[k + 1]
        exit_target = calendar.next_session(next_rebal)
        if entry_date is None or exit_target is None:
            continue
        hold_sessions_by_date[t] = len(calendar.sessions_between(entry_date, exit_target))
    if months:
        hold_sessions_by_date.setdefault(months[-1], 21)

    selection_out = {}
    for t, tickers in picks.items():
        for tk in tickers:
            selection_out.setdefault(tk, []).append(
                {"date": t, "holdSessions": hold_sessions_by_date.get(t, 21)})
    for tk in selection_out:
        selection_out[tk].sort(key=lambda e: e["date"])

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "selection.json"), "w", encoding="utf-8") as f:
        json.dump({
            "generatedFrom": "build_factor_rv60_top30_selection.py (research-only)",
            "sourcePanel": "A4 (PIT) - build_factor_selection.py 와 동일 파이프라인",
            "period": f"{START} ~ {END}",
            "minTurnover": MIN_TURNOVER,
            "selectionRule": f"rv60_pct 하위 {TOP_N}종목 (유동성 게이트 후)",
            "rebalanceMonths": len(monthly_counts),
            "avgSelectedPerMonth": round(sum(monthly_counts.values()) / len(monthly_counts), 1) if monthly_counts else None,
            "maxSelectedPerMonth": max(monthly_counts.values()) if monthly_counts else None,
            "tickersEverSelected": len(selection_out),
            "selection": selection_out,
        }, f, ensure_ascii=False, indent=2)

    print(f"  saved: {os.path.join(OUT_DIR, 'selection.json')} "
          f"({len(selection_out)} tickers, {len(monthly_counts)} months)")
    if monthly_counts:
        print(f"  avg/month: {sum(monthly_counts.values()) / len(monthly_counts):.1f}, "
              f"max/month: {max(monthly_counts.values())}")

    policy = {
        "strategyId": "factor_rv60_v1_top30",
        "version": "1.0",
        "note": "Low-vol 단독 long-only 30종목 판 (독립 실험 05_lowvol_factor_oos). "
                "decile 판(factor_rv60_v1)과 파이프라인 동일, 선택 규칙만 상위 30 으로 변경.",
        "direction": "LONG_ONLY",
        "factor": {
            "name": "rv60_pct",
            "direction": "low",
            "rebalanceFrequency": "monthly",
            "selectionRule": "rv60_pct 하위 30종목 (dv20>=1e8 게이트 후)",
            "sourcePanel": "A4 (PIT) - std(logret,60)*100",
            "universe": "A1A_ONLY",
            "liquidityGate": "dv20 >= 1e8 KRW (20d mean trading value)",
        },
        "entry": {
            "timing": "next_tradable_session_open",
            "entryDateField": "next_session(t)",
            "entryPriceField": "Open[entry_date]"
        },
        "risk": {
            "note": "No price-based stop/target - pure time exit",
            "stopDistanceFormula": "entry_price * 100",
            "rewardRisk": 1.0,
            "maxHoldingSessions": 21,
            "timeExitRule": "close of the Nth tradable session counting entry_date as session 1"
        },
        "sameBarRule": "STOP_FIRST",
        "gapRule": "fill at session Open if Open already through stop_price",
        "entryDaySameBarCheck": True,
        "cost": {"entryCostBps": 15, "exitCostBps": 15, "roundTripBps": 30, "slippageBps": 0},
        "portfolio": {
            "initialCapital": 100_000_000,
            "currency": "KRW",
            "maxPositions": 30,
            "equalWeight": True,
            "fractionalShares": False,
            "sameDayCashReuse": False,
            "tieBreak": "ticker_ascending"
        },
        "universe": {"mode": "A1A_ONLY", "runClassAllowed": ["SMOKE"]},
        "scheduling": {"continuousHoldOnRenewal": True},
        "warmup": {"note": "Factor values from monthly panel - no technical warmup"}
    }
    with open(os.path.join(OUT_DIR, "policy.json"), "w", encoding="utf-8") as f:
        json.dump(policy, f, ensure_ascii=False, indent=2)

    rule = '''"""Low-vol top-30 전략. 선택은 selection.json 에 구워져 있다.

build_factor_rv60_top30_selection.py 가 생성한다 - 직접 고치지 말 것.
factor_rv60_v1/rule.py 와 동일한 구조(오프라인 선택 + 정확한 holdSessions 전달).
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
    with open(os.path.join(OUT_DIR, "rule.py"), "w", encoding="utf-8") as f:
        f.write(rule)
    print(f"  created: {OUT_DIR}/{{selection.json, policy.json, rule.py}}")


if __name__ == "__main__":
    main()