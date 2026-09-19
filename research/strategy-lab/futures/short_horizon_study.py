#!/usr/bin/env python3
"""단기·저비용 신호 스터디 — 사전등록 `findings/short-horizon-lowcost-preregistration-2026-09.md`.

    python research/strategy-lab/futures/short_horizon_study.py            # 실행
    python research/strategy-lab/futures/short_horizon_study.py --selftest # 데이터 없이

셀 15개·분할·비용·바닥선·판정 규칙은 전부 사전등록 문서에 고정돼 있다. 여기서 바꾸지 않는다.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from futures_intraday_signal_study import load_day, minute_of, cost_bp, EXIT  # noqa: E402

CACHE = HERE.parent / ".cache"
D_COST, D_COST2 = 5.0, 10.0
D_SPLIT = ("2019-01-01", "2022-01-01")
M_SPLITS = (150, 37, 63)
N_FLIPS = 500
SEED = 20260920
T0915, T1500 = minute_of("091500"), minute_of("150000")


# ---------------------------------------------------------------- 일봉
def load_daily() -> pd.DataFrame:
    df = pd.concat([pd.read_parquet(p) for p in sorted((CACHE / "kospi200_daily").glob("kospi200_*.parquet"))])
    df = df[df["ISU_NM"].str.contains("주간", na=False)].copy()
    for f in ["TDD_CLSPRC", "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "SPOT_PRC", "ACC_TRDVOL"]:
        df[f] = pd.to_numeric(df[f], errors="coerce")
    df["date"] = pd.to_datetime(df["BAS_DD"], format="%Y%m%d")
    fr = df.sort_values("ACC_TRDVOL", ascending=False).groupby("date").first().sort_index()
    fr = fr[(fr["ACC_TRDVOL"] > 0) & (fr["TDD_OPNPRC"] > 0)]
    return pd.DataFrame({"code": fr["ISU_CD"], "o": fr["TDD_OPNPRC"], "h": fr["TDD_HGPRC"],
                         "l": fr["TDD_LWPRC"], "c": fr["TDD_CLSPRC"], "spot": fr["SPOT_PRC"]})


def rsi2(s: pd.Series) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    dn = (-d).clip(lower=0).ewm(alpha=0.5, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def daily_events(f: pd.DataFrame, spy: pd.Series) -> dict:
    """셀 → [(신호일, gross bp)] (부호 = 가설 방향)."""
    dates = f.index
    n = len(f)
    o, c, code = f["o"].to_numpy(), f["c"].to_numpy(), f["code"].to_numpy()
    rng = (f["h"] - f["l"]).replace(0, np.nan)
    ibs = ((f["c"] - f["l"]) / rng).to_numpy()
    r2 = rsi2(f["spot"]).to_numpy()
    down = (f["spot"].diff() < 0).astype(int)
    down3 = (down.rolling(3).sum() == 3).to_numpy()
    low10 = (f["spot"] == f["spot"].rolling(10).min()).to_numpy()

    def seq(cond, direction, h):
        out, i = [], 0
        while i < n - h:
            if cond[i] and code[i + 1] == code[i + h]:
                out.append((dates[i], direction * (c[i + h] / o[i + 1] - 1) * 1e4))
                i += h + 1          # 보유 중 신호 무시
            else:
                i += 1
        return out

    ev = {"D1": seq(ibs < 0.2, 1, 1), "D2": seq(ibs > 0.8, -1, 1),
          "D3": seq(r2 < 10, 1, 3), "D4": seq(r2 > 90, -1, 3),
          "D5": seq(down3, 1, 3), "D6": seq(low10, 1, 5)}

    # D7: 직전 미국 세션
    spy_r = spy.pct_change()
    pos = spy_r.index.searchsorted(dates, side="left") - 1   # t 이전 마지막 미국 거래일
    d7 = []
    for i, p in enumerate(pos):
        if p >= 1 and abs(spy_r.iloc[p]) > 0.01:
            d7.append((dates[i], np.sign(spy_r.iloc[p]) * (c[i] / o[i] - 1) * 1e4))
    ev["D7"] = d7

    d8 = []
    for i in range(1, n):
        g = o[i] / c[i - 1] - 1
        if code[i] == code[i - 1] and abs(g) >= 0.005:
            d8.append((dates[i], np.sign(g) * (c[i] / o[i] - 1) * 1e4))
    ev["D8"] = d8

    # D9: 월 끝 둘째 거래일 종가 → 새 달 셋째 거래일 종가
    ym = dates.to_period("M")
    idx = pd.Series(np.arange(n), index=dates)
    groups = [g.to_numpy() for _, g in idx.groupby(ym)]
    d9 = []
    for a, b in zip(groups[:-1], groups[1:]):
        if len(a) >= 2 and len(b) >= 3:
            i, j = a[-2], b[2]
            if code[i] == code[j]:
                d9.append((dates[i], (c[j] / c[i] - 1) * 1e4))
    ev["D9"] = d9

    d10 = []
    for i in range(n - 1):
        if np.busday_count(dates[i].date(), dates[i + 1].date()) > 1 and code[i] == code[i + 1]:
            d10.append((dates[i], (c[i + 1] / c[i] - 1) * 1e4))
    ev["D10"] = d10
    return ev


def d_split(dt) -> str:
    return "TRAIN" if dt < pd.Timestamp(D_SPLIT[0]) else ("VALID" if dt < pd.Timestamp(D_SPLIT[1]) else "TEST")


# ---------------------------------------------------------------- 분봉
def minute_events() -> tuple[dict, list]:
    days = [load_day(p) for p in sorted(glob.glob(str(CACHE / "futures_minute" / "kospi200_day" / "*.parquet")))]
    night = {}
    for p in sorted(glob.glob(str(CACHE / "futures_minute" / "kospi200_night" / "*.parquet"))):
        d = pd.read_parquet(p)
        if len(d):
            night[str(d["date"].iloc[0])[:10]] = (float(d["close"].iloc[-1]), d["kisCode"].iloc[-1])
    ev = {k: [] for k in ("M1", "M2", "M4", "M5")}
    m2_abs = []
    for k in range(1, len(days)):
        day, prev = days[k], days[k - 1]
        c = day["close"]
        dt = pd.Timestamp(str(day["date"])[:10])
        if prev["code"] == day["code"]:
            for cell, t in (("M1", T0915), ("M2", T1500)):
                r = c[t] / prev["last"] - 1
                if r != 0:
                    e, x = c[T1500 + 1], c[EXIT]
                    ev[cell].append((dt, np.sign(r) * (x / e - 1) * 1e4, cost_bp(e)))
                    if cell == "M2":
                        m2_abs.append(abs(r))
        nk = night.get(str(prev["date"])[:10])
        if nk and nk[1] == day["code"]:
            dd = day["open"] / nk[0] - 1
            if dd != 0:
                e = c[1]
                ev["M4"].append((dt, -np.sign(dd) * (c[T0915] / e - 1) * 1e4, cost_bp(e)))
                ev["M5"].append((dt, -np.sign(dd) * (c[EXIT] / e - 1) * 1e4, cost_bp(e)))
    dts = [pd.Timestamp(str(d["date"])[:10]) for d in days]
    b1, b2 = dts[M_SPLITS[0]], dts[M_SPLITS[0] + M_SPLITS[1]]
    tr = [(dt, abs(v)) for (dt, v, _), a in zip(ev["M2"], m2_abs) if dt < b1]
    thr = np.quantile([a for (dt, _), a in zip(ev["M2"], m2_abs) if dt < b1], 2 / 3) if tr else np.inf
    ev["M3"] = [e for e, a in zip(ev["M2"], m2_abs) if a >= thr]
    return ev, [b1, b2, float(thr)]


# ---------------------------------------------------------------- 판정
def tstat(x: np.ndarray) -> float:
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else 0.0


def null_bar(train_by_cell: list[np.ndarray], rng) -> float:
    mx = []
    for _ in range(N_FLIPS):
        mx.append(max(abs(tstat(x * rng.choice([-1, 1], len(x)))) for x in train_by_cell if len(x) > 2))
    return float(np.quantile(mx, 0.95))


def judge(parts: dict, cost: np.ndarray, bar: float) -> dict:
    """parts: split → (gross 배열, 비용 배열)."""
    tr, va, te = (parts[s][0] for s in ("TRAIN", "VALID", "TEST"))
    t_tr = tstat(tr)
    s = np.sign(tr.mean()) if len(tr) else 0
    oos_g = np.concatenate([va, te])
    oos_c = np.concatenate([parts["VALID"][1], parts["TEST"][1]])
    net1, net2 = s * oos_g - oos_c, s * oos_g - 2 * oos_c
    info = abs(t_tr) >= bar and len(va) and len(te) and np.sign(va.mean()) == s and np.sign(te.mean()) == s
    eco = bool(info) and net1.mean() > 0 and net2.mean() > 0
    rob = eco and abs(tstat(s * oos_g)) >= 2
    verdict = "판정불가" if len(te) < 20 else ("ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT")
    r = {"verdict": verdict, "train_sign": int(s), "t_train": round(t_tr, 2),
         "t_oos_dir": round(tstat(s * oos_g), 2) if len(oos_g) > 2 else None,
         "net1_oos_bp": round(float(net1.mean()), 2) if len(net1) else None,
         "net2_oos_bp": round(float(net2.mean()), 2) if len(net2) else None}
    for k in ("TRAIN", "VALID", "TEST"):
        g = parts[k][0]
        r[k] = {"n": int(len(g)), "gross_bp": round(float(g.mean()), 2) if len(g) else None,
                "t": round(tstat(g), 2), "hit": round(float((g > 0).mean()), 3) if len(g) else None}
    return r


def run_family(ev: dict, splitter, cost_fn, rng) -> dict:
    parts = {}
    for cell, lst in ev.items():
        p = {"TRAIN": ([], []), "VALID": ([], []), "TEST": ([], [])}
        for e in lst:
            sp = splitter(e[0])
            p[sp][0].append(e[1])
            p[sp][1].append(cost_fn(e))
        parts[cell] = {k: (np.array(v[0], float), np.array(v[1], float)) for k, v in p.items()}
    bar = null_bar([parts[c]["TRAIN"][0] for c in parts], rng)
    out = {"bar": round(bar, 2), "cells": {c: judge(parts[c], None, bar) for c in parts}}
    return out, parts


def yearly(ev_list, cost_fn) -> dict:
    s = pd.Series({e[0]: e[1] - cost_fn(e) for e in ev_list})
    if s.empty:
        return {}
    return {int(y): round(float(v.mean()), 1) for y, v in s.groupby(s.index.year)}


def main():
    rng = np.random.default_rng(SEED)
    f = load_daily()
    spy = pd.read_parquet(CACHE / "market_data" / "SPY_2010_2026.parquet")["Close"]
    dev = daily_events(f, spy)
    dres, _ = run_family(dev, d_split, lambda e: D_COST, rng)
    # 방향 보정 전 연도별 net(가설 방향 기준, 1배 비용) — 보조 보고
    for c in dres["cells"]:
        dres["cells"][c]["yearly_net_bp"] = yearly(dev[c], lambda e: D_COST)
    mev, (b1, b2, thr) = minute_events()
    msplit = lambda dt: "TRAIN" if dt < b1 else ("VALID" if dt < b2 else "TEST")
    mres, _ = run_family(mev, msplit, lambda e: e[2], rng)
    out = {"daily": {"span": [str(f.index[0].date()), str(f.index[-1].date())], **dres},
           "minute": {"bounds": [str(b1.date()), str(b2.date())], "m3_thr": thr, **mres}}
    (HERE / "short-horizon-lowcost-study.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for fam in ("daily", "minute"):
        print(f"== {fam}  bar |t|={out[fam]['bar']}")
        for c, r in out[fam]["cells"].items():
            print(f"{c:4s} {r['verdict']:11s} sign{r['train_sign']:+d} tTR {r['t_train']:6.2f} "
                  f"n {r['TRAIN']['n']}/{r['VALID']['n']}/{r['TEST']['n']} "
                  f"g {r['TRAIN']['gross_bp']}/{r['VALID']['gross_bp']}/{r['TEST']['gross_bp']} "
                  f"netOOS {r['net1_oos_bp']}/{r['net2_oos_bp']} tOOS {r['t_oos_dir']}")


def selftest():
    rng = np.random.default_rng(1)
    # 1) 순수 잡음 → 바닥선 밖 통과가 드물어야 한다
    cells = {f"X{i}": [(pd.Timestamp("2015-01-01") + pd.Timedelta(days=k), rng.normal(0, 50)) for k in range(3000)] for i in range(5)}
    res, _ = run_family(cells, d_split, lambda e: 5.0, rng)
    assert all(r["verdict"] in ("REJECT", "INFORMATION") for r in res["cells"].values()), res
    # 2) 강한 양의 신호 → ROBUST
    strong = {"S": [(pd.Timestamp("2010-01-01") + pd.Timedelta(days=k), rng.normal(30, 50)) for k in range(6000)],
              "N": cells["X0"]}
    res, _ = run_family(strong, d_split, lambda e: 5.0, rng)
    assert res["cells"]["S"]["verdict"] == "ROBUST", res["cells"]["S"]
    # 3) 신호가 비용보다 작으면 ECONOMIC 불가
    weak = {"W": [(pd.Timestamp("2010-01-01") + pd.Timedelta(days=k), rng.normal(4, 10)) for k in range(6000)]}
    res, _ = run_family(weak, d_split, lambda e: 5.0, rng)
    assert res["cells"]["W"]["verdict"] in ("INFORMATION", "REJECT"), res["cells"]["W"]
    # 4) 음의 TRAIN 부호 → 반대 방향으로 판정
    neg = {"G": [(pd.Timestamp("2010-01-01") + pd.Timedelta(days=k), rng.normal(-30, 50)) for k in range(6000)]}
    res, _ = run_family(neg, d_split, lambda e: 5.0, rng)
    assert res["cells"]["G"]["train_sign"] == -1 and res["cells"]["G"]["verdict"] == "ROBUST"
    # 5) RSI2 경계 / 비중첩
    s = pd.Series([100, 99, 98, 97, 96.0])
    assert rsi2(s).iloc[-1] < 1
    print("selftest 5/5 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
