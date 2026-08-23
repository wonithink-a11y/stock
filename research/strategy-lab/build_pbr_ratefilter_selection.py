#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pbr_value_v1_ratefilter의 selection.json 생성 — 미국 10년물 hiking regime
조건부 진입 필터(pbr_macro_rate_regime_check.py 발견의 실전 backtest).

가설: PBR 초과수익은 미국 10년물이 상승하는 6개월 창(trailing 126거래일)에
집중된다(2022년을 빼도 방향 유지, findings/pbr-macro-rate-regime-check-
2026-08.md). 이 필터를 실제로 걸면 성과가 개선되는지 확인한다.

방법: `strategies/pbr_value_v1/selection.json`(원본 무변경)을 읽어, **연속보유
런(run) 단위**로 필터링한다 — continuousHoldOnRenewal(policy.json)이 같은
종목의 연속 리밸런싱을 청산-재진입 없이 병합하므로, 런 중간 한 달만 빼면
그 병합이 깨지고 존재하지 않던 청산/재진입이 생긴다. 그래서 "런의 시작월
시점 hiking 여부"로 런 전체를 살리거나 버린다 — 진입 판단만 필터링하고
이미 진행 중인 보유의 청산 로직은 건드리지 않는다.

usTreasury10yChg6m(126거래일 trailing)은 PBR·CAND1·Opening Fade 조사와
동일 사전고정값 — 재최적화 없음. threshold도 그대로(>0 = hiking).

원본 selection.json·policy.json·rule.py 무변경 — 새 전략 디렉터리만 생성.

  python build_pbr_ratefilter_selection.py
"""
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(HERE, "strategies", "pbr_value_v1")
DST_DIR = os.path.join(HERE, "strategies", "pbr_value_v1_ratefilter")
REGIME_PARQUET = os.path.join(HERE, "data", "market-regime", "market_regime_features.parquet")
TRAIL_DAYS = 126  # PBR·CAND1·Opening Fade 조사와 동일 사전고정(재최적화 없음)


def load_rate_axis():
    df = pd.read_parquet(REGIME_PARQUET)[["date", "usTreasury10y"]].copy()
    df = df.sort_values("date").reset_index(drop=True)
    df["usTreasury10yChg6m"] = df["usTreasury10y"] - df["usTreasury10y"].shift(TRAIL_DAYS)
    df["date_dt"] = pd.to_datetime(df["date"])
    return df


def hiking_lookup(rate_df):
    """rebalance date(신호일) -> hiking(bool) 함수. asof-backward — 그
    parquet의 usTreasury10y는 이미 '관측일 < D' 규칙으로 시프트돼 있어
    직접 조회가 PIT 안전하다(pbr_macro_rate_regime_check.py와 동일 방식)."""
    rd = rate_df.dropna(subset=["usTreasury10yChg6m"]).reset_index(drop=True)

    def _fn(date_str):
        d = pd.Timestamp(date_str)
        idx = rd["date_dt"].searchsorted(d, side="right") - 1
        if idx < 0:
            return None  # 커버리지 이전 - 지어내지 않음, 이 런은 판단 불가로 제외
        return bool(rd.loc[idx, "usTreasury10yChg6m"] > 0)

    return _fn


def build_runs(entries, all_dates_index):
    """entries(그 종목의 [{date, holdSessions}, ...], 날짜순 정렬됨 가정)를
    전역 리밸런싱일 인덱스 기준 연속 런으로 묶는다."""
    runs, cur = [], []
    prev_idx = None
    for e in entries:
        idx = all_dates_index[e["date"]]
        if prev_idx is not None and idx == prev_idx + 1:
            cur.append(e)
        else:
            if cur:
                runs.append(cur)
            cur = [e]
        prev_idx = idx
    if cur:
        runs.append(cur)
    return runs


def main():
    with open(os.path.join(SRC_DIR, "selection.json"), encoding="utf-8") as f:
        src = json.load(f)
    selection = src["selection"]

    all_dates = sorted({e["date"] for entries in selection.values() for e in entries})
    all_dates_index = {d: i for i, d in enumerate(all_dates)}
    print("원본: %d종목, 리밸런싱일 %d개(%s~%s)"
          % (len(selection), len(all_dates), all_dates[0], all_dates[-1]))

    rate_df = load_rate_axis()
    is_hiking = hiking_lookup(rate_df)

    kept_selection = {}
    n_runs_total = n_runs_kept = n_entries_total = n_entries_kept = n_no_axis = 0
    for ticker, entries in selection.items():
        entries_sorted = sorted(entries, key=lambda e: e["date"])
        runs = build_runs(entries_sorted, all_dates_index)
        kept_entries = []
        for run in runs:
            n_runs_total += 1
            n_entries_total += len(run)
            start_date = run[0]["date"]
            hiking = is_hiking(start_date)
            if hiking is None:
                n_no_axis += 1
                continue
            if hiking:
                n_runs_kept += 1
                n_entries_kept += len(run)
                kept_entries.extend(run)
        if kept_entries:
            kept_selection[ticker] = kept_entries

    print("런 단위: 전체 %d개 중 hiking으로 유지 %d개(%.1f%%), axis 매칭 불가 %d개"
          % (n_runs_total, n_runs_kept, n_runs_kept / n_runs_total * 100, n_no_axis))
    print("진입(entry) 단위: 전체 %d건 중 유지 %d건(%.1f%%)"
          % (n_entries_total, n_entries_kept, n_entries_kept / n_entries_total * 100))
    print("종목수: 원본 %d -> 필터후 %d" % (len(selection), len(kept_selection)))

    out = dict(src)
    out["selection"] = kept_selection
    out["generatedFrom"] = "build_pbr_ratefilter_selection.py (pbr_value_v1/selection.json 런단위 필터)"
    out["rateFilter"] = {
        "axis": "usTreasury10y trailing %d거래일(6개월) 변화 > 0 (hiking)" % TRAIL_DAYS,
        "unit": "연속보유 런(run) 시작월 기준 - 런 중간 필터링 없음",
        "runsTotal": n_runs_total, "runsKept": n_runs_kept,
        "entriesTotal": n_entries_total, "entriesKept": n_entries_kept,
        "noAxisMatch": n_no_axis,
    }

    os.makedirs(DST_DIR, exist_ok=True)
    with open(os.path.join(DST_DIR, "selection.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # policy.json: 원본 그대로 복사하되 strategyId·note만 갱신(계약 무변경)
    with open(os.path.join(SRC_DIR, "policy.json"), encoding="utf-8") as f:
        policy = json.load(f)
    policy["strategyId"] = "pbr_value_v1_ratefilter"
    policy["note"] = (
        "pbr_value_v1의 런단위 미국10Y hiking 필터 변형. 신호·체결·비용·"
        "portfolio·scheduling 블록 전부 pbr_value_v1과 동일(무변경 복사) — "
        "차이는 selection.json 하나뿐(hiking 런만 남김, build_pbr_ratefilter_"
        "selection.py). pbr_macro_rate_regime_check.py 발견의 실전 backtest.")
    with open(os.path.join(DST_DIR, "policy.json"), "w", encoding="utf-8") as f:
        json.dump(policy, f, ensure_ascii=False, indent=2)

    # rule.py: _THIS_DIR 상대경로라 무변경 그대로 복사만 하면 된다
    with open(os.path.join(SRC_DIR, "rule.py"), encoding="utf-8") as f:
        rule_src = f.read()
    with open(os.path.join(DST_DIR, "rule.py"), "w", encoding="utf-8") as f:
        f.write(rule_src)

    print("\nwrote", os.path.join(DST_DIR, "selection.json"))
    print("wrote", os.path.join(DST_DIR, "policy.json"))
    print("wrote", os.path.join(DST_DIR, "rule.py"), "(원본과 byte-identical)")


if __name__ == "__main__":
    main()
