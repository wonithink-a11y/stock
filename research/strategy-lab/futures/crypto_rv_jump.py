#!/usr/bin/env python3
"""크립토 실현분산·점프 횡단면. 사전등록 findings/crypto-rv-jump-preregistration-2026-10.md.

    python research/strategy-lab/futures/crypto_rv_jump.py --collect   # data.binance.vision 월 파일 → data/crypto/rv1h/
    python research/strategy-lab/futures/crypto_rv_jump.py             # 판정
    python research/strategy-lab/futures/crypto_rv_jump.py --selftest
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from short_horizon_study import null_bar, tstat  # noqa: E402

SEED = 20261029
DATA = HERE.parent / "data" / "crypto" / "rv1h"
SYMS = ["1000PEPE", "1000SHIB", "AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "BCH", "BNB", "BTC", "DOGE", "DOT", "ETH",
        "FIL", "INJ", "LINK", "LTC", "NEAR", "OP", "SOL", "SUI", "TRX", "UNI", "WLD", "XMR", "XRP", "ZEC"]
MONTHS = pd.period_range("2019-09", "2026-09", freq="M")
BASE = "https://data.binance.vision/data/futures/um/monthly"
H = pd.Timedelta(hours=1)
WEEK = 168
T_FIRST, T_LAST = pd.Timestamp("2020-01-06", tz="UTC"), pd.Timestamp("2026-09-21", tz="UTC")
MIN_RET, MIN_N, COST = 160, 12, 10.0
NO_FUND = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))


# ---------- 수집 ----------
def _url(kind: str, sym: str, m: pd.Period) -> str:
    s = f"{sym}USDT"
    if kind == "mark":
        return f"{BASE}/markPriceKlines/{s}/1h/{s}-1h-{m}.zip"
    return f"{BASE}/fundingRate/{s}/{s}-fundingRate-{m}.zip"


def _fetch(args) -> tuple:
    import requests
    kind, sym, m = args
    raw = DATA / "raw" / kind / f"{sym}-{m}.zip"
    if raw.exists():
        return args, "cached"
    for _ in range(4):
        try:
            r = requests.get(_url(kind, sym, m), timeout=60)
        except requests.RequestException:
            continue
        if r.status_code == 404:
            return args, "404"
        if r.status_code == 200:
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(r.content)
            return args, "ok"
    return args, "fail"


def _read_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        txt = z.read(z.namelist()[0]).decode()
    df = pd.read_csv(io.StringIO(txt), header=None)
    df = df[pd.to_numeric(df[0], errors="coerce").notna()]   # 헤더가 있는 달·없는 달이 섞여 있다
    return df.apply(pd.to_numeric)


def _ms(x: pd.Series) -> pd.DatetimeIndex:
    x = x.astype("int64")
    return pd.to_datetime(np.where(x > 1e14, x // 1000, x), unit="ms", utc=True)   # 마이크로초 파일 대비


def collect():
    jobs = [(k, s, m) for k in ("mark", "funding") for s in SYMS for m in MONTHS]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(_fetch, jobs))
    fails = [a for a, st in res if st == "fail"]
    diag = {"fail": [f"{k}/{s}-{m}" for k, s, m in fails], "symbols": {}}
    for s in SYMS:
        mk = [DATA / "raw" / "mark" / f"{s}-{m}.zip" for m in MONTHS]
        mk = [p for p in mk if p.exists()]
        fu = [p for p in (DATA / "raw" / "funding" / f"{s}-{m}.zip" for m in MONTHS) if p.exists()]
        d = pd.concat([_read_zip(p) for p in mk]) if mk else pd.DataFrame()
        info = {"mark_months": len(mk), "funding_months": len(fu)}
        if len(d):
            t = _ms(d[0])
            p = pd.Series(d[1].to_numpy(float), index=t).sort_index()
            info["dup_hours"] = int(p.index.duplicated().sum())
            info["off_grid"] = int((p.index != p.index.floor("h")).sum())
            p = p[~p.index.duplicated(keep="last")]
            full = pd.date_range(p.index[0], p.index[-1], freq="h")
            info.update(first=str(p.index[0]), last=str(p.index[-1]), rows=len(p), missing_hours=int(len(full) - len(p)))
            p.rename("mark_open").to_frame().to_parquet(DATA / f"{s}_mark1h.parquet")
        if fu:
            f = pd.concat([_read_zip(p) for p in fu])
            rate = pd.Series(f[f.columns[-1]].to_numpy(float), index=_ms(f[0]).floor("h")).sort_index()
            rate = rate[~rate.index.duplicated(keep="last")]
            info["funding_rows"] = len(rate)
            rate.rename("funding").to_frame().to_parquet(DATA / f"{s}_funding.parquet")
        diag["symbols"][s] = info
    (DATA / "_diagnostics.json").write_text(json.dumps(diag, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"jobs": len(jobs), "fail": len(fails),
                      "symbols": {s: (v.get("first", "-")[:10], v.get("missing_hours")) for s, v in diag["symbols"].items()}},
                     ensure_ascii=False))
    if fails:
        sys.exit(1)


def load() -> dict:
    out = {}
    for s in SYMS:
        p = pd.read_parquet(DATA / f"{s}_mark1h.parquet")["mark_open"]
        f = pd.read_parquet(DATA / f"{s}_funding.parquet")["funding"] if (DATA / f"{s}_funding.parquet").exists() else NO_FUND
        out[s] = (p.asfreq("h"), f)
    return out


# ---------- 계산 ----------
def week_stats(p: pd.Series, fund: pd.Series, mondays: pd.DatetimeIndex) -> pd.DataFrame:
    """월요일 T 마다: 형성 창 가격 [T−168h, T] 의 168개 로그수익으로 RV·BV·JV, 보유 R = p(T+168h)/p(T) − 1."""
    lr = np.log(p).diff()
    rows = []
    for T in mondays:
        r = lr.reindex(pd.date_range(T - (WEEK - 1) * H, T, freq="h")).to_numpy()
        ok = ~np.isnan(r)
        p0, p1 = p.get(T, np.nan), p.get(T + WEEK * H, np.nan)
        if ok.sum() < MIN_RET or not np.isfinite(p0) or not np.isfinite(p1):
            continue
        a = np.abs(r)
        pair = a[1:] * a[:-1]
        pair = pair[~np.isnan(pair)]
        n = len(pair)
        rv = float(np.nansum(r ** 2))
        bv = float(np.pi / 2 * n / (n - 1) * pair.sum()) if n > 1 else np.nan
        fw = fund[(fund.index > T) & (fund.index <= T + WEEK * H)]
        rows.append({"T": T, "RV": rv, "BV": bv, "JV": max(rv - bv, 0.0), "RJ": max(rv - bv, 0.0) / rv if rv > 0 else np.nan,
                     "R": p1 / p0 - 1, "form": float(np.nansum(r)), "F": float(fw.sum()), "F_n": len(fw)})
    return pd.DataFrame(rows).set_index("T") if rows else pd.DataFrame()


def split(t) -> str:
    return "TRAIN" if t.year <= 2022 else ("VALID" if t.year == 2023 else "TEST")


def period(t) -> str:
    return "~2023" if t.year <= 2023 else ("2024" if t.year == 2024 else "2025~")


def sort_cell(panel: pd.DataFrame, key: str) -> pd.DataFrame:
    """panel: (T, sym) 행. 주별 LOW·HIGH 다리 → 스프레드·펀딩차·교체비율."""
    out, prev = [], {}
    for T, g in panel.groupby(level=0):
        g = g.droplevel(0).dropna(subset=[key, "R"])
        if len(g) < MIN_N:
            prev = {}
            continue
        k = len(g) // 3
        g = g.reset_index().sort_values([key, "sym"])
        low, high = g.head(k), g.tail(k)
        tau = {}
        for leg, d in (("L", low), ("H", high)):
            s = set(d["sym"])
            tau[leg] = 1.0 if leg not in prev else len(s - prev[leg]) / k
            prev[leg] = s
        out.append({"T": T, "spread": (low["R"].mean() - high["R"].mean()) * 1e4,
                    "fdiff": (high["F"].mean() - low["F"].mean()) * 1e4, "tauL": tau["L"], "tauH": tau["H"],
                    "lo_ex": (low["R"].mean() - g["R"].mean()) * 1e4, "FL": low["F"].mean() * 1e4, "FH": high["F"].mean() * 1e4,
                    "fund_missing": int((g["F_n"] == 0).sum()), "N": len(g)})
    return pd.DataFrame(out).set_index("T")


def judge(c: pd.DataFrame, bar: float) -> dict:
    sp = c["spread"]
    parts = {k: sp[sp.index.map(split) == k].to_numpy() for k in ("TRAIN", "VALID", "TEST")}
    tr = parts["TRAIN"]
    s = int(np.sign(tr.mean())) if len(tr) else 0
    info = bool(abs(tstat(tr)) >= bar and len(parts["VALID"]) and len(parts["TEST"])
                and np.sign(parts["VALID"].mean()) == s and np.sign(parts["TEST"].mean()) == s)
    o = c[c.index.map(split) != "TRAIN"]
    gross = s * o["spread"].to_numpy()
    carry = s * (o["spread"] + o["fdiff"]).to_numpy()
    tc = COST * (o["tauL"] + o["tauH"]).to_numpy()
    net1, net2 = carry - tc, carry - 2 * tc
    eco = info and net1.mean() > 0 and net2.mean() > 0
    rob = eco and tstat(net1) >= 2
    rng = np.random.default_rng(SEED)
    ci = [round(float(np.percentile([rng.choice(gross, len(gross)).mean() for _ in range(2000)], q)), 1) for q in (2.5, 97.5)]
    v = ("판정불가" if len(parts["TEST"]) < 20 else "ROBUST" if rob else "ECONOMIC" if eco
         else "INFORMATION" if info else "REJECT")
    sg = s or 1
    return {"verdict": v, "sign": s, "t_train": round(tstat(tr), 2),
            **{k: {"n": len(x), "bp": round(float(x.mean()), 1), "t": round(tstat(x), 2)} for k, x in parts.items()},
            "oos_gross_bp": round(float(gross.mean()), 1), "oos_gross_ci95": ci,
            "oos_funding_bp": round(float((carry - gross).mean()), 1), "oos_turnover": round(float((o["tauL"] + o["tauH"]).mean()), 3),
            "net10_bp": round(float(net1.mean()), 1), "net20_bp": round(float(net2.mean()), 1), "t_net10": round(tstat(net1), 2),
            "breakeven_rt_bp": round(float(carry.mean() / (o["tauL"] + o["tauH"]).mean()), 1),
            "periods_bp": {g: {"n": int(len(x)), "bp": round(float(x.mean() * sg), 1), "t": round(tstat(x.to_numpy() * sg), 2)}
                           for g, x in sp.groupby(sp.index.map(period))},
            "yearly_bp": {int(y): round(float(x * sg), 1) for y, x in sp.groupby(sp.index.year).mean().items()},
            "fund_missing_coin_weeks": int(c["fund_missing"].sum())}


def spearman_by_week(panel: pd.DataFrame, a: str, b: str) -> np.ndarray:
    v = [g[a].rank().corr(g[b].rank()) for _, g in panel.groupby(level=0) if g[[a, b]].dropna().shape[0] >= MIN_N]
    return np.array([x for x in v if np.isfinite(x)])


def build_panel(coins: dict) -> pd.DataFrame:
    mondays = pd.date_range(T_FIRST, T_LAST, freq="7D")
    frames = []
    for s, (p, f) in coins.items():
        w = week_stats(p, f, mondays)
        if len(w):
            frames.append(w.assign(sym=s).set_index("sym", append=True))
    return pd.concat(frames).sort_index()


def main():
    panel = build_panel(load())
    cells = {k: sort_cell(panel, k) for k in ("RV", "JV")}
    rng = np.random.default_rng(SEED)
    bar = null_bar([c["spread"][c.index.map(split) == "TRAIN"].to_numpy() for c in cells.values()], rng)
    out = {"bar": round(bar, 2), "weeks": {k: len(c) for k, c in cells.items()}, "cells": {}}
    for name, k in (("V1", "RV"), ("V2", "JV")):
        out["cells"][name] = judge(cells[k], bar)
    # 기록 전용
    rec = {}
    for k in ("RV", "JV", "BV", "RJ"):
        c = cells.get(k, sort_cell(panel, k))
        lo = c["lo_ex"].to_numpy() - COST * c["tauL"].to_numpy()
        rec[k] = {"spread_by_split": {sp: {"bp": round(float(x.mean()), 1), "t": round(tstat(x.to_numpy()), 2)}
                                      for sp, x in c["spread"].groupby(c.index.map(split))},
                  "long_only_low_minus_ew": {"gross_bp": round(float(c["lo_ex"].mean()), 1), "t": round(tstat(c["lo_ex"].to_numpy()), 2),
                                             "net10_bp": round(float(lo.mean()), 1)},
                  "leg_funding_bp": {"LOW": round(float(c["FL"].mean()), 2), "HIGH": round(float(c["FH"].mean()), 2)}}
    ic = spearman_by_week(panel, "RV", "R")
    mo = spearman_by_week(panel, "RV", "form")
    ab = spearman_by_week(panel.assign(aform=panel["form"].abs()), "RV", "aform")
    rec["ic_rv_next"] = {"mean": round(float(ic.mean()), 4), "t": round(tstat(ic), 2), "weeks": len(ic)}
    rec["rank_corr_rv_formation_ret"] = round(float(mo.mean()), 3)
    rec["rank_corr_rv_abs_formation_ret"] = round(float(ab.mean()), 3)
    rec["coins_per_week"] = {"min": int(cells["RV"]["N"].min()), "median": float(cells["RV"]["N"].median()), "max": int(cells["RV"]["N"].max())}
    out["record"] = rec
    (HERE / "crypto-rv-jump.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    rng = np.random.default_rng(7)
    idx = pd.date_range("2020-12-28", periods=24 * 7 * 80, freq="h", tz="UTC")
    mondays = pd.date_range("2021-01-11", periods=70, freq="7D", tz="UTC")
    # 1) 점프 없는 정규 수익이면 BV ≈ RV(JV 작음), 큰 점프 하나를 넣으면 JV ≈ 점프²
    p = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.005, len(idx)))), index=idx)
    w = week_stats(p, NO_FUND, mondays[:1])
    assert abs(w["BV"].iloc[0] / w["RV"].iloc[0] - 1) < 0.25 and w["JV"].iloc[0] < 0.25 * w["RV"].iloc[0]
    q = p.copy()
    q[q.index >= mondays[0] - 50 * H] *= np.exp(0.10)
    wj = week_stats(q, NO_FUND, mondays[:1])
    assert 0.6 * 0.01 < wj["JV"].iloc[0] < 1.4 * 0.01, wj["JV"].iloc[0]
    # 2) 보유 수익은 T 이후 가격만 쓴다 — T 이후를 바꿔도 RV 는 그대로
    q2 = p.copy()
    q2[q2.index > mondays[0]] *= 1.5
    w2 = week_stats(q2, NO_FUND, mondays[:1])
    assert np.isclose(w2["RV"].iloc[0], w["RV"].iloc[0]) and not np.isclose(w2["R"].iloc[0], w["R"].iloc[0])
    # 3) 점프가 잦은 코인의 다음 주 수익을 낮게 심으면 V2 스프레드가 양
    coins = {}
    for i in range(18):
        lr = rng.normal(0, 0.004, len(idx))
        jumpy = i < 6
        if jumpy:
            for T in mondays:
                j = idx.get_loc(T - 30 * H)
                lr[j] += rng.choice([-1, 1]) * 0.06
                h = (idx > T) & (idx <= T + WEEK * H)
                lr[h] -= 0.02 / WEEK
        coins[f"C{i:02d}"] = (pd.Series(100 * np.exp(np.cumsum(lr)), index=idx), NO_FUND)
    frames = [week_stats(pp, f, mondays).assign(sym=s).set_index("sym", append=True) for s, (pp, f) in coins.items()]
    panel = pd.concat(frames).sort_index()
    c = sort_cell(panel, "JV")
    assert c["spread"].mean() > 0 and tstat(c["spread"].to_numpy()) > 3, c["spread"].mean()
    assert c["tauL"].iloc[0] == 1.0 and c["tauH"].iloc[1:].mean() < 0.2   # 같은 코인이 계속 HIGH → 교체 적음
    print("selftest 3/3 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
