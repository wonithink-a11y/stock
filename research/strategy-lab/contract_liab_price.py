#!/usr/bin/env python3
"""계약부채 증가 → 사업보고서 공시 뒤 주가(2단계). 사전등록: findings/contract-liab-price-preregistration-2026-10.md (7d034d87).
정의·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

  python research/strategy-lab/contract_liab_price.py --selftest
  python research/strategy-lab/contract_liab_price.py            # 1회 실행 → reports/2026-10-contract-liab/price-results.json
"""
import glob
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import contract_liab_revenue as S1  # noqa: E402  (cl_amount·A3 로더 재사용)

ROOT = HERE.parent.parent
PRICE = ROOT / "data" / "backfill" / "price"
OUT = HERE / "reports" / "2026-10-contract-liab" / "price-results.json"
H, H12, COST, LIQ, N_NULL, SEED = 126, 252, 0.00335, 1e9, 10000, 20261019
SPLIT = {"TRAIN": (2018, 2021), "VALID": (2022, 2023), "TEST": (2024, 2026)}
ERAS = {"2018~23": (2018, 2023), "2024": (2024, 2024), "2025~": (2025, 2026)}
FIN, SEMI = ("64", "65", "66"), "261"


# ------------------------------------------------------------------ 자료
def load_fin():
    cl, avail = {}, {}
    for line in open(S1.FULL, encoding="utf-8"):
        d = json.loads(line)
        k = (d["ticker"], d["fiscalYear"])
        cl[k], avail[k] = S1.cl_amount(d["rows"]), d["availableFrom"]
    rev, sic = _a3()
    return cl, avail, rev, sic


def _a3():
    import gzip
    rev, sic = {}, {}
    for p in S1.A3.glob("20*.jsonl.gz"):
        for line in gzip.open(p, "rt", encoding="utf-8"):
            d = json.loads(line)
            rev[(d["ticker"], d["fiscalYear"])] = d.get("revenue")
            sic[d["ticker"]] = str(d.get("sicCode") or "")
    return rev, sic


def load_px():
    frames = []
    for src in ("a2a", "a2b"):
        for p in sorted(glob.glob(str(PRICE / src / "20*.jsonl.gz"))):
            f = pd.read_json(p, lines=True, compression="gzip", dtype={"ticker": str})[["ticker", "date", "close", "volume"]]
            f["src"] = 0 if src == "a2a" else 1
            frames.append(f)
    df = pd.concat(frames, ignore_index=True).sort_values("src").drop_duplicates(["ticker", "date"])   # 같은 날 중복은 A2a 우선
    df["date"] = pd.to_datetime(df["date"])
    C = df.pivot(index="date", columns="ticker", values="close").sort_index()
    TV = (df.assign(tv=df.close * df.volume).pivot(index="date", columns="ticker", values="tv")).reindex_like(C)
    return C, TV


# ------------------------------------------------------------------ 순수 계산
def events(cl, avail, rev, sic):
    rows = []
    for (t, y), c in cl.items():
        c0, r0, r1 = cl.get((t, y - 1)), rev.get((t, y - 1)), rev.get((t, y))
        if c is None or c0 is None or r0 is None or r1 is None or r0 < 1e9 or r1 < 1e9 or sic.get(t, "")[:2] in FIN:
            continue
        rows.append({"ticker": t, "fy": y, "avail": avail[(t, y)], "dcl": (c - c0) / r0})
    ev = pd.DataFrame(rows)
    q = ev.groupby("fy").dcl.quantile([0.2, 0.8]).unstack()
    ev["q20"] = ev.fy.map(lambda y: q.loc[y - 1, 0.2] if y - 1 in q.index else np.nan)   # 직전 회계연도 분포(PIT)
    ev["q80"] = ev.fy.map(lambda y: q.loc[y - 1, 0.8] if y - 1 in q.index else np.nan)
    ev = ev.dropna(subset=["q80"])
    ev["cell"] = np.where(ev.dcl >= ev.q80, "Q5", np.where(ev.dcl <= ev.q20, "Q1", "M"))
    return ev


class Market:
    """진입일별 적격 종목 수익·대조 그룹(캐시)."""

    def __init__(self, C, TV, sic, drop_semi=False):
        self.C, self.idx = C, C.index
        self.tv20 = TV.rolling(20, min_periods=20).mean().shift(1)
        self.sic = sic
        self.drop_semi = drop_semi
        self.cache = {}

    def day(self, i0, h):
        if (i0, h) in self.cache:
            return self.cache[(i0, h)]
        if i0 + h >= len(self.idx):
            self.cache[(i0, h)] = None
            return None
        px0, tv = self.C.iloc[i0], self.tv20.iloc[i0]
        ok = px0.notna() & (tv >= LIQ)
        cols = [t for t in ok[ok].index if self.sic.get(t, "")[:2] not in FIN and not (self.drop_semi and self.sic.get(t, "").startswith(SEMI))]
        last = self.C[cols].iloc[i0:i0 + h + 1].ffill().iloc[-1]
        r = last / px0[cols] - 1
        terc = pd.qcut(tv[cols].rank(method="first"), 3, labels=False)
        g = pd.DataFrame({"r": r, "terc": terc, "sic2": [self.sic.get(t, "")[:2] for t in cols]})
        self.cache[(i0, h)] = g
        return g

    def excess(self, ticker, avail, h):
        after = np.searchsorted(self.idx.values, np.datetime64(pd.Timestamp(avail)), side="right")
        if after >= len(self.idx):
            return None, "immature"
        g = self.day(after, h)
        if g is None:
            return None, "immature"
        if ticker not in g.index:
            return None, "ineligible"
        me = g.loc[ticker]
        peers = g[(g.terc == me.terc) & (g.sic2 == me.sic2)].drop(ticker)
        fb = len(peers) < 5
        if fb:
            peers = g[g.terc == me.terc].drop(ticker)
        return (float(me.r - peers.r.mean()), int(self.idx[after].year), fb), None


def cohort_stat(df):
    """df: fy, x → 회계연도 코호트 평균의 평균."""
    return float(df.groupby("fy").x.mean().mean()) if len(df) else np.nan


def null_p(all_df, cell_df, n=N_NULL, seed=SEED):
    """같은 회계연도 사건 전체에서 같은 개수 무작위 → 코호트 평균의 평균 분포. p = 귀무 ≥ 실제."""
    if cell_df.empty:
        return np.nan
    rng = np.random.default_rng(seed)
    draws = []
    for fy, k in cell_df.groupby("fy").size().items():
        a = all_df[all_df.fy == fy].x.values
        idx = rng.random((n, len(a))).argsort(axis=1)[:, :k]
        draws.append(a[idx].mean(axis=1))
    return float(np.mean(np.mean(draws, axis=0) >= cohort_stat(cell_df)))


def boot_ci(df, n=10000, seed=SEED):
    if df.empty:
        return [np.nan, np.nan]
    rng = np.random.default_rng(seed)
    m = df.groupby("fy").x.mean().values
    b = m[rng.integers(0, len(m), (n, len(m)))].mean(axis=1)
    return [float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))]


def summarize(xs, span):
    a, b = span
    s = xs[(xs.entry_year >= a) & (xs.entry_year <= b)]
    q5 = s[s.cell == "Q5"]
    m = cohort_stat(q5)
    return {"n": int(len(q5)), "cohorts": int(q5.fy.nunique()), "gross": m, "ci": boot_ci(q5), "net": m - COST if m == m else np.nan,
            "breakeven_bp": m * 1e4 if m == m else np.nan, "p": null_p(s, q5), "q1": cohort_stat(s[s.cell == "Q1"]),
            "fallback_share": float(q5.fb.mean()) if len(q5) else np.nan}


def verdict(sp):
    tr, va, te = sp["TRAIN"], sp["VALID"], sp["TEST"]
    if not tr["gross"] > 0:
        return "REJECT"
    later_pos = va["gross"] > 0 and te["gross"] > 0
    if tr["p"] < 0.05:
        if not later_pos:
            return "REJECT"
        return "ECONOMIC" if all(sp[k]["net"] > 0 for k in sp) else "INFORMATION"
    return "INCONCLUSIVE" if later_pos else "REJECT"


def run(ev, mk, h):
    out, drop = [], defaultdict(int)
    for e in ev.itertuples():
        v, why = mk.excess(e.ticker, e.avail, h)
        if v is None:
            drop[why] += 1
            continue
        out.append({"ticker": e.ticker, "fy": e.fy, "cell": e.cell, "x": v[0], "entry_year": v[1], "fb": v[2]})
    return pd.DataFrame(out), dict(drop)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    cl, avail, rev, sic = load_fin()
    ev = events(cl, avail, rev, sic)
    C, TV = load_px()
    res = {"events": int(len(ev)), "by_fy": ev.groupby(["fy", "cell"]).size().unstack(fill_value=0).to_dict("index"), "price_end": str(C.index.max().date())}
    mk = Market(C, TV, sic)
    xs, drop = run(ev, mk, H)
    sp = {k: summarize(xs, v) for k, v in SPLIT.items()}
    res.update(main_drop=drop, split=sp, verdict=verdict(sp), eras={k: summarize(xs, v) for k, v in ERAS.items()})
    x12, d12 = run(ev, mk, H12)
    res["rec_252"] = {k: summarize(x12, v) for k, v in {**SPLIT, **ERAS}.items()}
    res["rec_252_drop"] = d12
    q5_q1 = {k: (sp[k]["gross"] - sp[k]["q1"]) for k in sp}
    res["rec_q5_minus_q1"] = q5_q1
    mk2 = Market(C, TV, sic, drop_semi=True)
    xs2, _ = run(ev[~ev.ticker.map(lambda t: sic.get(t, "").startswith(SEMI))], mk2, H)
    res["rec_ex_semi"] = {k: summarize(xs2, v) for k, v in {**SPLIT, **ERAS}.items()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("events", "main_drop", "verdict", "split", "eras")}, ensure_ascii=False, indent=1, default=str))


def selftest():
    idx = pd.bdate_range("2016-01-01", periods=900)
    rng = np.random.default_rng(3)
    cols = [f"{i:06d}" for i in range(60)]
    C = pd.DataFrame(np.exp(np.cumsum(rng.normal(0, 0.01, (900, 60)), axis=0)), index=idx, columns=cols)
    TV = pd.DataFrame(5e9, index=idx, columns=cols)
    C.iloc[:, 0] *= np.linspace(1, 2, 900)                       # 000000 만 꾸준히 오른다
    C.iloc[300:, 1] = np.nan                                     # 000001 폐지 → 마지막 종가
    sic = {t: "26" for t in cols}
    sic["000059"] = "64"                                         # 금융 → 대조에서 빠짐
    mk = Market(C, TV, sic)
    g = mk.day(100, 126)
    assert "000059" not in g.index and len(g) == 59
    assert abs(g.loc["000001", "r"] - (C.iat[226, 1] / C.iat[100, 1] - 1)) < 1e-12        # 창 안에서는 그대로
    g2 = mk.day(250, 126)
    assert abs(g2.loc["000001", "r"] - (C.iat[299, 1] / C.iat[250, 1] - 1)) < 1e-12
    v, why = mk.excess("000000", idx[99].strftime("%Y%m%d"), 126)
    assert why is None and v[0] > 0                               # 다음 거래일(100) 진입, 자기 제외 대조보다 높음
    assert mk.excess("000000", idx[-10].strftime("%Y%m%d"), 126) == (None, "immature")
    # 분위 기준은 직전 회계연도
    cl = {}
    rev = {}
    avail = {}
    for i, t in enumerate(cols[:50]):
        for y in range(2015, 2019):
            cl[(t, y)] = 1e9 * (1 + (i if y == 2017 else 0) * 0.01) if y != 2016 else 1e9 * (1 + i * 0.02)
            rev[(t, y)] = 1e10
            avail[(t, y)] = f"{y + 1}0320"
    ev = events(cl, avail, rev, {t: "26" for t in cols})
    assert set(ev.fy) == {2017, 2018}                            # 2016 은 직전(2015) 사건 분포가 없어 기준 해로만 쓰인다
    assert abs(ev[ev.fy == 2017].q80.iloc[0] - np.quantile(np.arange(50) * 0.002, 0.8)) < 1e-12   # 2017 기준 = 2016 사건 dCL 80백분위
    # null: 같은 개수 무작위가 실제보다 크거나 같을 확률
    df_all = pd.DataFrame({"fy": [2017] * 100, "x": np.r_[np.full(20, 0.1), np.zeros(80)]})
    assert null_p(df_all, df_all.iloc[:20]) < 0.01
    sp = {k: {"gross": 0.02, "p": 0.01, "net": 0.01} for k in SPLIT}
    assert verdict(sp) == "ECONOMIC"
    sp["TEST"]["gross"] = -0.01
    assert verdict(sp) == "REJECT"
    sp = {k: {"gross": 0.02, "p": 0.3, "net": 0.01} for k in SPLIT}
    assert verdict(sp) == "INCONCLUSIVE"
    print("selftest OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
