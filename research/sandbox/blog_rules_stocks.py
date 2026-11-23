"""놀이터 — 블로그 매매법 3종(woluck100.tistory 연재) 종목 단위, 국내 유동 500 · 미국 S&P500 PIT (판정 아님).
우리 종목 자료는 종가만 있어 '다음날 시가 진입'은 '신호일 종가 진입'으로, '저가가 20선 터치'는 '종가가 20선 위 1% 이내'로 근사한다.
청산은 글의 규칙 대신 고정 보유 5·21·63일로 본다(엔진 공통)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from event_engine import study

def ma(c, n): return c.rolling(n, min_periods=n).mean()

def pullback(r, c, m, tv):          # 1 눌림목
    m20, m60 = ma(c, 20), ma(c, 60)
    up = (m20 > m60) & (c > m60) & (c.rolling(10).max().shift(1) >= m20 * 1.05)
    return up & (c >= m20) & (c <= m20 * 1.01)

def aligned_start(r, c, m, tv):     # 2 정배열 초입
    a = (ma(c, 5) > ma(c, 20)) & (ma(c, 20) > ma(c, 60)) & (ma(c, 60) > ma(c, 120))
    return a & ~a.shift(1, fill_value=False)

def box_break(r, c, m, tv):         # 4 박스권 돌파
    hi, lo = c.rolling(20).max().shift(1), c.rolling(20).min().shift(1)
    box = (hi / lo) <= 1.15
    brk = box & (c > hi)
    return brk & ~brk.shift(1, fill_value=False)

for name, f in [("눌림목(20선 지지)", pullback), ("정배열 초입(5>20>60>120 첫날)", aligned_start), ("박스권(20일 폭 ≤15%) 돌파", box_break)]:
    study(name, f)
