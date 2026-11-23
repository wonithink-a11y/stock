"""[11-24 결과 뒤 보정] 기준을 '매일 재조정 등가중'(국내에서 63일 +5.8%p 과대)에서 '같은 날 유니버스 사서 들고 있기 평균'으로 바꿨다. 옛 값은 ex_rebal 로 함께 낸다.
종목 고유 급락 뒤 63일 — E(findings/idio-crash-explore-prereg-2026-11.md) · C(idio-crash-confirm-prereg-2026-11.md) 그대로.

  python research/strategy-lab/idio_crash.py --selftest
  python research/strategy-lab/idio_crash.py                 # E (미국 2015~, 국내 2016~)
  python research/strategy-lab/idio_crash.py --confirm kr    # 국내 2010~2015 홀드아웃
  python research/strategy-lab/idio_crash.py --confirm us    # 미국 2006~2015 PIT 패널(커버리지 게이트)
"""
import argparse, json, re, sys
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "sandbox"))
from us_daily_yahoo import load                       # noqa: E402
from trials import bh_with_prior                       # noqa: E402
from cross_section_us_kr import us_panel, kr_panel     # noqa: E402

PR = {k: int(v) for k, v in re.findall(r"누적 (kr|us) (\d+)", (HERE / "findings/idio-crash-explore-prereg-2026-11.md").read_text(encoding="utf-8"))}
SIGN = {"us": 1, "kr": -1}
IDX = {"us": "^GSPC", "kr": "^KS11"}
P = [("~2015", "1900", "2015-12-31"), ("2016~23", "2016-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", "2100")]


def events(ret, mem, ix, horizons=(21, 63)):
    lvl = (1 + ret.fillna(0)).cumprod()
    dd10 = lvl / lvl.rolling(10, min_periods=10).max() - 1
    ix = ix.reindex(ret.index).ffill()
    idd = ix / ix.rolling(10, min_periods=10).max() - 1
    ew = (1 + ret.where(mem).mean(axis=1).fillna(0)).cumprod()     # 옛 기준(매일 재조정) — 기록용
    bh = {h: (lvl.shift(-h) / lvl - 1).where(mem).mean(axis=1) for h in horizons}   # 11-24 보정: 같은 날 유니버스를 사서 들고 있기 평균
    rows = []
    for col in ret.columns:
        hit = ((dd10[col] <= -0.30) & mem[col].fillna(False) & (idd > -0.05)).to_numpy()
        last = -10**9
        for i in np.where(hit)[0]:
            if i - last < 63:
                continue
            last = i
            for h in horizons:
                if i + h < len(ret):
                    raw = lvl[col].iloc[i + h] / lvl[col].iloc[i] - 1
                    rows.append((ret.index[i], col, h, raw - bh[h].iloc[i], raw - (ew.iloc[i + h] / ew.iloc[i] - 1)))
    return pd.DataFrame(rows, columns=["date", "tk", "h", "ex", "ex_rebal"])


def cluster_test(x, sign):
    m = x.groupby(x.index.to_period("M")).mean()
    t = m.mean() / (m.std(ddof=1) / np.sqrt(len(m)))
    p = 1 - stats.t.cdf(sign * t, len(m) - 1)
    return t, p, len(m)


def describe(df, label):
    out = {}
    for h in (21, 63):
        x = df[df.h == h].set_index("date").ex
        if len(x) < 5:
            continue
        out[h] = x
        per = " · ".join(f"{k} {x[(x.index >= a) & (x.index <= b)].mean():+.1%}(n{len(x[(x.index >= a) & (x.index <= b)])})" for k, a, b in P
                         if len(x[(x.index >= a) & (x.index <= b)]))
        print(f"  {label} {h}일: n={len(x)} · 평균 {x.mean():+.2%} · 중앙 {x.median():+.2%} · 양수 {(x > 0).mean():.0%} | {per}")
    return out


def run():
    for smp, loader in (("us", us_panel), ("kr", kr_panel)):
        ret, close, mem = loader()
        df = events(ret, mem, load(IDX[smp])["close"])
        xs = describe(df, smp)
        t, p, nm = cluster_test(xs[63], SIGN[smp])
        adj, ok, m = bh_with_prior([p], q=0.10, prior=PR[smp])
        print(f"[{smp}] 63일 월 군집 t {t:+.2f} (월 {nm}) · 단측({'>' if SIGN[smp] > 0 else '<'}0) p {p:.2e} · BH {adj[0]:.4f}(m={m}) → {'탐색 통과(사후)' if ok[0] else '미통과'}")
        if smp == "kr":
            semis = set(pd.read_parquet(HERE / "data/factor-panel/kr-monthly-v1.parquet", columns=["ticker", "sector"])
                        .query("sector.str.contains('반도체')", engine="python").ticker)
            x = df[(df.h == 63) & ~df.tk.isin(semis)].ex
            print(f"  [kr 반도체 제외·진단] 63일 평균 {x.mean():+.2%} (n {len(x)})")


def us_panel_2006():
    p = pd.read_parquet(HERE / "data/us-pit/panel_2006/prices.parquet").sort_values(["ticker", "start", "date"])
    p["ret"] = p.groupby(["ticker", "start"])["close"].pct_change()
    p = p.drop_duplicates(["ticker", "date"], keep="last")
    return p.pivot(index="date", columns="ticker", values="ret"), p.pivot(index="date", columns="ticker", values="member").fillna(False).astype(bool)


def confirm(smp):
    if smp == "kr":
        from hi52_explore import kr_holdout_panel
        ret, close, mem = kr_holdout_panel()
        lo, hi = "2010-02-01", "2015-10-31"
        gate = True
    else:
        cov = json.loads((HERE / "data/us-pit/panel_2006/coverage.json").read_text(encoding="utf-8"))
        gate = cov["coverage_mean"] >= 0.95
        print(f"자료 게이트(미국): 커버리지 {cov['coverage_mean']:.1%} → {'통과' if gate else '미달 — 판정 안 함'}")
        ret, mem = us_panel_2006()
        lo, hi = "2007-01-01", "2015-09-30"
    df = events(ret, mem, load(IDX[smp])["close"])
    df = df[(df.date >= lo) & (df.date <= hi)]
    xs = describe(df, f"확인 {smp}")
    t, p, nm = cluster_test(xs[63], SIGN[smp])
    ok = gate and p <= 0.05
    print(f"확인 [{smp}] 63일 월 군집 t {t:+.2f} (월 {nm}) · 단측 p {p:.2e} → {'확인됨' if ok else ('REJECT' if gate else 'INCONCLUSIVE(자료)')}")


def selftest():
    idx = pd.bdate_range("2020-01-01", periods=120)
    ret = pd.DataFrame(0.0, idx, ["A", "B"])
    ret.loc[idx[20], "A"] = -0.35                      # A 하루 −35%
    mem = pd.DataFrame(True, idx, ["A", "B"])
    ix = pd.Series(100.0, idx)
    df = events(ret, mem, ix)
    assert len(df[df.h == 63]) == 1 and df.date.iloc[0] == idx[20]
    ix2 = ix.copy(); ix2.iloc[15:25] = 90                # 시장도 −10% 면 사건 아님
    assert idx[20] not in set(events(ret, mem, ix2).date)   # 시장도 빠진 날은 사건 아님(시장 회복 뒤 날은 정의상 사건일 수 있다)
    x = pd.Series([-0.1, -0.2, -0.05, -0.15, -0.1, -0.12], pd.date_range("2020-01-31", periods=6, freq="ME"))
    t, p, n = cluster_test(x, -1)
    assert t < 0 and p < 0.01 and n == 6
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--selftest", action="store_true"); ap.add_argument("--confirm", choices=["kr", "us"])
    a = ap.parse_args()
    selftest() if a.selftest else (confirm(a.confirm) if a.confirm else run())
