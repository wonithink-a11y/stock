"""진바닥 국내 대입 C — findings/true-bottom-kr-confirm-prereg-2026-11.md 그대로.

  python research/strategy-lab/true_bottom_kr_confirm.py --selftest
  python research/strategy-lab/true_bottom_kr_confirm.py
"""
import argparse, sys
from pathlib import Path
import numpy as np, pandas as pd
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "sandbox"))
from true_bottom_explore import onsets, fwd, null_means, H, SEED, NULL_N   # noqa: E402
from us_daily_yahoo import load                                              # noqa: E402

LEADER, LO, HI = "005930", "2010-02-01", "2026-08-31"
CELLS = [(-0.22, 0.40, True), (-0.22, 0.20, False), (-0.10, 0.40, False), (-0.10, 0.20, False)]


def kr_daily():
    fs = sorted((HERE / "data/krx-pbr-history/daily").glob("*.parquet")) + sorted((HERE / "data/krx-daily-ext").glob("*.parquet"))
    d = pd.concat(pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "FLUC_RT", "ACC_TRDVAL"]) for f in fs)
    d["date"] = pd.to_datetime(d["BAS_DD"].astype(str))
    for c in ("FLUC_RT", "ACC_TRDVAL"):
        d[c] = pd.to_numeric(d[c].astype(str).str.replace(",", ""), errors="coerce")
    d = d.drop_duplicates(["ISU_CD", "date"])
    ret = d.pivot(index="date", columns="ISU_CD", values="FLUC_RT") / 100
    ret = ret.where(ret.abs() < 0.31)
    mem = d.pivot(index="date", columns="ISU_CD", values="ACC_TRDVAL").rolling(20, min_periods=15).mean().rank(axis=1, ascending=False) <= 500
    return ret, mem


def features(ret, mem):
    lvl = (1 + ret.fillna(0)).cumprod().where(ret.notna())
    ma50 = lvl.rolling(50, min_periods=50).mean()
    ok = mem & ma50.notna() & lvl.notna()
    br = ((lvl > ma50) & ok).sum(axis=1) / ok.sum(axis=1)
    s = (1 + ret[LEADER].fillna(0)).cumprod()
    dd = s / s.rolling(252, min_periods=252).max() - 1
    return pd.DataFrame({"dd": dd, "br": br}).dropna()


def run():
    f = features(*kr_daily())
    px = load("^KS11")["close"].dropna()
    f = f[(f.index >= LO) & (f.index <= HI)]
    pool = np.flatnonzero((px.index >= LO) & (px.index <= HI))
    pool = pool[pool + H < len(px)]
    rng = np.random.default_rng(SEED)
    print(f"구간 {f.index.min().date()}~{f.index.max().date()} · 삼성 낙폭 최저 {f.dd.min():.1%} · 폭 최저 {f.br.min():.1%} · 무작위 {NULL_N}")
    for d_, b_, main in CELLS:
        ev = [d for d in onsets((f.dd <= d_) & (f.br <= b_)) if not np.isnan(fwd(px, d, H))]
        lab = f"낙폭≤{d_:.0%}·폭≤{b_:.0%}" + (" [본 칸]" if main else " [기록 전용]")
        if not ev:
            print(f"{lab}: 사건 0" + (" → INCONCLUSIVE(자료)" if main else "")); continue
        r = np.array([fwd(px, d, H) for d in ev])
        nm = null_means(pool, px, len(ev), rng)
        p = (np.sum(nm >= r.mean()) + 1) / (NULL_N + 1)
        verdict = ("확인됨" if p <= 0.05 and len(ev) >= 5 else ("INCONCLUSIVE(사건<5)" if len(ev) < 5 else "REJECT")) if main else "-"
        per = " · ".join(f"{k} {r[[a <= str(x.date()) <= b for x in ev]].mean():+.1%}" for k, a, b in [("2010~15", "2010", "2015-12-31"), ("2016~23", "2016", "2023-12-31"), ("2024~", "2024", "2100")] if any(a <= str(x.date()) <= b for x in ev))
        print(f"{lab}: n={len(ev)} · 63일 {r.mean():+.2%} vs 무작위 {nm.mean():+.2%} · 양수 {(r > 0).mean():.0%} · p {p:.3f} → {verdict} | {per}")
        print("   " + ", ".join(f"{d.date()}({x:+.0%})" for d, x in zip(ev, r)))


def selftest():
    idx = pd.bdate_range("2015-01-01", periods=400)
    ret = pd.DataFrame(0.001, idx, [LEADER, "A", "B"])
    ret.iloc[300:330] = -0.02
    mem = pd.DataFrame(True, idx, ret.columns)
    f = features(ret, mem)
    assert f.dd.min() < -0.40 and f.br.min() == 0.0
    on = onsets((f.dd <= -0.22) & (f.br <= 0.40))
    assert len(on) == 1 and idx[300] < on[0] < idx[330]
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--selftest", action="store_true")
    selftest() if ap.parse_args().selftest else run()
