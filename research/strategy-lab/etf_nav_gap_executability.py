#!/usr/bin/env python3
"""ETF 종가 괴리 — 실행 가능성(15:19 판단). 사전등록 findings/etf-nav-gap-executability-preregistration-2026-10.md (커밋 986f5995) 그대로.

    python research/strategy-lab/etf_nav_gap_executability.py --collect     # KIS VTS 분봉 수집(재개 가능, 수익률 안 봄)
    python research/strategy-lab/etf_nav_gap_executability.py --selftest
    python research/strategy-lab/etf_nav_gap_executability.py               # → findings/etf-nav-gap-executability-results-2026-10.{md,json}

분봉 저장(gitignore): .cache/etf_minute/<code>.jsonl — 줄 = {"date", "bars": [[hhmmss, close, volume], ...]} (13:21~15:30).
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
sys.path.insert(0, str(HERE))
import etf_nav_gap_explore as eg  # noqa: E402

OUT = HERE / "findings" / "etf-nav-gap-executability-results-2026-10"
MIN_DIR = HERE / ".cache" / "etf_minute"
FUT_DIR = HERE / ".cache" / "futures_minute"
START, END = "2025-10-10", "2026-09-03"
CODES = ["069500", "229200", "102110", "148020", "232080", "152100", "105190", "069660", "270810", "293180", "354500", "448100", "316670", "450910", "304770"]
FUT = {"코스피 200": "kospi200", "코스닥 150": "kosdaq150"}
TH, LIQ, COST, BLOCK, NBOOT, SEED = -0.005, 1e9, 3.54e-4, 10, 2000, 20261009
PATH = "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"


# ───────────────────── 수집 ─────────────────────
def panel():
    import run_night_forward as nf
    p = nf.fb_panel(2025)
    return p[p["code"].isin(CODES)].sort_values(["code", "date"]).reset_index(drop=True)


def collect():
    from engine.live.kisVtsClient import BASE_URL, KisVtsClient, _call
    c = KisVtsClient()
    p = panel()
    days = sorted(d.strftime("%Y%m%d") for d in p["date"].unique() if START <= d.strftime("%Y-%m-%d") <= END)
    MIN_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    for code in CODES:
        f = MIN_DIR / f"{code}.jsonl"
        done = {json.loads(l)["date"] for l in open(f, encoding="utf-8")} if f.exists() else set()
        listed = {d.strftime("%Y%m%d") for d in p.loc[p["code"] == code, "date"]}
        todo = [d for d in days if d in listed and d not in done]
        with open(f, "a", encoding="utf-8") as fh:
            for d in todo:
                _, resp = _call("GET", BASE_URL + PATH, f"분봉({code} {d})", headers=c._headers("FHKST03010230"),
                                params={"FID_ETC_CLS_CODE": "", "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code, "FID_INPUT_HOUR_1": "153000",
                                        "FID_PW_DATA_INCU_YN": "N", "FID_INPUT_DATE_1": d, "FID_FAKE_TICK_INCU_YN": "N"}, timeout=20)
                rows = [r for r in (resp.get("output2") or []) if r.get("stck_cntg_hour") and r.get("stck_bsop_date") == d]   # 교훈81: 요청일 대조
                bars = sorted([r["stck_cntg_hour"], float(r["stck_prpr"]), float(r.get("cntg_vol") or 0)] for r in rows)
                fh.write(json.dumps({"date": d, "bars": bars, "rt_cd": resp.get("rt_cd")}) + "\n")
                fh.flush()
                n += 1
        print(f"{code}: 새 {len(todo)}일 (누적 {len(done) + len(todo)})", flush=True)
    print(f"수집 끝 — 호출 {n}")


# ───────────────────── 계산 ─────────────────────
def bar_at(bars, hhmmss):
    """hhmmss 이하 마지막 봉 종가(없으면 None)."""
    x = [b for b in bars if b[0] <= hhmmss]
    return x[-1][1] if x else None


def fut_at(product, date):
    f = FUT_DIR / f"{product}_day" / f"{date}.parquet"
    if not f.exists():
        return None, None
    d = pd.read_parquet(f, columns=["hhmmss", "close"])
    bars = sorted([h, float(c)] for h, c in zip(d["hhmmss"].astype(str), d["close"]))
    return bar_at(bars, "151900"), bar_at(bars, "153000")


def build_rows(p, minute, fut):
    """p: 일별 패널(CODES·기간), minute: {(code, 'YYYY-MM-DD'): bars}, fut: {(product, date): (F1519, F1530)} → 행 DataFrame."""
    p = p.sort_values(["code", "date"]).copy()
    g = p.groupby("code")
    p["gap_c"] = p["close"] / p["nav"] - 1
    p["prev_val"] = g["val"].shift(1)
    p["dist_next"] = ((g["idx"].shift(-1) / p["idx"] - 1) - (g["nav"].shift(-1) / p["nav"] - 1)) > 0.002
    p["nxt_ex"] = (g["close"].shift(-1) / p["close"] - 1) - (g["idx"].shift(-1) / p["idx"] - 1)
    p["close_n"], p["idx_n"] = g["close"].shift(-1), g["idx"].shift(-1)
    ds = p["date"].dt.strftime("%Y-%m-%d")
    p = p[(ds >= START) & (ds <= END) & p["nxt_ex"].notna() & (p["nxt_ex"].abs() < 0.2)].copy()
    ds = p["date"].dt.strftime("%Y-%m-%d")
    out = []
    for (_, r), d in zip(p.iterrows(), ds):
        bars = minute.get((r["code"], d))
        f19, f30 = fut.get((FUT[r["idx_name"]], d), (None, None))
        if not bars or f19 is None or f30 is None:
            continue
        p19, p30 = bar_at(bars, "151900"), bar_at(bars, "153000")
        if p19 is None:
            continue
        inav19 = r["nav"] * f19 / f30
        idx19 = r["idx"] * f19 / f30
        out.append(dict(date=d, code=r["code"], name=r["name"], index=r["idx_name"], gap_c=r["gap_c"], gap_19=p19 / inav19 - 1,
                        val=r["val"], prev_val=r["prev_val"], dist_next=bool(r["dist_next"]), nxt_ex=r["nxt_ex"],
                        ex_1519=(r["close_n"] / p19 - 1) - (r["idx_n"] / idx19 - 1), auction_move=(r["close"] / p19 - 1) - (f30 / f19 - 1),
                        p30_match=None if p30 is None else bool(abs(p30 - r["close"]) < 1e-9)))
    return pd.DataFrame(out)


def signals(D):
    O = D[(D["gap_c"] <= TH) & (D["val"] >= LIQ) & ~D["dist_next"]]
    R = D[(D["gap_19"] <= TH) & (D["prev_val"] >= LIQ) & ~D["dist_next"]]
    return O, R


def block_ci(x, rng):
    x = np.asarray(x, float)
    n = len(x)
    if n < 2 * BLOCK:
        return float("nan"), float("nan")
    nb = int(np.ceil(n / BLOCK))
    st = rng.integers(0, n - BLOCK + 1, (NBOOT, nb))
    idx = (st[:, :, None] + np.arange(BLOCK)).reshape(NBOOT, -1)[:, :n]
    m = x[idx].mean(1)
    return float(np.percentile(m, 5)), float(np.percentile(m, 95))


def decide(mR, mO, lo_net, days):
    if days < 30:
        return "INCONCLUSIVE"
    if mR - COST <= 0:
        return "NOT_EXECUTABLE"
    if lo_net > 0 and mR >= 0.5 * mO:
        return "EXECUTABLE"
    return "INCONCLUSIVE"


def load_minute():
    m = {}
    for f in MIN_DIR.glob("*.jsonl"):
        for l in open(f, encoding="utf-8"):
            r = json.loads(l)
            d = r["date"]
            m[(f.stem, f"{d[:4]}-{d[4:6]}-{d[6:]}")] = r["bars"]
    return m


def run():
    p = panel()
    minute = load_minute()
    dates = sorted({d for _, d in minute})
    fut = {(pr, d): fut_at(pr, d) for pr in FUT.values() for d in dates}
    D = build_rows(p, minute, fut)
    O, R = signals(D)
    rng = np.random.default_rng(SEED)
    sO, sR = O.groupby("date")["nxt_ex"].mean(), R.groupby("date")["nxt_ex"].mean()
    mO, mR = float(sO.mean()) if len(sO) else float("nan"), float(sR.mean()) if len(sR) else float("nan")
    lo, hi = block_ci(sR.to_numpy() - COST, rng)
    verdict = decide(mR, mO, lo, len(sR))
    keyO, keyR = set(zip(O["date"], O["code"])), set(zip(R["date"], R["code"]))
    rec = dict(
        rows=len(D), etfs=int(D["code"].nunique()), days=int(D["date"].nunique()),
        p30_match_rate=float(D["p30_match"].dropna().mean()) if D["p30_match"].notna().any() else None,
        corr_gap=float(D[["gap_19", "gap_c"]].corr().iloc[0, 1]),
        O=dict(n=len(O), days=len(sO), mean_bp=mO * 1e4), R=dict(n=len(R), days=len(sR), mean_bp=mR * 1e4, net_ci90_bp=[lo * 1e4, hi * 1e4]),
        hit_O_in_R=len(keyO & keyR) / len(keyO) if keyO else None, hit_R_in_O=len(keyO & keyR) / len(keyR) if keyR else None,
        R_1519_mean_bp=float(R.groupby("date")["ex_1519"].mean().mean() * 1e4) if len(R) else None,
        auction_move_R_bp=float(R["auction_move"].mean() * 1e4) if len(R) else None,
        by_index={k: dict(O_days=int(O[O["index"] == k]["date"].nunique()), O_bp=float(O[O["index"] == k].groupby("date")["nxt_ex"].mean().mean() * 1e4) if (O["index"] == k).any() else None,
                          R_days=int(R[R["index"] == k]["date"].nunique()), R_bp=float(R[R["index"] == k].groupby("date")["nxt_ex"].mean().mean() * 1e4) if (R["index"] == k).any() else None)
                  for k in FUT},
        by_etf_R=R.groupby("name").size().sort_values(ascending=False).head(8).to_dict())
    out = dict(verdict=verdict, **rec)
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    f = lambda x: "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:+.1f}"
    sig = "있음" if verdict == "EXECUTABLE" else ("없음" if verdict == "NOT_EXECUTABLE" else "판단 불가")
    L = ["---", "track: kr", "factor: etf-nav-gap-executability", "date: 2026-10-09", f"verdict: {verdict}",
         "criteria_version: research-only (etf-nav-gap-executability-preregistration-2026-10)",
         'conditions: ["코스피 200·코스닥 150 패시브 ETF 15종, 2025-10-10 ~ 2026-09-03", "R = 15:19 가격 ÷ 추정 iNAV(NAV × F1519/F1530) − 1 ≤ −0.5% → 종가 단일가 매수", "O = 종가 ÷ NAV − 1 ≤ −0.5%(사후)", "다음 날 ETF − 기초지수, 비용 3.54bp"]',
         "reason: >-", f"  실행 가능 신호: {sig} · 경제성: {'통과' if verdict == 'EXECUTABLE' else '미달/판단 불가'}. R 신호일 {len(sR)}일 평균 {f(mR * 1e4)}bp(비용 후 90% [{f(lo * 1e4)}, {f(hi * 1e4)}]) vs O {len(sO)}일 {f(mO * 1e4)}bp. (스크립트 판정)", "---", "",
         "# ETF 종가 괴리 — 실행 가능성(15:19 판단) 결과", "",
         f"ETF {rec['etfs']}종 · {rec['days']}거래일 · {rec['rows']:,}행. 15:30 분봉 종가 = 일별 종가 일치율 {f(None if rec['p30_match_rate'] is None else rec['p30_match_rate'] * 100)}%.", "",
         "| 신호 | 건수 | 신호일 | 다음 날 초과 평균(bp) | 비용 후(bp) | 비용 후 90% 구간 |", "|---|---:|---:|---:|---:|---|",
         f"| O 사후(종가 ÷ NAV) | {len(O)} | {len(sO)} | {f(mO * 1e4)} | {f((mO - COST) * 1e4)} | |",
         f"| **R 15:19 판단 → 종가 매수** | {len(R)} | {len(sR)} | {f(mR * 1e4)} | {f((mR - COST) * 1e4)} | [{f(lo * 1e4)}, {f(hi * 1e4)}] |",
         "", f"판정 **{verdict}** (사전등록 §4: 비용 후 > 0 ∧ 90% 하단 > 0 ∧ m_R ≥ 0.5 × m_O, 신호일 ≥ 30).", "", "## 기록", "",
         f"- gap_19 와 gap_C 상관 {rec['corr_gap']:.2f} · O 중 R 도 신호 {f(None if rec['hit_O_in_R'] is None else rec['hit_O_in_R'] * 100)}% · R 중 O 도 신호 {f(None if rec['hit_R_in_O'] is None else rec['hit_R_in_O'] * 100)}%",
         f"- R 을 15:19 가격에 샀다면 {f(rec['R_1519_mean_bp'])}bp · R 신호의 단일가 동안 ETF − 추정 iNAV 움직임 {f(rec['auction_move_R_bp'])}bp",
         "- 지수별: " + " · ".join(f"{k} O {v['O_days']}일 {f(v['O_bp'])}bp / R {v['R_days']}일 {f(v['R_bp'])}bp" for k, v in rec["by_index"].items()),
         "- R 신호가 많은 ETF: " + " · ".join(f"{k} {v}" for k, v in rec["by_etf_R"].items())]
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[11:]))
    return 0


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        ok &= bool(c)
        print(("PASS " if c else "FAIL ") + n)

    bars = [["151800", 99.0, 1], ["151900", 100.0, 1], ["153000", 101.0, 5]]
    check("bar_at: 이하 마지막 봉", bar_at(bars, "151900") == 100.0 and bar_at(bars, "152500") == 100.0 and bar_at(bars, "151000") is None)
    d0, d1 = pd.Timestamp("2025-10-13"), pd.Timestamp("2025-10-14")
    p = pd.DataFrame([dict(date=d0, code="A", name="A", idx_name="코스닥 150", close=99.0, nav=100.0, idx=1000.0, val=2e9),
                      dict(date=d1, code="A", name="A", idx_name="코스닥 150", close=100.0, nav=100.0, idx=1000.0, val=2e9)])
    # 전일 거래대금이 있어야 R → 앞에 하루 추가
    pm1 = pd.DataFrame([dict(date=pd.Timestamp("2025-10-10"), code="A", name="A", idx_name="코스닥 150", close=100.0, nav=100.0, idx=1000.0, val=2e9)])
    P = pd.concat([pm1, p]).reset_index(drop=True)
    minute = {("A", "2025-10-13"): [["151900", 98.0, 1], ["153000", 99.0, 1]], ("A", "2025-10-10"): [["151900", 100.0, 1], ["153000", 100.0, 1]]}
    fut = {("kosdaq150", "2025-10-13"): (1000.0, 1010.0), ("kosdaq150", "2025-10-10"): (1000.0, 1000.0)}
    D = build_rows(P, minute, fut)
    r = D[D["date"] == "2025-10-13"].iloc[0]
    check("gap_19 = 98 ÷ (100 × 1000/1010) − 1", abs(r["gap_19"] - (98 / (100 * 1000 / 1010) - 1)) < 1e-12)
    check("다음 날 초과 = 100/99 − 1 − 0", abs(r["nxt_ex"] - (100 / 99 - 1)) < 1e-12 and r["p30_match"])
    O, R = signals(D)
    check("O·R 둘 다 신호(−1% · −3%)", len(O) == 1 and len(R) == 1)
    check("판정 산수", decide(0.003, 0.004, 0.0001, 40) == "EXECUTABLE" and decide(0.0003, 0.004, 0.0, 40) == "NOT_EXECUTABLE"
          and decide(0.001, 0.004, 0.0001, 40) == "INCONCLUSIVE" and decide(0.003, 0.004, 0.0001, 20) == "INCONCLUSIVE")
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--collect", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else (collect() or 0) if a.collect else run())
