# -*- coding: utf-8 -*-
"""Stage 4-2 판정 보조 분석: 분위수 패턴의 기간별 일관성 + 통계적 유의성."""
import sys
sys.path.insert(0, r"research\strategy-lab\futures")
import numpy as np
import pandas as pd
from scipy import stats as st

from stage4_2_basis import load, front_series, same_contract_ret

df = load()
fr = front_series(df)
basis = (fr["TDD_CLSPRC"] - fr["SPOT_PRC"]).to_numpy()
n = len(fr)
HORIZONS = [1, 5, 20]
PERIODS = [("2010-2017", 0, 2080), ("2018-2024", 2080, 0), ("ALL", 0, n)]

# 2025~ 시작 인덱스
idx_2025 = int((fr.index >= "2025-01-01").argmax()) if (fr.index >= "2025-01-01").any() else n
PERIODS = [("2010-2017", 0, int((fr.index >= "2018-01-01").argmax())),
           ("2018-2024", int((fr.index >= "2018-01-01").argmax()), idx_2025),
           ("2025-", idx_2025, n),
           ("ALL", 0, n)]

fwd = {h: same_contract_ret(fr, h).to_numpy() for h in HORIZONS}

# expanding 과거분위수 (stage4_2와 동일 로직)
q = np.full(n, np.nan)
hist = []
for i in range(n):
    if i == 0:
        hist.append(basis[i]); continue
    hist.append(basis[i - 1])
    if len(hist) < 252:
        continue
    qs = np.quantile(hist, [0.2, 0.4, 0.6, 0.8])
    q[i] = int(np.digitize(basis[i], qs, right=True)) + 1

print("== 기간별 분위수 평균 수익률 (expanding 과거분위수) ==")
for pn, a, b in PERIODS:
    print(f"\n[{pn}]")
    for h in HORIZONS:
        x = pd.DataFrame({"q": q[a:b], "fwd": fwd[h][a:b]}).dropna()
        x["q"] = x["q"].astype(int)
        means = x.groupby("q")["fwd"].mean()
        line = "  ".join([f"Q{k}={means.get(k, float('nan')):.5f}" for k in [1, 2, 3, 4, 5]])
        print(f"  h={h:2d}  {line}  (n={len(x)})")

# Spearman 상관 (basis vs forward ret) 과거정보 기준 basis 순위
print("\n== Spearman 상관 (과거-분위수 기반 순위 vs 이후수익률) ==")
for h in HORIZONS:
    x = pd.DataFrame({"q": q, "fwd": fwd[h]}).dropna()
    rho, p = st.spearmanr(x["q"], x["fwd"])
    print(f"h={h:2d}: rho={rho:.4f} p={p:.4g}")

# 원basis 직접 spearman (봐: 정보계수도)
print("\n== Spearman 상관 (원basis vs 이후수익률) ==")
bs = pd.Series(basis)
for h in HORIZONS:
    x = pd.DataFrame({"b": bs, "fwd": fwd[h]}).dropna()
    rho, p = st.spearmanr(x["b"], x["fwd"])
    print(f"h={h:2d}: rho={rho:.4f} p={p:.4g}")

# Q1 vs Q5 차이 t-test
print("\n== Q1 vs Q5 평균 차이 t-test (expanding 분위수) ==")
for h in HORIZONS:
    x = pd.DataFrame({"q": q, "fwd": fwd[h]}).dropna()
    x["q"] = x["q"].astype(int)
    q1 = x.loc[x.q == 1, "fwd"]
    q5 = x.loc[x.q == 5, "fwd"]
    t, p = st.ttest_ind(q1, q5, equal_var=False)
    print(f"h={h:2d}: diff(Q1-Q5)={q1.mean()-q5.mean():.5f} t={t:.3f} p={p:.4g}  n1={len(q1)} n5={len(q5)}")