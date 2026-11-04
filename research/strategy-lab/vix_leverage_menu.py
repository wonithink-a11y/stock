"""VIX 상품 배율 메뉴(+2·+1·−0.5·−1) 최적 조합 — 사전등록 vix-leverage-menu-preregistration-2026-11.md 그대로.

    python research/strategy-lab/vix_leverage_menu.py

신호 4종(상시·B20/16·C1·C2) × 켜짐/꺼짐 배율 → 64셀. TRAIN 에서 O1(샤프)·O2(MDD ≥ −50% 중 연복리) 로 고르고 VALID·TEST 로 판정.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

import vix_community_shortvol as CS   # V.END = 2026-10-30 설정 포함
from vix_community_shortvol import V

END = CS.END
ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "findings/vix-leverage-menu-results.json"
SEED, BOOT, P_MAX, COST = 20261104, 4000, 0.025, V.COST_US
START = "2011-10-04"
SPLITS = {"TRAIN": (START, "2018-12-31"), "VALID": ("2019-01-01", "2022-12-31"), "TEST": ("2023-01-01", END)}
EXTRA = {"2016~23": ("2016-01-01", "2023-12-31"), "2024": ("2024-01-01", "2024-12-31"), "2025~": ("2025-01-01", END), "REAL2022~": ("2022-03-30", END)}
KS = (2.0, 1.0, 0.0, -0.5, -1.0)
CUT1, CUT2 = pd.Timestamp("2018-02-28"), pd.Timestamp("2022-03-30")
ER = {2.0: 0.0165, -0.5: 0.0095, -1.0: 0.0095}


def real(sym, start="2011-01-01"):
    x = V.dl(sym, start)[["Open", "Close"]].dropna()
    return V.bars(x.Open, x.Close, x.index)


def synth(gy, k):
    rday = (1 + gy.gon) * (1 + gy.gid) - 1
    gon = k * gy.gon
    day = k * (rday + 0.0085 / 252) - ER[k] / 252
    return pd.DataFrame({"gon": gon, "gid": (1 + day) / (1 + gon) - 1}, index=gy.index)


def splice(idx, parts):
    """parts = [(frame, from, to_exclusive)] → idx 위 한 계열."""
    out = pd.DataFrame(0.0, index=idx, columns=["gon", "gid"])
    for f, a, b in parts:
        mk = (idx >= a) & (idx < b)
        out.loc[mk] = f.reindex(idx[mk]).fillna(0.0).to_numpy()
    return out


def products():
    gy = real("VIXY")
    idx = gy.index[(gy.index >= pd.Timestamp(START)) & (gy.index <= pd.Timestamp(END))]
    lo, hi = pd.Timestamp(START), pd.Timestamp(END) + pd.Timedelta(days=1)
    uvxy, svxy, uvix, svix = real("UVXY"), real("SVXY"), real("UVIX", "2022-03-01"), real("SVIX", "2022-03-01")
    return idx, {
        2.0: splice(idx, [(uvxy, lo, CUT1), (synth(gy, 2.0), CUT1, CUT2), (uvix, CUT2, hi)]),
        1.0: splice(idx, [(gy, lo, hi)]),
        -0.5: splice(idx, [(synth(gy, -0.5), lo, CUT1), (svxy, CUT1, hi)]),
        -1.0: splice(idx, [(svxy, lo, CUT1), (synth(gy, -1.0), CUT1, CUT2), (svix, CUT2, hi)]),
    }


def legs(P, K):
    """K[t] = 봉 t 종가 뒤 배율 → 하루 수익과 다리별 (T1,T2)."""
    r, TT = 0.0, {}
    for k, g in P.items():
        rk, T1, T2 = V.ret(g, (K == k).astype(float), COST)
        r = r + rk
        TT[k] = (T1, T2)
    return r, TT


def perm(P, TT, mk, sh_obs, rng):
    gs = {k: (g["gon"].to_numpy()[1:][mk], g["gid"].to_numpy()[1:][mk]) for k, g in P.items()}
    n, hit = int(mk.sum()), 0
    for _ in range(BOOT):
        s = int(rng.integers(21, n - 21))
        r = 0.0
        for k, (gon, gid) in gs.items():
            a, b = np.roll(TT[k][0][mk], s), np.roll(TT[k][1][mk], s)
            r = r + (1 + b * gon) * (1 + a * gid) - 1 - COST * np.abs(a - b)
        hit += r.mean() / r.std(ddof=1) * np.sqrt(252) >= sh_obs
    return (hit + 1) / (BOOT + 1)


def wstats(r, idx):
    out = {}
    for nm, w in {**SPLITS, **EXTRA}.items():
        mk = V.sl(idx, *w)
        s = V.stats(r[mk])
        s["cagr"] = float((1 + s["total"]) ** (252 / mk.sum()) - 1)
        out[nm] = s
    return out


def pick(cells, obj, keys):
    ok = [c for c in keys if obj != "O2" or cells[c]["TRAIN"]["mdd"] >= -0.5]
    if not ok:
        return None
    m = "sharpe" if obj == "O1" else "cagr"
    return max(ok, key=lambda c: cells[c]["TRAIN"][m])


def beats(a, b, obj, w):
    if obj == "O1":
        return a[w]["sharpe"] > b[w]["sharpe"]
    return a[w]["cagr"] > b[w]["cagr"] and a[w]["mdd"] >= -0.5


def main():
    rng = np.random.default_rng(SEED)
    idx, P = products()
    vix = V.dl("^VIX", "2007-01-01", False)["Close"].dropna()
    v3 = V.dl("^VIX3M", "2007-01-01", False)["Close"].dropna()
    spx = V.dl("^GSPC", "2007-01-01", False)["Close"].dropna()
    sig = CS.signals(idx, vix, v3, spx)
    sig = {"S0": np.ones(len(idx)), "B": sig["B20/16"], "C1": sig["C1"], "C2": sig["C2"]}
    cells, raw = {}, {}
    for s, x in sig.items():
        pairs = [(k, k) for k in KS if k != 0] if s == "S0" else [(a, b) for a in KS for b in KS if a != b]
        for a, b in pairs:
            K = np.where(x == 1, a, b)
            r, TT = legs(P, K)
            nm = f"{s}:{a:+g}/{b:+g}" if s != "S0" else f"S0:{a:+g}"
            cells[nm] = wstats(r, idx[1:])
            cells[nm]["exposure"] = {f"{k:+g}": float((K[:-1] == k).mean()) for k in KS}
            raw[nm] = (r, TT)
    static = [c for c in cells if c.startswith("S0")]
    df = pd.DataFrame({c: {f"{w}_sharpe": cells[c][w]["sharpe"] for w in SPLITS} for c in cells}).T
    res = dict(end=END, n_cells=len(cells), spearman=dict(VALID=float(df.TRAIN_sharpe.corr(df.VALID_sharpe, method="spearman")),
                                                      TEST=float(df.TRAIN_sharpe.corr(df.TEST_sharpe, method="spearman"))),
               hindsight={w: max(cells, key=lambda c: cells[c][w]["sharpe"]) for w in SPLITS}, objectives={}, cells=cells)
    for obj in ("O1", "O2"):
        sel, bench = pick(cells, obj, list(cells)), pick(cells, obj, static)
        o = dict(selected=sel, benchmark=bench)
        if sel is None:
            o["verdict"] = "해당 없음"
        elif sel.startswith("S0"):
            o["verdict"] = "NO-TIMING"
        else:
            S, Bm = cells[sel], cells[bench]
            mk = V.sl(idx[1:], *SPLITS["TEST"])
            o["perm_p"] = perm(P, raw[sel][1], mk, S["TEST"]["sharpe"], rng)
            if S["VALID"]["sharpe"] <= 0 or S["TEST"]["sharpe"] <= 0 or o["perm_p"] > P_MAX:
                o["verdict"] = "REJECT"
            elif beats(S, Bm, obj, "VALID") and beats(S, Bm, obj, "TEST"):
                o["verdict"] = "ECONOMIC"
            else:
                o["verdict"] = "INFORMATION"
        res["objectives"][obj] = o
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    for obj, o in res["objectives"].items():
        print(obj, o)
        for c in (o["selected"], o["benchmark"]):
            if c:
                print("  ", c, {w: (round(cells[c][w]["total"], 3), round(cells[c][w]["cagr"], 3), round(cells[c][w]["sharpe"], 2), round(cells[c][w]["mdd"], 3)) for w in (*SPLITS, *EXTRA)})
    print("spearman", res["spearman"], "hindsight", res["hindsight"])


if __name__ == "__main__":
    main()
