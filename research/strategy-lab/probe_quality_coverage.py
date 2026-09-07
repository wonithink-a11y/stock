#!/usr/bin/env python
"""Coverage probe for quality factors in kr-monthly-v1 panel (data-only, no performance).
Decide composite membership on coverage grounds, not on IC — the composite must be
pre-specified before seeing any performance number."""
import pandas as pd

LAB = r"C:\Users\User\projects\stock\research\strategy-lab"
PANEL_PATH = f"{LAB}\\data\\factor-panel\\kr-monthly-v1.parquet"

QUALITY_FACTORS = ["roe", "op_margin", "net_margin", "retention", "debt_ratio",
                   "current_ratio", "roe_consistency", "op_margin_trend"]

df = pd.read_parquet(PANEL_PATH, columns=["date", "period", "liquid"] + QUALITY_FACTORS)
df = df[df["liquid"]].copy()

print("== 전체 (liquid, % non-null) ==")
for f in QUALITY_FACTORS:
    print(f"  {f:>18s}: {df[f].notna().mean()*100:6.1f}%")

print("\n== 구간별 non-null 비율 ==")
print(f"{'factor':>18s} {'TRAIN':>8s} {'VALID':>8s} {'TEST':>8s}")
for f in QUALITY_FACTORS:
    row = []
    for p in ["TRAIN", "VALID", "TEST"]:
        sub = df[df["period"] == p]
        row.append(f"{sub[f].notna().mean()*100:6.1f}")
    print(f"  {f:>18s} {' '.join(row)}")

print("\n== 교집합 커버리지 (전 팩터 non-null인 liquid 종목 비율) ==")
sub_liq = df
for p in ["TRAIN", "VALID", "TEST"]:
    sub = sub_liq[sub_liq["period"] == p]
    print(f"  {p}: all-8: {sub[QUALITY_FACTORS].notna().all(axis=1).mean()*100:6.1f}%  "
          f"all-but-retention(7): {sub[[f for f in QUALITY_FACTORS if f != 'retention']].notna().all(axis=1).mean()*100:6.1f}%")

print("\n== 월별 최소 종목수 (liquid, 전팩터 교집합이 30 이상인 달 비율) ==")
for label, cols in [("all-8", QUALITY_FACTORS),
                    ("all-but-retention", [f for f in QUALITY_FACTORS if f != "retention"])]:
    cnt = df[df["liquid"]].groupby("date")[cols].apply(lambda g: g.notna().all(axis=1).sum())
    print(f"  {label}: 월평균 {cnt.mean():.0f}, 30미만 달 비율 {(cnt < 30).mean()*100:.0f}%")