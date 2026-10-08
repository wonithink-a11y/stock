#!/usr/bin/env python3
"""대량 거래 장대음봉(분산일) 뒤 개별주 — 사전등록 findings/distribution-day-preregistration-2026-10.md 그대로.

    python research/strategy-lab/distribution_day_study.py --selftest
    python research/strategy-lab/distribution_day_study.py           # → findings/distribution-day-results-2026-10.{md,json}

로더·적격·결과(R20)·플라시보·귀무·블록 부트스트랩은 surge_day_continuation.py 를 그대로 쓴다.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import surge_day_continuation as s

OUT = HERE / "findings" / "distribution-day-results-2026-10"
A3D = ROOT / "data" / "backfill" / "fundamentals" / "a3d"
SHARE_EVENTS = ("split", "bonusIssue", "reverseOrConsolidation", "capitalReductionFree", "capitalReductionPaid", "capitalReductionUnknown")
SEED = 20261009
UP60, VR_MIN, BODY, GAP, A3D_DAYS, HALT_BACK = 0.20, 3.0, 0.04, 60, 120, 30
CENTRAL = ("D1", "D2")


def share_event_mask(dates, tick):
    """A3d 주식 수 변동 공시일부터 120일 안 = True (D × N)."""
    ti = {t: j for j, t in enumerate(tick)}
    M = np.zeros((len(dates), len(tick)), bool)
    for cat in SHARE_EVENTS:
        f = A3D / f"{cat}.jsonl.gz"
        if not f.exists():
            continue
        for line in gzip.open(f, "rt", encoding="utf-8"):
            r = json.loads(line)
            j = ti.get(r.get("ticker"))
            d = r.get("disclosureDate")
            if j is None or not d:
                continue
            d0 = pd.Timestamp(d)
            a, b = np.searchsorted(dates, d0), np.searchsorted(dates, d0 + timedelta(days=A3D_DAYS), side="right")
            M[a:b, j] = True
    return M


def conditions(O, C, V):
    """(VR30, 60일 수익, 음봉 몸통, 양봉 몸통, 전일 대비 하락) — 신호일 t 에 아는 값만."""
    Vz = np.where(V > 0, V, np.nan)
    v30 = pd.DataFrame(Vz).shift(1).rolling(30, min_periods=20).mean().to_numpy()
    vr = V / v30
    up60 = C / s.sh(C, -60) - 1
    red = (O - C) / O
    green = (C - O) / O
    down = C < s.sh(C, -1)
    return vr, up60, red, green, down


def cell_masks(vr, up60, red, green, down):
    with np.errstate(invalid="ignore"):
        climax = vr >= VR_MIN
        D2 = climax & (red >= BODY) & down
        D1 = D2 & (up60 >= UP60)
        D0 = climax & (green >= BODY) & (up60 >= UP60)
    return {"D1": D1, "D2": D2, "D0": D0}


def run():
    t0 = pd.Timestamp.now()
    dates, tick, raw = s.load_raw()
    P = s.derive(raw, dates)
    O, H, L, C, V = P["On"], P["Hn"], P["Ln"], P["Cn"], P["Vn"]
    halt0 = (raw["open"] == 0) & (raw["volume"] == 0)
    halt_back = pd.DataFrame(halt0.astype(float)).rolling(HALT_BACK + 1, min_periods=1).sum().to_numpy() > 0
    ok = P["elig"] & ~share_event_mask(dates, tick) & ~halt_back
    vr, up60, red, green, down = conditions(O, C, V)
    raw_masks = {k: m & ok for k, m in cell_masks(vr, up60, red, green, down).items()}
    U = np.zeros_like(ok)
    for m in raw_masks.values():
        U |= m
    rng = np.random.default_rng(SEED)
    M = s.outcome_mats(P)
    PL, PM, pool = s.placebo(P, U, M, rng)
    hi250 = pd.DataFrame(H).shift(1).rolling(250, min_periods=200).max().to_numpy()
    rng_pos = (C - L) / (H - L)

    cells, arrs = {}, {}
    for k, m in raw_masks.items():
        t, j = np.nonzero(m)
        t, j = s.dedup(t, j, GAP)
        mi = np.asarray(s.month_idx(dates, t), dtype=np.int64)
        keep = (mi >= 0) & (mi < s.NM)
        t, j, mi = t[keep], j[keep], mi[keep]
        cells[k] = s.cell_summary(k, t, j, mi, P, M, PM, rng)
        arrs[k] = (t, j, mi)
    null = s.null_dist([(arrs[k][0], arrs[k][2]) for k in CENTRAL], pool, M["R20"], PM["R20"], rng, s.N_PERM)
    verdicts = {}
    for c, k in enumerate(CENTRAL):
        r = cells[k]
        lo, hi = np.nanpercentile(null[:, c, 1], [1, 99])
        w = [r["info_mean"][x] for x in ("TRAIN", "VALID", "TEST")]
        ci = r["ci"]["ALL"]
        if r["info_all"] < lo and all(x < 0 for x in w) and ci[1] < 0:
            v = "REVERSE"
        elif r["info_all"] > hi and all(x > 0 for x in w) and ci[0] > 0:
            v = "INFORMATION"
        else:
            v = "NONE"
        econ = all(-r["info_mean"][x] > s.COST for x in ("VALID", "TEST")) if v == "REVERSE" else False
        verdicts[k] = dict(verdict=v, null_1=float(lo), null_99=float(hi), avoid_economic=econ)

    # 기록: 세분
    segs = {}
    for k in CENTRAL:
        t, j, mi = arrs[k]
        feats = {
            "몸통 4~7%": red[t, j] < 0.07, "몸통 ≥7%": red[t, j] >= 0.07,
            "VR30 3~5": vr[t, j] < 5, "VR30 ≥5": vr[t, j] >= 5,
            "52주 고점 근처": C[t, j] >= 0.9 * hi250[t, j], "52주 고점 아래": ~(C[t, j] >= 0.9 * hi250[t, j]),
            "종가 하루 범위 하위 25%": rng_pos[t, j] <= 0.25, "종가 하루 범위 25% 위": ~(rng_pos[t, j] <= 0.25),
        }
        if k == "D1":
            feats |= {"앞선 상승 20~50%": up60[t, j] < 0.5, "앞선 상승 ≥50%": up60[t, j] >= 0.5}
        segs[k] = {}
        for name, sel in feats.items():
            if sel.sum() >= 30:
                r = s.cell_summary(name, t[sel], j[sel], mi[sel], P, M, PM, rng, with_ci=False)
                segs[k][name] = dict(n=r["n"], info_all=r["info_all"], info=r["info_mean"])
    years = {k: pd.Series(dates[arrs[k][0] + 1].year).value_counts().sort_index().to_dict() for k in cells}
    out = dict(cells={k: {x: v for x, v in r.items() if x != "_arr"} for k, r in cells.items()}, verdicts=verdicts, segments=segs,
               years={k: {int(a): int(b) for a, b in v.items()} for k, v in years.items()},
               d1_minus_d0=cells["D1"]["info_all"] - cells["D0"]["info_all"], price_last=str(dates[-1].date()),
               runtime_s=(pd.Timestamp.now() - t0).total_seconds())
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    for k in cells:
        r = cells[k]
        print(k, r["n"], {w: round(r["info_mean"][w] * 100, 2) for w in s.WIN}, "all", round(r["info_all"] * 100, 2), verdicts.get(k))
    return 0


def p(x, d=2):
    return "" if x is None or not np.isfinite(x) else f"{x * 100:+.{d}f}%"


def render(o):
    v = o["verdicts"]
    sig = "있음(" + "·".join(f"{k} {x['verdict']}" for k, x in v.items() if x["verdict"] != "NONE") + ")" if any(x["verdict"] != "NONE" for x in v.values()) else "없음"
    econ = "통과" if any(x["avoid_economic"] for x in v.values()) else "미달"
    L = ["---", "track: kr", "factor: distribution-day", "date: 2026-10-09",
         f"verdict: {'REVERSE' if any(x['verdict'] == 'REVERSE' for x in v.values()) else ('INFORMATION' if any(x['verdict'] == 'INFORMATION' for x in v.values()) else 'NONE')}",
         "criteria_version: research-only (distribution-day-preregistration-2026-10)",
         'conditions: ["A2a+A2b 일봉 2016~2026-10-02", "D1 = 60일 +20% ∧ 거래량 30일 평균 3배 ∧ 음봉 몸통 4% ∧ 하락", "D2 = 앞선 상승 무관", "Info = 20일 수익 − 같은 날 무작위 20종목", "가짜 사건 1,000회 1·99백분위, 6개월 블록"]',
         "reason: >-", f"  신호: {sig} · 경제성(회피 규칙): {econ}. " + " · ".join(f"{k} {x['verdict']}" for k, x in v.items()) + ". (스크립트 판정, 정의는 사전등록 그대로)",
         "---", "", "# 대량 거래 장대음봉(분산일) 뒤 개별주 — 결과", "",
         f"수치는 `distribution_day_study.py` 가 계산한 값 그대로. 가격 마지막 날 {o['price_last']}.", "",
         "## 1. 칸별 20일 Info (진입월 평균, %)", "",
         "| 칸 | 사건 | 종목 | TRAIN | VALID | TEST | 2026 | 전체 [블록 95%] | 귀무 1·99백분위 | 판정 | 비용 후 OOS 절대 | 중앙 수익 | 승률(비용 후) |",
         "|---|---:|---:|---:|---:|---:|---:|---|---|---|---:|---:|---:|"]
    for k, r in o["cells"].items():
        vv = v.get(k, {})
        ci = r["ci"]["ALL"]
        L.append(f"| {k} | {r['n']:,} | {r['firms']:,} | {p(r['info_mean']['TRAIN'])} | {p(r['info_mean']['VALID'])} | {p(r['info_mean']['TEST'])} | {p(r['info_mean']['REC'])} | "
                 f"{p(r['info_all'])} [{p(ci[0])}, {p(ci[1])}] | {'' if not vv else p(vv['null_1']) + ' · ' + p(vv['null_99'])} | **{vv.get('verdict', '기록')}** | "
                 f"{'' if r['oos_net_mean_pct'] is None else format(r['oos_net_mean_pct'], '+.2f') + '%'} | "
                 f"{r['median_ret_pct']:+.2f}% | {r['win_rate_net'] * 100:.0f}% |")
    L += ["", f"D1 − D0(음봉이 거래량 절정의 약세를 키우는가, 기록): {p(o['d1_minus_d0'])}.", "",
          "회피 규칙 경제성 = 약세 확정 칸에서 VALID·TEST 모두 −Info > 23.54bp: " + ", ".join(f"{k} {'통과' if x['avoid_economic'] else '미달'}" for k, x in v.items()), "",
          "## 2. 기록 — 세분 (Info 전체, TRAIN/VALID/TEST)", "", "| 칸 | 세분 | 사건 | 전체 | TRAIN | VALID | TEST |", "|---|---|---:|---:|---:|---:|---:|"]
    for k, segs in o["segments"].items():
        for name, r in segs.items():
            L.append(f"| {k} | {name} | {r['n']} | {p(r['info_all'])} | {p(r['info']['TRAIN'])} | {p(r['info']['VALID'])} | {p(r['info']['TEST'])} |")
    L += ["", "## 3. 기록 — 연도별 사건 수", ""]
    for k, ys in o["years"].items():
        L.append(f"- {k}: " + " · ".join(f"{y} {n}" for y, n in ys.items()))
    L += ["", "## 4. 기록 — 연속성(20일, 사건 − 플라시보)", "", "| 칸 | 5일 상승일 비율 | 20일 뒤 종가 > 신호일 종가 | MFE20 | MAE20 |", "|---|---:|---:|---:|---:|"]
    for k, r in o["cells"].items():
        c = r["cont"]
        L.append(f"| {k} | {p(c['UP5']['diff'], 1)} | {p(c['POS20']['diff'], 1)} | {p(c['MFE20']['diff'], 1)} | {p(c['MAE20']['diff'], 1)} |")
    return "\n".join(L) + "\n"


def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    D = 100
    C = np.full((D, 1), 100.0)
    C[30:90, 0] = np.linspace(100, 130, 60)          # 60일 +30%
    O = C.copy()
    V = np.full((D, 1), 1000.0)
    O[90, 0], C[90, 0], V[90, 0] = 131.0, 124.0, 4000.0   # 몸통 5.3%, 거래량 4배, 전일(130) 대비 하락
    O[95, 0], C[95, 0], V[95, 0] = 120.0, 126.0, 4000.0   # 양봉 5%
    vr, up60, red, green, down = conditions(O, C, V)
    m = cell_masks(vr, up60, red, green, down)
    check("D1·D2 는 90일만", np.flatnonzero(m["D1"][:, 0]).tolist() == [90] and np.flatnonzero(m["D2"][:, 0]).tolist() == [90])
    check("D0 는 95일(양봉·앞선 상승)", np.flatnonzero(m["D0"][:, 0]).tolist() == [95])
    V2 = V.copy()
    V2[90, 0] = 2500.0
    check("거래량 2.5배면 아님", not cell_masks(*conditions(O, C, V2))["D1"][90, 0])
    O3 = O.copy()
    O3[90, 0] = 127.0
    check("몸통 2.4% 면 아님", not cell_masks(*conditions(O3, C, V))["D1"][90, 0])
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    sys.exit(selftest() if ap.parse_args().selftest else run())
