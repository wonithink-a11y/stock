#!/usr/bin/env python3
"""국내 상장 미국채 ETF 월말 효과. 사전등록 findings/kr-ust-etf-month-end-preregistration-2026-11.md

    python research/strategy-lab/kr_ust_etf_month_end.py            # 결과 JSON + 요약 (수십 초, IEF 달력은 yfinance 공개)
    python research/strategy-lab/kr_ust_etf_month_end.py --selftest

한국 거래일 k 는 k 날짜보다 앞선 마지막 미국 거래일 D_k 까지를 반영한다. 창 = D_k 가 미국 월 마지막 3거래일인 한국 거래일들.
월 초과 E = 창 일 수익 합 − |창| × 같은 월 나머지 평균. 바닥선 = 같은 월 안 같은 길이 연속 창 순열. 기록 전용.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import us_treasury_month_end as T  # noqa: E402  (boot_ci·perm_p·ALPHA 를 그대로 쓴다)

OUT_JSON = HERE / "findings" / "kr-ust-etf-month-end-results.json"
PRIMARY, RECORD = "305080", ("304660", "308620")
COST_BP, COST_REF_BP, SEED, FIRST, LAST = 10.0, 5.0, 20261117, "2018-10", "2026-10"
SPLITS = {"전 기간": (FIRST, LAST), "전반": ("2018-10", "2022-06"), "후반": ("2022-07", "2026-10")}
ERAS = {"2018-10~2023-12": ("2018-10", "2023-12"), "2024": ("2024-01", "2024-12"), "2025~": ("2025-01", "2026-10")}


def kr_close(code: str) -> pd.Series:
    rows = {}
    for f in sorted(glob.glob(str(HERE / "data" / "etf-ohlc" / "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            r = json.loads(line)
            if r.get("ISU_CD") == code and float(r.get("TDD_CLSPRC") or 0) > 0:
                rows[pd.Timestamp(r["BAS_DD"])] = float(r["TDD_CLSPRC"])
    s = pd.Series(rows).sort_index()
    assert len(s) > 1500, f"{code} 행 {len(s)}"                                          # 빈 자료를 성공으로 세지 않는다(교훈 81)
    return s


def month_tables(close: pd.Series, us_dates: pd.DatetimeIndex):
    """완결 월별 (키, 관측 E, 위치별 E 배열, 창 일수). 한국 일 수익을 반영 미국일 D_k 의 월로 묶는다."""
    r = close.pct_change().dropna()
    us = np.asarray(us_dates)
    pos = np.searchsorted(us, r.index.to_numpy(), side="left") - 1                      # k 날짜보다 앞선 마지막 미국 거래일
    ok = pos >= 0
    r, D = r[ok], pd.DatetimeIndex(us[pos[ok]])
    mk = pd.Series(us_dates.strftime("%Y-%m"), index=us_dates)
    last3 = {d for _, g in pd.Series(us_dates, index=us_dates).groupby(mk.to_numpy()) for d in g.iloc[-3:]}
    inw = np.array([d in last3 for d in D])
    keys, obs, alls, ws = [], [], [], []
    for k, idx in pd.Series(np.arange(len(r))).groupby(D.strftime("%Y-%m").to_numpy()):
        if k < FIRST or k > LAST:
            continue
        i = idx.to_numpy()
        v, w = r.to_numpy()[i], int(inw[i].sum())
        if w < 1 or len(v) < 15 + w or not inw[i][-w:].all():                            # 창은 그 달 마지막 w 일이어야 한다
            continue
        csum = np.r_[0.0, np.cumsum(v)]
        tot = csum[-1]
        wsum = csum[w:] - csum[:-w]
        E_all = wsum - w * (tot - wsum) / (len(v) - w)
        keys.append(k); obs.append(float(E_all[-1])); alls.append(E_all); ws.append(w)
    return keys, np.array(obs), alls, ws


def summarize(keys, obs, alls, rng):
    out = {}
    for nm, (a, b) in {**SPLITS, **ERAS}.items():
        m = T.in_period(keys, a, b)
        if m.sum() < 6:
            out[nm] = None
            continue
        x = obs[m]
        mean = float(x.mean())
        row = dict(n=int(m.sum()), grossBp=round(mean * 1e4, 2), ci95Bp=T.boot_ci(x, rng), netBp=round(mean * 1e4 - COST_BP, 2),
                   netBp5=round(mean * 1e4 - COST_REF_BP, 2), breakevenBp=round(mean * 1e4, 2), pos=round(float((x > 0).mean() * 100)))
        if nm in SPLITS:
            row["permP"] = round(T.perm_p(alls, m, mean, rng), 4)
        out[nm] = row
    return out


def verdict(res) -> tuple[str, str]:
    full, h1, h2 = res["전 기간"], res["전반"], res["후반"]
    if full["grossBp"] <= 0 or full["permP"] > 0.05:
        sig = "REJECT"
    elif full["permP"] <= T.ALPHA and h1["grossBp"] > 0 and h2["grossBp"] > 0:
        sig = "신호 있음"
    else:
        sig = "INFORMATION"
    econ = "통과" if full["netBp"] > 0 and h2["netBp"] > 0 else "미달"
    return sig, econ


def selftest() -> int:
    ok = 0
    us = pd.bdate_range("2018-09-03", "2026-11-06")
    us = us[~us.isin(pd.to_datetime(["2020-12-25", "2022-12-26"]))]                          # 미국 휴장 두어 개
    kr = pd.bdate_range("2018-09-04", "2026-11-09")
    rng = np.random.default_rng(5)
    r = pd.Series(rng.normal(0, 0.003, len(kr)), index=kr)
    pos = np.searchsorted(np.asarray(us), kr.to_numpy(), side="left") - 1
    Dk = pd.DatetimeIndex(np.asarray(us)[pos])
    mkey = pd.Series(us.strftime("%Y-%m"), index=us)
    l3 = {d for _, g in pd.Series(us, index=us).groupby(mkey.to_numpy()) for d in g.iloc[-3:]}
    r[[d in l3 for d in Dk]] += 0.001                                                         # 창 한국일마다 +10bp
    close = pd.Series(100 * np.cumprod(1 + r.to_numpy()), index=kr)
    keys, obs, alls, ws = month_tables(close, us)
    assert keys[0] == "2018-10" and keys[-1] == "2026-10" and len(keys) == 97, (keys[:2], keys[-1], len(keys)); ok += 1
    assert set(ws) <= {2, 3} and np.mean(ws) > 2.8, set(ws); ok += 1
    assert abs(obs.mean() / np.mean(ws) - 0.001) < 0.0006, obs.mean(); ok += 1             # 창 일수당 약 +10bp
    res = summarize(keys, obs, alls, np.random.default_rng(6))
    assert res["전 기간"]["permP"] <= 0.01 and verdict(res)[0] == "신호 있음", res["전 기간"]; ok += 1
    print(f"selftest OK ({ok})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    import yfinance as yf
    x = yf.download("IEF", start="2018-01-01", auto_adjust=True, progress=False)
    x.columns = x.columns.get_level_values(0)
    us = x["Close"].dropna().index
    keys, obs, alls, ws = month_tables(kr_close(PRIMARY), us)
    res = summarize(keys, obs, alls, np.random.default_rng(SEED))
    sig, econ = verdict(res)
    out = {PRIMARY: dict(result=res, signal=sig, economics=econ, months=len(keys), windowDays={str(w): ws.count(w) for w in set(ws)},
                         monthly={k: round(float(e) * 1e4, 2) for k, e in zip(keys, obs)})}
    print(f"{PRIMARY} TIGER 미국채10년선물: 월 {len(keys)}개 → 신호 {sig} · 경제성 {econ}  창일수 {out[PRIMARY]['windowDays']}")
    for nm, row in res.items():
        print(f"  {nm}: {row}")
    rec = {}
    for code in RECORD:
        k2, o2, a2, _ = month_tables(kr_close(code), us)
        rec[code] = summarize(k2, o2, a2, np.random.default_rng(SEED + 1))
    ief_keys, ief_obs, _ = T.month_tables(T.fetch("IEF"))
    m = T.in_period(ief_keys, FIRST, LAST)
    rec["IEF 같은 기간 월 E"] = dict(n=int(m.sum()), grossBp=round(float(ief_obs[m].mean()) * 1e4, 2))
    out["기록전용"] = rec
    for nm, v in rec.items():
        print("기록", nm, {k: (r["grossBp"], r.get("permP")) for k, r in v.items() if r} if nm in RECORD else v)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
