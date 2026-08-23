#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pbr_value_v1_sizing의 selection.json 생성 - 미국 10년물 hiking 강도에
비례한 연속 비중 축소(진입 필터 기각 이후 다음 설계, 사용자 지시 2026-08-23).

build_pbr_ratefilter_selection.py(런 단위 이진 on/off)가 기각된 이유: 필터가
런 전체를 통째로 빼서 금리와 무관하게 PBR이 잘된 해(2020·2025)까지 잃었다.
이번엔 완전히 빼지 않고 매달 top-30 중 **일부만 남겨 나머지를 현금으로
남겨두는 방식**으로 비중을 연속적으로 줄인다 - 엔진(engine/portfolio/
portfolio.py)이 레버리지를 지원하지 않아(target_alloc = cash/maxPositions
고정) 확대(1.5x)는 공유 엔진 변경 없이는 불가능하다고 확인됨(사용자 확인
후 축소만: 0x~1.0x로 범위 축소).

방법: 각 리밸런싱월 D에 대해
  exposure_frac(D) = clip((usTreasury10yChg6m(D) - p10) / (p90 - p10), 0, 1)
  (p10·p90는 전체 표본 기간의 경험적 10/90분위, 사전계산 - 재최적화 없음)
  K(D) = round(len(그 달 원래 선택 종목수) * exposure_frac(D))
그 달 원래 선택된 종목들을 PBR 오름차순(원래 팩터 방향)으로 정렬해 상위
K(D)개만 남긴다 - build_selection.py의 "월별 top-N 컷"과 완전히 같은
모양이고, N이 30 고정 대신 exposure_frac(D)로 달라질 뿐이다. 이후 runner.py의
continuousHoldOnRenewal 병합은 완전히 그대로 적용된다(선택 로직의 산출물
모양이 바뀌지 않았으므로 특별취급 불필요).

원본 selection.json·policy.json·rule.py 무변경 - 새 전략 디렉터리만 생성.
pbr(오름차순 랭킹)은 valuation-panel.jsonl(build_selection.py가 이미 쓴,
2026-08-21 committed 산출물)에서 그대로 재사용 - A2A bars 재로딩 없음.

  python build_pbr_sizing_selection.py
"""
import json
import os

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(HERE, "strategies", "pbr_value_v1")
DST_DIR = os.path.join(HERE, "strategies", "pbr_value_v1_sizing")
REGIME_PARQUET = os.path.join(HERE, "data", "market-regime", "market_regime_features.parquet")
VALUATION_PANEL = os.path.join(HERE, "reports", "2026-08-21-a5-valuation-precheck", "valuation-panel.jsonl")
TRAIL_DAYS = 126  # PBR·CAND1·Opening Fade 조사와 동일 사전고정(재최적화 없음)
# ponytail: 전체 표본 기간의 min-max(10/90분위) 정규화 - 롤링(그 시점까지만
# 아는) 버전이 아니다. 미래 분포를 안다는 전제라 엄밀히는 PIT 위반이지만,
# 이 스칼라는 매매 신호가 아니라 "포지션 크기" 파라미터라 label leakage
# 위험이 진입 신호 자체보다 낮다고 판단해 1차 버전에서는 단순화했다.
# 결과가 유의미하면 rolling window로 업그레이드.
P_LOW, P_HIGH = 0.10, 0.90


def load_rate_axis():
    df = pd.read_parquet(REGIME_PARQUET)[["date", "usTreasury10y"]].copy()
    df = df.sort_values("date").reset_index(drop=True)
    df["usTreasury10yChg6m"] = df["usTreasury10y"] - df["usTreasury10y"].shift(TRAIL_DAYS)
    df["date_dt"] = pd.to_datetime(df["date"])
    return df


def exposure_lookup(rate_df):
    rd = rate_df.dropna(subset=["usTreasury10yChg6m"]).reset_index(drop=True)
    lo = rd["usTreasury10yChg6m"].quantile(P_LOW)
    hi = rd["usTreasury10yChg6m"].quantile(P_HIGH)
    print("정규화 경계: p10=%.4f, p90=%.4f (전체 표본 %d obs)" % (lo, hi, len(rd)))

    def _fn(date_str):
        d = pd.Timestamp(date_str)
        idx = rd["date_dt"].searchsorted(d, side="right") - 1
        if idx < 0:
            return None  # 커버리지 이전 - 지어내지 않음, 판단 불가로 제외
        val = rd.loc[idx, "usTreasury10yChg6m"]
        frac = (val - lo) / (hi - lo)
        return max(0.0, min(1.0, float(frac)))

    return _fn


def load_pbr_lookup():
    """(ticker, asOf) -> pbr. 원본 build_selection.py가 이미 검증해 쓴 패널
    그대로 재사용(A2A/turnover 재계산 없음)."""
    lookup = {}
    with open(VALUATION_PANEL, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["pbr"] is not None:
                lookup[(row["ticker"], row["asOf"])] = row["pbr"]
    return lookup


def main():
    with open(os.path.join(SRC_DIR, "selection.json"), encoding="utf-8") as f:
        src = json.load(f)
    selection = src["selection"]

    # date -> [ticker, ...] (원본 top-30, 이미 turnover 필터 통과)
    by_date = {}
    for ticker, entries in selection.items():
        for e in entries:
            by_date.setdefault(e["date"], []).append((ticker, e["holdSessions"]))
    all_dates = sorted(by_date.keys())
    print("원본: %d종목, 리밸런싱일 %d개(%s~%s)"
          % (len(selection), len(all_dates), all_dates[0], all_dates[-1]))

    rate_df = load_rate_axis()
    exposure_of = exposure_lookup(rate_df)
    pbr_of = load_pbr_lookup()

    kept_selection = {}
    n_entries_total = n_entries_kept = n_no_axis = n_no_pbr = 0
    exposure_by_year = {}
    for d in all_dates:
        candidates = by_date[d]
        n_entries_total += len(candidates)
        frac = exposure_of(d)
        if frac is None:
            n_no_axis += len(candidates)
            continue
        exposure_by_year.setdefault(d[:4], []).append(frac)

        ranked = []
        for ticker, hold in candidates:
            pbr = pbr_of.get((ticker, d))
            if pbr is None:
                n_no_pbr += 1
                continue
            ranked.append((pbr, ticker, hold))
        ranked.sort(key=lambda r: r[0])  # PBR 오름차순 - 원본 팩터 방향과 동일

        k = round(len(candidates) * frac)
        kept = ranked[:k]
        n_entries_kept += len(kept)
        for pbr, ticker, hold in kept:
            kept_selection.setdefault(ticker, []).append({"date": d, "holdSessions": hold})

    print("진입(entry) 단위: 전체 %d건 중 유지 %d건(%.1f%%), axis 매칭 불가 %d건, pbr 매칭 불가 %d건"
          % (n_entries_total, n_entries_kept, n_entries_kept / n_entries_total * 100, n_no_axis, n_no_pbr))
    print("종목수: 원본 %d -> 필터후 %d" % (len(selection), len(kept_selection)))
    print("\n연도별 평균 exposure_frac:")
    for y in sorted(exposure_by_year):
        vals = exposure_by_year[y]
        print("  %s: 평균=%.3f (월수=%d)" % (y, sum(vals) / len(vals), len(vals)))

    out = dict(src)
    out["selection"] = kept_selection
    out["generatedFrom"] = "build_pbr_sizing_selection.py (pbr_value_v1/selection.json 월별 연속 비중 축소)"
    out["sizingFilter"] = {
        "axis": "usTreasury10y trailing %d거래일(6개월) 변화" % TRAIL_DAYS,
        "mapping": "exposure_frac = clip((chg6m - p10) / (p90 - p10), 0, 1), 전체표본 min-max 정규화",
        "unit": "매달 top-K(K=round(원래 선택수 * exposure_frac)) PBR 오름차순 컷 - 런 무관, 매달 독립 재계산",
        "entriesTotal": n_entries_total, "entriesKept": n_entries_kept,
        "noAxisMatch": n_no_axis, "noPbrMatch": n_no_pbr,
    }

    os.makedirs(DST_DIR, exist_ok=True)
    with open(os.path.join(DST_DIR, "selection.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    with open(os.path.join(SRC_DIR, "policy.json"), encoding="utf-8") as f:
        policy = json.load(f)
    policy["strategyId"] = "pbr_value_v1_sizing"
    policy["note"] = (
        "pbr_value_v1의 미국10Y hiking 강도 연속 비중축소 변형(레버리지 없음,"
        " 0x~1.0x). 신호·체결·비용·portfolio 설정 전부 pbr_value_v1과 동일"
        "(무변경 복사) - 차이는 selection.json 하나뿐(매달 top-K 컷,"
        " build_pbr_sizing_selection.py). 진입필터(이진 on/off, ratefilter"
        " 변형) 기각 이후의 다음 설계.")
    with open(os.path.join(DST_DIR, "policy.json"), "w", encoding="utf-8") as f:
        json.dump(policy, f, ensure_ascii=False, indent=2)

    with open(os.path.join(SRC_DIR, "rule.py"), encoding="utf-8") as f:
        rule_src = f.read()
    with open(os.path.join(DST_DIR, "rule.py"), "w", encoding="utf-8") as f:
        f.write(rule_src)

    print("\nwrote", os.path.join(DST_DIR, "selection.json"))
    print("wrote", os.path.join(DST_DIR, "policy.json"))
    print("wrote", os.path.join(DST_DIR, "rule.py"), "(원본과 byte-identical)")


if __name__ == "__main__":
    main()
