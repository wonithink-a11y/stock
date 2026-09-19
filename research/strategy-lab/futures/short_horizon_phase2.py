#!/usr/bin/env python3
"""단기 신호 2차 — 사전등록 `findings/short-horizon-phase2-preregistration-2026-09.md`.

    python research/strategy-lab/futures/short_horizon_phase2.py            # 실행
    python research/strategy-lab/futures/short_horizon_phase2.py --selftest

셀·분할·비용·바닥선·판정 규칙은 사전등록 문서에 고정. 여기서 바꾸지 않는다.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from futures_intraday_signal_study import load_day, cost_bp, EXIT  # noqa: E402
from short_horizon_study import tstat, null_bar, rsi2  # noqa: E402

CACHE = HERE.parent / ".cache"
SEED = 20260921
LIQ_MIN = 2e9
S_COST, S_COST2 = 30.0, 40.0
U_COST, U_COST2 = 20.0, 40.0
SPLITS = (150, 37, 63)
MARKS = [f"{h:02d}{m:02d}" for h in range(9, 16) for m in range(0, 60, 5)
         if "0905" <= f"{h:02d}{m:02d}" <= "1530"]
MI = {m: i for i, m in enumerate(MARKS)}
J1520 = MI["1520"]


def judge(parts: dict, bar: float, cost_mult=(1, 2), long_only=False, info_only=False) -> dict:
    """parts[split] = (info 배열, gross 배열, cost 배열). 양 = 셀 방향."""
    tr_i = parts["TRAIN"][0]
    s = np.sign(tr_i.mean()) if len(tr_i) else 0
    va_i, te_i = parts["VALID"][0], parts["TEST"][0]
    info = (abs(tstat(tr_i)) >= bar and len(va_i) and len(te_i)
            and np.sign(va_i.mean()) == s and np.sign(te_i.mean()) == s)
    g = np.concatenate([parts["VALID"][1], parts["TEST"][1]])
    c = np.concatenate([parts["VALID"][2], parts["TEST"][2]])
    net1, net2 = s * g - cost_mult[0] * c, s * g - cost_mult[1] * c
    capped = info_only or (long_only and s < 0)
    eco = bool(info) and not capped and len(g) and net1.mean() > 0 and net2.mean() > 0
    rob = eco and abs(tstat(s * g)) >= 2
    v = ("판정불가" if len(te_i) < 20 else "ROBUST" if rob else "ECONOMIC" if eco
         else "INFORMATION" if info else "REJECT")
    r = {"verdict": v, "train_sign": int(s), "t_train": round(tstat(tr_i), 2),
         "t_oos_dir": round(tstat(s * g), 2) if len(g) > 2 else None,
         "net1_oos_bp": round(float(net1.mean()), 2) if len(g) else None,
         "net2_oos_bp": round(float(net2.mean()), 2) if len(g) else None}
    for k in ("TRAIN", "VALID", "TEST"):
        i, gg = parts[k][0], parts[k][1]
        r[k] = {"n": int(len(i)), "info_bp": round(float(i.mean()), 2) if len(i) else None,
                "gross_bp": round(float(gg.mean()), 2) if len(gg) else None, "t": round(tstat(i), 2)}
    return r


def family(cells: dict, splitter, rng, flags=None) -> dict:
    """cells[id] = [(날짜, info, gross, cost)]."""
    flags = flags or {}
    parts = {}
    for cid, ev in cells.items():
        p = {k: ([], [], []) for k in ("TRAIN", "VALID", "TEST")}
        for dt, i, g, c in ev:
            b = p[splitter(dt)]
            b[0].append(i); b[1].append(g); b[2].append(c)
        parts[cid] = {k: tuple(np.array(x, float) for x in v) for k, v in p.items()}
    bar = null_bar([parts[c]["TRAIN"][0] for c in parts], rng)
    return {"bar": round(bar, 2),
            "cells": {c: judge(parts[c], bar, **flags.get(c, {})) for c in parts}}


# ---------------------------------------------------------------- S
def load_grid():
    panel = pd.read_parquet(CACHE / "intraday_panel.parquet", columns=["date", "ticker", "liq_base", "open_price"])
    panel = panel[panel["liq_base"] >= LIQ_MIN]
    keys = set(zip(panel["date"].astype(str), panel["ticker"]))
    cols = ["date", "ticker"] + [f"{p}{m}" for m in MARKS for p in "chlv"]
    pf = pq.ParquetFile(CACHE / "intraday_grid5m.parquet")
    frames = []
    for rg in range(pf.num_row_groups):
        t = pf.read_row_group(rg, columns=cols).to_pandas()
        k = list(zip(t["date"].astype(str), t["ticker"]))
        frames.append(t[[x in keys for x in k]])
    g = pd.concat(frames, ignore_index=True)
    g["date"] = g["date"].astype(str)
    panel["date"] = panel["date"].astype(str)
    g = g.merge(panel, on=["date", "ticker"], how="left").sort_values(["date", "ticker"]).reset_index(drop=True)
    arr = {p: g[[f"{p}{m}" for m in MARKS]].to_numpy(float) for p in "chlv"}
    return g[["date", "ticker", "open_price"]], arr


def s_events(meta, A):
    c, h, l, v = A["c"], A["h"], A["l"], A["v"]
    n = len(c)
    dates = meta["date"].to_numpy()
    # 유니버스 EW 지수: 일자별 평균(c_j / c0905)
    rel = c / c[:, [0]]
    idx = pd.DataFrame(rel).groupby(dates).mean()
    I = idx.loc[dates].to_numpy()
    out = {k: [] for k in ("S1", "S2", "S3a", "S3b", "S4a", "S4b", "S5")}
    rows = np.arange(n)

    def emit(cell, sel, j_dec, j_exit, direction):
        je = j_dec + 1
        ok = sel & (je <= J1520) & (j_exit <= J1520) & (j_exit > je)
        r_ = rows[ok]
        if not len(r_):
            return
        a, b = je[ok], j_exit[ok]
        e, x = c[r_, a], c[r_, b]
        gross = direction * (x / e - 1) * 1e4
        mkt = direction * (I[r_, b] / I[r_, a] - 1) * 1e4
        good = np.isfinite(gross) & np.isfinite(mkt)
        out[cell].extend(zip(dates[r_][good], (gross - mkt)[good], gross[good]))

    ORL, ORH = np.nanmin(l[:, :3], 1), np.nanmax(h[:, :3], 1)
    for cell, brk, back, d in (("S1", l < ORL[:, None], c > ORL[:, None], 1),
                               ("S2", h > ORH[:, None], c < ORH[:, None], -1)):
        jb = np.full(n, -1)
        for j in range(MI["0920"], MI["1100"] + 1):
            m = (jb < 0) & brk[:, j]
            jb[m] = j
        jd = np.full(n, -1)
        for k in range(4):
            jj = np.clip(jb + k, 0, len(MARKS) - 1)
            m = (jb >= 0) & (jd < 0) & back[rows, jj]
            jd[m] = jj[m]
        emit(cell, jd >= 0, jd, np.full(n, J1520), d)

    # S3 압축 돌파
    r0 = (np.nanmax(h[:, :6], 1) - np.nanmin(l[:, :6], 1)) / c[:, MI["0930"]]
    js = np.full(n, -1)
    for j in range(MI["1030"], MI["1345"] + 1):
        hi6, lo6 = np.nanmax(h[:, j - 6:j], 1), np.nanmin(l[:, j - 6:j], 1)
        cond = (((hi6 - lo6) / c[:, j - 1]) < 0.25 * r0) & (r0 > 0) & (c[:, j] > hi6) \
            & (v[:, j] > 3 * np.nanmean(v[:, j - 6:j], 1))
        m = (js < 0) & cond
        js[m] = j
    emit("S3a", js >= 0, js, js + 7, 1)
    emit("S3b", js >= 0, js, np.full(n, J1520), 1)

    # S4 / S5 소진
    j4, j5 = np.full(n, -1), np.full(n, -1)
    for j in range(MI["1005"], MI["1345"] + 1):
        r20 = c[:, j] / c[:, j - 4] - 1
        vs = v[:, j] >= 3 * np.nanmean(v[:, j - 12:j], 1)
        dn = (r20 <= -0.03) & vs & (c[:, j] <= np.nanmin(l[:, :j + 1], 1) * 1.002)
        up = (r20 >= 0.03) & vs & (c[:, j] >= np.nanmax(h[:, :j + 1], 1) * 0.998)
        j4[(j4 < 0) & dn] = j
        j5[(j5 < 0) & up] = j
    emit("S4a", j4 >= 0, j4, j4 + 7, 1)
    emit("S4b", j4 >= 0, j4, np.full(n, J1520), 1)
    emit("S5", j5 >= 0, j5, j5 + 7, -1)

    # 일자 평균 → 관측 단위
    cells = {}
    for k, ev in out.items():
        if not ev:
            cells[k] = []
            continue
        df = pd.DataFrame(ev, columns=["d", "i", "g"]).groupby("d").mean()
        cells[k] = [(d, r.i, r.g, S_COST) for d, r in df.iterrows()]
    counts = {k: len(v) for k, v in out.items()}
    return cells, counts, I


def x_timing(meta, A, dates_sorted):
    c = A["c"]
    op = meta["open_price"].to_numpy(float)
    close = c[:, MI["1530"]]
    rows = {"open": op}
    for m in ("0930", "1030", "1200", "1400", "1500", "1520"):
        rows[m] = c[:, MI[m]]
    df = pd.DataFrame({k: (close / p - 1) * 1e4 for k, p in rows.items()})
    df["date"] = meta["date"].to_numpy()
    # 익일 갭
    nxt = meta.assign(close=close).copy()
    nxt["open_next"] = nxt.groupby("ticker")["open_price"].shift(-1)
    nxt["date_next"] = nxt.groupby("ticker")["date"].shift(-1)
    pos = {d: i for i, d in enumerate(dates_sorted)}
    consec = nxt["date_next"].map(pos) == nxt["date"].map(pos) + 1
    df["overnight"] = np.where(consec, (nxt["open_next"] / nxt["close"] - 1) * 1e4, np.nan)
    daily = df.groupby("date").mean()
    res = {}
    for part, sl in (("TRAIN", slice(0, SPLITS[0])), ("VALID", slice(SPLITS[0], SPLITS[0] + SPLITS[1])),
                     ("TEST", slice(SPLITS[0] + SPLITS[1], None)), ("ALL", slice(None))):
        d = daily.iloc[sl]
        res[part] = {k: {"bp": round(float(d[k].mean()), 2), "t": round(tstat(d[k].dropna().to_numpy()), 2)}
                     for k in d.columns}
    return res


# ---------------------------------------------------------------- F
def f_events():
    days = [load_day(p) for p in sorted(glob.glob(str(CACHE / "futures_minute" / "kospi200_day" / "*.parquet")))]
    out = {"F1": [], "F2": []}
    for d in days:
        c, hi, lo, vol = d["close"], d["high"], d["low"], d["vol"]
        dt = pd.Timestamp(str(d["date"])[:10])
        orh, orl = np.nanmax(hi[:15]), np.nanmin(lo[:15])
        for t in range(15, 136):                       # 09:00 ~ 11:00
            up, dn = hi[t] > orh, lo[t] < orl
            if up or dn:
                bd = 1 if up else -1
                for k in range(t, t + 16):
                    if (bd == 1 and c[k] < orh) or (bd == -1 and c[k] > orl):
                        e = c[k + 1]
                        out["F1"].append((dt, -bd * (c[EXIT] / e - 1) * 1e4, cost_bp(e)))
                        break
                break
        r0 = np.nanmax(hi[:30]) - np.nanmin(lo[:30])
        for t in range(75, 316):                       # 10:00 ~ 14:00
            h30, l30 = np.nanmax(hi[t - 30:t]), np.nanmin(lo[t - 30:t])
            if r0 > 0 and (h30 - l30) < 0.25 * r0 and vol[t] > 3 * vol[t - 30:t].mean():
                bd = 1 if c[t] > h30 else (-1 if c[t] < l30 else 0)
                if bd:
                    e = c[t + 1]
                    out["F2"].append((dt, bd * (c[t + 31] / e - 1) * 1e4, cost_bp(e)))
                    break
    dts = [pd.Timestamp(str(d["date"])[:10]) for d in days]
    return {k: [(a, g, g, co) for a, g, co in v] for k, v in out.items()}, dts


# ---------------------------------------------------------------- U
def u_events(tk):
    f = pd.read_parquet(CACHE / "market_data" / f"{tk}_ohlc_full.parquet")
    o, h, l, c = (f[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    dates = f.index
    ibs = (c - l) / np.where(h > l, h - l, np.nan)
    r2 = rsi2(f["Close"]).to_numpy()
    down3 = (f["Close"].diff() < 0).rolling(3).sum().to_numpy() == 3
    low10 = (f["Close"] == f["Close"].rolling(10).min()).to_numpy()
    n = len(f)
    res, aux = {}, {}
    for cid, cond, hh in (("U1", ibs < 0.2, 1), ("U2", r2 < 10, 3), ("U3", down3, 3), ("U4", low10, 5)):
        ev, evc, i = [], [], 0
        while i < n - hh:
            if cond[i]:
                g = (c[i + hh] / o[i + 1] - 1) * 1e4
                ev.append((dates[i], g, g, U_COST))
                evc.append((dates[i], (c[i + hh] / c[i] - 1) * 1e4 - U_COST))
                i += hh + 1
            else:
                i += 1
        res[f"{tk}-{cid}"] = ev
        s = pd.Series(dict(evc))
        aux[f"{tk}-{cid}"] = {p: round(float(s[(s.index >= a) & (s.index < b)].mean()), 2)
                              for p, (a, b) in U_PERIODS.items()}
    return res, aux


U_PERIODS = {"TRAIN": ("1990", "2009"), "VALID": ("2009", "2017"), "TEST": ("2017", "2100")}


def u_split(dt):
    return "TRAIN" if dt < pd.Timestamp("2009-01-01") else ("VALID" if dt < pd.Timestamp("2017-01-01") else "TEST")


def day_splitter(dts):
    b1, b2 = pd.Timestamp(dts[SPLITS[0]]), pd.Timestamp(dts[SPLITS[0] + SPLITS[1]])
    return lambda dt: "TRAIN" if pd.Timestamp(dt) < b1 else ("VALID" if pd.Timestamp(dt) < b2 else "TEST")


def main():
    rng = np.random.default_rng(SEED)
    out = {}
    meta, A = load_grid()
    sd = sorted(meta["date"].unique())
    scells, counts, _ = s_events(meta, A)
    flags = {"S2": {"info_only": True}, "S5": {"info_only": True}}
    for k in ("S1", "S3a", "S3b", "S4a", "S4b"):
        flags[k] = {"long_only": True, "cost_mult": (1, S_COST2 / S_COST)}
    out["S"] = family(scells, day_splitter(sd), rng, flags)
    out["S"]["event_counts"] = counts
    out["S"]["span"] = [sd[0], sd[-1], len(sd)]
    out["X"] = x_timing(meta, A, sd)
    del A
    fcells, fd = f_events()
    out["F"] = family(fcells, day_splitter(fd), rng)
    ucells, uaux = {}, {}
    for tk in ("SPY", "QQQ"):
        a, b = u_events(tk)
        ucells.update(a); uaux.update(b)
    out["U"] = family(ucells, u_split, rng, {k: {"cost_mult": (1, U_COST2 / U_COST)} for k in ucells})
    out["U"]["close_entry_net_bp_aux"] = uaux
    (HERE / "short-horizon-phase2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    for fam in ("S", "F", "U"):
        print(f"== {fam} bar |t|={out[fam]['bar']}")
        for cid, r in out[fam]["cells"].items():
            print(f"{cid:8s} {r['verdict']:11s} s{r['train_sign']:+d} tTR {r['t_train']:6.2f} "
                  f"n {r['TRAIN']['n']}/{r['VALID']['n']}/{r['TEST']['n']} "
                  f"info {r['TRAIN']['info_bp']}/{r['VALID']['info_bp']}/{r['TEST']['info_bp']} "
                  f"gross {r['TRAIN']['gross_bp']}/{r['VALID']['gross_bp']}/{r['TEST']['gross_bp']} "
                  f"netOOS {r['net1_oos_bp']}/{r['net2_oos_bp']}")
    print("S event counts", counts)
    print("U close-entry aux", uaux)
    print("== X")
    for p, d in out["X"].items():
        print(p, {k: v["bp"] for k, v in d.items()})


def selftest():
    rng = np.random.default_rng(3)
    base = pd.Timestamp("2000-01-01")
    strong = {"A": [(base + pd.Timedelta(days=int(k)), 40 + rng.normal(0, 60), 40 + rng.normal(0, 60), 10.0) for k in range(9000)]}
    r = family(strong, u_split, rng, {"A": {"long_only": True}})
    assert r["cells"]["A"]["verdict"] == "ROBUST", r
    r = family(strong, u_split, rng, {"A": {"info_only": True}})
    assert r["cells"]["A"]["verdict"] == "INFORMATION", r
    neg = {"B": [(base + pd.Timedelta(days=int(k)), -40 + rng.normal(0, 60), -40 + rng.normal(0, 60), 10.0) for k in range(9000)]}
    r = family(neg, u_split, rng, {"B": {"long_only": True}})
    assert r["cells"]["B"]["verdict"] == "INFORMATION", r      # 숏이 필요한 방향은 경제성 판정 불가
    costly = {"C": [(base + pd.Timedelta(days=int(k)), 15 + rng.normal(0, 30), 15 + rng.normal(0, 30), 20.0) for k in range(9000)]}
    r = family(costly, u_split, rng)
    assert r["cells"]["C"]["verdict"] in ("INFORMATION", "REJECT"), r
    assert MARKS[0] == "0905" and MARKS[-1] == "1530" and len(MARKS) == 78
    print("selftest 5/5 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
