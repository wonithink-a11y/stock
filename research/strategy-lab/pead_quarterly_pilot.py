#!/usr/bin/env python
"""PEAD 분기 SUE 로컬 파일럿 — findings/pead-annual-precheck-2026-08.md가
"표준 분기 PEAD는 A3b(연간 EPS만)로 재현 불가"라 정정한 뒤, 실제 DART
`fnlttSinglAcnt.json`을 소규모(유동성 상위 100종목) 실측해 분기 단독
순이익을 얻는 방법을 확인했다: reprtCode=11012(반기)·11014(3분기)의
`thstrm_amount`가 이미 **해당 분기 단독** 값이다(반기 report의 thstrm_amount는
Q2 단독, 3분기 report의 thstrm_amount는 Q3 단독) - 삼성전자 2023년 실측으로
Q1+Q2=반기누적, (Q1+Q2)+Q3=3분기누적이 소수점 단위까지 일치함을 확인. Q4는
A3의 연간 총계에서 3분기 누적(`thstrm_add_amount`)을 빼면 되므로 추가 DART
호출이 필요 없다. `frmtrm_amount`도 전년동기 단독값을 바로 준다 - SUE의
분자(당기-전년동기)를 우리가 따로 회사 시계열을 이어붙이지 않고 DART 응답
한 건에서 바로 얻는다.

전면 수집(정책 파일·GH Actions, 🔴 승인 대상) 전에, 유동성 상위 100종목만
이 세션의 DART_API_KEY로 직접 호출해(로컬 진단 전용, `data/backfill/`에
쓰지 않음 - 규칙 4) 분기 SUE가 실제로 T+20/T+60 드리프트와 상관이 있는지
정찰한다. 통과하면 그때 정식 A3e 수집기 설계를 다시 승인받는다.

  python pead_quarterly_pilot.py
"""
import gzip
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import requests  # noqa: E402

from engine.data.a2aProvider import A2aProvider  # noqa: E402
from engine.data.calendar import TradingCalendar  # noqa: E402
from engine.runner import _drop_suspension_rows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
START, END = "2016-01-01", "2026-08-14"
MIN_TURNOVER = 100_000_000.0
COST_RT_BPS = 30.0
HORIZONS = [20, 60]
N_DECILES = 10
N_PILOT_TICKERS = 100
MIN_PRIOR_DEPS = 2
BASE = "https://opendart.fss.or.kr/api"
KEY = os.environ.get("DART_API_KEY", "")
SECRET_RE = re.compile(r"(crtfc_key=)[^&\s\"')]+")
REPRT_CODES = ["11013", "11012", "11014"]  # Q1·반기(=Q2단독)·3분기(=Q3단독)


def redact(s):
    return SECRET_RE.sub(r"\1<redacted>", str(s))


def load_a3_grid():
    rows = []
    for fname in sorted(os.listdir(A3_DIR)):
        if not fname.endswith(".jsonl.gz"):
            continue
        with gzip.open(os.path.join(A3_DIR, fname), "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                rows.append({"ticker": d["ticker"], "corp": d["corp"],
                             "fiscalYear": d["fiscalYear"], "netIncomeFY": d.get("netIncome")})
    return pd.DataFrame(rows)


def pick_pilot_tickers(a3_grid, bars_by_ticker, n):
    avg_turnover = {}
    for ticker in a3_grid["ticker"].unique():
        bars = bars_by_ticker.get(ticker)
        if bars is None or bars.empty:
            continue
        avg_turnover[ticker] = float((bars["close"] * bars["volume"]).mean())
    ranked = sorted(avg_turnover, key=avg_turnover.get, reverse=True)
    return ranked[:n]


def dart_call(reprt_code, corp, year):
    if not KEY:
        raise RuntimeError("DART_API_KEY not set")
    params = {"crtfc_key": KEY, "corp_code": corp, "bsns_year": str(year), "reprt_code": reprt_code}
    try:
        r = requests.get(f"{BASE}/fnlttSinglAcnt.json", params=params, timeout=(10, 60))
    except Exception as e:
        return None, redact(str(e))
    try:
        body = r.json()
    except Exception as e:
        return None, redact(str(e))
    if body.get("status") != "000":
        return None, body.get("status")
    return body.get("list", []), None


def extract_net_income(rows):
    """CFS 우선, 없으면 OFS. account_nm=당기순이익(손실), sj_div=IS,
    가장 작은 ord(중복 표기행 중 대표행)."""
    for fs_div in ("CFS", "OFS"):
        cands = [r for r in rows if r.get("fs_div") == fs_div and r.get("sj_div") == "IS"
                 and r.get("account_nm") == "당기순이익(손실)"]
        if cands:
            cands.sort(key=lambda r: int(r.get("ord", 999)))
            r = cands[0]
            def num(x):
                try:
                    return float(str(x).replace(",", ""))
                except (TypeError, ValueError):
                    return None
            return {"thstrm": num(r.get("thstrm_amount")), "frmtrm": num(r.get("frmtrm_amount")),
                     "thstrmAdd": num(r.get("thstrm_add_amount")), "rceptNo": r.get("rcept_no")}
    return None


def build_quarterly_panel(a3_grid, tickers):
    """(ticker, fiscalYear)마다 Q1~Q4 단독 순이익 + 전년동기 값을 모은다."""
    grid = a3_grid[a3_grid["ticker"].isin(tickers)].drop_duplicates(["ticker", "fiscalYear"])
    n_calls, n_fail = 0, 0
    records = []
    for _, row in grid.iterrows():
        ticker, corp, fy = row["ticker"], row["corp"], int(row["fiscalYear"])
        # Q4는 스킵 - A3(reprtCode 11011)엔 availableFrom이 이 grid 로더에 안 뽑혀
        # 있어 공시일을 알 수 없다(추가 호출 없이 재사용하려던 시도였으나 정보가
        # 없어 성립 안 함). Q1~Q3만으로도 파일럿 표본은 충분하다(연 4개 중 3개 유지).
        q_vals = {}
        for reprt_code, q_label in zip(REPRT_CODES, ["Q1", "Q2", "Q3"]):
            rows_, err = dart_call(reprt_code, corp, fy)
            n_calls += 1
            if err:
                n_fail += 1
                continue
            info = extract_net_income(rows_)
            if info is None:
                continue
            q_vals[q_label] = info
            time.sleep(0.15)
        for q_label in ["Q1", "Q2", "Q3"]:
            info = q_vals.get(q_label)
            if info is None or info["thstrm"] is None or info["frmtrm"] is None or not info["rceptNo"]:
                continue
            records.append({"ticker": ticker, "fiscalYear": fy, "quarter": q_label,
                             "availableFrom": info["rceptNo"][:8],
                             "thstrm": info["thstrm"], "frmtrm": info["frmtrm"]})
        print(f"  {ticker} FY{fy}: Q1={('Q1' in q_vals)} Q2={('Q2' in q_vals)} Q3={('Q3' in q_vals)} "
              f"calls={n_calls} fails={n_fail}", end="\r")
    print()
    return pd.DataFrame(records), n_calls, n_fail


def compute_sue(panel):
    panel = panel.copy()
    panel["deps"] = panel["thstrm"] - panel["frmtrm"]
    panel = panel.sort_values(["ticker", "fiscalYear", "quarter"]).reset_index(drop=True)
    out = []
    for ticker, g in panel.groupby("ticker"):
        g = g.sort_values(["fiscalYear", "quarter"]).reset_index(drop=True)
        g["priorDepsStd"] = g["deps"].shift(1).rolling(8, min_periods=MIN_PRIOR_DEPS).std()
        g["priorDepsCount"] = g["deps"].shift(1).rolling(8, min_periods=1).count()
        out.append(g)
    merged = pd.concat(out, ignore_index=True)
    merged["sue"] = merged["deps"] / merged["priorDepsStd"]
    return merged


def build_events(sue_df, bars_by_ticker):
    rows = []
    for _, r in sue_df.dropna(subset=["sue", "priorDepsStd"]).iterrows():
        if r["priorDepsStd"] == 0 or r["priorDepsCount"] < MIN_PRIOR_DEPS:
            continue
        ticker = r["ticker"]
        bars = bars_by_ticker.get(ticker)
        if bars is None or bars.empty:
            continue
        close, open_, vol = bars["close"], bars["open"], bars["volume"]
        idx = close.index.astype(str)
        avail = f"{r['availableFrom'][:4]}-{r['availableFrom'][4:6]}-{r['availableFrom'][6:8]}"
        after = idx[idx >= avail]
        if len(after) == 0:
            continue
        i = idx.get_loc(after[0])
        if i + 1 >= len(idx):
            continue
        entry_i = i + 1
        entry_price = float(open_.iloc[entry_i])
        if entry_price <= 0 or entry_i < 20:
            continue
        turnover20 = float((close * vol).iloc[max(0, entry_i - 20):entry_i].mean())
        row = {"ticker": ticker, "availableFrom": avail, "sue": float(r["sue"]), "turnover20": turnover20}
        ok = True
        for h in HORIZONS:
            exit_i = entry_i + h
            if exit_i >= len(idx):
                ok = False
                break
            row[f"ret_t{h}"] = float(open_.iloc[exit_i]) / entry_price - 1
        if ok:
            rows.append(row)
    return pd.DataFrame(rows)


def rank_ic(factor_vals, fwd_rets):
    if len(factor_vals) < 5:
        return None
    fr = pd.Series(factor_vals).rank()
    rr = pd.Series(fwd_rets).rank()
    return float(np.corrcoef(fr, rr)[0, 1])


def decile_analysis(events, ret_col, cost_bps=COST_RT_BPS):
    events = events.copy()
    events["month"] = events["availableFrom"].str.slice(0, 7)
    months = sorted(events["month"].unique())
    decile_rets = {d: [] for d in range(1, N_DECILES + 1)}
    monthly_ics = []
    for m in months:
        g = events[events["month"] == m]
        if len(g) < N_DECILES:
            continue
        try:
            ranks = g["sue"].rank(ascending=False, method="first")
            deciles = pd.qcut(ranks, min(N_DECILES, len(g)), labels=False, duplicates="drop") + 1
        except ValueError:
            continue
        for d in range(1, int(deciles.max()) + 1 if len(deciles) else 1):
            sel = g.loc[deciles == d, ret_col]
            if len(sel):
                decile_rets[d].append(float(sel.mean()) - cost_bps / 1e4)
        ic = rank_ic(g["sue"].values, g[ret_col].values)
        if ic is not None:
            monthly_ics.append(ic)
    decile_avg = {d: (round(float(np.mean(v)), 4) if v else None) for d, v in decile_rets.items()}
    top_d = min(decile_avg, key=lambda d: (decile_avg[d] is None, d)) if decile_avg else None
    spread = None
    present = [d for d in decile_avg if decile_avg[d] is not None]
    if present:
        spread = round(decile_avg[min(present)] - decile_avg[max(present)], 4)
    ic_mean = round(float(np.mean(monthly_ics)), 4) if monthly_ics else None
    ic_tstat = (round(ic_mean / (np.std(monthly_ics) / np.sqrt(len(monthly_ics))), 2)
                if monthly_ics and np.std(monthly_ics) > 0 else None)
    return {"monthsUsed": len(monthly_ics), "nEvents": len(events), "decileAvgReturn": decile_avg,
            "topMinusBottomDecile": spread, "meanMonthlyIC": ic_mean, "icTstat": ic_tstat}


def main():
    t0 = time.time()
    if not KEY:
        print("DART_API_KEY not set - export it inline for this run only")
        sys.exit(1)

    a3_grid = load_a3_grid()
    tickers_all = sorted(a3_grid["ticker"].unique())
    calendar = TradingCalendar(repo_root=REPO_ROOT)
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    bars_raw = a2a.load(tickers_all, START, END, universe_hash="pead-quarterly-pilot")
    bars_by_ticker = {t: _drop_suspension_rows(df) for t, df in bars_raw.items()}
    print(f"bars loaded: {len(bars_by_ticker)} tickers ({time.time()-t0:.0f}s)")

    pilot_tickers = pick_pilot_tickers(a3_grid, bars_by_ticker, N_PILOT_TICKERS)
    print(f"pilot tickers: {len(pilot_tickers)} (top by avg turnover)")

    panel, n_calls, n_fail = build_quarterly_panel(a3_grid, pilot_tickers)
    print(f"DART calls: {n_calls}, failed: {n_fail}, quarterly records: {len(panel)} ({time.time()-t0:.0f}s)")

    sue_df = compute_sue(panel)
    n_valid = sue_df["sue"].notna().sum()
    print(f"SUE computable: {n_valid}/{len(sue_df)}")

    events = build_events(sue_df, bars_by_ticker)
    print(f"events with full T+{max(HORIZONS)} forward return: {len(events)}")
    eligible = events[events["turnover20"] >= MIN_TURNOVER]
    print(f"eligible (turnover20>={MIN_TURNOVER:,.0f}): {len(eligible)}")

    results = {}
    for h in HORIZONS:
        for label, df_ in [("allEvents", events), ("eligibleLiquidity", eligible)]:
            key = f"t{h}_{label}"
            results[key] = decile_analysis(df_, f"ret_t{h}")
            r = results[key]
            print(f"  {key}: IC={r['meanMonthlyIC']} t={r['icTstat']} "
                  f"top-bottom={r['topMinusBottomDecile']} months={r['monthsUsed']} n={r['nEvents']}")

    out_dir = os.path.join(REPO_ROOT, "research", "strategy-lab", "reports",
                            "2026-08-26-pead-quarterly-pilot")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "pead-quarterly-pilot.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "PEAD 진짜(분기) SUE 로컬 파일럿 - 유동성 상위 100종목, DART "
                       "fnlttSinglAcnt.json 실시간 호출(로컬 진단 전용, data/backfill/ "
                       "미기록). findings/pead-annual-precheck-2026-08.md 후속.",
            "nPilotTickers": len(pilot_tickers), "nCalls": n_calls, "nFailedCalls": n_fail,
            "nQuarterlyRecords": len(panel), "nValidSue": int(n_valid),
            "nEvents": len(events), "nEligible": len(eligible),
            "minTurnover": MIN_TURNOVER, "costBps": COST_RT_BPS, "horizons": HORIZONS,
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nsaved: {out_path} ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
