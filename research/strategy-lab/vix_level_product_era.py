"""VIX 수준 롱/인버스 매매 최적값 · 국내 ETN vs 미국 · 대통령·정당별 VIX — 사전등록 vix-level-product-era-preregistration-2026-11.md 를 그대로 실행.

    python research/strategy-lab/vix_level_product_era.py

격자·선택(TRAIN 샤프)·판정(VALID·TEST 샤프>0 ∧ TEST 순열 p ≤ 0.05)은 사전등록에서 고정. 대통령·정당 분석은 기술 통계(판정 불사용).
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent
OUT_JSON = ROOT / "findings/vix-level-product-era-results.json"
ETN = ROOT / "data/etp/vix/daily_prices.parquet"
END, BOOT, SEED = "2026-08-21", 4000, 20261103
SPLITS = {"TRAIN": ("2011-01-04", "2018-12-31"), "VALID": ("2019-01-01", "2022-12-31"), "TEST": ("2023-01-01", END)}
PRES = [("부시(父)", "1990-01-02", "1993-01-19", "R"), ("클린턴", "1993-01-20", "2001-01-19", "D"), ("부시", "2001-01-20", "2009-01-19", "R"),
        ("오바마", "2009-01-20", "2017-01-19", "D"), ("트럼프1기", "2017-01-20", "2021-01-19", "R"), ("바이든", "2021-01-20", "2025-01-19", "D"),
        ("트럼프2기", "2025-01-20", END, "R")]
STRAT_ERAS = ["오바마", "트럼프1기", "바이든", "트럼프2기"]
COST_US, COST_KR = 0.0005, 0.0015          # 편도(왕복 10bp / 30bp)
GRID_A = [(x, y) for x in (11, 12, 13, 14, 15, 16, 17) for y in (14, 16, 18, 20, 22, 25, 30) if y >= x + 2]
GRID_B = [(u, v) for u in (20, 22, 24, 26, 28, 30, 35) for v in (14, 16, 18, 20, 22, 24) if v <= u - 2]
PPY = 252


def dl(sym, start, adj=True):
    x = yf.download(sym, start=start, end="2026-11-04", auto_adjust=adj, progress=False)
    x.columns = x.columns.get_level_values(0)
    return x.loc[:END]


def bars(O, C, idx):
    O, C = np.asarray(O, float), np.asarray(C, float)
    gon = np.r_[0.0, O[1:] / C[:-1] - 1]
    gid = C / O - 1
    return pd.DataFrame({"gon": gon, "gid": gid}, index=idx)


def chain(g):
    """밤사이·장중 수익 → 합성 시가/종가."""
    C = 100 * np.cumprod((1 + g["gon"].to_numpy()) * (1 + g["gid"].to_numpy()))
    O = np.r_[100.0, C[:-1]] * (1 + g["gon"].to_numpy())
    return O, C


def ret(g, T, cost, init=0.0):
    """T[t]=봉 t 종가 뒤 목표. 봉 t 시가에 T[t-1] 로 전환, 밤사이는 T[t-2]."""
    gon, gid = g["gon"].to_numpy()[1:], g["gid"].to_numpy()[1:]
    T1 = T[:-1]
    T2 = np.r_[init, T[:-2]]
    r = (1 + T2 * gon) * (1 + T1 * gid) - 1 - cost * np.abs(T1 - T2)
    return r, T1, T2


def state(v, a, b, leg):
    T, cur = np.zeros(len(v)), 0.0
    for i in range(1, len(v)):
        if leg == "A":
            if cur == 0 and v[i] <= a:
                cur = 1.0
            elif cur == 1 and v[i] >= b:
                cur = 0.0
        else:
            if cur == 0 and v[i] >= a:
                cur = 1.0
            elif cur == 1 and v[i] <= b:
                cur = 0.0
        T[i] = cur
    return T


def stats(r, entries=None):
    if len(r) < 20:
        return dict(total=None, sharpe=None, mdd=None, n=len(r), entries=entries)
    eq = np.cumprod(1 + r)
    sd = r.std(ddof=1)
    return dict(total=float(eq[-1] - 1), sharpe=float(r.mean() / sd * np.sqrt(PPY)) if sd > 0 else 0.0,
                mdd=float((eq / np.maximum.accumulate(eq) - 1).min()), n=len(r), entries=entries)


def sl(idx, a, b):
    return (idx >= pd.Timestamp(a)) & (idx <= pd.Timestamp(b))


def run_cell(g, vix, leg, a, b, cost, windows):
    T = state(vix, a, b, leg)
    r, T1, T2 = ret(g, T, cost)
    idx = g.index[1:]
    out = {}
    for nm, (s, e) in windows.items():
        mk = sl(idx, s, e)
        out[nm] = stats(r[mk], int(((T1 - T2)[mk] > 0).sum()))
    return out, r, T1, T2


def perm_p(g, T1, T2, mk, cost, rng, sh_obs):
    gon, gid = g["gon"].to_numpy()[1:][mk], g["gid"].to_numpy()[1:][mk]
    p1, p2 = T1[mk], T2[mk]
    n = len(p1)
    hit = 0
    for _ in range(BOOT):
        k = int(rng.integers(21, n - 21))
        a, b = np.roll(p1, k), np.roll(p2, k)
        r = (1 + b * gon) * (1 + a * gid) - 1 - cost * np.abs(a - b)
        sd = r.std(ddof=1)
        hit += (r.mean() / sd * np.sqrt(PPY) if sd > 0 else 0) >= sh_obs
    return (hit + 1) / (BOOT + 1)


def us_frames():
    vix = dl("^VIX", "1990-01-02", False)["Close"].dropna()
    spx = dl("^GSPC", "1990-01-02", False)["Close"].dropna()
    vy = dl("VIXY", "2011-01-01")[["Open", "Close"]].dropna()
    sv = dl("SVXY", "2011-09-01")[["Open", "Close"]].dropna()
    gy = bars(vy.Open, vy.Close, vy.index)
    gs = bars(sv.Open, sv.Close, sv.index)
    syn = pd.DataFrame(index=gy.index)
    syn["gon"] = -0.5 * gy.gon
    rday = (1 + gy.gon) * (1 + gy.gid) - 1
    syn["gid"] = (1 - 0.5 * rday) / (1 + syn.gon) - 1
    cut = pd.Timestamp("2018-03-01")
    inv = pd.concat([syn[syn.index < cut], gs[gs.index >= cut].reindex(gy.index[gy.index >= cut])]).sort_index().fillna(0.0)
    chk = pd.concat([syn, gs], axis=1, keys=["syn", "real"]).dropna()
    chk = chk[chk.index >= cut]
    rs = (1 + chk["syn"]["gon"]) * (1 + chk["syn"]["gid"]) - 1
    rr = (1 + chk["real"]["gon"]) * (1 + chk["real"]["gid"]) - 1
    check = dict(corr=float(rs.corr(rr)), cum_syn=float((1 + rs).prod() - 1), cum_real=float((1 + rr).prod() - 1), n=len(rs))
    v = vix.reindex(gy.index).ffill()
    return dict(vix_full=vix, spx=spx, long=gy, inv=inv, vix=v, check=check)


def kr_frames(us):
    d = pd.read_parquet(ETN)
    d["date"] = pd.to_datetime(d["date"])

    def series(sym):
        x = d[d.symbol == sym].set_index("date").sort_index()
        return bars(x.open, x.close, x.index)
    def splice(a, b, start):
        ga, gb = series(a), series(b)
        gb.iloc[0, gb.columns.get_loc("gon")] = 0.0
        out = pd.concat([ga[ga.index < pd.Timestamp(start)], gb[gb.index >= pd.Timestamp(start)]])
        return out
    start = "2025-02-10"
    longk, invk = splice("570088", "530130", start), splice("500077", "530131", start)
    idx = longk.index.intersection(invk.index)
    longk, invk = longk.loc[idx], invk.loc[idx]
    longk.iloc[0, longk.columns.get_loc("gon")] = 0.0
    invk.iloc[0, invk.columns.get_loc("gon")] = 0.0
    vs = us["vix_full"]
    v = vs.reindex(vs.index.union(idx)).ffill().reindex(idx)       # 같은 달력일 미국 종가 → 다음 한국 시가 체결
    return dict(long=longk, inv=invk, vix=v)


def main():
    us = us_frames()
    rng = np.random.default_rng(SEED)
    res = dict(check_synth=us["check"])
    gA, gB, vix = us["long"], us["inv"], us["vix"].to_numpy()
    idx = gA.index[1:]
    legs = {"A": (gA, GRID_A, "롱 VIX(VIXY)"), "B": (gB, GRID_B, "인버스 −0.5x")}
    sel = {}
    for leg, (g, grid, nm) in legs.items():
        cells = {}
        for (a, b) in grid:
            o, r, T1, T2 = run_cell(g, vix, leg, a, b, COST_US, SPLITS)
            cells[(a, b)] = (o, r, T1, T2)
        df = pd.DataFrame({k: {f"{s}_{m}": v[s][m] for s in SPLITS for m in ("total", "sharpe", "entries")} for k, (v, *_) in cells.items()}).T
        elig = df[df["TRAIN_entries"] >= 6]
        res[f"leg{leg}"] = dict(name=nm, ncells=len(grid), n_eligible=len(elig))
        if elig.empty:
            continue
        best = elig["TRAIN_sharpe"].idxmax()
        o, r, T1, T2 = cells[best]
        mk = sl(idx, *SPLITS["TEST"])
        p = perm_p(g, T1, T2, mk, COST_US, rng, o["TEST"]["sharpe"]) if o["TEST"]["sharpe"] is not None else None
        pos = {s: float((df[f"{s}_total"] > 0).mean()) for s in SPLITS}
        sp = {"VALID": float(df["TRAIN_sharpe"].corr(df["VALID_sharpe"], method="spearman")), "TEST": float(df["TRAIN_sharpe"].corr(df["TEST_sharpe"], method="spearman"))}
        rk = {s: float((df[f"{s}_sharpe"] < df.loc[best, f"{s}_sharpe"]).mean()) for s in ("VALID", "TEST")}
        hind = {s: dict(cell=list(df[f"{s}_sharpe"].idxmax()), sharpe=float(df[f"{s}_sharpe"].max()), total=float(df.loc[df[f"{s}_sharpe"].idxmax(), f"{s}_total"])) for s in SPLITS}
        verdict = "OOS 통과" if (o["VALID"]["sharpe"] > 0 and o["TEST"]["sharpe"] > 0 and p is not None and p <= 0.05) else "OOS 실패"
        # 정권별
        er = {}
        for e in PRES:
            if e[0] in STRAT_ERAS:
                s_, e_ = max(e[1], "2011-01-04"), e[2]
                mk2 = sl(idx, s_, e_)
                er[e[0]] = dict(sel=stats(r[mk2], int(((T1 - T2)[mk2] > 0).sum())),
                                grid_pos=float(np.mean([stats(cells[k][1][mk2])["total"] > 0 for k in cells])),
                                grid_median_total=float(np.median([stats(cells[k][1][mk2])["total"] for k in cells])))
        sel[leg] = dict(cell=list(best), table=df, verdict=verdict)
        res[f"leg{leg}"].update(dict(selected=list(best), splits=o, p_test=p, pos_share=pos, spearman=sp, sel_rank=rk, hindsight=hind, verdict=verdict, eras=er,
                                     grid={f"{k[0]}/{k[1]}": {kk: (None if pd.isna(vv) else float(vv)) for kk, vv in df.loc[k].items()} for k in df.index}))
    # A+B 기록
    if "A" in sel and "B" in sel:
        rA = run_cell(gA, vix, "A", *sel["A"]["cell"], COST_US, SPLITS)[1]
        rB = run_cell(gB, vix, "B", *sel["B"]["cell"], COST_US, SPLITS)[1]
        res["combo_AB"] = {s: stats(((rA + rB) / 2)[sl(idx, *w)]) for s, w in SPLITS.items()}
    # 국내 vs 미국 (2023-03-30~)
    kr = kr_frames(us)
    kidx = kr["long"].index[1:]
    w0, w1 = kr["long"].index[0], kr["long"].index[-1]
    cmp = {"window": [str(w0.date()), str(w1.date())]}
    for leg, (gk, gu) in {"A": (kr["long"], gA), "B": (kr["inv"], gB)}.items():
        if leg not in sel:
            continue
        a, b = sel[leg]["cell"]
        kv = kr["vix"].to_numpy()
        _, rk_, *_ = run_cell(gk, kv, leg, a, b, COST_KR, {"all": (str(w0.date()), str(w1.date()))})
        k_out = stats(rk_)
        k_hold = stats((1 + gk["gon"].to_numpy()[1:]) * (1 + gk["gid"].to_numpy()[1:]) - 1)
        gu2 = gu.loc[w0:w1]
        uv = vix[gu.index.get_indexer(gu2.index)]
        _, ru_, *_ = run_cell(gu2, uv, leg, a, b, COST_US, {"all": (str(w0.date()), str(w1.date()))})
        u_out = stats(ru_)
        u_hold = stats((1 + gu2["gon"].to_numpy()[1:]) * (1 + gu2["gid"].to_numpy()[1:]) - 1)
        rkk = pd.Series((1 + gk["gon"]) * (1 + gk["gid"]) - 1, index=gk.index).iloc[1:]
        ruu = pd.Series((1 + gu["gon"]) * (1 + gu["gid"]) - 1, index=gu.index)
        c0 = float(rkk.corr(ruu.reindex(rkk.index)))
        c1 = float(rkk.corr(ruu.shift(1).reindex(rkk.index)))
        cmp[leg] = dict(cell=[a, b], kr=k_out, us=u_out, kr_hold=k_hold, us_hold=u_hold, corr_same_day=c0, corr_us_prev_day=c1,
                        kr_trades=int((np.diff(np.r_[0.0, state(kv, a, b, leg)]) > 0).sum()))
    res["kr_vs_us"] = cmp
    # 대통령·정당 VIX
    vf, spx = us["vix_full"], us["spx"]
    lv = np.log(vf)
    chg = vf.pct_change()
    z = (vf - vf.rolling(252, min_periods=126).mean()) / vf.rolling(252, min_periods=126).std()
    spike = (z >= 2) & (z.shift(1) < 2)
    fwd20 = vf.shift(-20) / vf - 1
    sfwd = spx.shift(-20) / spx - 1
    sfwd = sfwd.reindex(vf.index)
    pres = {}
    for nm, s, e, party in PRES:
        mk = (vf.index >= pd.Timestamp(s)) & (vf.index <= pd.Timestamp(e))
        v, l = vf[mk], lv[mk]
        phi = float(np.polyfit(l.iloc[:-1].to_numpy(), l.iloc[1:].to_numpy(), 1)[0])
        sp_ = spike[mk] & fwd20[mk].notna()
        sx = spx[(spx.index >= pd.Timestamp(s)) & (spx.index <= pd.Timestamp(e))]
        yrs = (sx.index[-1] - sx.index[0]).days / 365.25
        b = {}
        mks = pd.Series(mk, index=vf.index)
        for lab, lo, hi in (("≤14", 0, 14), ("14~20", 14, 20), ("20~30", 20, 30), ("≥30", 30, 999)):
            q = sfwd[mks & (vf >= lo) & (vf < hi)].dropna()
            b[lab] = dict(n=int(len(q)), mean=float(q.mean()) if len(q) else None)
        pres[nm] = dict(party=party, start=s, end=e, days=int(mk.sum()), mean=float(v.mean()), median=float(v.median()), p10=float(v.quantile(.1)), p90=float(v.quantile(.9)),
                        le14=float((v <= 14).mean()), ge20=float((v >= 20).mean()), ge30=float((v >= 30).mean()), vol_of_vix=float(chg[mk].std()), vmax=float(v.max()),
                        phi=phi, halflife=float(np.log(.5) / np.log(phi)) if 0 < phi < 1 else None,
                        spikes=int(sp_.sum()), spike_fwd20=float(fwd20[mk][sp_].mean()) if sp_.sum() else None, spike_down=float((fwd20[mk][sp_] < 0).mean()) if sp_.sum() else None,
                        spx_cagr=float((sx.iloc[-1] / sx.iloc[0]) ** (1 / yrs) - 1), spx_vol=float(sx.pct_change().std() * np.sqrt(252)), spx_fwd20_by_vix=b)
    res["presidents"] = pres
    # 임기 연차
    ty = {}
    for nm, s, e, party in PRES:
        sd = pd.Timestamp(s) if nm != "부시(父)" else pd.Timestamp("1989-01-20")
        mk = (vf.index >= pd.Timestamp(s)) & (vf.index <= pd.Timestamp(e))
        yrn = np.minimum(((vf.index[mk] - sd).days / 365.25).astype(int) + 1, 4)
        for k in range(1, 5):
            ty.setdefault(party, {}).setdefault(k, []).extend(vf[mk][yrn == k].tolist())
    res["term_year"] = {p: {k: dict(mean=float(np.mean(v)), n=len(v)) for k, v in d.items() if len(v)} for p, d in ty.items()}
    # 부트스트랩 차이
    def grp(names):
        return pd.concat([lv[(lv.index >= pd.Timestamp(s)) & (lv.index <= pd.Timestamp(e))] for nm, s, e, p in PRES if nm in names])
    def bdiff(x, y, blk=21):
        x, y = x.to_numpy(), y.to_numpy()
        out = np.empty(BOOT)
        def rs(a):
            nb = int(np.ceil(len(a) / blk))
            return a[((rng.integers(0, len(a) - blk, nb)[:, None]) + np.arange(blk)).ravel()[:len(a)]]
        for i in range(BOOT):
            out[i] = rs(x).mean() - rs(y).mean()
        return dict(diff=float(x.mean() - y.mean()), lo=float(np.quantile(out, .025)), hi=float(np.quantile(out, .975)), pct=float(np.exp(x.mean() - y.mean()) - 1))
    R = grp([n for n, _, _, p in PRES if p == "R"])
    D = grp([n for n, _, _, p in PRES if p == "D"])
    res["tests"] = dict(rep_minus_dem=bdiff(R, D), trump2_minus_trump1=bdiff(grp(["트럼프2기"]), grp(["트럼프1기"])))
    OUT_JSON.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    report(res, sel)


def pc(x, d=1):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:+.{d}f}%"


def report(res, sel):
    print("## 합성 인버스 점검 (2018-03-01~, 합성 vs 실제 SVXY)", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in res["check_synth"].items()})
    for leg in ("A", "B"):
        L = res.get(f"leg{leg}")
        if not L or "selected" not in L:
            print(f"\n## 레그 {leg}: 선택 불가", L)
            continue
        print(f"\n## 레그 {leg} ({L['name']}) — 선택 셀 {L['selected']} → **{L['verdict']}**  (격자 {L['ncells']} 중 자격 {L['n_eligible']})")
        print("| 구간 | 총수익 | 샤프 | MDD | 진입수 |\n|---|---|---|---|---|")
        for s in SPLITS:
            o = L["splits"][s]
            print(f"| {s} | {pc(o['total'])} | {o['sharpe']:.2f} | {pc(o['mdd'])} | {o['entries']} |")
        print(f"TEST 순열 p {L['p_test']:.4f} · 격자 양(+) 셀 비율 TRAIN/VALID/TEST {L['pos_share']['TRAIN']:.0%}/{L['pos_share']['VALID']:.0%}/{L['pos_share']['TEST']:.0%} · "
              f"TRAIN↔VALID 샤프 순위상관 {L['spearman']['VALID']:+.2f}, TRAIN↔TEST {L['spearman']['TEST']:+.2f} · 선택 셀의 VALID/TEST 순위 백분위 {L['sel_rank']['VALID']:.0%}/{L['sel_rank']['TEST']:.0%}")
        print("사후 최적(사용 불가, 참고): " + " · ".join(f"{s} {h['cell']} 샤프 {h['sharpe']:.2f} 총수익 {pc(h['total'])}" for s, h in L["hindsight"].items()))
        print("| 정권 | 선택 셀 총수익 | 샤프 | MDD | 진입수 | 격자 양(+) 셀 비율 | 격자 총수익 중앙값 |\n|---|---|---|---|---|---|---|")
        for nm, e in L["eras"].items():
            s = e["sel"]
            print(f"| {nm} | {pc(s['total'])} | {(s['sharpe'] if s['sharpe'] is not None else float('nan')):.2f} | {pc(s['mdd'])} | {s['entries']} | {e['grid_pos']:.0%} | {pc(e['grid_median_total'])} |")
        print("\n격자 전체 (진입/청산: TRAIN·VALID·TEST 총수익 [진입수])")
        print("| 셀 | TRAIN | VALID | TEST |\n|---|---|---|---|")
        for k, v in L["grid"].items():
            print(f"| {k} | {pc(v['TRAIN_total'])} [{int(v['TRAIN_entries'])}] | {pc(v['VALID_total'])} [{int(v['VALID_entries'])}] | {pc(v['TEST_total'])} [{int(v['TEST_entries'])}] |")
    if "combo_AB" in res:
        print("\n## A+B 동시(50:50, 기록 전용):", {s: (pc(o['total']), round(o['sharpe'], 2), pc(o['mdd'])) for s, o in res["combo_AB"].items()})
    k = res["kr_vs_us"]
    print(f"\n## 국내 ETN vs 미국 ({k['window'][0]}~{k['window'][1]}) — 선택 셀을 같은 규칙으로")
    print("| 레그 | 셀 | 국내 ETN 규칙(왕복30bp) 총수익·샤프·MDD·진입 | 미국 ETF 규칙(왕복10bp) 총수익·샤프·MDD | 국내 단순보유 | 미국 단순보유 | 일수익 상관(같은 날/미국 전날) |\n|---|---|---|---|---|---|---|")
    for leg in ("A", "B"):
        if leg in k:
            x = k[leg]
            print(f"| {leg} | {x['cell']} | {pc(x['kr']['total'])} · {x['kr']['sharpe']:.2f} · {pc(x['kr']['mdd'])} · {x['kr_trades']} | {pc(x['us']['total'])} · {x['us']['sharpe']:.2f} · {pc(x['us']['mdd'])} | {pc(x['kr_hold']['total'])} | {pc(x['us_hold']['total'])} | {x['corr_same_day']:.2f} / {x['corr_us_prev_day']:.2f} |")
    print("\n## 대통령·정당별 VIX (1990-01-02~2026-08-21, 기술 통계)")
    print("| 정권 | 정당 | 일수 | 평균 | 중앙값 | 10%/90% | ≤14 | ≥20 | ≥30 | 일간변화 σ | 최대 | AR(1) φ | 반감기(일) | 급등 n | 급등 후 20일 VIX | 하락비율 | S&P 연수익 | S&P 연변동 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for nm, p in res["presidents"].items():
        hl = "-" if p["halflife"] is None else f"{p['halflife']:.0f}"
        sd_ = "-" if p["spike_down"] is None else f"{p['spike_down']:.0%}"
        print(f"| {nm} | {p['party']} | {p['days']} | {p['mean']:.1f} | {p['median']:.1f} | {p['p10']:.1f}/{p['p90']:.1f} | {p['le14']:.0%} | {p['ge20']:.0%} | {p['ge30']:.0%} | {p['vol_of_vix']*100:.1f}% | {p['vmax']:.0f} | {p['phi']:.3f} | {hl} | {p['spikes']} | {pc(p['spike_fwd20'])} | {sd_} | {pc(p['spx_cagr'])} | {p['spx_vol']*100:.0f}% |")
    print("\n## 정당별·차이 검정(log VIX 평균 차이, 월 블록 부트스트랩)")
    for nm, t in res["tests"].items():
        print(f"- {nm}: 차이 {t['diff']:+.3f} (VIX 약 {t['pct']*100:+.1f}%), 95% 구간 [{t['lo']:+.3f}, {t['hi']:+.3f}]")
    print("\n## 임기 연차별 VIX 평균 (정당 합산, n=일수)")
    for p, d in res["term_year"].items():
        print(f"- {p}: " + " · ".join(f"{k}년차 {v['mean']:.1f}(n{v['n']})" for k, v in d.items()))
    print("\n## VIX 구간별 이후 20거래일 S&P500 평균 수익 (정권별, n)")
    print("| 정권 | ≤14 | 14~20 | 20~30 | ≥30 |\n|---|---|---|---|---|")
    for nm, p in res["presidents"].items():
        b = p["spx_fwd20_by_vix"]
        print(f"| {nm} | " + " | ".join(f"{pc(b[l]['mean'])} (n{b[l]['n']})" for l in ("≤14", "14~20", "20~30", "≥30")) + " |")


if __name__ == "__main__":
    sys.exit(main())
