"""VIX · 공탐지수 · RSI 조합 규칙 16셀 + 진단 — 사전등록 vix-fng-rsi-combo-preregistration-2026-11.md 를 그대로 실행.

    python research/strategy-lab/vix_fng_rsi_combo.py

단독 6셀도 같은 함수로 다시 돌려(반복 4,000회·α 0.05/22) 조합과 나란히 낸다. 문턱·조합·판정 기준은 사전등록에서 고정.
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import vix_fng_rsi_timing as m  # noqa: E402

warnings.filterwarnings("ignore")
m.BOOT, m.ALPHA = 4000, 0.05 / 22
OUT_JSON = ROOT / "findings/vix-fng-rsi-combo-results.json"
ZONES = {"VIX": ("vix", lambda v: v <= 14, lambda v: v >= 20),
         "공탐": ("fg", lambda v: v >= 80, lambda v: v <= 20),
         "RSI": ("rsi", lambda v: v >= 80, lambda v: v <= 30)}
COMBOS = {"C1 VIX+공탐": ["VIX", "공탐"], "C2 VIX+RSI": ["VIX", "RSI"], "C3 공탐+RSI": ["공탐", "RSI"], "C4 VIX+공탐+RSI": ["VIX", "공탐", "RSI"]}
FWD = {"D": 20, "W": 4}


def zone_arrays(f, names):
    out = []
    for n in names:
        col, sell, buy = ZONES[n]
        x = f[col].to_numpy()
        ok = ~np.isnan(x)
        out.append((np.where(ok, [bool(sell(v)) for v in x], False), np.where(ok, [bool(buy(v)) for v in x], False)))
    return out


def combo_state(zl, mode):
    S, B = np.array([z[0] for z in zl]), np.array([z[1] for z in zl])
    if mode == "ALL":
        sell, buy = S.all(0), B.all(0)
    else:
        a, b = S.any(0), B.any(0)
        sell, buy = a & ~b, b & ~a
    s, cur = np.ones(S.shape[1]), 1.0
    for i in range(1, S.shape[1]):
        if sell[i]:
            cur = 0.0
        elif buy[i]:
            cur = 1.0
        s[i] = cur
    return s


def runs(mask):
    i, out = 0, []
    while i < len(mask):
        if mask[i]:
            j = i
            while j + 1 < len(mask) and mask[j + 1]:
                j += 1
            out.append((i, j))
            i = j + 1
        else:
            i += 1
    return out


def cell(f, T, ppy, blk, rng, tf):
    O, C = f["O"].to_numpy(), f["C"].to_numpy()
    r, T1 = m.returns(O, C, T)
    rb = C[1:] / C[:-1] - 1
    idx = f.index[1:]
    mr, mb = m.metrics(r, idx, ppy), m.metrics(rb, idx, ppy)
    bt = m.boot_dsharpe(r, rb, blk, ppy, rng)
    n, yrs = len(T) - 1, (idx[-1] - idx[0]).days / 365.25
    nsh, ncg = np.empty(m.BOOT), np.empty(m.BOOT)
    for b in range(m.BOOT):
        k = int(rng.integers(21, n - 21))
        rr, _ = m.returns(O, C, np.r_[1.0, np.roll(T[1:], k)])
        nsh[b], ncg[b] = rr.mean() / rr.std(ddof=1) * np.sqrt(ppy), np.prod(1 + rr) ** (1 / yrs) - 1
    p = (int((nsh >= mr["sharpe"]).sum()) + 1) / (m.BOOT + 1)
    dsh = mr["sharpe"] - mb["sharpe"]
    lo, hi = np.quantile(bt, m.ALPHA / 2), np.quantile(bt, 1 - m.ALPHA / 2)
    ser = pd.DataFrame({"r": r, "b": rb, "pos": T1}, index=idx)
    yr = ser.groupby(ser.index.year).agg(r=("r", lambda x: (1 + x).prod() - 1), b=("b", lambda x: (1 + x).prod() - 1), pos=("pos", "mean"))
    eras = {nm: dict(rule=(1 + s.r).prod() - 1, hold=(1 + s.b).prod() - 1, inmkt=s.pos.mean())
            for nm, a, z in m.ERAS for s in [ser[(ser.index.year >= a) & (ser.index.year <= z)]]}
    # 진단
    inm, cash = T1 == 1, T1 == 0
    d = dict(in_ann=float(rb[inm].mean() * ppy), cash_ann=float(rb[cash].mean() * ppy) if cash.any() else None, cash_bars=int(cash.sum()))
    if cash.sum() > 2 and inm.sum() > 2:
        d["welch_t"] = float((rb[inm].mean() - rb[cash].mean()) / np.sqrt(rb[inm].var(ddof=1) / inm.sum() + rb[cash].var(ddof=1) / cash.sum()))
    ep = [float(np.prod(1 + rb[a:b + 1]) - 1) for a, b in runs(cash)]
    d["cash_ep"] = dict(n=len(ep), mean=float(np.mean(ep)) if ep else None, median=float(np.median(ep)) if ep else None,
                        pct_neg=float(np.mean([e < 0 for e in ep])) if ep else None,
                        avoided=float(-sum(e for e in ep if e < 0)), missed=float(sum(e for e in ep if e > 0)),
                        growth=float(np.prod([1 + e for e in ep])) if ep else 1.0)
    d["inmkt_growth"] = float(np.prod([1 + np.prod(1 + rb[a:b + 1]) - 1 for a, b in runs(inm)]))
    d["null"] = dict(sharpe_mean=float(nsh.mean()), p5=float(np.quantile(nsh, .05)), p95=float(np.quantile(nsh, .95)),
                     rank=float((nsh < mr["sharpe"]).mean()), cagr_mean=float(ncg.mean()))
    H = FWD[tf]
    ev = {"sell": [i for i in range(1, len(T)) if T[i] == 0 and T[i - 1] == 1], "buy": [i for i in range(1, len(T)) if T[i] == 1 and T[i - 1] == 0]}
    fwd = lambda i: C[i + H] / O[i + 1] - 1
    allf = [fwd(i) for i in range(len(T) - H - 1)]
    d["signal"] = dict(H=H, uncond=float(np.mean(allf)),
                       **{k: dict(n=len(v), mean=float(np.mean([fwd(i) for i in v if i + H < len(T)])) if any(i + H < len(T) for i in v) else None) for k, v in ev.items()})
    d["cost_bp_yr"] = float(np.abs(np.diff(T)).sum() * m.COST * 1e4 / yrs)
    return dict(rule=mr, hold=mb, dsharpe=dsh, ci=[lo, hi], p=p, inmkt=float(T1.mean()), trades=int(np.abs(np.diff(T)).sum()),
                verdict=m.verdict(p, lo, dsh, mr["cagr"], mb["cagr"]),
                years={int(y): dict(rule=v.r, hold=v.b, inmkt=v.pos) for y, v in yr.iterrows()}, eras=eras, diag=d)


def main():
    frames = m.build_frames()
    rng = np.random.default_rng(m.SEED)
    res = {}
    for tf, p in m.FRAMES.items():
        f = m.window(frames[tf])
        for nm, (col, sell, buy) in m.RULES.items():
            res[f"{nm}|{tf}"] = cell(f, m.state(f[col].to_numpy(), sell, buy), p["ppy"], p["blk"], rng, tf)
        for cn, members in COMBOS.items():
            zl = zone_arrays(f, members)
            for mode, mk in (("ALL", "합의"), ("ANY", "하나라도")):
                res[f"{cn} {mk}|{tf}"] = cell(f, combo_state(zl, mode), p["ppy"], p["blk"], rng, tf)
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    pc = lambda x: f"{x * 100:+.1f}%"
    print("## 판정 (α 0.05/22 = 0.00227)")
    print("| 셀 | 판정 | CAGR 규칙/보유 | 샤프 규칙/보유 | ΔSharpe [99.77% CI] | 타이밍 p | MDD 규칙/보유 | 체류 | 전환 | 초과 양 연수 |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for k, v in res.items():
        print(f"| {k} | **{v['verdict']}** | {pc(v['rule']['cagr'])}/{pc(v['hold']['cagr'])} | {v['rule']['sharpe']:.2f}/{v['hold']['sharpe']:.2f} | "
              f"{v['dsharpe']:+.2f} [{v['ci'][0]:+.2f}, {v['ci'][1]:+.2f}] | {v['p']:.4f} | {pc(v['rule']['mdd'])}/{pc(v['hold']['mdd'])} | {v['inmkt']*100:.0f}% | {v['trades']} | "
              f"{sum(1 for x in v['years'].values() if x['rule'] > x['hold'] + 1e-9)}/{len(v['years'])} |")
    print("\n## 진단: 시장이 쉬는 동안 어땠나")
    print("| 셀 | 시장 연수익: 체류봉 / 현금봉 (차이 t) | 현금 에피소드 n · 평균 · 중앙값 · 하락비율 | 피한 손실 합 vs 놓친 이익 합 | 현금 동안 시장 성장 ×배 / 체류 동안 ×배 | 널 샤프 평균 [5%,95%] · 규칙 순위 | 널 CAGR 평균 | 매도 후/매수 후 시장(기간수익) vs 무조건 | 비용 bp/년 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for k, v in res.items():
        d = v["diag"]
        ce = d["cash_ep"]
        cash = pc(d["cash_ann"]) if d["cash_ann"] is not None else "-"
        sg = d["signal"]
        f1 = lambda x: "-" if x is None else pc(x)
        print(f"| {k} | {pc(d['in_ann'])} / {cash} ({d.get('welch_t', float('nan')):+.1f}) | {ce['n']} · {f1(ce['mean'])} · {f1(ce['median'])} · {f1(ce['pct_neg'])} | "
              f"{ce['avoided']*100:.0f}%p vs {ce['missed']*100:.0f}%p | ×{ce['growth']:.2f} / ×{d['inmkt_growth']:.2f} | "
              f"{d['null']['sharpe_mean']:.2f} [{d['null']['p5']:.2f},{d['null']['p95']:.2f}] · {d['null']['rank']*100:.0f}% | {pc(d['null']['cagr_mean'])} | "
              f"{f1(sg['sell']['mean'])}(n{sg['sell']['n']}) / {f1(sg['buy']['mean'])}(n{sg['buy']['n']}) vs {pc(sg['uncond'])} ({sg['H']}봉) | {d['cost_bp_yr']:.1f} |")
    print("\n## 시기별 초과(규칙−보유, %p)")
    print("| 셀 | " + " | ".join(n for n, _, _ in m.ERAS) + " |\n|---|" + "---|" * len(m.ERAS))
    for k, v in res.items():
        print(f"| {k} | " + " | ".join(f"{(e['rule']-e['hold'])*100:+.0f} ({e['inmkt']*100:.0f}%)" for e in v["eras"].values()) + " |")
    print("\n## 연도별 초과(규칙−보유, %p)")
    ys = list(next(iter(res.values()))["years"])
    print("| 셀 | " + " | ".join(str(y) for y in ys) + " |\n|---|" + "---|" * len(ys))
    for k, v in res.items():
        print(f"| {k} | " + " | ".join(f"{(v['years'][y]['rule']-v['years'][y]['hold'])*100:+.0f}" for y in ys) + " |")


if __name__ == "__main__":
    sys.exit(main())
