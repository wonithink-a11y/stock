"""놀이터 — 블로그 매매법 2차(woluck100 연재 #3·#7·#10·#13·#14), 국내 유동 500 · 미국 S&P500 PIT (판정 아님).
종가만 있어 근사: 가격 = 등락률 누적(수정 기준 — 원 종가는 분할에서 가짜 패턴), %R·VCP 폭은 종가 고저, 진입 = 신호일 종가, 청산 = 고정 5·21·63일.
VCP 거래량 조건은 국내만(미국 패널에 거래량 없음)."""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))
from event_engine import study

def lv(r): return (1 + r.fillna(0)).cumprod().where(r.notna() | r.shift(1).notna())
def ma(c, n): return c.rolling(n, min_periods=n).mean()
def first(x): return x & ~x.shift(1, fill_value=False)

def bb_upper(r, c, m, tv):          # 7 볼린저 상단(+2σ, 20일) 돌파 첫날
    p = lv(r); mu, sd = ma(p, 20), p.rolling(20, min_periods=20).std()
    return first(p > mu + 2 * sd)

def willr_up(r, c, m, tv):          # 3 %R(14) −80 아래→위 (종가 고저 근사)
    p = lv(r); hi, lo = p.rolling(14).max(), p.rolling(14).min()
    w = -100 * (hi - p) / (hi - lo)
    return (w > -80) & (w.shift(1) <= -80)

def gc_5_20(r, c, m, tv):           # 10 5·20 골든크로스
    p = lv(r); a = ma(p, 5) > ma(p, 20)
    return first(a)

def vcp(r, c, m, tv):               # 13 VCP 근사
    p = lv(r)
    w = [(p.rolling(20).max().shift(k) / p.rolling(20).min().shift(k) - 1) for k in (41, 21, 1)]
    contract = (w[0] > w[1]) & (w[1] > w[2]) & (w[2] <= 0.12)
    trend = ma(p, 50) > ma(p, 150)
    brk = p > p.rolling(20).max().shift(1)
    sig = contract & trend & brk
    if tv is not None:
        sig &= tv >= 1.5 * tv.rolling(20, min_periods=15).mean().shift(1)
    return first(sig)

def double_bottom(r, c, m, tv):     # 14 쌍바닥 넥라인 돌파(60일 안 두 저점 차 ≤5%, 저점 간 ≥10일, 넥라인 ≥ 저점+2%)
    P = lv(r).to_numpy(); out = np.zeros_like(P, bool)
    for j in range(P.shape[1]):
        x = P[:, j]; n = len(x)
        # 5일 창 국소 최저(앞뒤 5일 확인 → 신호에는 5일 뒤부터만 쓸 수 있다)
        lows = [i for i in range(5, n - 5) if np.isfinite(x[i]) and x[i] == np.nanmin(x[i - 5:i + 6])]
        for a, b in zip(lows, lows[1:]):
            if not (10 <= b - a <= 60) or abs(x[b] / x[a] - 1) > 0.05:
                continue
            neck = np.nanmax(x[a:b + 1])
            if neck < max(x[a], x[b]) * 1.02:
                continue
            for i in range(b + 5, min(b + 40, n)):          # 두 번째 저점 확인 뒤 40일 안 첫 돌파
                if x[i] > neck:
                    out[i, j] = True; break
                if x[i] < min(x[a], x[b]):
                    break
    return pd.DataFrame(out, r.index, r.columns)

for name, f in [("볼린저 상단 돌파", bb_upper), ("%R(14) −80 재상향", willr_up), ("5·20 골든크로스", gc_5_20),
                ("VCP 근사(국내 거래량 1.5배)", vcp), ("쌍바닥 넥라인 돌파", double_bottom)]:
    study(name, f)
