"""놀이터 — '이벤트성 악재 급락 매수'의 기계적 대용(판정 아님).
사건: 유니버스 종목 종가가 직전 10거래일 최고 대비 −30% 이하(처음 넘은 날, 종목별 63일 간격) ∧ 같은 10일 지수 낙폭 > −5%(시장 하락 아님).
결과: 사건일 종가 → 21·63일 종목 수익 − 유니버스 등가중 수익(초과, 11-24 지수 기준에서 바꿈 — 국내 2025~ 반도체 쏠림이 초과를 왜곡). 미국 S&P500 PIT(2015~) · 국내 유동 500(2016~)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategy-lab"))
from cross_section_us_kr import us_panel, kr_panel
from us_daily_yahoo import load
P = [("~2023", "1900", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", "2100")]
for name, (ret, close, mem), isym in [("미국 S&P500", us_panel(), "^GSPC"), ("국내 유동 500", kr_panel(), "^KS11")]:
    lvl = (1 + ret.fillna(0)).cumprod()
    dd10 = lvl / lvl.rolling(10, min_periods=10).max() - 1
    ix = load(isym)["close"].reindex(ret.index).ffill()
    idd = ix / ix.rolling(10, min_periods=10).max() - 1            # 사건 조건(시장 하락 아님)은 지수로
    ew = (1 + ret.where(mem).mean(axis=1).fillna(0)).cumprod()      # 결과 기준 = 유니버스 등가중(반도체 쏠림 회피)
    rows = []
    for col in ret.columns:
        hit = (dd10[col] <= -0.30) & mem[col].fillna(False) & (idd > -0.05)
        last = -10**9
        for i in np.where(hit.to_numpy())[0]:
            if i - last < 63: continue
            last = i
            for h in (21, 63):
                if i + h >= len(ret): break
                s = lvl[col].iloc[i + h] / lvl[col].iloc[i] - 1
                m = ew.iloc[i + h] / ew.iloc[i] - 1
                rows.append((ret.index[i], col, h, s - m))
    df = pd.DataFrame(rows, columns=["date", "tk", "h", "ex"])
    for h in (21, 63):
        x = df[df.h == h].set_index("date").ex
        t = x.mean() / (x.std() / np.sqrt(len(x)))
        per = " · ".join(f"{k} {x[(x.index >= a) & (x.index <= b)].mean():+.1%}(n{len(x[(x.index >= a) & (x.index <= b)])})" for k, a, b in P)
        print(f"{name} {h}일 초과: n={len(x)} · 평균 {x.mean():+.2%} · 중앙 {x.median():+.2%} · 양수 {(x>0).mean():.0%} · t {t:+.2f} | {per}")
