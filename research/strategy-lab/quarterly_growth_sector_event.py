#!/usr/bin/env python3
"""분기 실적 급변 + 연속 흑자·매출 가속 + 업종 분리 — 결과 산출.
사전등록: findings/quarterly-growth-sector-preregistration-2026-10.md. 정의·구간·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.

    python research/strategy-lab/quarterly_growth_sector_event.py --selftest
    python research/strategy-lab/quarterly_growth_sector_event.py   # data/quarterly-multi + A2a 캐시 + docs/data/a5-latest.json 필요

판정 셀 C = B ∧ A ∧ G, 판정 값 = 업종 중립 초과수익(60거래일), 동종 ≥ 8. 나머지(B·BA·BG, 동반형/개별형, 동종 5·10, 보유 20·120)는 기록 전용.
산출: findings/quarterly-growth-sector-results-2026-10.{md,json}
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))
import quarterly_acceleration_event as q

PANELS = sorted(glob.glob(str(HERE / "data" / "quarterly-multi" / "quarterly-multi-panel-*.jsonl")))
A5 = ROOT / "docs" / "data" / "a5-latest.json"
OUT = HERE / "findings" / "quarterly-growth-sector-results-2026-10"
LIQ_MIN, COST_BP, STRESS_BP = 2e9, 33.5, 67.0
SEED, N_NULL, N_BOOT = 20261011, 1000, 2000
WINDOWS = {"TRAIN": (2016, 2020), "VALID": (2021, 2022), "TEST": (2023, 2025)}
MIN_PEERS_MAIN, MIN_PEERS_REC = 8, (5, 10)
MIN_LIQ_PEERS, MIN_G_PEERS = 5, 5
G_MIN, OP_MULT, EPS = 0.20, 1.3, 1e-9
PERIOD_END = {"11013": "03", "11012": "06", "11014": "09", "11011": "12"}
QOF = {"11013": 1, "11012": 2, "11014": 3}
LAG_DAYS = {"11013": 100, "11012": 100, "11014": 100, "11011": 120}


def window_of(year):
    for k, (a, b) in WINDOWS.items():
        if a <= year <= b:
            return k
    return None


def growth(cur, prev):
    if cur is None or prev is None or not (cur > 0 and prev > 0):
        return None
    return cur / prev - 1


def period_end(dt):
    """'2024.01.01 ~ 2024.03.31' → '20240331'."""
    try:
        return dt.split("~")[1].strip().replace(".", "")
    except Exception:
        return None


def pit_ok(avail, pend, lag):
    try:
        return datetime.strptime(avail, "%Y%m%d") <= datetime.strptime(pend, "%Y%m%d") + timedelta(days=lag)
    except Exception:
        return False


def load_records(paths):
    """패널 → {(corp, year, reprt): {fs: rec}} (같은 키의 중복은 마지막 것)."""
    by = {}
    for p in paths:
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            by.setdefault((r["corp"], r["year"], r["reprt"]), {})[r["fsDiv"]] = r
    return by


def build_quarters(by):
    """분기 시계열 {(corp, t): {rev, rev_prev, op, op_prev, fs, date, ticker, year, q}}, t = year*4+q. 제외 집계 포함."""
    out, ex = {}, defaultdict(int)

    def val(rec, name):
        return rec.get(name) or {}

    for (corp, yr, rp), fsd in by.items():
        if rp == "11011":
            continue
        for fs in ("CFS", "OFS"):
            rec = fsd.get(fs)
            if rec is None:
                continue
            pend = period_end(rec.get("dt") or "")
            if not pend or pend[4:6] != PERIOD_END[rp]:
                ex["비12월 결산·기간 불일치"] += 1
                continue
            if not pit_ok(rec["availableFrom"], pend, LAG_DAYS[rp]):
                ex["지연·정정 공시"] += 1
                continue
            rev, op = val(rec, "revenue"), val(rec, "op_income")
            if rev.get("cur") is None or op.get("cur") is None:
                ex["계정 없음"] += 1
                continue
            t = yr * 4 + QOF[rp]
            if (corp, t) not in out or fs == "CFS":
                out[(corp, t)] = {"rev": rev["cur"], "rev_prev": rev.get("prev"), "op": op["cur"], "op_prev": op.get("prev"), "fs": fs,
                                  "date": rec["availableFrom"], "ticker": rec["ticker"], "year": yr, "q": QOF[rp]}
    # Q4 = 연간 − 3분기 누적 (같은 fs)
    for (corp, yr, rp), fsd in by.items():
        if rp != "11011":
            continue
        q3 = by.get((corp, yr, "11014"), {})
        for fs in ("CFS", "OFS"):
            a, b = fsd.get(fs), q3.get(fs)
            if a is None or b is None:
                continue
            pend = period_end(a.get("dt") or "")
            if not pend or pend[4:6] != "12" or not pit_ok(a["availableFrom"], pend, LAG_DAYS["11011"]):
                ex["Q4 지연·기간 불일치"] += 1
                continue
            ra, oa, rb, ob = a.get("revenue") or {}, a.get("op_income") or {}, b.get("revenue") or {}, b.get("op_income") or {}
            if None in (ra.get("cur"), oa.get("cur"), rb.get("cur_add"), ob.get("cur_add")):
                ex["Q4 계정 없음"] += 1
                continue
            rev_prev = ra["prev"] - rb["prev_add"] if ra.get("prev") is not None and rb.get("prev_add") is not None else None
            op_prev = oa["prev"] - ob["prev_add"] if oa.get("prev") is not None and ob.get("prev_add") is not None else None
            t = yr * 4 + 4
            if (corp, t) not in out or fs == "CFS":
                out[(corp, t)] = {"rev": ra["cur"] - rb["cur_add"], "rev_prev": rev_prev, "op": oa["cur"] - ob["cur_add"], "op_prev": op_prev,
                                  "fs": fs, "date": a["availableFrom"], "ticker": a["ticker"], "year": yr, "q": 4}
    return out, dict(ex)


def classify(qs):
    """분기 시계열 → 이벤트 [{ticker, corp, t, date, year, cells[], g}] 와 (연·분기)별 g 사전."""
    gmap = {k: growth(v["rev"], v["rev_prev"]) for k, v in qs.items()}
    ev = []
    for (corp, t), v in qs.items():
        g = gmap[(corp, t)]
        if g is None or v["op_prev"] is None or not v["ticker"]:
            continue
        ok = v["op"] > 0 and (v["op_prev"] <= 0 or v["op"] >= OP_MULT * v["op_prev"] - EPS)
        if not (g >= G_MIN - EPS and ok):
            continue
        cells = ["B"]
        p1, p2 = qs.get((corp, t - 1)), qs.get((corp, t - 2))
        a_ok = bool(p1 and p2 and p1["fs"] == v["fs"] == p2["fs"] and p1["op"] > 0 and p2["op"] > 0)      # v["op"] > 0 은 B 에서 이미
        g1 = gmap.get((corp, t - 1))
        g_ok = bool(p1 and p1["fs"] == v["fs"] and g1 is not None and g > g1)
        if a_ok:
            cells.append("BA")
        if g_ok:
            cells.append("BG")
        if a_ok and g_ok:
            cells.append("C")
        ev.append({"ticker": v["ticker"], "corp": corp, "t": t, "date": v["date"], "year": int(v["date"][:4]), "cells": cells, "g": g})
    return ev, gmap


def coincidence(qs, gmap, sector_of):
    """(t, 업종) → [(ticker, g)] 로 만들고, 사건마다 본인 제외 동종 중 g ≥ 20% 비율(동종 g 정의 ≥ 5)을 돌려주는 함수."""
    tick = {}
    for (corp, t), v in qs.items():
        g = gmap[(corp, t)]
        s = sector_of.get(v["ticker"])
        if g is not None and s and v["ticker"]:
            tick.setdefault((t, s), []).append((v["ticker"], g))

    def frac(ticker, t):
        s = sector_of.get(ticker)
        peers = [g for tk, g in tick.get((t, s), []) if tk != ticker]
        if len(peers) < MIN_G_PEERS:
            return None
        return sum(1 for g in peers if g >= G_MIN - EPS) / len(peers)
    return frac


def tercile_labels(vals):
    """동반도 3등분: 상위 1/3 = 동반형, 하위 1/3 = 개별형, 중간 제외. 동점은 같은 쪽(경계값 기준)."""
    v = np.array(vals, float)
    lo, hi = np.quantile(v, 1 / 3), np.quantile(v, 2 / 3)
    return ["개별" if x <= lo and lo < hi else "동반" if x >= hi and lo < hi else "중간" for x in v]


def sn_mats(close, vol, liq, sector_idx, n_sec, static_ok_by_n, h):
    """진입일×종목 업종 중립 초과(SN)·시장 초과(MK) 행렬. SN 은 동종 유동 ≥ MIN_LIQ_PEERS 일 때만, 최소 동종 N 은 static_ok_by_n[N] 마스크로 따로."""
    ret = close.shift(-h) / close - 1
    liquid = (liq >= LIQ_MIN) & (vol > 0) & ret.notna()
    R = ret.to_numpy()
    L = liquid.to_numpy()
    R0 = np.where(L, R, 0.0)
    mk = R0.sum(1) / np.maximum(L.sum(1), 1)
    MK = np.where(L, R - mk[:, None], np.nan)
    sec_sum = np.zeros((R.shape[0], n_sec))
    sec_cnt = np.zeros((R.shape[0], n_sec))
    for s in range(n_sec):
        cols = np.where(sector_idx == s)[0]
        if len(cols):
            sec_sum[:, s] = R0[:, cols].sum(1)
            sec_cnt[:, s] = L[:, cols].sum(1)
    SN = np.full(R.shape, np.nan)
    has = sector_idx >= 0
    cols = np.where(has)[0]
    ss, cc = sec_sum[:, sector_idx[cols]], sec_cnt[:, sector_idx[cols]]
    peers_cnt = cc - L[:, cols]
    peers_mean = (ss - R0[:, cols]) / np.maximum(peers_cnt, 1)
    ok = L[:, cols] & (peers_cnt >= MIN_LIQ_PEERS)
    SN[:, cols] = np.where(ok, R[:, cols] - peers_mean, np.nan)
    return {"SN": SN, "MK": MK, "liquid": L, "static_ok": static_ok_by_n}


def stats_arr(x, groups, rng):
    x = np.asarray(x, float)
    if not len(x):
        return {"n": 0, "mean_bp": None, "median_bp": None, "hit": None, "ci95": [None, None]}
    lo, hi = q.boot_ci(x, groups, rng, N_BOOT)
    return {"n": int(len(x)), "mean_bp": float(x.mean()), "median_bp": float(np.median(x)), "hit": float((x > 0).mean()), "ci95": [lo, hi]}


def main():
    import close_open_phase5 as p5
    a = p5.load()[["date", "ticker", "close", "volume", "liq"]]
    dates = np.sort(a.date.unique())
    close = a.pivot(index="date", columns="ticker", values="close").reindex(dates)
    vol = a.pivot(index="date", columns="ticker", values="volume").reindex(dates)
    liq = a.pivot(index="date", columns="ticker", values="liq").reindex(dates)
    items = json.load(open(A5, encoding="utf-8"))["items"]
    sector_of = {x["t"]: x["s"] for x in items if x.get("s")}
    sec_names = sorted(set(sector_of.values()))
    sidx = {s: i for i, s in enumerate(sec_names)}
    size = pd.Series(sector_of).value_counts()
    cols = list(close.columns)
    sector_idx = np.array([sidx.get(sector_of.get(c), -1) for c in cols])
    static_peers = np.array([size.get(sector_of.get(c), 0) - 1 if sector_of.get(c) else -1 for c in cols])
    static_ok = {n: static_peers >= n for n in (MIN_PEERS_MAIN,) + MIN_PEERS_REC}
    colpos = {c: i for i, c in enumerate(cols)}

    by = load_records(PANELS)
    qs, excl = build_quarters(by)
    ev, gmap = classify(qs)
    frac = coincidence(qs, gmap, sector_of)
    rng = np.random.default_rng(SEED)
    res = {"seed": SEED, "excluded": excl, "quarter_records": len(qs), "events_raw": {c: sum(1 for e in ev if c in e["cells"]) for c in ("B", "BA", "BG", "C")},
           "cells": {}, "records": {}}

    M60 = sn_mats(close, vol, liq, sector_idx, len(sec_names), static_ok, 60)
    # 이벤트 → (진입 인덱스, 열)
    for e in ev:
        e["i"] = q.entry_index(dates, e["date"])
        e["j"] = colpos.get(e["ticker"], -1)
        e["w"] = window_of(e["year"])
        e["frac"] = frac(e["ticker"], e["t"])
    n = len(dates)

    def frame(M, h, nmin):
        rows = []
        for e in ev:
            if e["w"] is None or e["j"] < 0 or e["i"] >= n - h or not M["liquid"][e["i"], e["j"]] or not M["static_ok"][nmin][e["j"]]:
                continue
            sn, mk = M["SN"][e["i"], e["j"]], M["MK"][e["i"], e["j"]]
            if np.isnan(sn) or np.isnan(mk):
                continue
            rows.append({"i": e["i"], "j": e["j"], "w": e["w"], "year": e["year"], "cells": e["cells"], "frac": e["frac"], "ticker": e["ticker"], "sn": sn * 1e4, "mk": mk * 1e4})
        return pd.DataFrame(rows)

    def pool(M, nmin):
        P = {}
        for i in range(n):
            row = M["SN"][i][M["static_ok"][nmin] & ~np.isnan(M["SN"][i])]
            if len(row):
                P[i] = row * 1e4
        return P

    def cell_df(df, c):
        return df[df.cells.apply(lambda x: c in x)]

    def summarize(d, with_cohort=True):
        out = {"events": int(len(d)), "firms": int(d.ticker.nunique()) if len(d) else 0}
        for w in WINDOWS:
            x = d[d.w == w]
            out[w] = {"sn": stats_arr(x.sn, x.i, rng), "mk_mean_bp": float(x.mk.mean()) if len(x) else None}
        oos = d[d.w != "TRAIN"]
        out["OOS"] = {"n": int(len(oos)), "sn_mean_bp": float(oos.sn.mean()) if len(oos) else None,
                      "net_bp": float(oos.sn.mean() - COST_BP) if len(oos) else None, "net_stress_bp": float(oos.sn.mean() - STRESS_BP) if len(oos) else None}
        oy = oos.groupby("year").sn.mean()
        out["oos_cohort_t"] = float(oy.mean() / (oy.std(ddof=1) / np.sqrt(len(oy)))) if len(oy) > 2 and oy.std(ddof=1) > 0 else None
        if with_cohort:
            coh = d.groupby("year").sn.agg(["count", "mean"])
            out["cohorts"] = {int(y): {"n": int(r["count"]), "mean_bp": float(r["mean"])} for y, r in coh.iterrows()}
            posc = coh["mean"].clip(lower=0)
            out["top_year_share_of_positive"] = float(posc.max() / posc.sum()) if posc.sum() > 0 else None
        return out

    # ── 판정 셀 (동종 8) ──
    for nmin in (MIN_PEERS_MAIN,) + MIN_PEERS_REC:
        df = frame(M60, 60, nmin)
        P = pool(M60, nmin)
        blk = {}
        for c in ("B", "BA", "BG", "C"):
            d = cell_df(df, c)
            s = summarize(d, with_cohort=(nmin == MIN_PEERS_MAIN))
            tr = d[d.w == "TRAIN"]
            s["null_p95_train_bp"] = q.null_p95(tr.groupby("i").size().to_dict(), P, rng, N_NULL) if len(tr) else None
            if c == "C" and nmin == MIN_PEERS_MAIN:
                arr = [d[d.w == w].sn.to_numpy() for w in WINDOWS]
                s["verdict"] = q.verdict(arr[0], arr[1], arr[2], s["null_p95_train_bp"] if s["null_p95_train_bp"] is not None else np.inf,
                                         s["OOS"]["net_bp"] if s["OOS"]["net_bp"] is not None else -1e9,
                                         s["OOS"]["net_stress_bp"] if s["OOS"]["net_stress_bp"] is not None else -1e9, s["oos_cohort_t"])
            blk[c] = s
        res["cells"][str(nmin)] = blk
        if nmin == MIN_PEERS_MAIN:
            # 증분: C vs (B − C), 같은 업종 중립 기준
            inc = {}
            dB, dC = cell_df(df, "B"), cell_df(df, "C")
            rest = dB[~dB.cells.apply(lambda x: "C" in x)]
            for w in WINDOWS:
                inc[w] = {"C_n": int((dC.w == w).sum()), "rest_n": int((rest.w == w).sum()),
                          "C_mean_bp": float(dC[dC.w == w].sn.mean()) if (dC.w == w).any() else None,
                          "rest_mean_bp": float(rest[rest.w == w].sn.mean()) if (rest.w == w).any() else None}
            res["increment"] = inc
            # 동반형/개별형: (연·분기=공시 연 + 분기) 안에서 3등분 — 사건의 t 로 묶는다
            tmap = {(e["ticker"], e["i"]): e["t"] for e in ev}
            df2 = df.copy()
            df2["t"] = [tmap.get((tk, i)) for tk, i in zip(df2.ticker, df2.i)]
            df2 = df2[df2.frac.notna() & df2.t.notna()]
            lab = pd.Series("중간", index=df2.index)
            for t, g in df2.groupby("t"):
                if len(g) >= 6:
                    lab.loc[g.index] = tercile_labels(g.frac.to_numpy())
            df2["lab"] = lab
            cs = {}
            for c in ("B", "C"):
                d = cell_df(df2, c)
                cs[c] = {}
                for L in ("동반", "개별"):
                    x = d[d.lab == L]
                    cs[c][L] = {w: {"n": int((x.w == w).sum()), "sn_mean_bp": float(x[x.w == w].sn.mean()) if (x.w == w).any() else None,
                                    "mk_mean_bp": float(x[x.w == w].mk.mean()) if (x.w == w).any() else None} for w in WINDOWS}
                    cs[c][L]["all"] = {"n": int(len(x)), "sn_mean_bp": float(x.sn.mean()) if len(x) else None, "mk_mean_bp": float(x.mk.mean()) if len(x) else None,
                                       "sn_median_bp": float(x.sn.median()) if len(x) else None, "hit": float((x.sn > 0).mean()) if len(x) else None}
            res["coincidence"] = cs
    # ── 기록: 보유 20·120 (동종 8, B·C 평균만) ──
    for h in (20, 120):
        Mh = sn_mats(close, vol, liq, sector_idx, len(sec_names), static_ok, h)
        df = frame(Mh, h, MIN_PEERS_MAIN)
        res["records"][str(h)] = {c: {w: {"n": int(((cell_df(df, c)).w == w).sum()), "sn_mean_bp": float(cell_df(df, c)[cell_df(df, c).w == w].sn.mean()) if (cell_df(df, c).w == w).any() else None}
                                      for w in WINDOWS} for c in ("B", "C")}
    OUT.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(res), encoding="utf-8")
    C = res["cells"][str(MIN_PEERS_MAIN)]["C"]
    print("C", C["verdict"], "events", C["events"], "| OOS sn mean", C["OOS"]["sn_mean_bp"], "| 제외", res["excluded"])


f = q.f


def render(r):
    N = str(MIN_PEERS_MAIN)
    C = r["cells"][N]["C"]
    v = C["verdict"]
    sig = "있음" if v in ("INFORMATION", "ECONOMIC", "ROBUST") else "없음"
    eco = "통과" if v in ("ECONOMIC", "ROBUST") else "미달"

    def row(c, x):
        return [f"{f(x[w]['sn']['mean_bp'])} [{f(x[w]['sn']['ci95'][0])}, {f(x[w]['sn']['ci95'][1])}] · {x[w]['sn']['n']}" for w in WINDOWS]

    L = ["---", "track: kr", "factor: quarterly-growth-sector", "date: 2026-10-08", f"verdict: {v}",
         "criteria_version: research-only (quarterly-growth-sector-preregistration-2026-10)",
         'conditions: ["C = 분기 기본 사건(매출 ≥ +20% ∧ 영업이익 흑자·×1.3) ∧ 3분기 연속 흑자 ∧ 매출 증가율 가속", "업종 중립 초과수익 60거래일(동종 ≥ 8)", "TRAIN 2016~2020/VALID 2021~22/TEST 2023~25", "비용 33.5bp"]',
         f"reason: >-\n  신호: {sig} · 경제성: {eco}. (스크립트가 계산한 판정 {v}. 업종 중립 기준, 공시 연도 10개 — 검출력 낮음.)", "---\n",
         "# 분기 실적 급변 + 연속 흑자·매출 가속 + 업종 분리 — 결과\n",
         "수치는 `quarterly_growth_sector_event.py` 가 계산해 그대로 옮긴 값이다. 정의·구간·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않았다.\n",
         "## 1. 판정 셀 C (동종 ≥ 8, 업종 중립 초과수익 60거래일)\n", f"**{v}** (신호: {sig} · 경제성: {eco})\n",
         "| 항목 | 값 |\n|---|---|",
         f"| 분기 레코드 / 원 이벤트 B·BA·BG·C | {r['quarter_records']} / {r['events_raw']['B']}·{r['events_raw']['BA']}·{r['events_raw']['BG']}·{r['events_raw']['C']} |",
         f"| C 이벤트(조건 충족·청산 가능) / 회사 | {C['events']} / {C['firms']} |",
         f"| TRAIN 평균 업종 중립 초과 | {f(C['TRAIN']['sn']['mean_bp'])}bp · 난수 바닥선 95p {f(C['null_p95_train_bp'])}bp |",
         f"| VALID / TEST | {f(C['VALID']['sn']['mean_bp'])} / {f(C['TEST']['sn']['mean_bp'])}bp |",
         f"| OOS 평균 = 손익분기 비용 | **{f(C['OOS']['sn_mean_bp'])}**bp (net {f(C['OOS']['net_bp'])} / 스트레스 {f(C['OOS']['net_stress_bp'])}) |",
         f"| OOS 코호트(연도) t / 상위 1개 연도 비중 | {f(C['oos_cohort_t'], 2)} / {f(C['top_year_share_of_positive'], 2)} |",
         f"| 제외 집계 | {json.dumps(r['excluded'], ensure_ascii=False)} |\n",
         "## 2. 셀 비교 — 업종 중립 초과 bp (구간 평균 [군집 부트스트랩 95%] · 이벤트)\n",
         "| 셀 | TRAIN | VALID | TEST | 난수 바닥선 | 중앙값(TRAIN/VALID/TEST) | 승률(전체 구간 평균 아님, TRAIN) |", "|---|---|---|---|---|---|---|"]
    for c in ("B", "BA", "BG", "C"):
        x = r["cells"][N][c]
        L.append(f"| {c}{' (판정)' if c == 'C' else ' (기록)'} | " + " | ".join(row(c, x)) + f" | {f(x['null_p95_train_bp'])} | " +
                 "/".join(f(x[w]["sn"]["median_bp"]) for w in WINDOWS) + f" | {f(x['TRAIN']['sn']['hit'] * 100 if x['TRAIN']['sn']['hit'] is not None else None)}% |")
    L.append("\n### 시장 초과(업종 미조정, 기록) — 구간 평균 bp\n")
    L.append("| 셀 | TRAIN | VALID | TEST |\n|---|---|---|---|")
    for c in ("B", "BA", "BG", "C"):
        x = r["cells"][N][c]
        L.append(f"| {c} | " + " | ".join(f(x[w]["mk_mean_bp"]) for w in WINDOWS) + " |")
    L.append("\n## 3. 증분 — 조건 C 를 만족한 사건 vs 기본 사건 B 중 C 가 아닌 사건 (업종 중립 평균 bp · 이벤트)\n")
    L.append("| 구간 | C | B − C |\n|---|---|---|")
    for w in WINDOWS:
        i = r["increment"][w]
        L.append(f"| {w} | {f(i['C_mean_bp'])} · {i['C_n']} | {f(i['rest_mean_bp'])} · {i['rest_n']} |")
    L.append("\n## 4. 업종 동반형 vs 개별형 (기록)\n")
    L.append("동반도 = 본인 제외 같은 업종 종목 중 같은 분기 매출 +20% 이상인 비율, 같은 공시 분기 안에서 3등분(상위 동반형·하위 개별형). 값 = 업종 중립 / 시장 초과 평균 bp · 이벤트.\n")
    L.append("| 사건 | 유형 | TRAIN | VALID | TEST | 전체(업종 중립·시장·중앙값·승률) |\n|---|---|---|---|---|---|")
    for c in ("B", "C"):
        for lab in ("동반", "개별"):
            x = r["coincidence"][c][lab]
            al = x["all"]
            L.append(f"| {c} | {lab}형 | " + " | ".join(f"{f(x[w]['sn_mean_bp'])} / {f(x[w]['mk_mean_bp'])} · {x[w]['n']}" for w in WINDOWS) +
                     f" | {f(al['sn_mean_bp'])} / {f(al['mk_mean_bp'])} · 중앙 {f(al['sn_median_bp'])} · 승률 {f(al['hit'] * 100 if al['hit'] is not None else None)}% · {al['n']} |")
    L.append("\n## 5. 민감도 — 최소 동종 수 5·8·10 (업종 중립 초과 평균 bp · 이벤트, 기록)\n")
    L.append("| 최소 동종 | 셀 | TRAIN | VALID | TEST | 난수 바닥선 |\n|---|---|---|---|---|---|")
    for nm in sorted(r["cells"], key=int):
        for c in ("B", "C"):
            x = r["cells"][nm][c]
            L.append(f"| {nm} | {c} | " + " | ".join(f"{f(x[w]['sn']['mean_bp'])} · {x[w]['sn']['n']}" for w in WINDOWS) + f" | {f(x['null_p95_train_bp'])} |")
    L.append("\n## 6. 코호트(공시 연도)별 — 판정 셀 C 와 기본 사건 B 의 업종 중립 평균 bp / 이벤트\n")
    yrs = sorted({y for c in ("B", "C") for y in r["cells"][N][c]["cohorts"]})
    L.append("| 셀 | " + " | ".join(str(y) for y in yrs) + " |\n|---|" + "---|" * len(yrs))
    for c in ("B", "C"):
        co = r["cells"][N][c]["cohorts"]
        L.append(f"| {c} | " + " | ".join(f"{f(co[y]['mean_bp'], 0)}/{co[y]['n']}" if y in co else "-" for y in yrs) + " |")
    L.append("\n## 7. 보유 20·120거래일 업종 중립 평균 bp (기록)\n")
    L.append("| 보유 | 셀 | TRAIN | VALID | TEST |\n|---|---|---|---|---|")
    for h, d in r["records"].items():
        for c, x in d.items():
            L.append(f"| {h}일 | {c} | " + " | ".join(f"{f(x[w]['sn_mean_bp'])} · {x[w]['n']}" for w in WINDOWS) + " |")
    L.append("\n## 8. 사전등록 대조\n")
    L.append("- 분기 주요계정(DART fnlttMultiAcnt) 4종 보고서 패널만 썼다. 12월 결산 법인만, 접수일이 기간 종료 +100일(사업 +120일) 안인 보고서만(제외 집계 위).")
    L.append("- 업종은 A5 스냅샷의 현재 시점 분류(PIT 아님). 업종 평균은 같은 진입일 유동·수익 정의 가능한 동종 ≥ 5개로 계산, 판정은 정적 동종 ≥ 8.")
    L.append("- 판정 REJECT 이면 임계값·조건을 바꿔 재실행하지 않는다. 점수·매매에 연결하지 않는다.")
    return "\n".join(L) + "\n"


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        print(("PASS " if c else "FAIL ") + n)
        ok = ok and bool(c)

    check("period_end 파싱", period_end("2024.01.01 ~ 2024.03.31") == "20240331" and period_end("") is None)
    check("pit_ok 경계", pit_ok("20240709", "20240331", 100) and not pit_ok("20240710", "20240331", 100) and pit_ok("20250430", "20241231", 120))
    # 분기 시계열: Q1~Q3 + 연간 → Q4 = 연간 − 3분기 누적
    def rec(corp, yr, rp, fs, dt, rev, op, date, add_r=None, add_o=None, tk="000001"):
        return {"ticker": tk, "corp": corp, "year": yr, "reprt": rp, "fsDiv": fs, "dt": dt, "availableFrom": date,
                "revenue": {"cur": rev[0], "prev": rev[1], "cur_add": add_r[0] if add_r else None, "prev_add": add_r[1] if add_r else None},
                "op_income": {"cur": op[0], "prev": op[1], "cur_add": add_o[0] if add_o else None, "prev_add": add_o[1] if add_o else None}}
    by = load_records([])
    for r in [rec("c", 2020, "11013", "CFS", "2020.01.01 ~ 2020.03.31", (100, 80), (10, 5), "20200515"),
              rec("c", 2020, "11012", "CFS", "2020.01.01 ~ 2020.06.30", (120, 90), (12, 6), "20200814"),
              rec("c", 2020, "11014", "CFS", "2020.01.01 ~ 2020.09.30", (150, 100), (15, 7), "20201113", (370, 270), (37, 18)),
              rec("c", 2020, "11011", "CFS", "2020.01.01 ~ 2020.12.31", (600, 420), (60, 30), "20210316")]:
        by.setdefault((r["corp"], r["year"], r["reprt"]), {})[r["fsDiv"]] = r
    qs, ex = build_quarters(by)
    q4 = qs.get(("c", 2020 * 4 + 4))
    check("Q4 = 연간 − 3분기 누적(매출 230·영업 23, 전년 150·12)", q4 and q4["rev"] == 230 and q4["op"] == 23 and q4["rev_prev"] == 150 and q4["op_prev"] == 12)
    check("Q1~Q3 는 3개월 값 그대로", qs[("c", 2020 * 4 + 2)]["rev"] == 120 and qs[("c", 2020 * 4 + 3)]["op"] == 15)
    ev, gmap = classify(qs)
    cells = {(e["t"] % 4 or 4, c) for e in ev for c in e["cells"]}
    # Q1: g=.25 op 2배 → B(과거 분기 없음 → A·G 없음). Q2: g=.333, Q1 g=.25 → G, 직전 2분기 없음 → A 없음. Q3: g=.5 ↑ G, 3연속 흑자 → C. Q4: g=.533 ↑ G, C
    check("Q1 은 B 만", (1, "B") in cells and (1, "C") not in cells and (1, "BA") not in cells)
    check("Q2 는 B·BG (연속 3분기 부족)", (2, "BG") in cells and (2, "BA") not in cells)
    check("Q3·Q4 는 C", (3, "C") in cells and (4, "C") in cells)
    ex_by = {("d", 2020, "11013"): {"CFS": rec("d", 2020, "11013", "CFS", "2020.04.01 ~ 2020.06.30", (1, 1), (1, 1), "20200815", tk="D")}}
    qs2, ex2 = build_quarters(ex_by)
    check("기간 불일치(비12월 결산) 제외", not qs2 and ex2.get("비12월 결산·기간 불일치") == 1)
    ex_late = {("e", 2020, "11013"): {"CFS": rec("e", 2020, "11013", "CFS", "2020.01.01 ~ 2020.03.31", (1, 1), (1, 1), "20200901", tk="E")}}
    qs3, ex3 = build_quarters(ex_late)
    check("지연 공시 제외", not qs3 and ex3.get("지연·정정 공시") == 1)
    lab = tercile_labels([0.0, 0.1, 0.2, 0.5, 0.6, 0.9])
    check("3등분: 하위 개별·상위 동반·중간", lab[0] == "개별" and lab[-1] == "동반" and "중간" in lab)
    check("3등분: 값이 전부 같으면 모두 중간", set(tercile_labels([0.2] * 6)) == {"중간"})
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        sys.exit(selftest())
    main()
