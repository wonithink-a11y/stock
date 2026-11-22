#!/usr/bin/env python3
"""월말 달러: 월중 나스닥 방향 → 마지막 거래일 달러 인덱스 수익. 사전등록 findings/dollar-month-end-preregistration-2026-11.md (blob 7edf78d8)

    python research/strategy-lab/dollar_month_end.py            # 실행(네트워크: yfinance) → findings/dollar-month-end-results.json
    python research/strategy-lab/dollar_month_end.py --selftest # 네트워크 없음

기록 전용 — 점수·매매 불연결. 대상·월 정의·신호·창·방향·α·구간·비용은 사전등록에 고정되어 있다(바꾸지 않는다).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "findings" / "dollar-month-end-results.json"
FIRST, LAST_FULL = "2000-01", "2026-10"
ALPHA, PERM, NBOOT, SEED, COST_BP = 0.05, 5000, 2000, 20261122, 5.0
PERIODS = {"TRAIN": ("2000-01", "2009-12"), "VALID": ("2010-01", "2020-12"), "TEST": ("2021-01", "2026-10")}
ERAS = {"2016~23": ("2016-01", "2023-12"), "2024": ("2024-01", "2024-12"), "2025~": ("2025-01", "2026-10")}


def fetch(tk: str) -> pd.Series:
    import yfinance as yf
    for n in range(4):
        try:
            x = yf.download(tk, start="1999-12-01", auto_adjust=True, progress=False)
            x.columns = x.columns.get_level_values(0)
            s = x["Close"].dropna()
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
            assert len(s) > 5000, f"{tk} 행 {len(s)}"                  # 빈 응답을 성공으로 세지 않는다(교훈 81)
            return s.sort_index()
        except Exception:
            if n == 3:
                raise
            time.sleep(2 ** (n + 1))


def month_rows(ix: pd.Series, dxy: pd.Series, alt: pd.Series | None = None) -> tuple[pd.DataFrame, int]:
    """월별 한 줄. ix 거래일 달력 기준. 반환 (표, 제외된 월 수).
    s = 월중(전월 마지막 거래일 → n−1) ix 수익 부호, r1 = dxy[n]/dxy[n−1]−1, E = −s·r1·1e4(bp).
    3일 창: s3 = (전월 말 → n−3) 부호, E3 = −s3·(dxy[n]/dxy[n−3]−1)·1e4. 되돌림: n+1 일 같은 베팅."""
    ix = ix.dropna()
    keys = ix.index.strftime("%Y-%m")
    months = sorted(set(keys))
    rows, skipped = [], 0
    for k in months:
        if k < FIRST or k > LAST_FULL:
            continue
        idx = np.nonzero(keys == k)[0]
        pos_prev = idx[0] - 1
        if pos_prev < 0 or len(idx) < 5:
            skipped += 1
            continue
        d = ix.index
        n, n1, n3 = d[idx[-1]], d[idx[-2]], d[idx[-4]]
        prev = d[pos_prev]
        nxt = d[idx[-1] + 1] if idx[-1] + 1 < len(d) else None
        try:
            r1 = dxy[n] / dxy[n1] - 1
            r3 = dxy[n] / dxy[n3] - 1
        except KeyError:
            skipped += 1
            continue
        s = np.sign(ix[n1] / ix[prev] - 1)
        s3 = np.sign(ix[n3] / ix[prev] - 1)
        if s == 0:
            skipped += 1
            continue
        rb = (dxy[nxt] / dxy[n] - 1) if nxt is not None and nxt in dxy.index else np.nan
        sa = np.sign(alt[n1] / alt[prev] - 1) if alt is not None and n1 in alt.index and prev in alt.index else np.nan
        rows.append({"month": k, "s": float(s), "r1": float(r1), "E": float(-s * r1 * 1e4),
                     "s3": float(s3), "E3": float(-s3 * r3 * 1e4),
                     "Erebound": float(-s * rb * 1e4) if not np.isnan(rb) else np.nan,
                     "Ealt": float(-sa * r1 * 1e4) if not np.isnan(sa) else np.nan})
    return pd.DataFrame(rows), skipped


def perm_p(s: np.ndarray, r: np.ndarray, n: int, rng) -> tuple[float, float]:
    """평균 E = mean(−s·r·1e4). 신호 부호 s 를 월 사이에서 섞은 귀무, 단측 p = P(귀무 평균 ≥ 관측)."""
    obs = float(np.mean(-s * r) * 1e4)
    cnt = 0
    for _ in range(n):
        if np.mean(-rng.permutation(s) * r) * 1e4 >= obs:
            cnt += 1
    return obs, (1 + cnt) / (1 + n)


def period_stats(df: pd.DataFrame, col: str = "E") -> dict:
    out = {}
    for name, (a, b) in {**PERIODS, **ERAS}.items():
        x = df[(df["month"] >= a) & (df["month"] <= b)][col].dropna()
        out[name] = {"months": int(len(x)), "meanBp": float(x.mean()) if len(x) else None,
                     "t": float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else None}
    return out


def verdict(mean_all, p, periods, test_mean):
    if mean_all is None or mean_all <= 0 or p > 0.10:
        return "REJECT"
    pos = sum(1 for k in ("TRAIN", "VALID", "TEST") if periods[k]["meanBp"] is not None and periods[k]["meanBp"] > 0)
    if p > ALPHA or pos < 2:
        return "INCONCLUSIVE"
    return "ECONOMIC" if (mean_all > COST_BP and test_mean is not None and test_mean > COST_BP) else "INFORMATION"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    ix, dxy, spx = fetch("^IXIC"), fetch("DX-Y.NYB"), fetch("^GSPC")
    df, skipped = month_rows(ix, dxy, spx)
    rng = np.random.default_rng(SEED)
    obs, p = perm_p(df["s"].values, df["r1"].values, PERM, rng)
    boot = np.array([df["E"].values[rng.integers(0, len(df), len(df))].mean() for _ in range(NBOOT)])
    per = period_stats(df)
    test_mean = per["TEST"]["meanBp"]
    v = verdict(obs, p, per, test_mean)
    res = {"months": int(len(df)), "skipped": int(skipped), "first": df["month"].iloc[0], "last": df["month"].iloc[-1],
           "meanBp": obs, "pOneSided": p, "bootCI95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
           "positiveShare": float((df["E"] > 0).mean()), "signUpShare": float((df["s"] > 0).mean()),
           "periods": per, "verdict": v, "costBp": COST_BP}
    print(f"월 {len(df)} (제외 {skipped}) {res['first']}~{res['last']} · 평균 E {obs:+.2f}bp [{res['bootCI95'][0]:+.1f}, {res['bootCI95'][1]:+.1f}] · 단측 p {p:.4f} → {v}")
    for k, b in per.items():
        print(f"   {k}: {b['months']}개월 평균 {'' if b['meanBp'] is None else f'{b['meanBp']:+.2f}bp'} t {'' if b['t'] is None else f'{b['t']:+.2f}'}")
    rec = {"calendarLastDayDxyBp": float(df["r1"].mean() * 1e4),
           "window3": {"meanBp": float(df["E3"].mean()), "periods": period_stats(df, "E3")},
           "rebound": {"meanBp": float(df["Erebound"].mean()), "periods": period_stats(df, "Erebound")},
           "altSignalGSPC": {"meanBp": float(df["Ealt"].mean()), "periods": period_stats(df, "Ealt")},
           "byYear": {str(y): round(float(g["E"].mean()), 2) for y, g in df.groupby(df["month"].str[:4].astype(int))}}
    res["recordOnly"] = rec
    print("\n(기록) 월말 마지막 거래일 DXY 평균 수익(주식 방향 무관):", f"{rec['calendarLastDayDxyBp']:+.2f}bp")
    print("(기록) 3일 창 평균 E:", f"{rec['window3']['meanBp']:+.2f}bp", {k: None if v['meanBp'] is None else round(v['meanBp'], 1) for k, v in rec['window3']['periods'].items() if k in PERIODS})
    print("(기록) 되돌림(같은 베팅, n+1일):", f"{rec['rebound']['meanBp']:+.2f}bp", {k: None if v['meanBp'] is None else round(v['meanBp'], 1) for k, v in rec['rebound']['periods'].items() if k in PERIODS})
    print("(기록) 대안 신호 ^GSPC:", f"{rec['altSignalGSPC']['meanBp']:+.2f}bp")
    print("(기록) 연도별 평균 E:", rec["byYear"])
    # 현재 상태(2026-11 월중)
    cur = ix[ix.index >= "2026-11-01"]
    prev = ix[ix.index < "2026-11-01"].iloc[-1]
    mtd = float(cur.iloc[-1] / prev - 1)
    res["current"] = {"month": "2026-11", "lastObs": str(cur.index[-1].date()), "ixicMtd": mtd,
                      "ruleDirection": "달러 약세 베팅" if mtd > 0 else "달러 강세 베팅", "note": "예측이 아니라 규칙 상태(월 마지막 거래일 전날 종가의 월중 수익으로 확정)"}
    print("\n(기록) 현재:", res["current"])
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", OUT)
    return 0


def selftest() -> int:
    ok = True

    def check(c, m):
        nonlocal ok
        print(("OK   " if c else "FAIL ") + m)
        ok &= bool(c)
    # 1) 월 정의: 신호는 n−1 종가까지, 수익은 n/n−1, 되돌림은 다음 달 첫날
    d = pd.bdate_range("1999-12-01", "2001-02-28")
    ix = pd.Series(np.linspace(100, 200, len(d)), index=d)
    dxy = pd.Series(np.linspace(100, 110, len(d)), index=d)
    df, sk = month_rows(ix, dxy)
    check(df["month"].iloc[0] == "2000-01" and df["month"].iloc[-1] == "2001-02", f"표본 월 범위 ({df['month'].iloc[0]}~{df['month'].iloc[-1]})")
    check((df["s"] == 1).all() and (df["E"] < 0).all(), "주식 계속 상승 + 달러 상승이면 규칙은 틀림(E<0)")
    jan = df[df.month == "2000-01"].iloc[0]
    last = d[(d.strftime("%Y-%m") == "2000-01")][-1]
    prev1 = d[(d.strftime("%Y-%m") == "2000-01")][-2]
    check(abs(jan["r1"] - (dxy[last] / dxy[prev1] - 1)) < 1e-12, "r1 = 월 마지막 거래일 / 전날 달러 수익")
    # 2) 합성: 신호와 반대로 달러가 움직이면 탐지, 무관하면 탐지 안 함
    rng = np.random.default_rng(5)
    n = 300
    s = rng.choice([-1.0, 1.0], n)
    for rel, lab in ((True, "관계 주입"), (False, "무관")):
        r = rng.normal(0, 0.005, n) + (-s * 0.001 if rel else 0.0)
        obs, p = perm_p(s, r, 2000, np.random.default_rng(1))
        if rel:
            check(obs > 5 and p < 0.01, f"{lab}: 평균 {obs:+.1f}bp p {p:.4f}")
        else:
            check(p > 0.05, f"{lab}: p {p:.3f}")
    # 3) 판정 규칙
    per = {"TRAIN": {"meanBp": 8}, "VALID": {"meanBp": 12}, "TEST": {"meanBp": 6}}
    check(verdict(9, 0.03, per, 6) == "ECONOMIC", "p≤0.05·2/3 양·전체·TEST>5bp → ECONOMIC")
    check(verdict(9, 0.03, per, 3) == "INFORMATION", "TEST≤5bp → INFORMATION")
    per2 = {"TRAIN": {"meanBp": -1}, "VALID": {"meanBp": 12}, "TEST": {"meanBp": -3}}
    check(verdict(9, 0.03, per2, -3) == "INCONCLUSIVE", "양인 구간 1/3 → INCONCLUSIVE")
    check(verdict(9, 0.07, per, 6) == "INCONCLUSIVE", "0.05<p≤0.10 → INCONCLUSIVE")
    check(verdict(9, 0.20, per, 6) == "REJECT", "p>0.10 → REJECT")
    check(verdict(-1, 0.01, per, 6) == "REJECT", "평균≤0 → REJECT")
    print("\nSELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
