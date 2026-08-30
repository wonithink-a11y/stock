#!/usr/bin/env python
"""게이트 검증: 기존 결과(JSON) 기반 추가 분석"""

import json
import numpy as np

with open(r'C:\Users\User\projects\stock\research\strategy-lab\reports\2026-08-26-universe-gate\gate-results.json') as f:
    r = json.load(f)

print("="*80)
print("게이트 검증: 최종 종합 분석")
print("="*80)

# 1. 스프레드 비교표
print("\n1. 팩터 스프레드 (D1-D10, 월별 평균, NW t)")
print("-"*80)
for sig in ["LOWMOM60_mom60", "REV20_mom20"]:
    print(f"\n{sig}:")
    for arm in ["A_full", "B_liq1e8", "C_B_plus_noExtremeVol", "D_C_plus_price5000"]:
        for h in ["fwd_d20", "fwd_d60", "fwd_d120"]:
            s = r["arms"][arm][sig][f"spread_{h}"]
            print(f"  {arm:25s} {h}: {s['monthlySpreadMean']:+.4f} (NWT {s['monthlySpreadNWT']:+.2f})")

# 2. 바스켓 수익률 (Net@30bps)
print("\n2. 시그널 바스켓 수익률 (Net@30bps, d60)")
print("-"*80)
for sig in ["LOWMOM60_mom60", "REV20_mom20"]:
    print(f"\n{sig}:")
    for arm in ["A_full", "B_liq1e8", "C_B_plus_noExtremeVol", "D_C_plus_price5000"]:
        b = r["arms"][arm][sig]["baskets"]["fwd_d60"]
        gross = b["basketGrossMeanFwd"]
        net = b.get("basketNetAt30bpsRTperMonth", "N/A")
        wr = b["basketWinrate"]
        print(f"  {arm:25s} gross={gross:+.4f}, net={net}, wr={wr:.2%}")

# 3. 표본 보존율
print("\n3. 표본 보존율 (vs A_full)")
print("-"*40)
for arm, ret in r["retentionVsA"].items():
    print(f"  {arm:25s}: {ret:.1%}")

# 4. 바스켓 겹침률 (A -> D)
print("\n4. 바스켓 겹침률 (A -> D, d60)")
print("-"*40)
for sig, ov in r["basketOverlapAtoD"].items():
    print(f"  {sig}: {ov['meanShareOfABasketSurvivingInD']:.1%} (n={ov['nMonthsCompared']} months)")

# 5. IC 안정성
print("\n5. IC 안정성 (d60, 연도별)")
print("-"*80)
for sig in ["LOWMOM60_mom60", "REV20_mom20"]:
    print(f"\n{sig}:")
    for arm in ["A_full", "B_liq1e8", "C_B_plus_noExtremeVol", "D_C_plus_price5000"]:
        yic = r["arms"][arm][sig]["yearlyIC_vs_d60"]
        neg_years = r["arms"][arm][sig]["yearlySignSummary"]["negativeYears"]
        total = r["arms"][arm][sig]["yearlySignSummary"]["totalYears"]
        years_neg = [y for y, v in yic.items() if v.get("icMean", 0) < 0]
        print(f"  {arm:25s}: 음의 연도 {neg_years}/{total} -> {years_neg}")

# 6. 핵심 비교: 게이트별 알파 보존도
print("\n6. 알파 보존도 요약 (d60 스프레드 기준)")
print("-"*80)
base_low = r["arms"]["A_full"]["LOWMOM60_mom60"]["spread_fwd_d60"]["monthlySpreadMean"]
base_rev = r["arms"]["A_full"]["REV20_mom20"]["spread_fwd_d60"]["monthlySpreadMean"]
for arm in ["B_liq1e8", "C_B_plus_noExtremeVol", "D_C_plus_price5000"]:
    low = r["arms"][arm]["LOWMOM60_mom60"]["spread_fwd_d60"]["monthlySpreadMean"]
    rev = r["arms"][arm]["REV20_mom20"]["spread_fwd_d60"]["monthlySpreadMean"]
    low_ret = low / base_low * 100
    rev_ret = rev / base_rev * 100
    print(f"  {arm:25s}: LOWMOM60 {low_ret:.0f}% 보존, REV20 {rev_ret:.0f}% 보존")

# 7. Net@30bps 기준 실전 수익성
print("\n7. 실전 수익성 (Net@30bps, d20 바스켓)")
print("-"*60)
for sig in ["LOWMOM60_mom60", "REV20_mom20"]:
    print(f"\n{sig}:")
    for arm in ["A_full", "B_liq1e8", "C_B_plus_noExtremeVol", "D_C_plus_price5000"]:
        b = r["arms"][arm][sig]["baskets"]["fwd_d20"]
        gross = b["basketGrossMeanFwd"]
        net = b.get("basketNetAt30bpsRTperMonth", 0)
        print(f"  {arm:25s}: gross={gross:+.4f}, net={net:+.4f}")

print("\n" + "="*80)
print("분석 완료")
print("="*80)