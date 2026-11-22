#!/usr/bin/env python3
"""연준 금리 기대 충격(6개월물 − 실효금리 주간 변화) → QQQ·SOXX·GLD·BTC-USD 다음 주 수익. 사전등록 findings/fed-expect-shock-preregistration-2026-11.md (blob a9797eb6)

    python research/strategy-lab/fed_expect_shock.py            # 실행(네트워크: FRED·yfinance) → findings/fed-expect-shock-results.json
    python research/strategy-lab/fed_expect_shock.py --selftest # 네트워크 없음

기록 전용 — 점수·매매 불연결. 문턱·창·자산·방향·α 는 사전등록에 고정되어 있다(바꾸지 않는다).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "findings" / "fed-expect-shock-results.json"
ASSETS = {"QQQ": 0.0005, "SOXX": 0.0005, "GLD": 0.0005, "BTC-USD": 0.0010}        # 왕복 비용(사전등록 §5)
ALPHA, PERM, SEED = 0.05 / 4, 5000, 20261122
ZLB = 0.50                                                    # TRAIN q 산정에서 제외할 제로금리 구간(주말 DFF < 0.50%)
TRAIN_END = pd.Timestamp("2015-12-31")
BUCKETS = [("2003~15", None, "2015-12-31"), ("2016~23", "2016-01-01", "2023-12-31"),
           ("2024", "2024-01-01", "2024-12-31"), ("2025~", "2025-01-01", None)]
MIN_BUCKET, MIN_SHOCK = 8, 20


def fetch_fred(sid: str) -> pd.Series:
    import requests
    for n in range(4):
        try:
            r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=60)
            r.raise_for_status()
            d = pd.read_csv(io.StringIO(r.text))
            d.columns = ["date", "v"]
            d["date"] = pd.to_datetime(d["date"])
            s = pd.to_numeric(d["v"], errors="coerce").dropna()   # 결측(휴장)은 행을 버린다
            s.index = d.loc[s.index, "date"]
            assert len(s) > 4000, f"{sid} 행 {len(s)}"            # 빈 응답을 성공으로 세지 않는다(교훈 81)
            return s.sort_index()
        except Exception:
            if n == 3:
                raise
            time.sleep(2 ** (n + 1))


def fetch_px(tk: str) -> pd.Series:
    import yfinance as yf
    for n in range(4):
        try:
            x = yf.download(tk, start="1999-01-01", auto_adjust=True, progress=False)
            x.columns = x.columns.get_level_values(0)
            s = x["Close"].dropna()
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
            assert len(s) > 1000, f"{tk} 행 {len(s)}"
            return s.sort_index()
        except Exception:
            if n == 3:
                raise
            time.sleep(2 ** (n + 1))


def weekly(dfii: pd.Series) -> pd.DataFrame:
    """ISO 주별 마지막 관측 = 주말 값. Δ = 주말 값 − 직전 주 주말 값. T = 그 주 뒤 첫 월요일."""
    d = dfii.copy()
    wk = d.index - pd.to_timedelta(d.index.weekday, unit="D")      # 그 주 월요일
    g = d.groupby(wk).agg(["last"]).rename(columns={"last": "v"})
    last_date = d.index.to_series().groupby(wk).max()
    g["week_end"] = last_date
    g["delta"] = g["v"].diff()
    g["T"] = g.index + pd.Timedelta(days=7)
    g.index.name = "week_start"
    return g.reset_index()


def close_on_or_after(px: pd.Series, d: pd.Timestamp, max_gap: int = 5):
    """날짜 d 이후 첫 종가(앞으로만). 5일 넘게 비면 None(결측을 메우지 않는다)."""
    i = px.index.searchsorted(d)
    if i >= len(px) or (px.index[i] - d).days > max_gap:
        return None
    return px.iloc[i], px.index[i]


def fwd(px: pd.Series, T: pd.Timestamp, days: int):
    a = close_on_or_after(px, T)
    b = close_on_or_after(px, T + pd.Timedelta(days=days))
    if a is None or b is None or b[1] <= a[1]:
        return np.nan
    return b[0] / a[0] - 1


def contemporaneous(px: pd.Series, wk_start: pd.Timestamp, week_end: pd.Timestamp):
    """같은 주(동행): 직전 주 마지막 종가 → 주말 종가. 기록 전용."""
    a = px[:wk_start - pd.Timedelta(days=1)]
    b = px[:week_end]
    if len(a) == 0 or len(b) == 0 or (week_end - b.index[-1]).days > 5:
        return np.nan
    return b.iloc[-1] / a.iloc[-1] - 1


def perm_p(r: np.ndarray, s: np.ndarray, n: int, rng) -> tuple[float, float]:
    """D = 충격 주 뒤 평균 − 대조 평균. 라벨 원형 이동 순열, 단측 p = P(D_null ≤ D_obs)."""
    d_obs = r[s].mean() - r[~s].mean()
    cnt = 0
    L = len(s)
    for _ in range(n):
        k = int(rng.integers(1, L))
        sk = np.roll(s, k)
        if sk.sum() == 0 or (~sk).sum() == 0:
            continue
        if r[sk].mean() - r[~sk].mean() <= d_obs:
            cnt += 1
    return d_obs, (1 + cnt) / (1 + n)


def bucket_stats(rows: pd.DataFrame, col: str = "r1") -> dict:
    out = {}
    for name, a, b in BUCKETS:
        m = pd.Series(True, index=rows.index)
        if a: m &= rows["week_end"] >= pd.Timestamp(a)
        if b: m &= rows["week_end"] <= pd.Timestamp(b)
        x = rows[m & rows[col].notna()]
        ns = int(x["shock"].sum())
        out[name] = {"weeks": int(len(x)), "shocks": ns,
                     "D": float(x.loc[x.shock, col].mean() - x.loc[~x.shock, col].mean()) if ns and (~x.shock).sum() else None}
    return out


def verdict(d, p, n_shock, buckets, mean_shock, cost):
    if d is None or d >= 0 or p > 0.05:
        return "REJECT"
    if p > ALPHA or n_shock < MIN_SHOCK:
        return "INCONCLUSIVE"
    cnt = [(b["D"] < 0) for b in buckets.values() if b["shocks"] >= MIN_BUCKET and b["D"] is not None]
    m = len(cnt)
    ok = (sum(cnt) >= -(-2 * m // 3)) if m >= 3 else (m >= 1 and all(cnt))
    if not ok:
        return "INCONCLUSIVE"
    return "ECONOMIC" if -mean_shock > cost else "INFORMATION"


def analyse(wk: pd.DataFrame, px: pd.Series, q: float, cost: float, rng, perm: int = PERM) -> dict:
    rows = wk.copy()
    rows["shock"] = rows["delta"] >= q
    rows["calm"] = rows["delta"] <= TRAIN_LOW
    rows["r1"] = [fwd(px, t, 7) for t in rows["T"]]
    rows["r4"] = [fwd(px, t, 28) for t in rows["T"]]
    rows["r0"] = [contemporaneous(px, a, b) for a, b in zip(rows["week_start"], rows["week_end"])]
    rows = rows[rows["delta"].notna() & rows["r1"].notna()].reset_index(drop=True)
    first = px.index[0]
    rows = rows[rows["week_end"] >= first + pd.Timedelta(days=14)].reset_index(drop=True)
    s = rows["shock"].values.astype(bool)
    r = rows["r1"].values
    d_obs, p = perm_p(r, s, perm, rng)
    bk = bucket_stats(rows)
    ms = float(r[s].mean())
    rec = {"weeks": int(len(rows)), "shocks": int(s.sum()), "meanShock1w": ms, "meanOther1w": float(r[~s].mean()),
           "D": float(d_obs), "pOneSided": float(p), "buckets": bk, "cost": cost,
           "verdict": verdict(d_obs, p, int(s.sum()), bk, ms, cost),
           "recordOnly": {
               "sameWeek": {"shock": float(rows.loc[rows.shock, "r0"].mean()), "other": float(rows.loc[~rows.shock, "r0"].mean())},
               "D4w": float(rows.loc[rows.shock & rows.r4.notna(), "r4"].mean() - rows.loc[~rows.shock & rows.r4.notna(), "r4"].mean()),
               "calmWeeksD1w": float(rows.loc[rows.calm, "r1"].mean() - rows.loc[~rows.calm, "r1"].mean()) if rows.calm.sum() else None,
               "shocksByYear": {str(k): int(v) for k, v in rows[rows.shock].groupby(rows["week_end"].dt.year).size().items()}}}
    return rec


TRAIN_LOW = float("nan")


def build_e() -> tuple[pd.Series, pd.Series]:
    """E = DGS6MO − DFF (두 계열이 모두 값이 있는 날만). 반환 (E, DFF)."""
    d6, ff = fetch_fred("DGS6MO"), fetch_fred("DFF")
    j = pd.concat({"d6": d6, "ff": ff}, axis=1).dropna()
    return (j["d6"] - j["ff"]), j["ff"]


def main() -> int:
    global TRAIN_LOW
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    e, ff = build_e()
    wk = weekly(e)
    wff = weekly(ff)[["week_start", "v"]].rename(columns={"v": "ff_end"})
    wk = wk.merge(wff, on="week_start", how="left")
    tr = wk[(wk["week_end"] <= TRAIN_END) & wk["delta"].notna() & (wk["ff_end"] >= ZLB)]["delta"]
    q = float(np.quantile(tr, 0.9))
    TRAIN_LOW = float(np.quantile(tr, 0.1))
    print(f"E {e.index[0].date()}~{e.index[-1].date()} · TRAIN 주(ZLB 제외) {len(tr)} · q(90분위)={q:.3f}%p · 10분위 {TRAIN_LOW:.3f}%p")
    rng = np.random.default_rng(SEED)
    res = {"eLast": str(e.index[-1].date()), "q": q, "qLow": TRAIN_LOW, "trainWeeks": int(len(tr)), "assets": {}}
    for tk, cost in ASSETS.items():
        px = fetch_px(tk)
        res["assets"][tk] = analyse(wk, px, q, cost, rng)
        r = res["assets"][tk]
        print(f"\n{tk}: 주{r['weeks']} · 충격 {r['shocks']} · 충격 뒤 {r['meanShock1w']*100:+.2f}% vs 평소 {r['meanOther1w']*100:+.2f}% · D {r['D']*100:+.2f}%p · p {r['pOneSided']:.4f} → {r['verdict']}")
        for k, b in r["buckets"].items():
            print(f"   {k}: 충격 {b['shocks']}/{b['weeks']}주 D {'' if b['D'] is None else f'{b['D']*100:+.2f}%p'}")
        print("   (기록) 같은 주", {k: f"{v*100:+.2f}%" for k, v in r["recordOnly"]["sameWeek"].items()}, "· 4주 D", f"{r['recordOnly']['D4w']*100:+.2f}%p", "· 기대 하락 충격 D", None if r["recordOnly"]["calmWeeksD1w"] is None else f"{r['recordOnly']['calmWeeksD1w']*100:+.2f}%p")
    last = wk.iloc[-1]
    res["currentWeek"] = {"weekStart": str(last["week_start"].date()), "lastObs": str(last["week_end"].date()),
                          "E": float(last["v"]), "delta": None if pd.isna(last["delta"]) else float(last["delta"]),
                          "isShock": bool(last["delta"] >= q) if not pd.isna(last["delta"]) else None,
                          "note": "DGS6MO 하루 지연 — 이 주 마지막 관측 기준(기록 전용)"}
    print("\n현재 주(기록 전용):", res["currentWeek"])
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", OUT)
    return 0


def selftest() -> int:
    ok = True
    def check(c, m):
        nonlocal ok
        print(("OK   " if c else "FAIL ") + m)
        ok &= bool(c)
    # 1) 주 정의: 금요일 마지막 값, T = 다음 월요일
    idx = pd.bdate_range("2020-01-06", "2020-01-31")
    w = weekly(pd.Series(np.arange(len(idx), dtype=float), index=idx))
    check(w.loc[0, "week_end"] == pd.Timestamp("2020-01-10") and w.loc[0, "T"] == pd.Timestamp("2020-01-13"), "주말=금요일, T=다음 월요일")
    check(abs(w.loc[1, "delta"] - 5.0) < 1e-9, "Δ = 주말 값 − 직전 주 주말 값")
    # 2) 앞으로만 당김: 월요일 휴장이면 화요일 종가
    px = pd.Series([1.0, 2.0, 3.0], index=pd.to_datetime(["2020-01-10", "2020-01-14", "2020-01-21"]))
    check(close_on_or_after(px, pd.Timestamp("2020-01-13"))[1] == pd.Timestamp("2020-01-14"), "휴장 시 이후 첫 종가(뒤로 안 당김)")
    check(close_on_or_after(px, pd.Timestamp("2020-02-20")) is None, "범위 밖이면 None")
    # 3) 합성: 충격 뒤 −2% 주입하면 탐지, 주입 없으면 탐지 안 함
    rng = np.random.default_rng(7)
    n = 600
    start = pd.Timestamp("2005-01-03")
    dates = pd.date_range(start, periods=n * 7, freq="D")
    dfii = pd.Series(np.cumsum(rng.normal(0, 0.06, len(dates))) + 2, index=dates)
    dfii = dfii[dfii.index.weekday < 5]
    wk = weekly(dfii)
    q = float(np.quantile(wk[wk.week_end <= TRAIN_END]["delta"].dropna(), 0.9))
    global TRAIN_LOW
    TRAIN_LOW = float(np.quantile(wk[wk.week_end <= TRAIN_END]["delta"].dropna(), 0.1))
    base = pd.Series(rng.normal(0.0005, 0.01, len(dfii)), index=dfii.index)
    for inject in (0.0, -0.02):
        ret = base.copy()
        if inject:
            for _, row in wk[wk.delta >= q].iterrows():
                t = row["T"]
                j = ret.index.searchsorted(t)
                ret.iloc[j + 1:j + 6] += inject / 5
        pxs = (1 + ret).cumprod()
        r = analyse(wk, pxs, q, 0.0005, np.random.default_rng(1), perm=1000)
        if inject:
            check(r["D"] < 0 and r["pOneSided"] < 0.01, f"주입 {inject:+.0%}: D<0·p<0.01 (p={r['pOneSided']:.4f}, 판정 {r['verdict']})")
        else:
            check(r["pOneSided"] > 0.02, f"주입 없음: 탐지 안 함 (p={r['pOneSided']:.3f}, 판정 {r['verdict']})")
    # 4) 판정 규칙
    bk = {"a": {"D": -0.01, "shocks": 10}, "b": {"D": -0.01, "shocks": 10}, "c": {"D": 0.01, "shocks": 10}}
    check(verdict(-0.01, 0.01, 30, bk, -0.01, 0.0005) == "ECONOMIC", "p≤α·구간 2/3 음·이득>비용 → ECONOMIC")
    check(verdict(-0.01, 0.04, 30, bk, -0.01, 0.0005) == "INCONCLUSIVE", "α<p≤0.05 → INCONCLUSIVE")
    check(verdict(0.01, 0.001, 30, bk, 0.01, 0.0005) == "REJECT", "D≥0 → REJECT")
    check(verdict(-0.01, 0.01, 10, bk, -0.01, 0.0005) == "INCONCLUSIVE", "충격 n<20 → INCONCLUSIVE")
    print("\nSELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
