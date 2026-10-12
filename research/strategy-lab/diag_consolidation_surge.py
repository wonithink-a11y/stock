"""횡보 폭(60일 고가/저가)과 거래 급증 → 5일 안 +15% 도달·5일 수익 — 사후 기술(EXPLORATORY). 결과: findings/consolidation-surge-2026-10.md

    python research/strategy-lab/diag_consolidation_surge.py
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import combined_rank_model as crm, surge_prob_model as spm
P = pd.read_parquet(crm.CACHE / "panel.parquet", columns=["t", "tj", "ret5", "exc5", "trd5", "rvol", "r1"])
import json
meta = json.load(open(crm.CACHE / "meta.json")); years = np.array(meta["years"])
dates, tickers, C, O, Hh, L, V, common, isdel = crm.load_dense()
y, e2 = spm.forward_targets(O, Hh, C)
n60, rng, since = spm.extras(C, Hh, L)
t, tj = P.t.to_numpy(), P.tj.to_numpy()
P["y"] = y[t, tj]; P["rng60"] = rng[t, tj]; e = e2[t, tj]
P["e2"] = np.where(np.isnan(e), P.ret5, e)
X = P[P.trd5 & (years[t] >= 2016)].copy()
X["per"] = pd.cut(years[X.t.to_numpy()], [2015, 2023, 2024, 2026], labels=["16~23", "24", "25~"])
X["rq"] = pd.cut(X.rng60, [0, 0.2, 0.3, 0.5, 1.0, 100], labels=["20%↓(좁은 횡보)", "20~30", "30~50", "50~100", "100%↑"])
X["rv"] = pd.cut(X.rvol, [-1, 0.33, 0.67, 0.9, 2], labels=["거래 평소↓", "보통", "많음", "가장 많음(rvol 순위 상위 10%)"])
L_ = ["---", "track: kr", "factor: consolidation-surge", "date: 2026-10-13", "verdict: EXPLORATORY", "reason: >-",
      "  사후 기술(판정 없음). 60일 횡보 폭·당일 거래 급증(순위)별 5일 안 +15% 도달 확률과 t+1 시가 → t+5 종가 초과·익절(+15%) 원수익.", "---", "",
      "# 횡보 폭과 거래 급증 → 급등 (2016~2026)", "", "`diag_consolidation_surge.py`. 결합 순위 모델 패널(적격 유니버스, 폐지 포함). 투자 자문이 아니다.", "",
      f"기본: 5일 안 +15% {X.y.mean():.1%} · 5일 초과 {X.exc5.mean() * 1e4:+.1f}bp", "",
      "| 60일 횡보 폭 | 건수 | +15% 도달 | 5일 초과(bp) | 익절 원수익(bp) | 초과 16~23 / 24 / 25~ |", "|---|---:|---:|---:|---:|---|"]
for k, g in X.groupby("rq", observed=True):
    per = g.groupby("per", observed=True).exc5.mean() * 1e4
    L_.append(f"| {k} | {len(g):,} | {g.y.mean():.1%} | {g.exc5.mean() * 1e4:+.1f} | {g.e2.mean() * 1e4:+.1f} | {' / '.join(f'{v:+.0f}' for v in per)} |")
L_ += ["", "좁은 횡보(폭 30% 이하) 안에서 당일 거래 급증 순위별(=횡보 중 거래 터짐):", "", "| 거래 | 건수 | +15% 도달 | 5일 초과(bp) | 익절 원수익(bp) | 초과 16~23 / 24 / 25~ |", "|---|---:|---:|---:|---:|---|"]
N = X[X.rng60 <= 0.3]
for k, g in N.groupby("rv", observed=True):
    per = g.groupby("per", observed=True).exc5.mean() * 1e4
    L_.append(f"| {k} | {len(g):,} | {g.y.mean():.1%} | {g.exc5.mean() * 1e4:+.1f} | {g.e2.mean() * 1e4:+.1f} | {' / '.join(f'{v:+.0f}' for v in per)} |")
b = N[(N.rvol > 0.9) & (N.r1 > 0.85)]
L_ += ["", f"좁은 횡보 + 거래 상위 10% + 당일 수익 상위 15%(횡보 돌파형): {len(b):,}건 · +15% 도달 {b.y.mean():.1%} · 5일 초과 {b.exc5.mean() * 1e4:+.1f}bp · 익절 {b.e2.mean() * 1e4:+.1f}bp · "
       + " / ".join(f"{k} {v * 1e4:+.0f}" for k, v in b.groupby('per', observed=True).exc5.mean().items()), "",
       "비용: 시가 진입·종가 청산 23.5bp, 익절(장중 지정가) 33.5bp. rvol·r1 은 그날 적격 안 순위 백분위.", ""]
(HERE / "findings" / "consolidation-surge-2026-10.md").write_text("\n".join(L_), encoding="utf-8")
print("\n".join(L_))
