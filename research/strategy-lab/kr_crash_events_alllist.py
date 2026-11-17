#!/usr/bin/env python3
"""한국 대형주 급락 사건 — 폐지 포함 전종목. 사전등록 findings/kr-crash-events-alllist-preregistration-2026-11.md

    python research/strategy-lab/kr_crash_events_alllist.py            # 결과 JSON + 요약 출력 (수십 초)
    python research/strategy-lab/kr_crash_events_alllist.py --selftest

수익 = FLUC_RT 누적 지수(|일 등락률| > 30.5% 는 불연속이라 그 구간을 쓰는 창 제외). 대형주 = 20거래일 전 시총 순위 ≤ 100.
초과수익 = 사건 종목 수익 − 같은 날 다른 대형주 등가중 평균. 폐지 종목은 마지막 종가로 청산. 기록 전용.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "krx-daily-ext"
OUT_JSON = HERE / "findings" / "kr-crash-events-alllist-results.json"
BREAK, R20, DD, GAP, RANK, REF, HS = 30.5, -0.25, -0.40, 40, 100, 20, (21, 63)
DELIST_TD, MIN_BENCH, WAVE_DAYS, K_MIN, ALPHA, COST_PP, NBOOT, SEED = 7, 20, 30, 8, 0.01, 0.335, 2000, 20261117
ORIG9 = {"005930", "005380", "035420", "051910", "006400", "005490", "035720", "000270", "105560"}
SPAC = re.compile(r"스팩|기업인수목적")


def load():
    d = pd.concat((pd.read_parquet(f, columns=["BAS_DD", "ISU_CD", "ISU_NM", "FLUC_RT", "MKTCAP"]) for f in sorted(glob.glob(str(DATA / "*.parquet")))),
                  ignore_index=True)
    d["date"] = pd.to_datetime(d.BAS_DD)
    assert not d.duplicated(["date", "ISU_CD"]).any()
    names = d.groupby("ISU_CD").ISU_NM.agg(lambda s: any(SPAC.search(str(x)) for x in s.unique()))
    common = pd.Series({c: c.endswith("0") and not names[c] for c in names.index})
    fl = pd.to_numeric(d.FLUC_RT, errors="coerce").fillna(0.0)
    d["brk"] = (fl.abs() > BREAK).astype(int)
    d["r"] = np.where(d.brk == 1, 0.0, fl / 100)
    first = ~d.duplicated("ISU_CD")                                               # 첫 행은 기준이 없어 0
    d.loc[first, "r"] = 0.0
    d = d.sort_values(["ISU_CD", "date"])
    d["idx"] = (1 + d.r).groupby(d.ISU_CD).cumprod()
    d["bcs"] = d.groupby("ISU_CD").brk.cumsum()
    return d, common


def panels(d, common):
    piv = lambda c: d.pivot(index="date", columns="ISU_CD", values=c)
    P = {"idx": piv("idx"), "bcs": piv("bcs"), "cap": piv("MKTCAP")}
    last = d.groupby("ISU_CD").date.max()
    dates = P["idx"].index
    pos = {t: i for i, t in enumerate(dates)}
    lastk = np.array([pos[last[c]] for c in P["idx"].columns])
    firstk = np.array([pos[t] for t in d.groupby("ISU_CD").date.min().reindex(P["idx"].columns)])
    k = np.arange(len(dates))[:, None]
    ok = (k >= firstk[None, :]) & (k <= lastk[None, :])
    P["idx"] = P["idx"].ffill().where(ok)                                          # 행 없는 날은 직전 값(정지), 상장 전·폐지 후는 NaN
    P["bcs"] = P["bcs"].ffill().where(ok)
    keep = [c for c in P["cap"].columns if common.get(c, False)]
    P["rank"] = P["cap"][keep].rank(axis=1, ascending=False).reindex(columns=P["cap"].columns)       # 보통주끼리 순위, 나머지 NaN
    return P, dates, lastk, firstk


def detect(P, rank_max):
    idx, bcs = P["idx"], P["bcs"]
    r20 = idx / idx.shift(REF) - 1
    dd = idx / idx.rolling(252, min_periods=252).max() - 1
    clean = (bcs - bcs.shift(252)) == 0
    cp = (r20 <= R20) & (dd <= DD) & clean
    first = cp & (cp.astype(int).rolling(GAP).sum().shift(1) == 0)                  # 직전 40거래일에 조건 충족일 없음
    uni = P["rank"].shift(REF) <= rank_max
    return first & uni, uni, cp


def forward(P, lastk, n, k, h):
    """종목 전체의 k → k+h 수익 벡터(NaN = 판정 불가). 폐지는 마지막 종가, 미성숙·불연속 창은 NaN. 두 번째 반환 = 폐지로 청산됐는지."""
    idx, bcs = P["idx"].to_numpy(), P["bcs"].to_numpy()
    m = idx.shape[1]
    end = k + h
    if end >= n:
        return np.full(m, np.nan), np.zeros(m, bool)
    eff = np.minimum(end, lastk)
    delisted = (end > lastk)
    valid = ~np.isnan(idx[k]) & (eff >= k) & (~delisted | (lastk <= n - 1 - DELIST_TD))
    cols = np.arange(m)
    val = idx[np.where(valid, eff, k), cols]
    brk_ok = (bcs[np.where(valid, eff, k), cols] - bcs[k]) == 0
    R = np.where(valid & brk_ok, val / idx[k] - 1, np.nan)
    return R, delisted & valid


def waves(rows) -> list[float]:
    out, start, cur = [], None, []
    for d, x in sorted(rows):
        if start is None or (d - start).days > WAVE_DAYS:
            if cur:
                out.append(float(np.mean(cur)))
            start, cur = d, []
        cur.append(x)
    if cur:
        out.append(float(np.mean(cur)))
    return out


def upper_tail(k: int, m: int) -> float:
    return sum(math.comb(k, j) for j in range(m, k + 1)) / 2 ** k


def judge(w: list[float]) -> str:
    k = len(w)
    if k < K_MIN:
        return f"INCONCLUSIVE(표본 부족: wave {k} < {K_MIN})"
    mean = float(np.mean(w))
    if mean > 0 and upper_tail(k, sum(x > 0 for x in w)) <= ALPHA:
        return "신호 있음(반등)"
    if mean < 0 and upper_tail(k, sum(x < 0 for x in w)) <= ALPHA:
        return "신호 있음(추가 하락)"
    return "INCONCLUSIVE"


def run_variant(P, dates, lastk, rank_max=RANK, drop_events=frozenset(), drop_bench=frozenset()):
    ev, uni, _ = detect(P, rank_max)
    cols = list(P["idx"].columns)
    n = len(dates)
    rk = P["rank"].shift(REF)
    bmask = (rk <= rank_max).to_numpy() & ~np.isin(cols, list(drop_bench))[None, :]
    evs = ev.to_numpy()
    rows = []
    for ki, ji in zip(*np.nonzero(evs)):
        if cols[ji] in drop_events:
            continue
        rec = dict(date=str(dates[ki].date()), isu=cols[ji], rank=int(rk.iloc[ki, ji]))
        ok = True
        for h in HS:
            R, dl = forward(P, lastk, n, ki, h)
            bm = bmask[ki].copy()
            bm[ji] = False
            b = R[bm]
            b = b[~np.isnan(b)]
            if np.isnan(R[ji]) or len(b) < MIN_BENCH:
                rec[f"ex{h}"] = None
                continue
            rec[f"r{h}"], rec[f"ex{h}"], rec[f"del{h}"] = float(R[ji] * 100), float((R[ji] - b.mean()) * 100), bool(dl[ji])
        end = min(ki + 63, lastk[ji])
        rec["mn63"] = float((P["idx"].iloc[ki + 1:end + 1, ji].min() / P["idx"].iloc[ki, ji] - 1) * 100) if end > ki else None
        rows.append(rec)
    return rows


def summarize(rows, h=63):
    got = [(pd.Timestamp(r["date"]), r[f"ex{h}"]) for r in rows if r.get(f"ex{h}") is not None]
    w = waves(got)
    k = len(w)
    rng = np.random.default_rng(SEED)
    ci = None
    if k >= 2:
        bs = [np.mean(rng.choice(w, k)) for _ in range(NBOOT)]
        ci = [round(float(np.percentile(bs, 2.5)), 2), round(float(np.percentile(bs, 97.5)), 2)]
    mean = float(np.mean(w)) if k else None
    ev = [x for _, x in got]
    per = {}
    for nm, (a, b) in {"2016~23": ("2016", "2023"), "2024": ("2024", "2024"), "2025~": ("2025", "2030")}.items():
        v = [r[f"ex{h}"] for r in rows if r.get(f"ex{h}") is not None and a <= r["date"][:4] <= b]
        per[nm] = None if not v else dict(n=len(v), mean=round(float(np.mean(v)), 2))
    return dict(events=len(rows), matured=len(got), waves=k, waveMean=None if mean is None else round(mean, 2), ci95=ci,
                net=None if mean is None else round(mean - COST_PP, 2), breakevenBp=None if mean is None else round(mean * 100, 0),
                evMean=round(float(np.mean(ev)), 2) if ev else None, evMed=round(float(np.median(ev)), 2) if ev else None,
                win=round(float(np.mean(np.array(ev) > 0) * 100)) if ev else None, wavePos=sum(x > 0 for x in w),
                delisted=sum(1 for r in rows if r.get(f"del{h}")), period=per, verdict=judge(w))


def selftest() -> int:
    ok = 0
    assert upper_tail(8, 8) == 1 / 256 and upper_tail(8, 7) > ALPHA; ok += 1       # 8/8 만 0.01 통과
    assert judge([1.0] * 8) == "신호 있음(반등)" and judge([-1.0] * 8) == "신호 있음(추가 하락)"; ok += 1
    assert judge([1.0] * 7).startswith("INCONCLUSIVE(표본 부족") and judge([1, 1, 1, 1, 1, 1, 1, -1.0]) == "INCONCLUSIVE"; ok += 1
    d0 = pd.Timestamp("2020-03-10")
    assert waves([(d0, 1.0), (d0 + pd.Timedelta(days=29), 3.0), (d0 + pd.Timedelta(days=31), 5.0)]) == [2.0, 5.0]; ok += 1
    # 합성 패널: 종목 A 는 급락 후 폐지, B~ 는 평탄. 사건·폐지 청산·불연속 제외 확인
    n, m = 420, 30
    dates = pd.bdate_range("2020-01-01", periods=n)
    idx = pd.DataFrame(100.0, index=dates, columns=[f"{i:06d}" for i in range(m)])
    idx.iloc[300:320, 0] = np.linspace(100, 55, 20)
    idx.iloc[320:, 0] = np.nan                                                      # 320 에서 폐지(마지막 행 319)
    idx.iloc[:, 1:] = idx.iloc[:, 1:] * (1 + 0.0005 * np.arange(n))[:, None]
    bcs = pd.DataFrame(0, index=dates, columns=idx.columns).where(idx.notna())
    cap = pd.DataFrame(np.tile(np.arange(m, 0, -1) * 1e9, (n, 1)), index=dates, columns=idx.columns)
    P = {"idx": idx, "bcs": bcs.astype(float), "cap": cap, "rank": cap.rank(axis=1, ascending=False)}
    lastk = np.array([319] + [n - 1] * (m - 1))
    rows = run_variant(P, dates, lastk)
    a = [r for r in rows if r["isu"] == "000000"]
    assert len(a) == 1 and a[0].get("del21") is True and a[0]["ex21"] < -5, a; ok += 1   # 폐지는 마지막 종가로 청산돼 음의 초과수익
    P2 = dict(P, bcs=P["bcs"].copy())
    P2["bcs"].iloc[310, 0] = 1.0
    P2["bcs"].iloc[311:, 0] = 1.0                                                   # 창 안에 불연속 → 제외
    rows2 = run_variant(P2, dates, lastk)
    assert all(r["isu"] != "000000" or r["ex21"] is None for r in rows2), rows2; ok += 1
    print(f"selftest OK ({ok})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        return selftest()
    d, common = load()
    P, dates, lastk, firstk = panels(d, common)
    print("자료", dates[0].date(), "~", dates[-1].date(), "종목", len(P["idx"].columns), "보통주", int(common.sum()))
    sys.path.insert(0, str(HERE))
    import diag_regime_semis as sm                                                 # 반도체 = 테마 'AI·반도체' ∪ 업종 '반도체 제조업'(사후 필터, 진단 전용)
    semi = set(sm.semi_set(pd.read_parquet(HERE / "data" / "factor-panel" / "kr-monthly-v1.parquet")))
    variants = {"기본(순위≤100)": dict(), "반도체 제외(진단)": dict(drop_events=semi, drop_bench=semi), "원 표본 9종 제외(기록)": dict(drop_events=ORIG9),
                "순위≤50(기록)": dict(rank_max=50)}
    out = {}
    for nm, kw in variants.items():
        rows = run_variant(P, dates, lastk, **kw)
        out[nm] = dict(h63=summarize(rows, 63), h21=summarize(rows, 21), events=rows if nm == "기본(순위≤100)" else None)
        s = out[nm]["h63"]
        print(f"{nm}: 사건 {s['events']} 성숙 {s['matured']} wave {s['waves']} | 63일 wave 평균 {s['waveMean']} CI {s['ci95']} net {s['net']} "
              f"양 wave {s['wavePos']}/{s['waves']} 폐지 {s['delisted']} | {s['verdict']} | 시기 {s['period']}")
    _, uni, cp = detect(P, RANK)
    cur = [P["idx"].columns[j] for j in np.nonzero((cp & uni).iloc[-1].to_numpy())[0]]       # 자료 끝에 조건 상태인 대형주
    out["_current"] = dict(asOf=str(dates[-1].date()), events=cur)
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("현재 조건 해당:", cur, "→", OUT_JSON.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
