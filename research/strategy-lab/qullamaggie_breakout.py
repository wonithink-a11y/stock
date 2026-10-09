#!/usr/bin/env python3
"""쿨라마기 돌파 — 사전등록 findings/qullamaggie-breakout-preregistration-2026-10.md 그대로.

    python research/strategy-lab/qullamaggie_breakout.py --selftest
    python research/strategy-lab/qullamaggie_breakout.py          # → findings/qullamaggie-breakout-results-2026-10.{md,json}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import surge_day_continuation as s  # noqa: E402

OUT = HERE / "findings" / "qullamaggie-breakout-results-2026-10"
COST = 0.00335
SEED = 20261010
TOP, PRICE_MIN, LIQ = 0.02, 1000.0, 2e9
WIN = {"TRAIN": (2016, 2020), "VALID": (2021, 2022), "TEST": (2023, 2025), "REC": (2026, 2026)}
MAXH, PART = 250, 5


def roll(A, k, fn):
    return getattr(pd.DataFrame(A).rolling(k, min_periods=k), fn)().to_numpy()


def simulate(O, H, L, C, S10, S20, t, j, entry, stop, trail="s10", partial=True):
    """t 진입 → 청산. 반환 (수익(비용 전), 보유일) 또는 None(자료 끝까지 안 닫힘). 정지일(NaN)은 건너뛴다."""
    idx = np.flatnonzero(~np.isnan(C[t + 1: t + 1 + MAXH + 60, j]))[:MAXH] + t + 1
    if len(idx) == 0:
        return None
    S = S10 if trail == "s10" else S20
    half, st, k0 = None, stop, None
    for n, d in enumerate(idx, 1):
        lo, op, cl, ma = L[d, j], O[d, j], C[d, j], S[d, j]
        if lo < st:
            px = min(op, st) / entry - 1
            return ((half + px) / 2 if half is not None else px), n
        if partial and n == PART and half is None:
            half, st = cl / entry - 1, max(st, entry)
            continue
        if (n > PART or not partial) and not np.isnan(ma) and cl < ma:
            px = cl / entry - 1
            return ((half + px) / 2 if half is not None else px), n
    last = idx[-1]
    if len(idx) < MAXH and last + 1 < C.shape[0] and np.isnan(C[last + 1:, j]).all() and last < C.shape[0] - 5:
        px = C[last, j] / entry - 1                      # 상장폐지: 마지막 종가
        return ((half + px) / 2 if half is not None else px), len(idx)
    if len(idx) == MAXH:
        px = C[idx[-1], j] / entry - 1
        return ((half + px) / 2 if half is not None else px), MAXH
    return None


def setup_ok(H, L, C, t, j):
    """급등·수축 조건(t−1 까지)."""
    w = C[t - 63: t, j]
    if np.isnan(w).all():
        return False
    h = t - 63 + int(np.nanargmax(w))
    base = C[max(h - 63, 0): h + 1, j]
    if np.isnan(base).all() or C[h, j] / np.nanmin(base) - 1 < 0.30:
        return False
    Ln = (t - 1) - h
    if not (10 <= Ln <= 40):
        return False
    lo = L[h + 1: t, j]
    if np.nanmin(lo) < H[h, j] * 0.75:
        return False
    half = len(lo) // 2
    if np.nanmin(lo[half:]) < np.nanmin(lo[:half]):
        return False
    rng = (H[h + 1: t, j] - L[h + 1: t, j]) / C[h + 1: t, j]
    return bool(np.nanmean(rng[-5:]) < np.nanmean(rng[:5]))


def run():
    dates, tick, raw = s.load_raw()
    P = s.derive(raw, dates)
    O, H, L, C = P["On"], P["Hn"], P["Ln"], P["Cn"]
    D, N = C.shape
    tv = pd.DataFrame(C * P["Vn"]).rolling(20, min_periods=15).mean().to_numpy()
    base = (tv >= LIQ) & (C >= PRICE_MIN) & ~P["halt"]                    # t−1 행 기준으로 쓴다
    leader = np.zeros((D, N), bool)
    for k in (21, 63, 126):
        r = C / s.sh(C, -k) - 1
        r = np.where(base, r, np.nan)
        q = np.nanquantile(r, 1 - TOP, axis=1, keepdims=True)
        leader |= r >= q
    S10, S20 = roll(C, 10, "mean"), roll(C, 20, "mean")
    adr = roll(H / L - 1, 20, "mean")
    B = roll(H, 10, "max")
    ew = np.r_[1.0, np.cumprod(1 + np.nan_to_num(np.nanmean(np.where(base, P["ret1"], np.nan), axis=1)))[1:]]
    mkt_up = ew >= pd.Series(ew).rolling(50, min_periods=50).mean().to_numpy()
    year = dates.year.to_numpy()
    t0 = int(np.searchsorted(dates, pd.Timestamp("2016-01-04")))
    cond = np.zeros((D, N), bool)
    cond[1:] = (leader & base & (C >= S20) & (S20 >= s.sh(S20, -5)))[:-1]   # t−1 조건을 t 행에
    Bt = np.vstack([np.full((1, N), np.nan), B[:-1]])
    adr_t = np.vstack([np.full((1, N), np.nan), adr[:-1]])
    brk = cond & (H > Bt)
    brk[:max(t0, 130)] = False
    trades, variants = [], {"trail20": [], "nopartial": [], "noadr": []}
    busy = np.full(N, -1)
    for t, j in zip(*np.nonzero(brk)):
        if t <= busy[j] or not setup_ok(H, L, C, t, j):
            continue
        entry = max(O[t, j], Bt[t, j])
        stop = L[t, j]
        wide = (entry - stop) / entry > adr_t[t, j]
        r_noadr = simulate(O, H, L, C, S10, S20, t, j, entry, stop)
        if r_noadr is not None:
            variants["noadr"].append((t, r_noadr[0]))
        if wide or np.isnan(adr_t[t, j]):
            continue
        r = simulate(O, H, L, C, S10, S20, t, j, entry, stop)
        if r is None:
            continue
        busy[j] = t + r[1]
        trades.append(dict(t=int(t), j=int(j), date=str(dates[t].date()), ticker=tick[j], ret=r[0], hold=r[1],
                           risk=(entry - stop) / entry, up=bool(mkt_up[t - 1])))
        for v, kw in (("trail20", dict(trail="s20")), ("nopartial", dict(partial=False))):
            rv = simulate(O, H, L, C, S10, S20, t, j, entry, stop, **kw)
            if rv is not None:
                variants[v].append((t, rv[0]))
    T = pd.DataFrame(trades)
    T["win"] = [next(w for w, (a, b) in WIN.items() if a <= y <= b) for y in pd.to_datetime(T["date"]).dt.year]
    # N1: 주도주 아무 날 시가 매수
    rng = np.random.default_rng(SEED)
    lead_t = np.zeros((D, N), bool)
    lead_t[1:] = (leader & base)[:-1]
    lead_t[:max(t0, 130)] = False
    nul = []
    for w, (a, b) in WIN.items():
        nt = int((T["win"] == w).sum())
        cand = np.argwhere(lead_t & ((year >= a) & (year <= b))[:, None])
        if nt == 0 or len(cand) == 0:
            continue
        pick = cand[rng.choice(len(cand), min(len(cand), nt * 5, 30000), replace=False)]
        for t, j in pick:
            e, st = O[t, j], L[t, j]
            if np.isnan(e) or np.isnan(st) or np.isnan(adr_t[t, j]) or (e - st) / e > adr_t[t, j]:
                continue
            r = simulate(O, H, L, C, S10, S20, t, j, e, st)
            if r is not None:
                nul.append(dict(date=str(dates[t].date()), ret=r[0], win=w))
    Nl = pd.DataFrame(nul)
    report(T, Nl, variants, dates)
    return 0


def month_series(df):
    m = pd.to_datetime(df["date"]).dt.to_period("M")
    return df.groupby(m)["net"].mean()


def block_ci(x, rng, block=6, reps=2000):
    x = np.asarray(x)
    if len(x) < 3:
        return (np.nan, np.nan)
    nb = int(np.ceil(len(x) / block))
    st = rng.integers(0, max(len(x) - block + 1, 1), (reps, nb))
    means = np.array([np.concatenate([x[s0: s0 + block] for s0 in row])[: len(x)].mean() for row in st])
    return float(np.percentile(means, 5)), float(np.percentile(means, 95))


def decide(tr, va, te, n_train):
    if n_train < 50:
        return "판정 불가"
    sig = tr["net"] > 0 and tr["lo"] > 0 and tr["net"] > tr["null"]
    if not sig:
        return "REJECT"
    oos = all(x["net"] > 0 and x["net"] > x["null"] for x in (va, te))
    return "ECONOMIC" if oos else "INFORMATION"


def report(T, Nl, variants, dates):
    rng = np.random.default_rng(SEED + 1)
    T["net"] = T["ret"] - COST
    Nl["net"] = Nl["ret"] - COST
    res = {}
    for w in WIN:
        d = T[T["win"] == w]
        if d.empty:
            continue
        ms = month_series(d)
        nd = Nl[Nl["win"] == w]
        lo, hi = block_ci(ms.to_numpy(), rng)
        gl, gh = block_ci((ms + COST).to_numpy(), rng)
        res[w] = dict(n=len(d), months=len(ms), gross=float(ms.mean() + COST), gross_lo=gl, gross_hi=gh, net=float(ms.mean()), lo=lo, hi=hi,
                      null=float(month_series(nd).mean()) if len(nd) else np.nan, null_n=len(nd),
                      winrate=float((d["net"] > 0).mean()), avg_win=float(d.loc[d["net"] > 0, "net"].mean()), avg_loss=float(d.loc[d["net"] <= 0, "net"].mean()),
                      hold_med=float(d["hold"].median()), risk_med=float(d["risk"].median()), r_med=float((d["ret"] / d["risk"]).median()),
                      r_p90=float((d["ret"] / d["risk"]).quantile(0.9)), up=float(d.loc[d["up"], "net"].mean()), down=float(d.loc[~d["up"], "net"].mean()),
                      n_up=int(d["up"].sum()))
    verdict = decide(res.get("TRAIN"), res.get("VALID"), res.get("TEST"), res.get("TRAIN", {}).get("n", 0))
    sig = "있음" if verdict in ("INFORMATION", "ECONOMIC") else "없음"
    eco = "통과" if verdict == "ECONOMIC" else "미달"
    var = {}
    for v, lst in variants.items():
        if not lst:
            continue
        V = pd.DataFrame(lst, columns=["t", "ret"])
        V["y"] = dates[V["t"].to_numpy()].year
        var[v] = {w: float((V.loc[(V["y"] >= a) & (V["y"] <= b), "ret"] - COST).mean()) for w, (a, b) in WIN.items()}
    yearly = T.groupby(pd.to_datetime(T["date"]).dt.year).agg(n=("net", "size"), net=("net", "mean"), win=("net", lambda x: (x > 0).mean())).reset_index()
    pc = lambda x: "" if x is None or pd.isna(x) else f"{x * 100:+.2f}%"
    L = ["---", "track: kr", "factor: qullamaggie-breakout", "date: 2026-10-10", f"verdict: {verdict}",
         "criteria_version: research-only (qullamaggie-breakout-preregistration-2026-10)", "reason: >-",
         f"  신호: {sig} · 경제성: {eco}. 거래 {len(T)}건, TRAIN 순수익 월평균 {pc(res['TRAIN']['net'])}(N1 {pc(res['TRAIN']['null'])}), "
         f"VALID {pc(res.get('VALID', {}).get('net'))} · TEST {pc(res.get('TEST', {}).get('net'))}. 비용 33.5bp.", "---", "",
         "# 쿨라마기 돌파 — 결과", "",
         "| 구간 | 거래 | 월 | gross 평균(90%) | 비용 후 net | net 90% | 손익분기 비용 | N1 주도주 그냥 매수 net | 승률 | 평균 이익 | 평균 손실 | 보유 중앙 |",
         "|---|---:|---:|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for w, r in res.items():
        L.append(f"| {w} | {r['n']} | {r['months']} | {pc(r['gross'])} [{pc(r['gross_lo'])}, {pc(r['gross_hi'])}] | {pc(r['net'])} | [{pc(r['lo'])}, {pc(r['hi'])}] | "
                 f"{r['gross'] * 1e4:+.0f}bp | {pc(r['null'])} ({r['null_n']}) | {r['winrate']:.0%} | {pc(r['avg_win'])} | {pc(r['avg_loss'])} | {r['hold_med']:.0f}일 |")
    L += ["", f"판정 **{verdict}** (사전등록 §5).", "", "## 기록 (판정 불사용)", "",
          "| 구간 | 손절 폭 중앙 | R 배수 중앙 | R 배수 90백분위 | 시장 50일선 위 net (건) | 아래 net |", "|---|---:|---:|---:|---:|---:|"]
    for w, r in res.items():
        L.append(f"| {w} | {r['risk_med'] * 100:.1f}% | {r['r_med']:+.2f} | {r['r_p90']:+.2f} | {pc(r['up'])} ({r['n_up']}) | {pc(r['down'])} |")
    L += ["", "변형(거래 단순 평균 net, 다중검정이라 판정 불사용): " + " · ".join(f"{v} " + "/".join(pc(x) for x in d.values()) for v, d in var.items()) + " (TRAIN/VALID/TEST/REC)", "",
          "| 해 | 거래 | net 평균 | 승률 |", "|---|---:|---:|---:|"] + [f"| {r.date} | {r.n} | {pc(r.net)} | {r.win:.0%} |" for r in yearly.itertuples()]
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    OUT.with_suffix(".json").write_text(json.dumps(dict(verdict=verdict, windows=res, variants=var), ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("\n".join(L))


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        ok &= bool(c)
        print(("PASS " if c else "FAIL ") + n)

    D = 40
    O = np.full((D, 1), 100.0); H = O + 2; L = O - 2; C = O.copy()
    S10 = np.full((D, 1), 90.0); S20 = S10.copy()
    C[1:6, 0] = [101, 102, 103, 104, 110]       # t=0 진입 100, 손절 95 → 5일째 종가 110 에 절반
    C[6:9, 0] = [112, 115, 113]; S10[8, 0] = 114   # 8행 종가 113 < 10일선 114 → 나머지 청산
    L[1:6, 0] = 98; L[6:9, 0] = 101             # 절반 뒤 손절은 본전(100) — 그 위
    r = simulate(O, H, L, C, S10, S20, 0, 0, 100.0, 95.0)
    check("부분 익절 + 10일선 청산", r is not None and abs(r[0] - (0.10 + 0.13) / 2) < 1e-12 and r[1] == 8)
    L2 = L.copy(); L2[2, 0] = 90; O2 = O.copy(); O2[2, 0] = 97
    r2 = simulate(O2, H, L2, C, S10, S20, 0, 0, 100.0, 95.0)
    check("손절: min(시가, 손절)", r2 is not None and abs(r2[0] - (-0.05)) < 1e-12 and r2[1] == 2)
    O3 = O.copy(); O3[2, 0] = 93
    r3 = simulate(O3, H, L2, C, S10, S20, 0, 0, 100.0, 95.0)
    check("갭 하락 손절은 시가", abs(r3[0] - (-0.07)) < 1e-12)
    L4 = L.copy(); L4[7, 0] = 99                    # 5일 뒤 손절 본전(100) — 7행 저가 99 < 100
    r4 = simulate(O, H, L4, C, S10, S20, 0, 0, 100.0, 95.0)
    check("부분 익절 뒤 본전 손절", abs(r4[0] - (0.10 + 0.0) / 2) < 1e-12)
    check("판정", decide(dict(net=.01, lo=.001, null=.0), dict(net=.01, null=0), dict(net=.01, null=0), 60) == "ECONOMIC"
          and decide(dict(net=.01, lo=-.001, null=.0), dict(net=.01, null=0), dict(net=.01, null=0), 60) == "REJECT"
          and decide(dict(net=.01, lo=.001, null=.0), dict(net=-.01, null=0), dict(net=.01, null=0), 60) == "INFORMATION"
          and decide(dict(net=.01, lo=.001, null=.0), None, None, 10) == "판정 불가")
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
