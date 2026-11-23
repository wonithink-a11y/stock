"""진바닥 확인(C) — 사전등록 findings/true-bottom-confirm-prereg-2026-11.md(711fd698) 그대로.
2006~2015 PIT 패널(us_pit_pre2016.py panel)로 애플 낙폭 × 50일선 위 비율, 사건 = 2007~2015, 결과 = ^GSPC 63거래일.
  python research/strategy-lab/true_bottom_confirm.py --selftest
  python research/strategy-lab/true_bottom_confirm.py           # 자료 게이트(커버리지 ≥ 95%) 먼저
"""
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from true_bottom_explore import onsets, DEBOUNCE   # 같은 사건 정의 재사용
from us_daily_yahoo import load
PANEL6 = HERE / "data/us-pit/panel_2006"
H, N_NULL, SEED, COST = 63, 2000, 20261124, 0.0005
CELLS = [(-0.22, 0.40, "주"), (-0.22, 0.20, "기록"), (-0.10, 0.40, "기록"), (-0.10, 0.20, "기록")]


def features(panel):
    p = panel.sort_values(["ticker", "start", "date"]).copy()
    p["ma50"] = p.groupby(["ticker", "start"])["close"].transform(lambda s: s.rolling(50).mean())
    m = p[p["member"] & p["ma50"].notna()].drop_duplicates(["ticker", "date"])
    br = (m["close"] > m["ma50"]).groupby(m["date"]).mean()
    aapl = pd.read_parquet(HERE / "data/us-pit/raw/yf/AAPL.parquet")["close"]
    aapl.index = pd.to_datetime(aapl.index).tz_localize(None).normalize()
    dd = aapl / aapl.rolling(252, min_periods=252).max() - 1
    return pd.DataFrame({"dd": dd, "br": br}).dropna()


def run():
    cov = json.loads((PANEL6 / "coverage.json").read_text(encoding="utf-8"))
    gate = cov["coverage_mean"] >= 0.95
    print(f"자료 게이트: 멤버-일 커버리지 평균 {cov['coverage_mean']:.1%} (최저 {cov['coverage_min']:.1%}) → {'통과' if gate else '미달 — INCONCLUSIVE'}")
    f = features(pd.read_parquet(PANEL6 / "prices.parquet"))
    f = f[(f.index >= "2007-01-01") & (f.index <= "2015-12-31")]
    spx = load("^GSPC")["close"].dropna()
    fr = spx.shift(-H) / spx - 1
    pool = fr[(fr.index >= "2007-01-01") & (fr.index <= "2015-12-31")].dropna()
    rng = np.random.default_rng(SEED)
    spx_dd = spx / spx.rolling(252, min_periods=1).max() - 1
    matched = pool[spx_dd.reindex(pool.index) <= -0.08]
    for d_, b_, role in CELLS:
        ev = [d for d in onsets((f.dd <= d_) & (f.br <= b_)) if d in fr.index and pd.notna(fr[d])]
        r = fr[ev]
        n = len(r)
        if n == 0:
            print(f"[{role}] 낙폭≤{d_:.0%}·비율≤{b_:.0%}: 사건 0"); continue
        nm = np.array([rng.choice(pool.values, n, replace=False).mean() for _ in range(N_NULL)])
        p = (np.sum(nm >= r.mean()) + 1) / (N_NULL + 1)
        mm = np.array([rng.choice(matched.values, n, replace=False).mean() for _ in range(500)]).mean() if len(matched) >= n else np.nan
        verdict = ("INCONCLUSIVE" if (n < 5 or not gate) else ("확인됨" if (p <= 0.05 and r.mean() > nm.mean()) else "REJECT")) if role == "주" else "기록 전용"
        print(f"[{role}] 낙폭≤{d_:.0%}·비율≤{b_:.0%}: n={n} · 63일 {r.mean():+.2%} (net {r.mean()-COST:+.2%}) vs 무작위 {nm.mean():+.2%} · 매칭 {mm:+.2%}"
              f" · 양수 {(r>0).mean():.0%} · p {p:.3f} → {verdict}")
        print("    " + ", ".join(f"{d.date()} {fr[d]:+.1%}" for d in ev))


def selftest():
    idx = pd.bdate_range("2008-01-01", periods=300)
    pan = pd.DataFrame({"date": list(idx) * 2, "close": list(np.linspace(100, 50, 300)) + list(np.linspace(50, 100, 300)),
                        "ticker": ["X"] * 300 + ["Y"] * 300, "start": "s", "member": True})
    p = pan.sort_values(["ticker", "start", "date"]).copy()
    p["ma50"] = p.groupby(["ticker", "start"])["close"].transform(lambda s: s.rolling(50).mean())
    m = p[p.ma50.notna()]
    br = (m.close > m.ma50).groupby(m.date).mean()
    assert abs(br.iloc[-1] - 0.5) < 1e-12
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--selftest", action="store_true")
    selftest() if ap.parse_args().selftest else run()
