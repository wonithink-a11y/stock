#!/usr/bin/env python3
"""바이낸스 신규 상장(BL7) 꼬리 위험 조건 — 사전등록 findings/binance-listing-tail-preregistration-2026-11.md (판정 §4 그대로).

    python research/strategy-lab/futures/binance_listing_tail.py --collect   # 월봉 일봉(data.binance.vision)·BTC 일봉(공개 시세 API) → data/crypto/listing/
    python research/strategy-lab/futures/binance_listing_tail.py             # 판정 → binance-listing-tail.json
    python research/strategy-lab/futures/binance_listing_tail.py --selftest
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binance_listing as bl  # noqa: E402  사건 정의(BL7 동결본)

D = pd.Timedelta(days=1)
H, TAIL, BIG = 7, 3000.0, 10000.0
END = pd.Timestamp("2026-10-01", tz="UTC")
SEED, BOOT = 20261108, 2000
BTC_F = bl.DATA / "_btc_daily.parquet"
COND_NAMES = ["#1 첫날 하락·보합", "#2 첫날 소폭 상승", "#3 첫날 급등(≥+50%)", "#4 첫날 폭등(≥+100%)", "#5 BTC 7일 ≥+10%", "#6 BTC 7일 ≤−10%", "#7 BTC 200일선 위", "#8 BTC 200일선 아래",
              "#9 동시 상장 쏠림(≥3)", "#10 급등∧BTC 급등", "#11 급등∧쏠림", "#12 하락·보합∧BTC 200일선 아래"]


def collect():
    import requests
    bl.collect()
    rows, t = [], int(pd.Timestamp("2017-08-01", tz="UTC").timestamp() * 1000)
    while True:
        r = requests.get("https://api.binance.com/api/v3/klines", params=dict(symbol="BTCUSDT", interval="1d", startTime=t, limit=1000), timeout=30)
        r.raise_for_status()
        k = r.json()
        if not k:
            break
        rows += k
        t = k[-1][0] + 86_400_000
        if len(k) < 1000:
            break
    d = pd.DataFrame(rows).iloc[:, :2]
    d.columns = ["t", "open"]
    d.index = pd.to_datetime(d["t"], unit="ms", utc=True)
    d[["open"]].astype(float).to_parquet(BTC_F)
    print("BTC 일봉", len(d))


def build_events():
    months = json.loads((bl.DATA / "months.json").read_text(encoding="utf-8"))
    ev = bl.events_table(months)
    btc = pd.read_parquet(BTC_F)["open"].astype(float)
    sma200 = btc.rolling(200).mean()
    prices = {}
    for r in ev:
        f = bl.DATA / f"{r['sym']}.parquet"
        if f.exists():
            d = pd.read_parquet(f)
            if len(d):
                prices[r["sym"]] = d["open"].astype(float).dropna()
    Ls = {s: p.index[0] for s, p in prices.items()}
    rows = []
    for s, p in prices.items():
        L = Ls[s]
        t0 = L + D
        p0, p1, b0, b1 = p.get(t0, np.nan), p.get(t0 + H * D, np.nan), btc.get(t0, np.nan), btc.get(t0 + H * D, np.nan)
        if not (np.isfinite(p0) and np.isfinite(p1) and np.isfinite(b0) and np.isfinite(b1)) or t0 + H * D >= END:
            continue
        rel = ((p1 / p0 - 1) - (b1 / b0 - 1)) * 1e4
        path = []
        for k in range(1, H + 1):
            pk, bk = p.get(t0 + k * D, np.nan), btc.get(t0 + k * D, np.nan)
            if np.isfinite(pk) and np.isfinite(bk):
                path.append(((pk / p0 - 1) - (bk / b0 - 1)) * 1e4)
        b7 = btc.get(t0 - 7 * D, np.nan)
        sm = sma200.get(t0, np.nan)
        crowd = sum(1 for s2, L2 in Ls.items() if s2 != s and L - 2 * D <= L2 <= L)
        rows.append(dict(sym=s, L=L, rel=rel, day1=(p0 / p.iloc[0] - 1) * 1e4, btc7=(b0 / b7 - 1) if np.isfinite(b7) else np.nan,
                         above=(b0 > sm) if np.isfinite(sm) else np.nan, crowd=crowd, touch=bool(path and max(path) >= TAIL)))
    return pd.DataFrame(rows).sort_values("L").reset_index(drop=True)


def conditions(o: pd.DataFrame) -> list[np.ndarray]:
    d1, b7, ab, cr = o["day1"].to_numpy(), o["btc7"].to_numpy(), o["above"].to_numpy(dtype=float), o["crowd"].to_numpy()
    f = lambda m: np.asarray(m, dtype=bool)
    c3, c5, c9, c1, c8 = f(d1 >= 5000), f(b7 >= 0.10), f(cr >= 3), f(d1 <= 0), f(ab == 0)
    return [c1, f((d1 > 0) & (d1 < 5000)), c3, f(d1 >= 10000), c5, f(b7 <= -0.10), f(ab == 1), c8, c9, c3 & c5, c3 & c9, c1 & c8]


def period(L):
    y = L.year
    return "TRAIN" if y <= 2022 else ("VALID" if y == 2023 else "TEST")


def fisher_p(a, b, c, d):
    from scipy.stats import fisher_exact
    return float(fisher_exact([[a, b], [c, d]])[1])


def bh(p):
    p = np.asarray(p, float)
    n = len(p)
    order = np.argsort(p)
    adj = np.empty(n)
    prev = 1.0
    for rank, i in zip(range(n, 0, -1), order[::-1]):
        prev = min(prev, p[i] * n / rank)
        adj[i] = prev
    return adj


def cluster_ids(L):
    cid, last, c = [], None, -1
    for t in L:
        if last is None or (t - last).days > 7:
            c += 1
        cid.append(c)
        last = t
    return np.array(cid)


def boot_diff(tail, cond, cid, rng):
    n_cl = cid.max() + 1
    members = [np.where(cid == c)[0] for c in range(n_cl)]
    out = []
    for _ in range(BOOT):
        pick = rng.integers(0, n_cl, n_cl)
        idx = np.concatenate([members[c] for c in pick])
        t, c = tail[idx], cond[idx]
        if c.sum() == 0 or (~c).sum() == 0:
            continue
        out.append(t[c].mean() - t[~c].mean())
    return [round(float(x), 4) for x in np.percentile(out, [2.5, 97.5])]


def judge(o):
    tail = (o["rel"] >= TAIL).to_numpy()
    big = (o["rel"] >= BIG).to_numpy()
    per = np.array([period(L) for L in o["L"]])
    cid = cluster_ids(o["L"])
    rng = np.random.default_rng(SEED)
    conds = conditions(o)
    rows = []
    for name, c in zip(COND_NAMES, conds):
        n = int(c.sum())
        if n < 20 or (~c).sum() < 20:
            rows.append(dict(cond=name, n=n, skipped=True))
            continue
        a, b, cc, dd = int(tail[c].sum()), int((~tail[c]).sum()), int(tail[~c].sum()), int((~tail[~c]).sum())
        diff = tail[c].mean() - tail[~c].mean()
        r = dict(cond=name, n=n, tail_rate=round(float(tail[c].mean()), 4), tail_rate_out=round(float(tail[~c].mean()), 4), diff=round(float(diff), 4),
                 p=fisher_p(a, b, cc, dd), ci95=boot_diff(tail, c, cid, rng), big_rate=round(float(big[c].mean()), 4), touch_rate=round(float(o["touch"].to_numpy()[c].mean()), 4),
                 mean_rel_bp=round(float(o["rel"].to_numpy()[c].mean()), 0), mean_rel_out_bp=round(float(o["rel"].to_numpy()[~c].mean()), 0))
        pd_ = {}
        for p in ("TRAIN", "VALID", "TEST"):
            m = per == p
            if (c & m).sum() >= 10 and (~c & m).sum() >= 10:
                pd_[p] = round(float(tail[c & m].mean() - tail[~c & m].mean()), 4)
        vt = np.isin(per, ["VALID", "TEST"])
        r["period_diff"] = pd_
        r["valid_test_diff"] = round(float(tail[c & vt].mean() - tail[~c & vt].mean()), 4) if (c & vt).sum() >= 10 and (~c & vt).sum() >= 10 else None
        rows.append(r)
    ok = [r for r in rows if not r.get("skipped")]
    adj = bh([r["p"] for r in ok])
    for r, a_ in zip(ok, adj):
        r["p_bh"] = round(float(a_), 4)
        sg = np.sign(r["diff"])
        signs = [np.sign(v) for v in r["period_diff"].values()]
        r["pass"] = bool(r["p_bh"] <= 0.05 and (r["ci95"][0] > 0 or r["ci95"][1] < 0) and signs and all(s == sg for s in signs) and r["valid_test_diff"] is not None and np.sign(r["valid_test_diff"]) == sg)
    n_bh = sum(1 for r in ok if r["p_bh"] <= 0.05)
    verdict = "INFORMATION" if any(r["pass"] for r in ok) else ("INCONCLUSIVE" if n_bh else "REJECT")
    return dict(events=len(o), tail_total=int(tail.sum()), tail_rate_all=round(float(tail.mean()), 4), big_total=int(big.sum()), K=len(ok), BH통과=n_bh, 판정=verdict,
                by_period={p: dict(n=int((per == p).sum()), tail=int(tail[per == p].sum())) for p in ("TRAIN", "VALID", "TEST")}, rows=rows)


def selftest():
    o = pd.DataFrame(dict(L=pd.date_range("2018-03-01", periods=6, tz="UTC", freq="10D"), day1=[-1, 6000, 12000, 100, 5001, 0], btc7=[0.2, -0.2, 0, 0, 0, 0], above=[1, 0, 1, np.nan, 1, 0], crowd=[0, 3, 0, 0, 0, 1]))
    cs = conditions(o)
    assert cs[0].tolist() == [True, False, False, False, False, True] and cs[2].tolist() == [False, True, True, False, True, False] and cs[3].tolist() == [False, False, True, False, False, False]
    assert list(bh([0.01, 0.04, 0.5]).round(3)) == [0.03, 0.06, 0.5]
    assert cluster_ids(o["L"]).tolist() == [0, 1, 2, 3, 4, 5]
    print("OK")


def main():
    if "--selftest" in sys.argv:
        return selftest()
    if "--collect" in sys.argv:
        return collect()
    o = build_events()
    res = judge(o)
    (HERE / "binance-listing-tail.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(f"사건 {res['events']} · 꼬리 {res['tail_total']}({res['tail_rate_all']:.1%}) · 큰 꼬리 {res['big_total']} · 기간 {res['by_period']}")
    print(f"K={res['K']} · BH 통과 {res['BH통과']} · 판정 {res['판정']}")
    for r in res["rows"]:
        if r.get("skipped"):
            print(f"{r['cond']:28s} n={r['n']} (20건 미만·생략)")
        else:
            print(f"{r['cond']:28s} n={r['n']:3d} 꼬리 {r['tail_rate']:.1%} vs {r['tail_rate_out']:.1%} Δ{r['diff']:+.1%} p_bh {r['p_bh']:.3f} CI {r['ci95']} 기간 {r['period_diff']} V+T {r['valid_test_diff']} {'★' if r['pass'] else ''}")


if __name__ == "__main__":
    main()
