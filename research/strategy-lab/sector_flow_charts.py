#!/usr/bin/env python3
"""sector_flow_calendar_excel 결과의 PNG 차트 3장 — 수급 생애주기 · 섹터x연도 성과 · 거래대금 비중 추이.
    python research/strategy-lab/sector_flow_charts.py   (findings/sector-flow-signal-results-2026-09.json 필요)
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
import sector_flow_calendar_excel as m  # noqa: E402
from sector_leadership_macro_excel import to_period  # noqa: E402

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
OUT = LAB / "reports" / "2026-09-sector-flows"
OUT.mkdir(parents=True, exist_ok=True)

res = json.loads((LAB / "findings" / "sector-flow-signal-results-2026-09.json").read_text(encoding="utf-8"))
L = res["lifecycle"]
prof = sorted(L["profile"].items(), key=lambda kv: int(kv[0]))
ks = [int(k) for k, _ in prof]

fig, ax = plt.subplots(1, 3, figsize=(17, 4.6))
ax[0].bar(ks, [v["F"] * 100 for _, v in prof], color=["#999" if k < 0 else "#1f77b4" for k in ks])
ax[0].axhline(0, color="k", lw=.6)
ax[0].set_title("① 외국인+기관 순매수 / 거래대금 (%)\n진입월(k=0)에 몰렸다가 1~2개월 만에 평균으로")
ax[0].set_xlabel("진입 신호월 기준 개월(k)")
ax[1].plot(ks, [v["still_top3"] * 100 for _, v in prof], "o-", color="#d62728", label="계속 상위3 비율(%)")
ax[1].axhline(L["chance_top3"] * 100, ls="--", color="k", lw=.8, label=f"우연 {L['chance_top3']:.0%}")
ax[1].set_title("② 매수 몰림이 이어지는 비율\n1개월 뒤 35% → 3개월 뒤 우연 수준")
ax[1].set_xlabel("k")
ax[1].legend()
cum = [v["cum_excess"] * 100 for _, v in prof]
ax[2].plot(ks, cum, "o-", color="#2ca02c")
ax[2].axvline(0, color="k", lw=.6, ls=":")
ax[2].set_title("③ 진입 전후 누적 초과수익 (%)\n(k<0 직전 |k|개월, k≥0 진입월부터 k+1개월)\n첫 달 이후 더 벌어지지 않음")
ax[2].set_xlabel("k")
plt.suptitle(f"돈의 생애주기 — 외국인+기관 순매수 순위가 새로 상위 3에 든 {L['n_entries']}건 (한국 20그룹, 2016~2026)")
plt.tight_layout()
plt.savefig(OUT / "chart1_flow_lifecycle.png", dpi=130)
plt.close()

# 섹터 x 연도 연수익 히트맵
agg = m.add_dtv3(m.group_table())
R = agg.pivot(index="date", columns="group", values="fwd").sort_index()
R = R.dropna(axis=1, thresh=int(len(R) * 0.9)).dropna(how="any")
R = to_period(R)
yrs = sorted(set(R.index.year))
yt = pd.DataFrame({y: (1 + R[[p.year == y for p in R.index]]).prod() - 1 for y in yrs})
yt = yt.loc[yt.mean(axis=1).sort_values(ascending=False).index]
fig, ax = plt.subplots(figsize=(12, 8))
im = ax.imshow(yt.values, cmap="RdYlGn", vmin=-0.5, vmax=0.5, aspect="auto")
ax.set_xticks(range(len(yrs)))
ax.set_xticklabels([f"{y}" + ("*" if y in (2016, 2026) else "") for y in yrs])
ax.set_yticks(range(len(yt)))
ax.set_yticklabels(yt.index)
for i in range(yt.shape[0]):
    for j in range(yt.shape[1]):
        ax.text(j, i, f"{yt.values[i, j]:+.0%}", ha="center", va="center", fontsize=8)
ax.set_title("한국 섹터별 연수익 (종목 평균, * = 일부 월만: 2016-02~, 2026-07까지)")
plt.colorbar(im, ax=ax, fraction=.03)
plt.tight_layout()
plt.savefig(OUT / "chart2_sector_year_heatmap.png", dpi=130)
plt.close()

# 거래대금 비중 추이 (상위 8 + 기타)
sh = agg.pivot(index="date", columns="group", values="share").sort_index()
sh.index = [pd.Period(d, "M") - 1 for d in sh.index]
top = sh.tail(24).mean().sort_values(ascending=False).index[:8]
cd = sh[top].copy()
cd["기타"] = 1 - cd.sum(axis=1)
fig, ax = plt.subplots(figsize=(13, 5.5))
x = np.arange(len(cd))
ax.stackplot(x, cd.T.values * 100, labels=cd.columns)
ticks = [i for i, p in enumerate(cd.index) if p.month == 1]
ax.set_xticks(ticks)
ax.set_xticklabels([str(cd.index[i].year) for i in ticks])
ax.set_ylabel("거래대금 비중 (%)")
ax.set_title("섹터별 20일 거래대금 비중 추이 (최근 24개월 평균 상위 8 + 기타, 2016-01~2026-06)")
ax.legend(loc="upper left", ncol=3, fontsize=8)
plt.tight_layout()
plt.savefig(OUT / "chart3_trading_value_share.png", dpi=130)
print("charts ok", [p.name for p in OUT.glob("*.png")])
