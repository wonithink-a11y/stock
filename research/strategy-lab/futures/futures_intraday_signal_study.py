#!/usr/bin/env python3
"""KOSPI200 선물 장중 신호 스터디 — 사전등록 `findings/futures-intraday-signal-preregistration-2026-09.md`.

    python research/strategy-lab/futures/futures_intraday_signal_study.py            # 실행
    python research/strategy-lab/futures/futures_intraday_signal_study.py --selftest # 데이터 없이

셀 10개·분할·비용·바닥선·판정 규칙은 전부 사전등록 문서에 고정돼 있다. 여기서 바꾸지 않는다.
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / ".cache" / "futures_minute" / "kospi200_day"
OPEN_MIN = 8 * 60 + 45                 # 08:45 = 격자 0
N_MIN = 15 * 60 + 45 - OPEN_MIN + 1    # 08:45..15:45 = 421분
EXIT = 15 * 60 + 30 - OPEN_MIN         # 15:30 (종가 단일가 구간 전)
NOON = 12 * 60 - OPEN_MIN
MULT = 250_000                         # 계약승수(원/포인트)
COST_KRW = 26_000                      # 왕복(편도 500원 수수료 + 편도 1틱 12,500원)
SPLITS = (150, 37, 63)                 # TRAIN / VALID / TEST 일수
N_FLIPS = 500
SEED = 20260919


def minute_of(hhmmss: str) -> int:
    return int(hhmmss[:2]) * 60 + int(hhmmss[2:4]) - OPEN_MIN


def load_day(path: str) -> dict:
    d = pd.read_parquet(path)
    m = d["hhmmss"].map(minute_of).to_numpy()
    close = np.full(N_MIN, np.nan)
    high = np.full(N_MIN, np.nan)
    low = np.full(N_MIN, np.nan)
    vol = np.zeros(N_MIN)
    for i, g in d.assign(m=m).groupby("m"):
        if 0 <= i < N_MIN:
            close[i] = g["close"].iloc[-1]
            high[i] = g["high"].max()
            low[i] = g["low"].min()
            vol[i] = g["volume"].sum()
    open_first = float(d["open"].iloc[0])
    if np.isnan(close[0]):
        close[0] = open_first
    close = pd.Series(close).ffill().to_numpy()
    return {"date": d["date"].iloc[0], "code": d["kisCode"].iloc[0], "open": open_first,
            "close": close, "high": high, "low": low, "vol": vol,
            "last": float(d["close"].iloc[-1])}


def cost_bp(entry: float) -> float:
    return COST_KRW / (entry * MULT) * 1e4


def ret_bp(entry: float, exit_: float, direction: int) -> float:
    return direction * (exit_ / entry - 1) * 1e4


def cells_for_day(day: dict, prev: dict | None, gap_cut: float | None) -> list[tuple]:
    """(셀ID, 통계량 bp, 왕복비용 bp) 목록. 통계량은 이미 방향이 곱해져 있다."""
    out = []
    c, o = day["close"], day["open"]

    def trade(cell, direction, t_dec, t_exit):
        e, x = c[t_dec + 1], c[t_exit]
        out.append((cell, ret_bp(e, x, direction), cost_bp(e)))

    for cell, w in (("S1a", 15), ("S1b", 30), ("S1c", 60)):        # 시가창: 반전 = 양
        r = c[w] / o - 1
        if r != 0:
            trade(cell, -int(np.sign(r)), w, EXIT)

    if prev is not None and prev["code"] == day["code"]:            # 롤오버일 제외
        gap = o / prev["last"] - 1
        if gap != 0:
            trade("S2a", -int(np.sign(gap)), 0, EXIT)
            if gap_cut is not None and abs(gap) >= gap_cut:
                trade("S2b", -int(np.sign(gap)), 0, EXIT)

    for cell, w in (("S3a", 15), ("S3b", 30)):                      # ORB: 추세 = 양
        hi, lo = np.nanmax(day["high"][:w]), np.nanmin(day["low"][:w])
        for t in range(w, NOON + 1):
            if c[t] > hi:
                trade(cell, 1, t, EXIT)
                break
            if c[t] < lo:
                trade(cell, -1, t, EXIT)
                break

    pv = np.cumsum(c * day["vol"])
    vv = np.cumsum(day["vol"])
    with np.errstate(invalid="ignore", divide="ignore"):
        vwap = np.where(vv > 0, pv / vv, np.nan)
        dev = (c - vwap) / vwap
    for cell, h in (("S4a", 15), ("S4b", 30), ("S4c", 60)):        # VWAP 페이드: 회귀 = 양
        for t in range(45, 316, 30):                                # 09:30 ~ 14:00
            if t + 1 + h > EXIT:
                continue
            past = dev[max(0, t - 120):t]
            past = past[~np.isnan(past)]
            if len(past) < 30 or np.isnan(dev[t]):
                continue
            sd = past.std()
            if sd <= 0:
                continue
            z = dev[t] / sd
            if abs(z) >= 2:
                trade(cell, -int(np.sign(z)), t, t + 1 + h)
    return out


def cluster_t(rows: pd.DataFrame, col: str) -> tuple[float, float, int]:
    """일자 클러스터 평균·t·이벤트 수."""
    n = len(rows)
    if n < 2:
        return float("nan"), float("nan"), n
    g = rows.groupby("day")[col].agg(["sum", "count"])
    mean = g["sum"].sum() / g["count"].sum()
    resid = g["sum"] - mean * g["count"]
    se = np.sqrt((resid ** 2).sum()) / g["count"].sum()
    return float(mean), float(mean / se) if se > 0 else float("nan"), n


def floor_from_flips(train: pd.DataFrame, cells: list[str], rng) -> float:
    days = np.array(sorted(train["day"].unique()))
    by = {c: train[train["cell"] == c].groupby("day")["gross"].agg(["sum", "count"]) for c in cells}
    mx = []
    for _ in range(N_FLIPS):
        sg = pd.Series(rng.choice([-1.0, 1.0], size=len(days)), index=days)
        best = 0.0
        for c in cells:
            g = by[c]
            if g["count"].sum() < 20:
                continue
            s = g["sum"] * sg.reindex(g.index).to_numpy()
            mean = s.sum() / g["count"].sum()
            resid = s - mean * g["count"]
            se = np.sqrt((resid ** 2).sum()) / g["count"].sum()
            if se > 0:
                best = max(best, abs(mean / se))
        mx.append(best)
    return float(np.percentile(mx, 95))


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    ck("분 격자 길이 421", N_MIN == 421 and minute_of("084500") == 0 and minute_of("154500") == 420)
    ck("청산 15:30 = 격자 405", EXIT == 405)
    ck("비용 ≈ 1.25bp @830", abs(cost_bp(830.0) - 1.2530) < 0.01)
    ck("롱 상승은 양, 숏 상승은 음", ret_bp(100, 101, 1) > 0 and ret_bp(100, 101, -1) < 0)
    # 합성 하루: 시가창에서 오르고 이후 하락 -> S1 반전 통계량이 양이어야 한다
    c = np.concatenate([np.linspace(100, 101, 61), np.linspace(101, 99, N_MIN - 61)])
    day = {"open": 100.0, "close": c, "high": c + 0.1, "low": c - 0.1,
           "vol": np.ones(N_MIN), "code": "X", "last": 99.0, "date": "d"}
    got = {x[0]: x[1] for x in cells_for_day(day, None, None)}
    ck("시가창 상승 후 하락 -> S1a 반전이 양", got.get("S1a", -1) > 0)
    ck("갭 셀은 prev 없으면 안 생긴다", "S2a" not in got)
    prev = {"code": "Y", "last": 98.0}
    ck("롤오버일은 갭 셀 제외", all(x[0] != "S2a" for x in cells_for_day(day, prev, None)))
    prev = {"code": "X", "last": 98.0}
    ck("같은 계약이면 갭 셀 생성(갭 상승 -> 페이드 = 숏, 이후 하락 -> 양)",
       {x[0]: x[1] for x in cells_for_day(day, prev, None)}.get("S2a", -1) > 0)
    df = pd.DataFrame({"day": [0, 0, 1], "gross": [1.0, 3.0, 2.0]})
    m, t, n = cluster_t(df, "gross")
    ck("클러스터 평균", abs(m - 2.0) < 1e-9 and n == 3)
    print(f"\nselftest {9 - len(fails)}/9" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    files = sorted(glob.glob(str(SRC / "*.parquet")))
    days = [load_day(f) for f in files]
    assert len(days) == sum(SPLITS), f"{len(days)}일 != {sum(SPLITS)}"
    split_of = ["TRAIN"] * SPLITS[0] + ["VALID"] * SPLITS[1] + ["TEST"] * SPLITS[2]

    gaps = [abs(days[i]["open"] / days[i - 1]["last"] - 1)
            for i in range(1, SPLITS[0]) if days[i]["code"] == days[i - 1]["code"]]
    gap_cut = float(np.percentile(gaps, 100 * 2 / 3))

    rows = []
    for i, d in enumerate(days):
        for cell, g, cst in cells_for_day(d, days[i - 1] if i else None, gap_cut):
            rows.append((i, split_of[i], cell, g, cst))
    ev = pd.DataFrame(rows, columns=["day", "split", "cell", "gross", "cost"])
    ev["net1"] = ev["gross"] - ev["cost"]
    ev["net2"] = ev["gross"] - 2 * ev["cost"]

    cells = ["S1a", "S1b", "S1c", "S2a", "S2b", "S3a", "S3b", "S4a", "S4b", "S4c"]
    floor = floor_from_flips(ev[ev["split"] == "TRAIN"], cells, np.random.default_rng(SEED))

    out, table = [], []
    for c in cells:
        e = ev[ev["cell"] == c]
        rec = {"cell": c}
        for sp in ("TRAIN", "VALID", "TEST"):
            g, t, n = cluster_t(e[e["split"] == sp], "gross")
            rec[sp] = {"n": n, "gross": g, "t": t}
        vt = e[e["split"].isin(["VALID", "TEST"])]
        vt_g, vt_t, vt_n = cluster_t(vt, "gross")
        rec["VT"] = {"n": vt_n, "gross": vt_g, "t": vt_t,
                     "net1": float(vt["net1"].mean()) if vt_n else float("nan"),
                     "net2": float(vt["net2"].mean()) if vt_n else float("nan")}
        rec["cost_bp"] = float(e["cost"].mean()) if len(e) else float("nan")

        tr, va, te = rec["TRAIN"], rec["VALID"], rec["TEST"]
        small = te["n"] < 20 or tr["n"] < 20
        sgn = np.sign(tr["gross"]) if tr["n"] else 0
        info = (not small and abs(tr["t"]) >= floor and sgn != 0
                and np.sign(va["gross"]) == sgn and np.sign(te["gross"]) == sgn)
        # 통계량은 이미 '가설 방향'이 곱해져 있어 TRAIN 부호가 음이면 반대 방향이 정보다.
        # 사전등록 규칙대로 정보 방향을 TRAIN 부호로 잡고 net 은 그 방향으로 재계산한다.
        if info and sgn < 0:
            flipped = vt["gross"].mul(-1) - vt["cost"]
            flipped2 = vt["gross"].mul(-1) - 2 * vt["cost"]
            rec["VT"]["net1"], rec["VT"]["net2"] = float(flipped.mean()), float(flipped2.mean())
        econ = info and rec["VT"]["net1"] > 0 and rec["VT"]["net2"] > 0
        robust = econ and abs(vt_t) >= 2
        rec["verdict"] = ("판정불가(표본<20)" if small else "ROBUST" if robust else
                          "ECONOMIC" if econ else "INFORMATION" if info else "REJECT")
        out.append(rec)

    res = {"floor95_trainMaxAbsT": floor, "gapCutTrainTercile": gap_cut,
           "nDays": len(days), "period": [days[0]["date"], days[-1]["date"]], "cells": out}
    (HERE / "futures-intraday-signal-study.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    ev.to_csv(HERE / "futures-intraday-signal-events.csv", index=False)

    print(f"바닥선(TRAIN 10셀 최대|t| 95%): {floor:.2f}   갭 컷(TRAIN 상위1/3): {gap_cut * 100:.3f}%")
    print(f"{'셀':4} {'비용bp':>6} | {'TRAIN n':>7} {'gross':>7} {'t':>6} | {'VALID n':>7} {'gross':>7} {'t':>6} | "
          f"{'TEST n':>6} {'gross':>7} {'t':>6} | {'VT net1':>7} {'net2':>7} {'t':>6} | 판정")
    for r in out:
        tr, va, te, vt = r["TRAIN"], r["VALID"], r["TEST"], r["VT"]
        print(f"{r['cell']:4} {r['cost_bp']:6.2f} | {tr['n']:7d} {tr['gross']:7.2f} {tr['t']:6.2f} | "
              f"{va['n']:7d} {va['gross']:7.2f} {va['t']:6.2f} | {te['n']:6d} {te['gross']:7.2f} {te['t']:6.2f} | "
              f"{vt['net1']:7.2f} {vt['net2']:7.2f} {vt['t']:6.2f} | {r['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else main())
