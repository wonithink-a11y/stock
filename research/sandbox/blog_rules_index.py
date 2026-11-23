"""놀이터 — 블로그·퀀트 사이트 지수 매매법 4종 (판정 아님). 미국 1990~(1970~89 는 확인용으로 비움), 국내 전 기간.
7 Double 7(Connors): 200일선 위 ∧ 종가 = 7일 최저 → 매수, 종가 = 7일 최고 → 매도
8 야간 보유(SPY·QQQ·국내 지수): 종가→다음 시가 vs 시가→종가 (일평균, 비용 전후)
9 10일 신고가 ∧ IBS<0.3: 고가 > 직전 10일 최고 고가 ∧ IBS<0.3 → 종가 매수, 종가 > 전일 고가면 매도
27 섹터 로테이션: XL* 9개 12-1개월 모멘텀 상위 3 월간 vs 9개 등가중
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "strategy-lab"))
from us_daily_yahoo import load
COST = 0.0005
IDX = [("S&P500", "^GSPC"), ("나스닥100", "^NDX"), ("러셀2000", "^RUT"), ("코스피", "^KS11"), ("코스닥", "^KQ11")]

def get(sym):
    d = load(sym).dropna(subset=["close"])
    d = d[(d.high > 0) & (d.low > 0)]
    return d[d.index >= "1990-01-01"] if sym in ("^GSPC", "^NDX", "^RUT", "SPY", "QQQ") else d

def trades(entry, exitf, c):
    out, i, n = [], 0, len(c)
    e, x = entry.to_numpy(), exitf.to_numpy()
    while i < n:
        if e[i]:
            j = i + 1
            while j < n and not x[j]: j += 1
            if j >= n: break
            out.append((c.index[i], c.iloc[j] / c.iloc[i] - 1, j - i)); i = j + 1
        else: i += 1
    return pd.DataFrame(out, columns=["d", "r", "days"])

def report(name, lab, t, c):
    if len(t) < 5: print(f"  {lab} {name}: 거래 {len(t)}"); return
    exp = t.days.sum() / len(c)
    bh_ann = (c.iloc[-1] / c.iloc[0]) ** (252 / len(c)) - 1
    strat = (1 + t.r - COST).prod() ** (252 / len(c)) - 1
    base = (c.shift(-int(t.days.mean())) / c - 1).mean()
    tt = (t.r.mean() - base) / (t.r.std() / np.sqrt(len(t)))
    print(f"  {lab} {name}: 거래 {len(t)} · 평균 {t.r.mean():+.2%}(보유 {t.days.mean():.1f}일, 같은 길이 아무 때 {base:+.2%}, t {tt:+.2f}) · 승률 {(t.r>0).mean():.0%}"
          f" · 노출 {exp:.0%} · 연 {strat:+.1%}(net) vs 보유 {bh_ann:+.1%}")

print("■ 7 Double 7 / ■ 9 10일 신고가+IBS")
for lab, sym in IDX:
    d = get(sym); c = d.close
    ent = (c > c.rolling(200).mean()) & (c <= c.rolling(7).min())
    report("Double 7", lab, trades(ent, c >= c.rolling(7).max(), c), c)
    ibs = (d.close - d.low) / (d.high - d.low).replace(0, np.nan)
    ent9 = (d.high > d.high.rolling(10).max().shift(1)) & (ibs < 0.3)
    report("10일고가+IBS<0.3", lab, trades(ent9, c > d.high.shift(1), c), c)
print("■ 8 야간 vs 장중 (일평균, bp)")
for lab, sym in [("SPY", "SPY"), ("QQQ", "QQQ"), ("코스피", "^KS11"), ("코스닥", "^KQ11")]:
    d = get(sym); on = (d.open / d.close.shift(1) - 1).dropna(); intr = (d.close / d.open - 1).dropna()
    on, intr = on[on.abs() < 0.2], intr[intr.abs() < 0.2]
    t = on.mean() / (on.std() / np.sqrt(len(on)))
    yr = lambda s, a, b: s[(s.index >= a) & (s.index <= b)].mean() * 1e4
    print(f"  {lab}: 야간 {on.mean()*1e4:+.2f}bp(t {t:+.2f}) · 장중 {intr.mean()*1e4:+.2f}bp · 야간−비용5bp {on.mean()*1e4-5:+.2f}bp | 야간 ~2015 {yr(on,'1900','2015-12-31'):+.1f} · 2016~23 {yr(on,'2016','2023-12-31'):+.1f} · 2024~ {yr(on,'2024','2100'):+.1f}")
print("■ 27 섹터 로테이션 12-1 상위 3 (월간, 미국)")
secs = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU"]
m = pd.DataFrame({s: load(s)["adjclose"] for s in secs}).resample("ME").last().dropna()
mom = m.shift(1) / m.shift(12) - 1
nxt = m.pct_change().shift(-1)
rows = []
for d in mom.index[12:-1]:
    top = mom.loc[d].nlargest(3).index
    rows.append((d, nxt.loc[d, top].mean() - nxt.loc[d].mean()))
x = pd.Series(dict(rows))
print(f"  상위3 − 9개 등가중: 월 {x.mean():+.2%} · t {x.mean()/(x.std()/np.sqrt(len(x))):+.2f} · n {len(x)}개월 · 2016~ {x[x.index>='2016'].mean():+.2%}")
