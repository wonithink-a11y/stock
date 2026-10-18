#!/usr/bin/env python3
"""RV20 규칙(동결) 2026 대형주 하락 진단 — 규칙 불변, 원인 기록용. findings/rv20-2026-crash-diagnosis-2026-10.md.
    python research/strategy-lab/futures/rv20_crash_diagnosis.py
"""
import numpy as np, pandas as pd
from stage5_1_volatility_event_study import load, front_series, process
from stage5_3_sizing_backtest import target_weight
fr = front_series(load()); d, _, _ = process(fr)
cts = fr[~fr["roll"]]
d["px"] = cts["TDD_CLSPRC"].astype(float).reindex(d.index)
rv = d["rv20"].dropna()
thr = rv.shift(1).rolling(252).quantile(0.8)          # 직전 252 유효 RV20 의 80% 분위(규칙 문턱을 RV20 값으로 환산)
d["thr80"] = thr.reindex(d.index)
d["w"] = d["pct_rv20_rol"].map(lambda p: target_weight(p, "defensive") if np.isfinite(p) else np.nan)
x = d.loc["2026-06-15":, ["px", "rv20", "thr80", "pct_rv20_rol", "pct_rv20_exp", "w"]]
# 0x↔1x 전환일
sw = x[x["w"].diff().fillna(0) != 0]
print("switches"); print(sw.round(3).to_string())
print("\nweekly"); print(x.resample("W-FRI").last().round(3).to_string())
print("\nall-history p80 rv20", round(rv.quantile(.8),3), "p95", round(rv.quantile(.95),3))

# --- 과거 −15% 이상 하락 국면
# 4) 과거 하락 국면(고점 대비 −15% 이상): 국면 동안 0x 비율과 B&H 대비 손실 회피
s = d["px"].dropna()
r = np.log(s).diff()  # 같은 계약 보장 안 됨 — 롤일 NaN 처리: process 의 rv 계산과 같은 원칙
roll = fr["roll"].reindex(s.index).fillna(False)
r[roll.values] = np.nan
w = d["w"].reindex(s.index).shift(1)   # t 신호 → t+1 적용
eps, peak, trough_i, inep = [], s.iloc[0], None, False
runmax = s.cummax(); ddser = s / runmax - 1
# 국면: ddser 가 −15% 를 처음 넘은 뒤, 고점 회복(dd=0)까지. 시작은 그 직전 고점일.
i = 0; idx = s.index
while i < len(s):
    if ddser.iloc[i] <= -0.15:
        st = s.iloc[:i+1].idxmax() if False else runmax.iloc[:i+1][runmax.iloc[:i+1] == runmax.iloc[i]].index[0]
        j = i
        while j < len(s) and ddser.iloc[j] < 0: j += 1
        en = idx[min(j, len(s)-1)]
        seg = (idx >= st) & (idx <= en)
        tr = s[seg].idxmin()
        segdn = (idx >= st) & (idx <= tr)
        bh = np.nansum(r[segdn]); rule = np.nansum((w * r)[segdn])
        eps.append({"start": str(st.date()), "trough": str(tr.date()), "end": str(en.date()), "dd%": round((s[tr]/s[st]-1)*100,1),
                    "zero_share_to_trough": round(float((w[segdn]==0).mean()),2), "bh_logret%": round(bh*100,1), "rule_logret%": round(rule*100,1),
                    "max_pct_rol": round(float(d["pct_rv20_rol"].reindex(idx[segdn]).max()),2), "pre_rv20_med": round(float(d["rv20"].loc[:st].tail(252).median()),3)})
        i = j
    i += 1
print(pd.DataFrame(eps).to_string())
