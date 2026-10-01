#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""공시·뉴스 점수화 A/B — 계산 (사전등록 findings/disclosure-news-score-ab-preregistration-2026-10.md).

    python disclosure_score_ab.py selftest
    python disclosure_score_ab.py count     # 건수·노출만 센다(수익률 없음)
    python disclosure_score_ab.py run       # 연구 A(전 종목 이벤트 4셀) + 연구 B(A/B 1셀) — 사전등록·코드·수집기가 커밋된 상태에서만

사전등록에 없는 구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다):
- 접수일 → 신호일 d* = 접수일 이하 마지막 거래일. 진입 = d* 다음 거래일 시가(= 접수일 다음 거래일). 층화(dv20 3분위·직전 20일 수익률 5분위)는 d* 의 적격 종목 순위 백분위로 자른다.
- 군집 제거: 같은 종목·같은 유형에서 **마지막으로 센 사건** 접수일로부터 60 달력일 안의 공시는 새 사건으로 세지 않는다.
- 대조 후보에서 '같은 유형의 사건을 d* 이전 60 달력일 안에 가진 종목'도 뺀다(사건 효과가 섞이지 않게).
- 연구 B 슬롯 수익 = 진입일(리밸런스일 다음 세션) 시가 → holdSessions 번째 세션 종가. 데이터가 모자라면 그 슬롯은 A·B 양쪽에서 뺀다. 월수익 = 슬롯 동일가중 평균.
- 연구 B 의 A 팔은 production 빌더의 turnover20·MAX5 계산을 그대로 따른다(A2aProvider·_drop_suspension_rows). 재구성 A 가 selection.json 과 같은지 일치율을 기록한다.
- 귀무: 월별로 B 가 실제 붙인 (+) 플래그 수·(−) 플래그 수와 같은 개수를 그 달 적격 종목에 무작위로 붙여 같은 파이프라인을 N_NULL 회. ΔSharpe 는 월수익 평균/표준편차×√12 의 차.
- 회전율 = 그 달 신규 편입 종목 수 ÷ 보유 종목 수. 비용 차 = (B 회전율 − A 회전율) × 왕복 23.54bp.
"""
from __future__ import annotations

import bisect
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))

PREREG = HERE / "findings" / "disclosure-news-score-ab-preregistration-2026-10.md"
COLLECTOR = HERE / "collect_dart_event_titles.py"
CACHE = HERE / "data" / "dart_event_titles"
PANEL = HERE / "reports" / "2026-08-21-a5-valuation-precheck" / "valuation-panel.jsonl"
CORPS = REPO / "data" / "backfill" / "dart" / "corpcode.jsonl"
SELECTION = HERE / "strategies" / "pbr_value_v1_combined" / "selection.json"
OUT = HERE / "findings" / "disclosure-score-ab-results-2026-10.json"
C1, C2 = 23.54, 33.5
SEED = 20261002
H = 20
DEDUP_DAYS = 60
FLAG_DAYS = 30
ADJ = 10.0
N_NULL = 200
TYPES = {   # id -> (이름, 정규식, 방향 +1/−1, 공시 종류)
    "E1": ("희석", r"유상증자결정|전환사채권발행결정|신주인수권부사채권발행결정|교환사채권발행결정", -1),
    "E2": ("자사주", r"자기주식취득결정|자기주식취득신탁계약체결결정|주식소각결정", +1),
    "E3": ("수주", r"단일판매.?공급계약체결", +1),
    "E4": ("중대위험", r"횡령|배임|(단일판매|공급계약).*해지|매매거래정지|관리종목", -1),
}
_RX = {k: re.compile(v[1]) for k, v in TYPES.items()}


# ---------------------------------------------------------------- 공통 보조
def committed_clean(p: Path) -> bool:
    from supply_mcap_flow import committed_clean as cc
    return cc(p)


def split(d):
    return "TRAIN" if d.year <= 2020 else ("VALID" if d.year <= 2022 else "TEST")


def classify(nm):
    """공시 제목 → 유형 id 목록. 정정·해제 공시는 뺀다."""
    n = re.sub(r"\s+", "", nm or "")
    if "정정" in n:
        return []
    out = []
    for k, rx in _RX.items():
        if rx.search(n) and not (k == "E4" and "해제" in n):
            out.append(k)
    return out


def dedupe(dates):
    """정렬된 접수일(date) 목록 → 마지막으로 센 사건에서 60일 이상 떨어진 것만."""
    out = []
    for d in sorted(dates):
        if not out or (d - out[-1]).days >= DEDUP_DAYS:
            out.append(d)
    return out


def to_date(s):
    s = str(s).replace("-", "")
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def load_events():
    """{유형: {종목: [사건일(date)]}} (군집 제거 후) + 커버리지."""
    corp2t = {}
    for line in open(CORPS, encoding="utf-8"):
        j = json.loads(line)
        if j.get("corp") and j.get("ticker"):
            corp2t[j["corp"]] = j["ticker"]
    raw = {k: defaultdict(list) for k in TYPES}
    seen_corp = 0
    for p in glob.glob(str(CACHE / "*.json")):
        corp = Path(p).stem
        t = corp2t.get(corp)
        if not t:
            continue
        seen_corp += 1
        d = json.load(open(p, encoding="utf-8"))
        for ty in ("I", "B"):
            for r in d.get(ty, []):
                for k in classify(r["nm"]):
                    raw[k][t].append(to_date(r["d"]))
    ev = {k: {t: dedupe(set(v)) for t, v in raw[k].items()} for k in TYPES}
    return ev, {"corps_cached": seen_corp}


# ---------------------------------------------------------------- 연구 A
def load_panel_a(tickers):
    import numpy as np
    import pandas as pd
    P = REPO / "data" / "backfill" / "price"
    rows, delisted = [], set()
    for sub in ("a2a", "a2b"):
        for p in sorted((P / sub).glob("20*.jsonl.gz")):
            import gzip
            for line in gzip.open(p, "rt", encoding="utf-8"):
                r = json.loads(line)
                if r["ticker"] in tickers:
                    rows.append((r["ticker"], r["date"], r["open"], r["close"], r["volume"]))
                    if sub == "a2b":
                        delisted.add(r["ticker"])
    d = pd.DataFrame(rows, columns=["t", "date", "o", "c", "v"])
    d = d[(d.o > 0) & (d.c > 0) & (d.v > 0)].drop_duplicates(["t", "date"])
    d["di"] = d["date"].str.replace("-", "", regex=False).astype(int)
    d = d.sort_values(["t", "di"]).reset_index(drop=True)
    g = d.groupby("t", sort=False)
    d["dv20"] = (d.c * d.v).groupby(d.t, sort=False).transform(lambda s: s.rolling(20).mean())
    d["ret20"] = d.c / g["c"].shift(20) - 1
    d["elig"] = (d.dv20 >= 1e8) & (d.c >= 1000) & d.ret20.notna()
    e = d[d.elig]
    d["dv3"] = -1
    d["rq5"] = -1
    d.loc[e.index, "dv3"] = np.minimum((e.groupby("di")["dv20"].rank(pct=True) * 3).astype(int), 2)
    d.loc[e.index, "rq5"] = np.minimum((e.groupby("di")["ret20"].rank(pct=True) * 5).astype(int), 4)
    arr = {t: (x.di.values, x.o.values.astype(float), x.c.values.astype(float)) for t, x in d.groupby("t", sort=False)}
    return d, arr, delisted


def study_a(ev, d, arr, delisted):
    import numpy as np
    import pandas as pd
    from supply_mcap_flow import fwd
    rng = np.random.default_rng(SEED)
    di_a, tk_a, dv_a, rq_a, el_a = d.di.values, d.t.values, d.dv3.values, d.rq5.values, d.elig.values
    key = defaultdict(list)
    for i in np.flatnonzero(el_a):
        key[(di_a[i], dv_a[i], rq_a[i])].append(i)
    row_of = {(tk_a[i], di_a[i]): i for i in np.flatnonzero(el_a)}
    days_by_t = {t: a[0] for t, a in arr.items()}
    out, rec = {}, {}
    for k, per_t in ev.items():
        cnt = Counter()
        rows = []
        for t, dates in per_t.items():
            if t not in days_by_t:
                cnt["no_price"] += len(dates)
                continue
            dd = days_by_t[t]
            for dt in dates:
                x = int(dt.strftime("%Y%m%d"))
                j = int(dd.searchsorted(x, side="right")) - 1       # 접수일 이하 마지막 거래일
                if j < 0:
                    cnt["before_listing"] += 1
                    continue
                dstar = int(dd[j])
                i = row_of.get((t, dstar))
                if i is None:
                    cnt["not_eligible"] += 1
                    continue
                fe = fwd(arr, delisted, t, dstar, H)
                if fe is None:
                    cnt["censored"] += 1
                    continue
                pool = []
                lo = (to_date(str(dstar)) - timedelta(days=DEDUP_DAYS))
                for jx in key.get((dstar, dv_a[i], rq_a[i]), []):
                    tj = tk_a[jx]
                    if tj == t:
                        continue
                    ds = per_t.get(tj)
                    if ds and any(lo < e <= to_date(str(dstar)) for e in ds):
                        continue
                    pool.append(jx)
                if len(pool) < 3:
                    cnt["no_match"] += 1
                    continue
                pick = list(rng.choice(pool, 5, replace=False)) if len(pool) > 5 else pool
                cg = [r_[0] for jx in pick if (r_ := fwd(arr, delisted, tk_a[jx], dstar, H)) is not None]
                if len(cg) < 3:
                    cnt["no_match"] += 1
                    continue
                rows.append({"t": t, "di": fe[1], "g": fe[0] * 1e4, "info": (fe[0] - float(np.mean(cg))) * 1e4,
                             "delisted": fe[3] == "delisted"})
                cnt["used"] += 1
        out[k] = pd.DataFrame(rows)
        rec[k] = dict(cnt)
    return out, rec


def monthly_a(df):
    import pandas as pd
    x = df.copy()
    x["m"] = pd.to_datetime(x.di.astype(str), format="%Y%m%d").dt.to_period("M").dt.to_timestamp()
    return x.groupby("m").agg(info=("info", "mean"), g=("g", "mean"), n=("g", "size"))


def judge_a(res_a):
    import numpy as np
    from structure_phase4 import family
    from short_horizon_study import tstat
    mo = {k: monthly_a(df) for k, df in res_a.items() if len(df)}
    cells = {k: [(m, r["info"], r["g"], C1, C2) for m, r in mm.iterrows()] for k, mm in mo.items()}
    fam = family(cells, lambda m: split(m), np.random.default_rng(SEED), {k: {"info_only": True} for k in cells})
    out = {"bar": fam["bar"], "cells": {}}
    for k, mm in mo.items():
        df = res_a[k]
        n = {s: int(sum(split(x) == s for x in mm.index)) for s in ("TRAIN", "VALID", "TEST")}
        v = dict(fam["cells"][k])
        small = n["TRAIN"] < 36 or n["VALID"] < 12 or n["TEST"] < 20
        tr = mm["info"][[split(x) == "TRAIN" for x in mm.index]]
        sign = int(np.sign(tr.mean())) if len(tr) else 0
        v["train_sign"], v["expected_sign"] = sign, TYPES[k][2]
        v["direction_supported"] = bool(str(v.get("verdict", "")).startswith("INFORMATION") and sign == TYPES[k][2] and not small)
        if small:
            v["verdict"] = "INCONCLUSIVE(표본 부족)"
        rng = np.random.default_rng(7)
        boot = [rng.choice(df.g.values, len(df)).mean() for _ in range(2000)]
        v["stats"] = {
            "events": int(len(df)), "tickers": int(df.t.nunique()), "months": n,
            "gross_mean_bp": round(float(df.g.mean()), 1), "gross_ci95": [round(float(np.quantile(boot, q)), 1) for q in (0.025, 0.975)],
            "info_mean_bp": round(float(df["info"].mean()), 1),
            "t_by_split": {s: round(float(tstat(mm["info"][[split(x) == s for x in mm.index]].values)), 2) for s in ("TRAIN", "VALID", "TEST")},
            "info_by_split_bp": {s: round(float(mm["info"][[split(x) == s for x in mm.index]].mean()), 1) for s in ("TRAIN", "VALID", "TEST")},
            "yearly_info_bp": {int(y): round(float(x), 1) for y, x in mm["info"].groupby(mm.index.year).mean().items()},
            "max_events_month": int(mm.n.max()), "top5_month_share": round(float(mm.n.nlargest(5).sum() / mm.n.sum()), 3),
            "delisted_events": int(df.delisted.sum()),
        }
        out["cells"][k] = v
    return out


# ---------------------------------------------------------------- 연구 B
def sharpe(x):
    import numpy as np
    x = np.asarray(x, float)
    return float(x.mean() / x.std(ddof=1) * 12 ** 0.5) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def flag_s(ev_dates_by_k, t_date):
    """리밸런스일 t 기준 (t−30일 ≤ 접수일 < t) 사건 가감 s ∈ {−1,0,+1}. 접수일 ≥ t 는 보지 않는다."""
    lo = t_date - timedelta(days=FLAG_DAYS)
    s = 0
    for k, ds in ev_dates_by_k.items():
        i = bisect.bisect_left(ds, lo)
        n = sum(1 for e in ds[i:] if e < t_date)
        s += n * TYPES[k][2]
    return max(-1, min(1, s))


def pipeline(months, score_of):
    """월별 (t, 순위 입력) → dropout(nDrop=3, top 30) → MAX 제외. 반환: {t: [종목]} · 회전율 {t: 신규/보유}."""
    sys.path.insert(0, str(HERE / "strategies" / "pbr_value_v1_dropout"))
    from build_selection_dropout import next_selection
    held, sel, turn = [], {}, {}
    for t in months:
        m = months[t]
        ranked = score_of(t, m)
        new = next_selection(held, ranked, 30, 3)
        kept = [x for x in new if x not in m["max5_ex"]]
        sel[t] = kept
        turn[t] = (len(set(new) - set(held)) / len(new)) if new else 0.0
        held = new
    return sel, turn


def study_b(ev, n_null=N_NULL, adj_list=(10.0,)):
    import numpy as np
    import pandas as pd
    sys.path.insert(0, str(HERE))
    from engine.data.a2aProvider import A2aProvider
    from engine.data.calendar import TradingCalendar
    from engine.runner import _drop_suspension_rows
    sys.path.insert(0, str(HERE / "strategies" / "pbr_value_v1_dropout"))
    from build_selection_dropout import monthly_rebalance_dates
    val = pd.DataFrame([json.loads(l) for l in open(PANEL, encoding="utf-8")]).dropna(subset=["pbr"])
    val = val[val["pbr"] > 0][["ticker", "asOf", "pbr"]]
    cal = TradingCalendar(repo_root=str(REPO))
    END = json.load(open(REPO / "data" / "backfill" / "calendar.json", encoding="utf-8"))["tradingDays"][-1]
    START = "2016-01-01"
    a2a = A2aProvider(repo_root=str(REPO), use_cache=True)
    bars = {t: _drop_suspension_rows(df) for t, df in a2a.load(sorted(val.ticker.unique()), START, END, universe_hash="disclosure-ab").items()}
    reb = monthly_rebalance_dates(cal, START, END)
    pos = {t: {d: i for i, d in enumerate(b.index.astype(str))} for t, b in bars.items() if len(b)}
    tv, m5 = [], []
    for t, b in bars.items():
        if b.empty:
            continue
        c, v = b["close"], b["volume"]
        idx = c.index.astype(str)
        t20 = (c * v).rolling(20).mean()
        mx = c.pct_change().rolling(21).apply(lambda w: float(np.mean(sorted(w, reverse=True)[:5])), raw=True)
        for r in reb:
            i = pos[t].get(r)
            if i is None or pd.isna(t20.iloc[i]):
                continue
            tv.append((t, r, float(t20.iloc[i]), None if pd.isna(mx.iloc[i]) else float(mx.iloc[i])))
    ta = pd.DataFrame(tv, columns=["ticker", "asOf", "tv", "max5"])
    el = val.merge(ta, on=["ticker", "asOf"]).query("tv >= 100000000")
    thr = el.dropna(subset=["max5"]).groupby("asOf")["max5"].quantile(0.8)
    hold = {}
    for k, t in enumerate(reb[:-1]):
        e, nx = cal.next_session(t), cal.next_session(reb[k + 1])
        if e and nx:
            hold[t] = len(cal.sessions_between(e, nx))
    months = {}
    for r, g in el.groupby("asOf"):
        if r not in hold:
            continue
        g = g.sort_values("pbr", kind="mergesort")
        tick = g.ticker.tolist()
        months[r] = {"tick": tick, "pct": {x: 100.0 * i / max(1, len(tick) - 1) for i, x in enumerate(tick)},
                     "max5_ex": {x for x, v in zip(g.ticker, g.max5) if pd.notna(v) and r in thr.index and v >= thr[r]},
                     "hold": hold[r]}
    dates_ev = {t: {k: ev[k][t] for k in TYPES if t in ev[k]} for t in {t for k in ev for t in ev[k]}}
    for r, m in months.items():
        td = to_date(r)
        m["s"] = {x: flag_s(dates_ev[x], td) for x in m["tick"] if x in dates_ev}

    def slot_ret(t, r, h):
        p = pos.get(t)
        if not p:
            return None
        e = cal.next_session(r)
        if e not in p:
            return None
        i = p[e]
        b = bars[t]
        j = i + h - 1
        if j >= len(b):
            return None
        return float(b["close"].iloc[j] / b["open"].iloc[i] - 1)

    # 슬롯 수익은 필요한 (종목, 월)만 지연 계산
    cache = {}

    def sr(t, r):
        k = (t, r)
        if k not in cache:
            cache[k] = slot_ret(t, r, months[r]["hold"])
        return cache[k]

    sel_a, turn_a = pipeline(months, lambda r, m: m["tick"])
    # 슬롯 수익은 (종목, 월)로만 정해져 A·B 가 같은 값을 쓴다 — 없는 슬롯은 양쪽에서 똑같이 빠진다
    def monthly_ret(sel):
        res = {}
        for r, ts in sel.items():
            v = [sr(t, r) for t in ts]
            v = [x for x in v if x is not None]
            if v:
                res[r] = float(np.mean(v)) * 1e4
        return res
    res = {"months": len(months)}
    # A 재구성 vs selection.json
    prod = json.load(open(SELECTION, encoding="utf-8"))["selection"]
    prod_by = defaultdict(set)
    for t, es in prod.items():
        for e in es:
            prod_by[e["date"]].add(t)
    common = [r for r in sel_a if r in prod_by]
    same = sum(set(sel_a[r]) == prod_by[r] for r in common)
    res["A_vs_production"] = {"months_compared": len(common), "months_identical": same,
                              "mean_jaccard": round(float(np.mean([len(set(sel_a[r]) & prod_by[r]) / max(1, len(set(sel_a[r]) | prod_by[r])) for r in common])), 4)}
    ra = monthly_ret(sel_a)
    out_arms = {}
    for adj in sorted(set(adj_list) | {ADJ}):
        sel_b, turn_b = pipeline(months, lambda r, m, adj=adj: sorted(m["tick"], key=lambda x: (m["pct"][x] - adj * m["s"].get(x, 0), m["pct"][x])))
        rb = monthly_ret(sel_b)
        out_arms[adj] = (sel_b, turn_b, rb)
    return res, months, sel_a, turn_a, ra, out_arms, monthly_ret, pipeline


def summarize_b(res, months, sel_a, turn_a, ra, out_arms, monthly_ret, n_null):
    import numpy as np
    from short_horizon_study import tstat
    rng = np.random.default_rng(SEED)
    ms = sorted(set(ra) & set(out_arms[ADJ][2]))
    mdt = {r: to_date(r) for r in ms}
    def spl(r):
        return split(mdt[r])
    def block(rb, tb):
        o = {}
        for s in ("TRAIN", "VALID", "TEST"):
            rr = [r for r in ms if spl(r) == s]
            a = np.array([ra[r] for r in rr]); b = np.array([rb[r] for r in rr])
            d = b - a
            ta = np.array([turn_a[r] for r in rr]); tbb = np.array([tb[r] for r in rr])
            o[s] = {"months": len(rr), "A_sharpe": round(sharpe(a / 1e4), 3), "B_sharpe": round(sharpe(b / 1e4), 3),
                    "d_sharpe": round(sharpe(b / 1e4) - sharpe(a / 1e4), 3), "mean_diff_bp": round(float(d.mean()), 1),
                    "t_diff": round(float(tstat(d)), 2), "turn_A": round(float(ta.mean()), 3), "turn_B": round(float(tbb.mean()), 3),
                    "net_diff_bp": round(float(d.mean() - (tbb.mean() - ta.mean()) * C1), 1)}
        return o
    out = {}
    for adj, (sel_b, turn_b, rb) in out_arms.items():
        out[f"adj{adj:g}"] = block(rb, turn_b)
    # 노출: A 팔 슬롯 중 플래그가 걸린 비율, B 가 A 와 달라진 달 수
    flagged = sum(1 for r in ms for x in sel_a[r] if months[r]["s"].get(x, 0) != 0)
    tot = sum(len(sel_a[r]) for r in ms)
    diff_months = sum(set(sel_a[r]) != set(out_arms[ADJ][0][r]) for r in ms)
    out["exposure"] = {"A_slots_flagged": flagged, "A_slots": tot, "share": round(flagged / max(1, tot), 4),
                       "months_B_differs_from_A": diff_months, "months": len(ms)}
    # 귀무: 같은 개수의 (+)/(−) 플래그를 적격 종목에 무작위로
    cnt = {r: (sum(1 for v in months[r]["s"].values() if v > 0), sum(1 for v in months[r]["s"].values() if v < 0)) for r in months}
    null = {s: [] for s in ("TRAIN", "VALID", "TEST")}
    for _ in range(n_null):
        rnd = {}
        for r, m in months.items():
            npos, nneg = cnt[r]
            tk = m["tick"]
            idx = rng.permutation(len(tk))[: npos + nneg]
            rnd[r] = {tk[i]: (1 if j < npos else -1) for j, i in enumerate(idx)}
        sel, _ = pipeline(months, lambda r, m: sorted(m["tick"], key=lambda x: (m["pct"][x] - ADJ * rnd[r].get(x, 0), m["pct"][x])))
        rn = monthly_ret(sel)
        for s in null:
            rr = [r for r in ms if spl(r) == s and r in rn]
            null[s].append(sharpe([rn[r] / 1e4 for r in rr]) - sharpe([ra[r] / 1e4 for r in rr]))
    out["null_d_sharpe"] = {s: {"p05": round(float(np.nanquantile(v, .05)), 3), "p50": round(float(np.nanquantile(v, .5)), 3),
                                "p95": round(float(np.nanquantile(v, .95)), 3)} for s, v in null.items()}
    b = out[f"adj{ADJ:g}"]
    ok = (b["TRAIN"]["d_sharpe"] > out["null_d_sharpe"]["TRAIN"]["p95"] and b["VALID"]["d_sharpe"] > 0
          and b["TEST"]["d_sharpe"] > 0 and b["TEST"]["net_diff_bp"] > 0)
    harmful = b["TRAIN"]["d_sharpe"] < out["null_d_sharpe"]["TRAIN"]["p05"]
    out["verdict"] = "B 채택 후보" if ok else ("점수에 넣으면 해롭다(귀무 5백분위 미만)" if harmful else "채택 후보 아님(조건 미충족)")
    return out


# ---------------------------------------------------------------- 명령
def cmd_count():
    ev, cov = load_events()
    print("커버리지", cov)
    for k, (nm, _, sgn) in TYPES.items():
        n = sum(len(v) for v in ev[k].values())
        yrs = Counter(d.year for v in ev[k].values() for d in v)
        print(f"{k} {nm}({'+' if sgn > 0 else '−'}) 사건 {n:,}건 · 종목 {len(ev[k]):,} · 연도별 {dict(sorted(yrs.items()))}")
    return 0


def cmd_run():
    for p in (PREREG, Path(__file__).resolve(), COLLECTOR):
        if not committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률을 계산하지 않는다")
            return 2
    ev, cov = load_events()
    tickers = {json.loads(l)["ticker"] for l in open(PANEL, encoding="utf-8")}
    d, arr, delisted = load_panel_a(tickers)
    print(f"패널 {len(d):,}행 · 적격 {int(d.elig.sum()):,} · 종목 {len(arr):,} · 폐지 {len(delisted):,}")
    res_a, rec = study_a(ev, d, arr, delisted)
    ja = judge_a(res_a)
    ja["counts"] = rec
    print("연구 A", json.dumps({k: {"verdict": v.get("verdict"), "dir": v.get("direction_supported"), **v["stats"]} for k, v in ja["cells"].items()},
                              ensure_ascii=False, default=str)[:4000])
    res, months, sel_a, turn_a, ra, arms, mret, _ = study_b(ev, adj_list=(5.0, 10.0, 20.0))
    jb = summarize_b(res, months, sel_a, turn_a, ra, arms, mret, N_NULL)
    jb["reconstruction"] = res
    print("연구 B", json.dumps(jb, ensure_ascii=False, default=str)[:4000])
    OUT.write_text(json.dumps({"prereg": PREREG.name, "coverage": cov, "A": ja, "B": jb}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("저장", OUT.relative_to(REPO))
    return 0


def selftest():
    assert classify("[기재정정]주요사항보고서(유상증자결정)") == []                 # 정정 제외
    assert classify("주요사항보고서(유상증자결정)") == ["E1"]
    assert classify("주요사항보고서(자기주식취득결정)") == ["E2"] and classify("주요사항보고서(자기주식처분결정)") == []
    assert classify("단일판매ㆍ공급계약체결") == ["E3"] and classify("단일판매ㆍ공급계약해지") == ["E4"]
    assert classify("매매거래정지") == ["E4"] and classify("매매거래정지해제") == []
    assert classify("횡령ㆍ배임혐의발생") == ["E4"]
    d = [date(2020, 1, 1), date(2020, 2, 1), date(2020, 3, 5), date(2020, 3, 20)]
    assert dedupe(d) == [date(2020, 1, 1), date(2020, 3, 5)]                   # 2/1(31일)은 흡수, 3/5(64일)는 새 사건, 3/20 은 흡수
    t = date(2020, 6, 30)
    assert flag_s({"E2": [date(2020, 6, 1)]}, t) == 1
    assert flag_s({"E2": [date(2020, 6, 30)]}, t) == 0                          # 접수일 = t 는 보지 않는다
    assert flag_s({"E2": [date(2020, 5, 30)]}, t) == 0                          # 31일 전은 창 밖
    assert flag_s({"E2": [date(2020, 6, 1)], "E1": [date(2020, 6, 2)]}, t) == 0 # +1 −1 = 0
    assert flag_s({"E2": [date(2020, 6, 1), date(2020, 6, 10)], "E3": [date(2020, 6, 5)]}, t) == 1   # 자름
    assert abs(sharpe([0.01, 0.02, 0.0, 0.03]) - (0.015 / (0.01291 ) * 12 ** 0.5)) < 0.05
    print("selftest ok")
    return 0


if __name__ == "__main__":
    sys.exit({"run": cmd_run, "count": cmd_count, "selftest": selftest}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__) or 2)())
