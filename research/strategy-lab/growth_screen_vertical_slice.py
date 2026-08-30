#!/usr/bin/env python
"""성장주 스크리닝(자산/매출/영업이익 3년 증가율 TOP20 교집합 + 부채비율 필터)
전면 백테스트 전 소규모 수직 슬라이스 검증 (사용자 지시, 2026-08-28).

목적: 전체 10년 횡단면 백테스트에 들어가기 전에 PIT 선택·성장률 계산·교집합·
부채필터 로직이 손계산과 일치하는지 몇 개 as-of 시점으로 먼저 확인한다.
이 단계는 A1a(현재 상장) 유니버스만 쓴다 - 상장폐지 종목 포함 유니버스는
eligibility 로직이 따로 필요해(exitAtConfirmed 등) 다음 단계로 미룬다.

음수 처리 정책(사용자 확정, 2026-08-28): base(t-3) <= 0이면 growth rate는
"계산불가"로 순위 대상에서 제외한다(0등/최하위가 아니라 아예 없음) - 절대
규칙 1(결측에 기본점수 금지)과 동일 원칙.

PIT: A3 fundamentals(data/backfill/fundamentals/a3/)의 availableFrom을
lib/a5/pitSelector.js와 동일한 규칙(availableFrom<=asOf만 후보, 그 중
최신 fiscalYear)으로 사용.

production 변경 없음, 새 API 호출 없음.
"""
import gzip
import json
import os
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
A1A_PATH = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")


def load_a3():
    by_ticker = defaultdict(dict)  # ticker -> {fiscalYear: record}
    for fname in sorted(os.listdir(A3_DIR)):
        if not fname.endswith(".jsonl.gz"):
            continue
        with gzip.open(os.path.join(A3_DIR, fname), "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                liab, eq = d.get("liabilities"), d.get("equity")
                d["assets"] = (liab + eq) if (liab is not None and eq is not None) else None
                by_ticker[d["ticker"]][d["fiscalYear"]] = d
    return by_ticker


def load_universe():
    with open(A1A_PATH, encoding="utf-8") as f:
        return [json.loads(l) for l in f]


def latest_fy_asof(recs_by_fy, as_of):
    candidates = [r for r in recs_by_fy.values() if r["availableFrom"] <= as_of]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["fiscalYear"])


def growth_3y(recs_by_fy, latest, metric):
    prev = recs_by_fy.get(latest["fiscalYear"] - 3)
    if prev is None or prev["availableFrom"] > latest["availableFrom"]:
        return None
    base = prev.get(metric)
    cur = latest.get(metric)
    if base is None or cur is None or base <= 0:
        return None  # 음수 처리 정책: base<=0이면 계산불가
    return cur / base - 1.0


def debt_ratio(latest):
    eq = latest.get("equity")
    liab = latest.get("liabilities")
    if eq is None or liab is None or eq <= 0:
        return None  # 자본잠식 등 - 정의 불가, Strategy A 필터에서는 탈락 처리
    return liab / eq * 100.0


def compute_snapshot(a3, universe, as_of):
    rows = []
    for u in universe:
        if u["listedAt"] > as_of:
            continue
        recs = a3.get(u["ticker"])
        if not recs:
            continue
        latest = latest_fy_asof(recs, as_of)
        if latest is None:
            continue
        rows.append({
            "ticker": u["ticker"], "name": u["name"], "fiscalYear": latest["fiscalYear"],
            "availableFrom": latest["availableFrom"],
            "assetGrowth": growth_3y(recs, latest, "assets"),
            "revenueGrowth": growth_3y(recs, latest, "revenue"),
            "opProfitGrowth": growth_3y(recs, latest, "opProfit"),
            "debtRatio": debt_ratio(latest),
        })
    return rows


def top20(rows, key):
    ranked = sorted([r for r in rows if r[key] is not None], key=lambda r: r[key], reverse=True)
    return ranked[:20]


def run(as_of):
    a3 = _A3_CACHE
    universe = _UNIVERSE_CACHE
    rows = compute_snapshot(a3, universe, as_of)
    print(f"\n{'='*80}\nas_of = {as_of} | 유니버스(A1a 상장중, 상장일<=as_of, A3 매칭) = {len(rows)}개\n{'='*80}")

    t_asset = top20(rows, "assetGrowth")
    t_rev = top20(rows, "revenueGrowth")
    t_op = top20(rows, "opProfitGrowth")
    print(f"  자산성장 TOP20 계산가능: {sum(1 for r in rows if r['assetGrowth'] is not None)}개")
    print(f"  매출성장 TOP20 계산가능: {sum(1 for r in rows if r['revenueGrowth'] is not None)}개")
    print(f"  영업이익성장 TOP20 계산가능: {sum(1 for r in rows if r['opProfitGrowth'] is not None)}개 "
          f"(제외 {sum(1 for r in rows if r['opProfitGrowth'] is None)}개 - base<=0)")

    set_asset = {r["ticker"] for r in t_asset}
    set_rev = {r["ticker"] for r in t_rev}
    set_op = {r["ticker"] for r in t_op}
    intersection = set_asset & set_rev & set_op
    print(f"  교집합(A∩B∩C): {len(intersection)}개")

    by_ticker = {r["ticker"]: r for r in rows}
    for tk in sorted(intersection):
        r = by_ticker[tk]
        dr = "N/A" if r["debtRatio"] is None else f"{r['debtRatio']:.0f}%"
        print(f"    {tk} {r['name']:12s} FY{r['fiscalYear']}(공시 {r['availableFrom']}) "
              f"자산+{r['assetGrowth']:.1%} 매출+{r['revenueGrowth']:.1%} 영업이익+{r['opProfitGrowth']:.1%} "
              f"부채비율={dr}")

    final_a = [tk for tk in intersection if by_ticker[tk]["debtRatio"] is not None
               and by_ticker[tk]["debtRatio"] <= 120]
    dropped_by_debt = [tk for tk in intersection if tk not in final_a]
    print(f"  Strategy A (부채<=120%): {len(final_a)}개 최종선정, 부채필터로 탈락 {len(dropped_by_debt)}개 "
          f"{dropped_by_debt}")
    print(f"  Strategy B (부채필터 없음): {len(intersection)}개 최종선정 (교집합 그대로)")

    return rows, t_asset, t_rev, t_op, intersection


_A3_CACHE = load_a3()
_UNIVERSE_CACHE = load_universe()

if __name__ == "__main__":
    for as_of in ("2019-06-25", "2021-06-25", "2023-06-25"):
        run(as_of)

    print("\n" + "=" * 80)
    print("손계산 대조용 원본 레코드 (교집합에 든 종목 하나를 골라 직접 확인)")
    print("=" * 80)
    rows, *_ = run("2021-06-25")
    sample = next((r for r in rows if r["assetGrowth"] is not None
                    and r["revenueGrowth"] is not None and r["opProfitGrowth"] is not None), None)
    if sample:
        tk = sample["ticker"]
        print(f"\n종목 {tk} ({sample['name']}) FY{sample['fiscalYear']} 및 FY{sample['fiscalYear']-3} 원본:")
        print(json.dumps(_A3_CACHE[tk][sample["fiscalYear"]], ensure_ascii=False, indent=2))
        print(json.dumps(_A3_CACHE[tk][sample["fiscalYear"] - 3], ensure_ascii=False, indent=2))
