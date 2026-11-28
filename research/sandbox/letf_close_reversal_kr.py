"""놀이터(S, 판정 아님) — 레버리지 ETF 마감 리밸런싱 반전 (arXiv 2608.03703 'Preying on Leveraged ETFs', 11-28 유입).

주장: LETF 추적 한국 종목은 '개장 전 미국 뉴스'에 대한 첫날 반응의 약 75% 를 다음 종가까지 되돌린다(2026, 통제군엔 없음).
일봉 대용: 미국 SMH(반도체) 야간 수익률 |x| ≥ thr 인 한국 거래일 t 에서, 종목 초과수익(그날 유니버스 평균 뺀 값) R1(t) 의 부호 반대로
t+1 에 베팅했을 때의 평균 = reversal = -sign(R1)·r(t+1) 과 회귀 기울기 b(r(t+1)=a+b·R1(t)). 음수 b·양수 reversal = 반전.
대상: 000660·005930(논문 사례) vs 통제 = 같은 기간 거래대금 상위 30(둘 제외). 시기: ~2025 / 2026~(LETF 시대).
LETF 상장 목록은 없다 → 종목 단위 대응은 못 한다(한계). 비용 미반영.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "strategy-lab"))
from event_engine import panels      # noqa: E402
from us_daily_yahoo import load      # noqa: E402

P = panels()
r, close, mem, tv = P["kr"]
smh = load("SMH")["close"].pct_change().dropna()
smh.index = pd.to_datetime(smh.index)
# 한국 거래일 t 의 '개장 전 미국' = t 보다 엄격히 이른 마지막 미국 거래일의 수익률
us = pd.merge_asof(pd.DataFrame({"date": r.index}), smh.rename("smh").reset_index().rename(columns={smh.index.name or "index": "d"}),
                   left_on="date", right_on="d", direction="backward", allow_exact_matches=False).set_index("date")["smh"]
ex = r.sub(r.mean(axis=1), axis=0)                  # 그날 유니버스 평균 뺀 초과수익
last = ex.loc["2025-01-01":].index
top = tv.loc["2025-01-01":].mean().sort_values(ascending=False).index
ctrl = [c for c in top if c not in ("000660", "005930")][:30]
GROUPS = {"하이닉스": ["000660"], "삼성전자": ["005930"], "통제30": ctrl}
PERIODS = [("~2025", "1900", "2025-12-31"), ("2026~", "2026-01-01", "2100")]


def run(thr):
    ev = us.index[(us.abs() >= thr)]
    print(f"\n== |SMH 야간| ≥ {thr:.0%}  (사건일 {len(ev)}일)")
    print(f"{'그룹':8s}{'시기':8s}{'종목일':>7s}{'b':>8s}{'반전수익%':>10s}{'양수비':>7s}")
    for g, cs in GROUPS.items():
        for pn, a, b in PERIODS:
            d = [t for t in ev if a <= str(t.date()) <= b]
            xs, ys = [], []
            for c in cs:
                if c not in ex:
                    continue
                s = ex[c]
                nxt = s.shift(-1)
                for t in d:
                    if np.isfinite(s.get(t, np.nan)) and np.isfinite(nxt.get(t, np.nan)):
                        xs.append(s[t]); ys.append(nxt[t])
            if len(xs) < 5:
                print(f"{g:8s}{pn:8s}{len(xs):7d}   (표본 부족)"); continue
            x, y = np.array(xs), np.array(ys)
            beta = np.polyfit(x, y, 1)[0]
            rev = -np.sign(x) * y
            print(f"{g:8s}{pn:8s}{len(x):7d}{beta:8.2f}{rev.mean()*100:10.3f}{(rev>0).mean():7.2f}")


if __name__ == "__main__":
    for thr in (0.02, 0.03):
        run(thr)
