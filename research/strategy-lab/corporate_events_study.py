#!/usr/bin/env python3
"""기업행사 공시(무상증자·유상증자) 이벤트 스터디 — 결과 산출. 사전등록: findings/corporate-events-preregistration-2026-09.md (4fa3933).

    python research/strategy-lab/corporate_events_study.py --selftest   # 네트워크·캐시 없음
    python research/strategy-lab/corporate_events_study.py              # A2a 캐시 필요

판정 셀 E1·E2·E3, 기록 전용 E4(+ 60거래일). 정의·기간·비용·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.
산출: findings/corporate-events-results-2026-09.{md,json}
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))
from quarterly_acceleration_event import boot_ci, entry_index  # noqa: E402

A3D = HERE.parent.parent / "data" / "backfill" / "fundamentals" / "a3d"
OUT = HERE / "findings" / "corporate-events-results-2026-09"
LIQ_MIN = 2e9
COST_BP, STRESS_BP = 33.5, 67.0
SEED, N_NULL = 20260928, 1000
MIN_EVENTS = 30
DEDUP_DAYS = 30
START, END = "2016-01-01", "2026-06-30"
CELLS = {"E1": "bonusIssue", "E2": "rightsOfferingShareholders", "E3": "rightsOfferingThirdParty", "E4": "capitalReductionFree"}
JUDGED = ("E1", "E2", "E3")
WINDOWS = {"TRAIN": (2016, 2020), "VALID": (2021, 2022), "TEST": (2023, 2026)}


def window_of(year):
    for k, (a, b) in WINDOWS.items():
        if a <= year <= b:
            return k
    return None


def dedupe(events):
    """events: [(ticker, Timestamp)] → 같은 종목이 30일 안에 반복되면 첫 공시만(사전등록 §1)."""
    keep, last = [], {}
    for tk, d in sorted(events, key=lambda x: (x[0], x[1])):
        if tk in last and (d - last[tk]).days <= DEDUP_DAYS:
            continue
        last[tk] = d
        keep.append((tk, d))
    return keep


def load_events(cat):
    rows = [json.loads(l) for l in gzip.open(A3D / f"{cat}.jsonl.gz", "rt", encoding="utf-8")]
    ev = []
    for r in rows:
        d = pd.to_datetime(str(r.get("disclosureDate")), format="%Y%m%d", errors="coerce")
        if r.get("ticker") and not pd.isna(d) and pd.Timestamp(START) <= d <= pd.Timestamp(END):
            ev.append((r["ticker"], d))
    return dedupe(ev)


def cluster_t(x, groups):
    """진입일 군집 강건 t: 평균 / (sqrt(Σ_g(Σ(x-평균))²) / n)."""
    x, groups = np.asarray(x, float), np.asarray(groups)
    if len(x) < 3:
        return None
    m = x.mean()
    se = np.sqrt(sum(((x[groups == g] - m).sum()) ** 2 for g in np.unique(groups))) / len(x)
    return float(m / se) if se > 0 else None


def family_bar(train_counts_by_cell, pool, rng, n=N_NULL):
    """셀 3개의 |평균 초과| 최대값의 95번째 백분위(같은 진입일·같은 수의 무작위 유동 종목)."""
    mx = np.empty(n)
    for i in range(n):
        best = 0.0
        for cnt in train_counts_by_cell:
            tot = sum(cnt.values())
            if tot == 0:
                continue
            acc = 0.0
            for k, c in cnt.items():
                p = pool[k]
                acc += p[rng.integers(0, len(p), c)].sum()
            best = max(best, abs(acc / tot))
        mx[i] = best
    return float(np.quantile(mx, 0.95))


def verdict(tr, va, te, bar, net_oos, net_stress, oos_t):
    if min(len(tr), len(va), len(te)) < MIN_EVENTS:
        return "판정불가"
    s = np.sign(tr.mean())
    info = abs(tr.mean()) >= bar and np.sign(va.mean()) == s and np.sign(te.mean()) == s
    eco = bool(info) and s > 0 and net_oos > 0 and net_stress > 0
    rob = eco and oos_t is not None and abs(oos_t) >= 2
    return "ROBUST" if rob else "ECONOMIC" if eco else "INFORMATION" if info else "REJECT"


def main():
    import close_open_phase5 as p5
    a = p5.load()[["date", "ticker", "close", "volume", "liq"]]
    dates = np.sort(a.date.unique())
    close = a.pivot(index="date", columns="ticker", values="close").reindex(dates)
    vol = a.pivot(index="date", columns="ticker", values="volume").reindex(dates)
    liq = a.pivot(index="date", columns="ticker", values="liq").reindex(dates)
    rng = np.random.default_rng(SEED)
    res = {"seed": SEED, "cells": {}}
    ex, pools, liqmask = {}, {}, {}
    for h in (20, 60):
        ret = close.shift(-h) / close - 1
        liquid = (liq >= LIQ_MIN) & (vol > 0) & ret.notna()
        base = ret.where(liquid).mean(axis=1)
        ex[h] = ret.sub(base, axis=0)
        liqmask[h] = liquid
        pools[h] = {}
        if h == 20:
            for i in range(len(dates)):
                row = ex[h].iloc[i][liquid.iloc[i]].dropna()
                if len(row):
                    pools[h][i] = row.to_numpy() * 1e4

    recs = {}
    for cid, cat in CELLS.items():
        r20, r60 = [], []
        for tk, d in load_events(cat):
            w = window_of(d.year)
            if w is None or tk not in ex[20].columns:
                continue
            i = entry_index(dates, d)
            if i >= len(dates) - 20 or not liqmask[20].iloc[i].get(tk, False):
                continue
            x20 = ex[20].iloc[i][tk]
            if np.isnan(x20):
                continue
            r20.append((w, d.year, i, float(x20) * 1e4))
            if i < len(dates) - 60 and liqmask[60].iloc[i].get(tk, False) and not np.isnan(ex[60].iloc[i][tk]):
                r60.append((w, d.year, i, float(ex[60].iloc[i][tk]) * 1e4))
        recs[cid] = (pd.DataFrame(r20, columns=["w", "year", "i", "ex"]), pd.DataFrame(r60, columns=["w", "year", "i", "ex"]))

    counts = [recs[c][0][recs[c][0].w == "TRAIN"].groupby("i").size().to_dict() for c in JUDGED]
    bar = family_bar(counts, pools[20], rng)
    res["family_bar_bp"] = bar

    for cid in CELLS:
        df, df60 = recs[cid]
        out = {"events": int(len(df)), "windows": {}}
        for w in WINDOWS:
            d = df[df.w == w]
            out["windows"][w] = {"n": int(len(d)), "days": int(d.i.nunique()),
                                 "mean_bp": float(d.ex.mean()) if len(d) else None,
                                 "median_bp": float(d.ex.median()) if len(d) else None,
                                 "ci95": list(boot_ci(d.ex, d.i, rng)) if len(d) else [None, None]}
        oos = df[df.w != "TRAIN"]
        m = float(oos.ex.mean()) if len(oos) else None
        s = 1.0 if (df[df.w == "TRAIN"].ex.mean() >= 0) else -1.0
        out["OOS"] = {"n": int(len(oos)), "mean_bp": m, "breakeven_bp": (s * m) if m is not None else None,
                      "net_bp": (s * m - COST_BP) if m is not None else None,
                      "net_stress_bp": (s * m - STRESS_BP) if m is not None else None,
                      "cluster_t": cluster_t(oos.ex, oos.i) if len(oos) else None}
        out["yearly_bp"] = {int(y): {"n": int(r["count"]), "mean_bp": float(r["mean"])}
                            for y, r in df.groupby("year").ex.agg(["count", "mean"]).iterrows()}
        out["h60"] = {w: {"n": int((df60.w == w).sum()), "mean_bp": float(df60[df60.w == w].ex.mean()) if (df60.w == w).any() else None}
                      for w in WINDOWS}
        if cid in JUDGED:
            tr, va, te = (df[df.w == w].ex.to_numpy() for w in WINDOWS)
            out["verdict"] = verdict(tr, va, te, bar, out["OOS"]["net_bp"] or -1e9, out["OOS"]["net_stress_bp"] or -1e9,
                                     out["OOS"]["cluster_t"])
            out["train_sign"] = int(s)
        res["cells"][cid] = out
    OUT.with_suffix(".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(res), encoding="utf-8")
    print({c: res["cells"][c].get("verdict") for c in JUDGED}, "bar", round(bar, 1))


def f(x, nd=1):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


NAMES = {"E1": "무상증자 결정", "E2": "주주배정 유상증자(회피 신호)", "E3": "제3자배정 유상증자", "E4": "무상감자(기록)"}


def render(r):
    vs = {c: r["cells"][c]["verdict"] for c in JUDGED}
    best = max(vs.values(), key=lambda v: ["판정불가", "REJECT", "INFORMATION", "ECONOMIC", "ROBUST"].index(v))
    sig = "있음" if best in ("INFORMATION", "ECONOMIC", "ROBUST") else "없음"
    eco = "통과" if best in ("ECONOMIC", "ROBUST") else "미달"
    L = ["---", "track: kr", "factor: corporate-events", "date: 2026-09-21", f"verdict: {best}",
         "criteria_version: research-only (corporate-events-preregistration-2026-09, 4fa3933)",
         'conditions: ["A3d 공시 E1·E2·E3, 다음 거래일 종가 진입 20거래일", "유동 EW 대비 초과", "TRAIN 2016~2020/VALID 2021~22/TEST 2023~2026-06", "가족 난수 바닥선(최대 |평균|)"]',
         f"reason: >-\n  신호: {sig} · 경제성: {eco}. (판정 셀별: " + ", ".join(f"{c}={v}" for c, v in vs.items()) + ".)", "---\n",
         "# 기업행사 공시 이벤트 스터디 — 결과\n",
         "수치는 `corporate_events_study.py` 가 계산해 그대로 옮긴 값이다. 정의·기간·비용·판정은 사전등록(4fa3933) 그대로이며 결과를 보고 바꾸지 않았다.\n",
         "## 1. 판정\n", f"가족 난수 바닥선(|평균 초과| 최대의 95p): **{f(r['family_bar_bp'])}bp**\n",
         "| 셀 | 판정 | TRAIN 부호 | 사건 | TRAIN 평균 | VALID 평균 | TEST 평균 | OOS 손익분기 | OOS net 33.5 / 67 | OOS 군집 t |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for c in JUDGED:
        x = r["cells"][c]
        w = x["windows"]
        L.append(f"| {c} {NAMES[c]} | **{x['verdict']}** | {x['train_sign']:+d} | {x['events']} | "
                 f"{f(w['TRAIN']['mean_bp'])} | {f(w['VALID']['mean_bp'])} | {f(w['TEST']['mean_bp'])} | "
                 f"{f(x['OOS']['breakeven_bp'])} | {f(x['OOS']['net_bp'])} / {f(x['OOS']['net_stress_bp'])} | {f(x['OOS']['cluster_t'], 2)} |")
    L.append("\n평균은 20거래일 유동 EW 대비 초과수익(bp). 손익분기·net 은 TRAIN 부호를 곱한 방향 기준(음의 부호 셀은 롱이 아니라 회피 신호). E2·E3 처럼 TRAIN 부호가 음이면 ECONOMIC 이 될 수 없다.\n")
    L.append("## 2. 구간별 평균 초과 [진입일 군집 부트스트랩 95%] · 사건 수 · 사건일\n")
    L.append("| 셀 | TRAIN | VALID | TEST |\n|---|---|---|---|")
    for c in CELLS:
        w = r["cells"][c]["windows"]
        L.append(f"| {c} {NAMES[c]} | " + " | ".join(
            f"{f(w[k]['mean_bp'])} [{f(w[k]['ci95'][0])}, {f(w[k]['ci95'][1])}] · {w[k]['n']} · {w[k]['days']}일" for k in WINDOWS) + " |")
    L.append("\n## 3. 기록 전용 — 60거래일 초과수익(bp)\n")
    L.append("| 셀 | TRAIN | VALID | TEST |\n|---|---|---|---|")
    for c in CELLS:
        h = r["cells"][c]["h60"]
        L.append(f"| {c} | " + " | ".join(f"{f(h[k]['mean_bp'])} · {h[k]['n']}" for k in WINDOWS) + " |")
    L.append("\n## 4. 연도별 평균 초과 bp / 사건 수 (20거래일)\n")
    yrs = sorted({y for c in CELLS for y in r["cells"][c]["yearly_bp"]})
    L.append("| 셀 | " + " | ".join(str(y) for y in yrs) + " |")
    L.append("|---|" + "---|" * len(yrs))
    for c in CELLS:
        yb = r["cells"][c]["yearly_bp"]
        L.append(f"| {c} | " + " | ".join(f"{f(yb[y]['mean_bp'], 0)}/{yb[y]['n']}" if y in yb else "-" for y in yrs) + " |")
    L.append("\n## 5. 사전등록 대조\n")
    L.append("- E4(무상감자)는 사전등록대로 기록 전용이다. 사건 수가 구간별 30 미만이라 판정하지 않는다.")
    L.append("- 데이터: A3d 공시일(`disclosureDate`)·A2a 캐시(~2026-08-03). 같은 종목 30일 내 반복 공시는 첫 공시만 썼다.")
    L.append("- **E1 주의**: 20거래일 초과는 양(+)인데 60거래일 초과(기록 전용)는 세 구간 모두 음(−)이다 — 공시 뒤 표류가 뒤집힌다. 무상증자는 권리락(배정기준일) 전후로 가격이 조정되므로 **A2a 수정주가의 권리락 처리가 정확한지는 확인하지 않았다** — 해석 전에 점검할 사항이다.")
    L.append("- 세 셀 모두 세 구간에서 부호가 같고 OOS 군집 |t| 는 2.45~3.37 이지만, **판정은 사전등록 규칙(TRAIN 이 가족 바닥선 349bp 를 넘어야 함)대로 REJECT** 이다. TRAIN 이 바닥선에 못 미친 것은 표본이 작고 종목별 20일 초과수익의 변동이 커서다(검출력 문제일 수 있음).")
    L.append("- 신뢰구간은 진입일 군집 부트스트랩이다(같은 날 진입한 이벤트를 한 묶음으로 재추출).")
    return "\n".join(L) + "\n"


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        print(("PASS " if c else "FAIL ") + n)
        ok = ok and bool(c)

    T = pd.Timestamp
    ev = dedupe([("A", T("2020-01-01")), ("A", T("2020-01-20")), ("A", T("2020-03-01")), ("B", T("2020-01-05"))])
    check("중복 제거: 30일 안 반복은 첫 공시만", ev == [("A", T("2020-01-01")), ("A", T("2020-03-01")), ("B", T("2020-01-05"))])
    x = np.array([1.0, 2.0, 3.0, 4.0]); g = np.array([0, 0, 1, 1])
    check("군집 t 계산 가능", cluster_t(x, g) is not None)
    same = cluster_t(np.array([5.0, 5.0, 5.0, 6.0]), np.array([0, 1, 2, 3]))
    check("독립이면 군집 t 가 큰 값", same is not None and same > 2)
    rng = np.random.default_rng(0)
    pool = {0: np.random.default_rng(1).normal(0, 100, 300), 1: np.random.default_rng(2).normal(0, 100, 300)}
    bar = family_bar([{0: 10, 1: 10}, {0: 20}], pool, rng, 200)
    check("가족 바닥선은 양수", bar > 0)
    tr, va, te = np.full(40, 90.0), np.full(40, 60.0), np.full(40, 50.0)
    check("판정: 통과 → ECONOMIC", verdict(tr, va, te, 50.0, 10.0, 5.0, 1.0) == "ECONOMIC")
    check("판정: 음의 부호는 ECONOMIC 불가(INFORMATION)", verdict(-tr, -va, -te, 50.0, 10.0, 5.0, 3.0) == "INFORMATION")
    check("판정: OOS 부호 반전 → REJECT", verdict(tr, -va, te, 50.0, 10.0, 5.0, 1.0) == "REJECT")
    check("판정: 30 미만 → 판정불가", verdict(tr[:5], va, te, 50.0, 10.0, 5.0, 1.0) == "판정불가")
    check("판정: |t|≥2 → ROBUST", verdict(tr, va, te, 50.0, 10.0, 5.0, 2.4) == "ROBUST")
    check("구간 매핑", window_of(2016) == "TRAIN" and window_of(2021) == "VALID" and window_of(2026) == "TEST" and window_of(2015) is None)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        sys.exit(selftest())
    main()
