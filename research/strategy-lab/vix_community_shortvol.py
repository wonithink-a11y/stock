"""커뮤니티 숏 변동성 타이밍(콘탱고·VRP) → 인버스 VIX 상품 — 사전등록 vix-community-shortvol-preregistration-2026-11.md 그대로.

    python research/strategy-lab/vix_community_shortvol.py

C1 콘탱고(5일평균 VIX/VIX3M < 1) · C2 VRP(5일평균 VIX − SPX HV10 > 0) → 인버스 −0.5x 보유, 아니면 현금.
판정 = OOS 2013-05-01~2026-10-30 순열 p ≤ 0.025 → INFORMATION → ECONOMIC → ROBUST. 나머지는 기록 전용.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import vix_level_product_era as V

END = "2026-10-30"
V.END = END                      # 앞 연구의 다운로드·합성 함수를 이 끝 날짜로 그대로 쓴다
ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "findings/vix-community-shortvol-results.json"
OUT_MD = ROOT / "findings/vix-community-shortvol-results-2026-11.md"
SEED, BOOT, P_MAX, COST = 20261104, 4000, 0.025, V.COST_US
OOS = ("2013-05-01", END)
SUB = {"P1": ("2013-05-01", "2018-12-31"), "P2": ("2019-01-01", "2022-12-31"), "P3": ("2023-01-01", END)}
ERAS = {"2016~23": ("2016-01-01", "2023-12-31"), "2024": ("2024-01-01", "2024-12-31"), "2025~": ("2025-01-01", END)}
PRE = ("2011-01-04", "2013-04-30")


def signals(idx, vix, v3, spx):
    v = vix.reindex(idx).ffill()
    r = (vix / v3).reindex(idx).ffill()
    hv = np.log(spx).diff().rolling(10).std() * np.sqrt(252) * 100
    d = (vix - hv.reindex(vix.index).ffill()).reindex(idx).ffill()
    c1 = (r.rolling(5).mean() < 1).astype(float).fillna(0).to_numpy()
    c2 = (d.rolling(5).mean() > 0).astype(float).fillna(0).to_numpy()
    b = V.state(v.to_numpy(), 20, 16, "B")
    return {"C1": c1, "C2": c2, "C1∧C2": c1 * c2, "B20/16": b}


def hold_r(g):
    return ((1 + g["gon"]) * (1 + g["gid"]) - 1).to_numpy()[1:]


def block_ci(a, b, rng, blk=21):
    n, out = len(a), np.empty(BOOT)
    sh = lambda x: x.mean() / x.std(ddof=1) * np.sqrt(252)
    for i in range(BOOT):
        j = ((rng.integers(0, n - blk, int(np.ceil(n / blk)))[:, None]) + np.arange(blk)).ravel()[:n]
        out[i] = sh(a[j]) - sh(b[j])
    return float(np.quantile(out, .025)), float(np.quantile(out, .975))


def evaluate(g, T, rng, judge=True):
    r, T1, T2 = V.ret(g, T, COST)
    r0, _, _ = V.ret(g, T, 0.0)
    h = hold_r(g)
    idx = g.index[1:]
    sw = np.abs(T1 - T2)
    out = {}
    for nm, w in {"OOS": OOS, **SUB, **ERAS, "PRE": PRE}.items():
        mk = V.sl(idx, *w)
        if mk.sum() < 20:
            continue
        s, hs = V.stats(r[mk], int((T1 - T2)[mk].clip(0).sum())), V.stats(h[mk])
        s["gross_total"] = V.stats(r0[mk])["total"]
        s["exposure"] = float(T1[mk].mean())
        s["switches"] = int((sw[mk] > 0).sum())
        yrs = mk.sum() / 252
        s["cagr"] = float((1 + s["total"]) ** (1 / yrs) - 1)
        hs["cagr"] = float((1 + hs["total"]) ** (1 / yrs) - 1)
        # 손익분기: 비용 전 초과 로그수익(보유 대비 아님, 현금 대비) 을 전환당으로
        gl = float(np.log1p(r0[mk]).sum())
        s["breakeven_bp_per_switch"] = float(gl / max(sw[mk].sum(), 1) * 1e4) if sw[mk].sum() else None
        out[nm] = dict(rule=s, hold=hs)
    if judge:
        mk = V.sl(idx, *OOS)
        out["perm_p"] = V.perm_p(g, T1, T2, mk, COST, rng, out["OOS"]["rule"]["sharpe"])
        out["dsharpe_ci"] = block_ci(r[mk], h[mk], rng)
    return out


def verdict(o):
    if o["perm_p"] > P_MAX:
        return "REJECT"
    R, H = o["OOS"]["rule"], o["OOS"]["hold"]
    eco = R["sharpe"] > H["sharpe"] and all(o[p]["rule"]["sharpe"] >= o[p]["hold"]["sharpe"] for p in SUB) and R["mdd"] > H["mdd"]
    if not eco:
        return "INFORMATION"
    rob = o["dsharpe_ci"][0] > 0 and o["2025~"]["rule"]["sharpe"] >= o["2025~"]["hold"]["sharpe"]
    return "ROBUST" if rob else "ECONOMIC"


def long_switch(g_inv, g_long, T):
    """신호 1 = 인버스, 0 = 롱 상품(Cooper 원형). 비용은 두 다리 각각 전환."""
    ri, a1, a2 = V.ret(g_inv, T, COST)
    rl, b1, b2 = V.ret(g_long.reindex(g_inv.index).fillna(0.0), 1 - T, COST)
    return ri + rl


def main():
    rng = np.random.default_rng(SEED)
    us = V.us_frames()
    vix = V.dl("^VIX", "2007-01-01", False)["Close"].dropna()
    v3 = V.dl("^VIX3M", "2007-01-01", False)["Close"].dropna()
    spx = us["spx"]
    g = us["inv"]
    sig = signals(g.index, vix, v3, spx)
    res = dict(end=END, data_last={k: str(s.index[-1].date()) for k, s in {"VIX": vix, "VIX3M": v3, "SPX": spx, "INV": g}.items()}, check_synth=us["check"], cells={}, record={})
    for c in ("C1", "C2"):
        o = evaluate(g, sig[c], rng)
        o["verdict"] = verdict(o)
        res["cells"][c] = o
    for c in ("C1∧C2", "B20/16"):
        res["record"][c] = evaluate(g, sig[c], rng, judge=False)
    # SVIX(−1x) · UVIX(+2x) · VIXY 롱 전환형
    sv = V.dl("SVIX", "2022-03-01")[["Open", "Close"]].dropna()
    uv = V.dl("UVIX", "2022-03-01")[["Open", "Close"]].dropna()
    gsv, guv = V.bars(sv.Open, sv.Close, sv.index), V.bars(uv.Open, uv.Close, uv.index)
    s2 = signals(gsv.index, vix, v3, spx)
    res["record"]["SVIX"] = {c: evaluate(gsv, s2[c], rng, judge=False) for c in ("C1", "C2", "B20/16")}
    for nm, gl in (("VIXY", us["long"]), ("UVIX", guv)):
        base = g if nm == "VIXY" else gsv
        ss = sig if nm == "VIXY" else s2
        res["record"][f"switch_{nm}"] = {}
        for c in ("C1", "C2"):
            r = long_switch(base, gl, ss[c])
            idx = base.index[1:]
            res["record"][f"switch_{nm}"][c] = {w: V.stats(r[V.sl(idx, *rng_)]) for w, rng_ in {"OOS": OOS, **SUB, **ERAS}.items() if V.sl(idx, *rng_).sum() >= 20}
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(json.dumps({c: dict(verdict=o["verdict"], p=o["perm_p"], ci=o["dsharpe_ci"], rule=o["OOS"]["rule"], hold=o["OOS"]["hold"]) for c, o in res["cells"].items()}, ensure_ascii=False, indent=1, default=float))
    print("data_last", res["data_last"])


if __name__ == "__main__":
    main()
