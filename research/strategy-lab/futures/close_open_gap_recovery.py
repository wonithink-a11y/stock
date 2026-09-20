#!/usr/bin/env python3
"""갭하락 후 종가 회복(O5) → 익일 시가 — 결과 산출. 사전등록: findings/close-open-gap-recovery-preregistration-2026-09.md (356b95c).

    python research/strategy-lab/futures/close_open_gap_recovery.py --selftest   # 네트워크 없음
    python research/strategy-lab/futures/close_open_gap_recovery.py              # 실행 (A2a 캐시 필요)

판정 셀은 O5 하나. R1~R3 는 기록 전용(가족에 넣지 않는다). 조건·임계·구간·판정은 사전등록 그대로이며 결과를 보고 바꾸지 않는다.
산출: findings/close-open-gap-recovery-results-2026-09.{md,json}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import close_open_phase5 as p5  # noqa: E402
import short_horizon_study as shs  # noqa: E402
from short_horizon_study import tstat  # noqa: E402
from structure_phase4 import family  # noqa: E402

OUT = HERE.parent / "findings" / "close-open-gap-recovery-results-2026-09"
SEED = 20260926
N_FLIPS = 1000                   # 사전등록 §3
N_BOOT = 2000                    # 사전등록 §5
MIN_EVENT_DAYS = 30              # 사전등록 §4
GAP_MAX, RET_MAX, CLV_MIN = -0.02, -0.04, 0.8
SPLITS = ("TRAIN", "VALID", "TEST")

O5 = (lambda u: (u.gap <= GAP_MAX) & (u.clv >= CLV_MIN), "on", 1, p5.LONG)


def add_prev_ret(u):
    u = u.copy()
    u["prev_ret"] = u.groupby("ticker")["ret"].shift(1)
    return u


def daily(u, cond, win):
    """조건 사건 → 일자별 (정보 bp, gross bp, 종가 tick bp) 등가중. 상한 제외는 phase5 와 같다."""
    ev = u[cond & u[win].notna() & (u.ret < p5.LIMIT_UP)]
    mkt = u.groupby("date")[win].mean()
    df = pd.DataFrame({"date": ev.date, "i": ev[win] - ev.date.map(mkt), "g": ev[win],
                       "tk": p5.tick_bp(ev["close"] if win == "on" else ev["open"])})
    return df.groupby("date").mean(), len(ev)


def to_obs(d):
    return [(dt, r.i, r.g, p5.FIXED_BP, p5.FIXED_BP + r.tk) for dt, r in d.iterrows()]


def window_of(dates):
    return np.array([p5.split(x) for x in dates])


def boot_ci(x, rng, n=N_BOOT):
    if len(x) < 3:
        return (None, None)
    m = np.array([rng.choice(x, len(x)).mean() for _ in range(n)])
    return (float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975)))


def null_rank(train_by_cell, observed_abs_t, rng, n=N_FLIPS):
    """가족 null(TRAIN 부호 반전 최대 |t|) 분포에서 관측값 이상인 비율."""
    mx = np.array([max(abs(tstat(x * rng.choice([-1, 1], len(x)))) for x in train_by_cell) for _ in range(n)])
    return float((mx >= observed_abs_t).mean()), float(np.quantile(mx, 0.95))


def cell_report(d, sign, rng):
    """gross/손익분기/net 표준 열. d = 일자별 프레임(i,g,tk). sign 은 TRAIN 정보 평균의 부호(None 이면 셀 자신의 TRAIN 부호)."""
    w = window_of(d.index)
    if sign is None:
        sign = 1 if d.i.to_numpy()[w == "TRAIN"].mean() >= 0 else -1
    rep = {"days": {k: int((w == k).sum()) for k in SPLITS}}
    for k in SPLITS:
        x = sign * d.g.to_numpy()[w == k]
        lo, hi = boot_ci(x, rng)
        rep[k] = {"gross_bp": float(x.mean()) if len(x) else None, "ci95": [lo, hi],
                  "info_bp": float(d.i.to_numpy()[w == k].mean()) if (w == k).any() else None}
    oos = (w != "TRAIN")
    x = sign * d.g.to_numpy()[oos]
    lo, hi = boot_ci(x, rng)
    rep["VT"] = {"gross_bp": float(x.mean()), "ci95": [lo, hi], "breakeven_bp": float(x.mean()),
                 "net_fixed_bp": float((x - p5.FIXED_BP).mean()),
                 "net_stress_bp": float((x - (p5.FIXED_BP + d.tk.to_numpy()[oos])).mean()),
                 "net_event_bp": float((x - p5.EVENT_BP).mean()), "t_gross": float(tstat(x)),
                 "days": int(oos.sum())}
    rep["train_t_info"] = float(tstat(d.i.to_numpy()[w == "TRAIN"]))
    return rep


def main():
    a = p5.load()
    u = add_prev_ret(a[a.liq >= p5.LIQ_MIN])
    p5.CELLS["O5"] = O5
    shs.N_FLIPS = N_FLIPS
    rng = np.random.default_rng(SEED)

    cells, counts = {}, {}
    for cid in p5.CELLS:
        cells[cid], counts[cid] = p5.cell_events(u, cid)
    flags = {c: p5.CELLS[c][3] for c in p5.CELLS}
    res = family(cells, p5.split, rng, flags)
    o5 = res["cells"]["O5"]

    d5, n5 = daily(u, O5[0](u), "on")
    s = int(o5["train_sign"]) if "train_sign" in o5 else 1
    rep = {"O5": cell_report(d5, s, rng)}
    # 판정불가 규칙(사전등록 §4): 구간별 사건일 < 30
    thin = [k for k in SPLITS if rep["O5"]["days"][k] < MIN_EVENT_DAYS]
    verdict = "판정불가" if thin else o5["verdict"]
    # 가족 백분위
    live = [c for c in cells if len(np.array([e[1] for e in cells[c] if p5.split(e[0]) == "TRAIN"])) > 2]
    train_lists = [np.array([e[1] for e in cells[c] if p5.split(e[0]) == "TRAIN"]) for c in live]
    tr = d5.i.to_numpy()[window_of(d5.index) == "TRAIN"]
    frac, bar1000 = null_rank(train_lists, abs(tstat(tr)), rng)

    # ---- 기록 전용 ----
    rec = {}
    rules = {"R1": (u.ret <= RET_MAX) & (u.clv >= CLV_MIN),
             "R2": O5[0](u) & (u.prev_ret < 0)}
    for cid, cond in rules.items():
        d, n = daily(u, cond, "on")
        rec[cid] = {"events": int(n), "report": cell_report(d, None, rng)}
    d3, n3 = daily(u, O5[0](u), "ocn")
    rec["R3_ocn"] = {"events": int(n3), "report": cell_report(d3, None, rng)}
    # 겹침, 연도별 net
    o5_mask, r1_mask = O5[0](u), rules["R1"]
    both = int((o5_mask & r1_mask & (u.ret < p5.LIMIT_UP)).sum())
    yrs = pd.Series(s * d5.g.to_numpy() - p5.FIXED_BP, index=pd.to_datetime(d5.index)).groupby(lambda x: x.year).mean()
    out = {"seed": SEED, "family_cells": live, "bar_1000": round(bar1000, 2), "bar_reported_by_family": res["bar"],
           "O5": {"verdict": verdict, "judge": o5, "events": int(n5), "report": rep["O5"],
                  "family_percentile_p": frac, "yearly_net_bp": {int(y): round(float(v), 1) for y, v in yrs.items()},
                  "thin_windows": thin},
           "record_only": rec, "overlap_R1_in_O5": both,
           "cost_bp": {"fixed": round(p5.FIXED_BP, 2), "event": p5.EVENT_BP}}
    (OUT.with_suffix(".json")).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    print("O5", verdict, "bar", res["bar"], "| 가족 백분위 p", round(frac, 4))
    print("VT gross", round(rep["O5"]["VT"]["gross_bp"], 2), "net", round(rep["O5"]["VT"]["net_fixed_bp"], 2))


def f(x, nd=1):
    return "n/a" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


def row(name, r):
    rr = r["report"] if "report" in r else r
    cells = []
    for k in SPLITS:
        x = rr[k]
        cells.append(f"{f(x['gross_bp'])} [{f(x['ci95'][0])}, {f(x['ci95'][1])}] · {rr['days'][k]}일")
    v = rr["VT"]
    return (f"| {name} | " + " | ".join(cells) +
            f" | {f(v['gross_bp'])} [{f(v['ci95'][0])}, {f(v['ci95'][1])}] | **{f(v['breakeven_bp'])}** | "
            f"{f(v['net_fixed_bp'])} / {f(v['net_stress_bp'])} / {f(v['net_event_bp'])} |")


def render(o):
    b = o["O5"]
    j = b["judge"]
    v = b["verdict"]
    sig = "있음" if v in ("INFORMATION", "ECONOMIC", "ROBUST") else "없음"
    eco = "통과" if v in ("ECONOMIC", "ROBUST") else "미달"
    L = ["---", "track: kr", "factor: close-open-gap-recovery", "date: 2026-09-20", f"verdict: {v}",
         "criteria_version: research-only (close-open-gap-recovery-preregistration-2026-09, 356b95c)",
         'conditions: ["갭≤-2% ∧ CLV≥0.8, 종가→익일 시가", "A2a 일봉 2016~2026-08 유동 종목", "TRAIN<=2020/VALID 2021~22/TEST 2023~", "가족 15셀 부호반전 1,000회"]',
         f"reason: >-\n  신호: {sig} · 경제성: {eco}. (스크립트가 계산한 판정 {v}; 수치는 아래 표.)", "---\n",
         "# 갭하락 후 종가 회복 → 익일 시가 — 결과\n",
         "수치는 `futures/close_open_gap_recovery.py` 가 계산해 그대로 옮긴 값이다. 조건·임계·구간·판정은 사전등록(356b95c) 그대로이며 결과를 보고 바꾸지 않았다.\n",
         "## 1. 판정\n",
         f"**{v}** (신호: {sig} · 경제성: {eco}) — 종가 동시 체결형이라 ECONOMIC 이면 ECONOMIC-OPTIMISTIC 이다.\n",
         "| 항목 | 값 |\n|---|---|",
         f"| 사건(종목-일) | {b['events']:,} |",
         f"| TRAIN 부호 | {j.get('train_sign')} · TRAIN 정보 t {f(j.get('t_train'), 2)} |",
         f"| 가족 바닥선(15셀, 1,000회) | {o['bar_1000']} (기존 함수 보고값 {o['bar_reported_by_family']}) |",
         f"| **O5 의 가족 백분위(null 최대 |t| 가 관측 이상인 비율)** | {b['family_percentile_p']:.4f} |",
         f"| VALID+TEST t(방향 gross) | {f(b['report']['VT']['t_gross'], 2)} |",
         f"| 판정불가 구간(사건일<30) | {b['thin_windows'] or '없음'} |\n",
         "## 2. gross · 손익분기 · net (표준 열, bp)\n",
         "gross 는 TRAIN 부호를 곱한 방향 수익, 괄호는 일자 단위 부트스트랩 95% 신뢰구간.\n",
         "| 셀 | TRAIN gross | VALID gross | TEST gross | VALID+TEST gross | **손익분기 비용** | net 23.54 / 스트레스 / 이벤트20 |",
         "|---|---|---|---|---|---|---|",
         row("**O5 (판정)**", b)]
    rec = o["record_only"]
    L.append(row("R1 급락≤−4%∧CLV≥0.8 (기록)", rec["R1"]))
    L.append(row("R2 O5∧전일<0 (기록)", rec["R2"]))
    L.append(row("R3 O5 익일 시가→종가 (기록)", rec["R3_ocn"]))
    L.append("")
    L.append("| 셀 | 사건 |\n|---|---|")
    L.append(f"| R1 | {rec['R1']['events']:,} (O5 에도 해당 {o['overlap_R1_in_O5']:,}) |")
    L.append(f"| R2 | {rec['R2']['events']:,} |")
    L.append(f"| R3 | {rec['R3_ocn']['events']:,} |")
    L.append("\n## 3. 구간별 정보(유니버스 EW 대비 초과) bp\n")
    L.append("| 구간 | O5 정보 | O5 gross | 사건일 |\n|---|---|---|---|")
    for k in SPLITS:
        x = b["report"][k]
        L.append(f"| {k} | {f(x['info_bp'])} | {f(x['gross_bp'])} | {b['report']['days'][k]} |")
    L.append("\n## 4. 연도별 net (23.54bp 적용, TRAIN 부호 기준, bp)\n")
    L.append("| " + " | ".join(str(y) for y in b["yearly_net_bp"]) + " |")
    L.append("|" + "---|" * len(b["yearly_net_bp"]))
    L.append("| " + " | ".join(str(v_) for v_ in b["yearly_net_bp"].values()) + " |")
    L.append("\n## 5. 사전등록 대조\n")
    L.append("- 데이터는 사전등록대로 `.cache/a2a_parquet`(2016~2026-08-03). 커밋된 a2a jsonl.gz(~09-16)와 끝이 다르다.")
    L.append(f"- 가족 바닥선은 사전등록대로 부호 반전 1,000회로 다시 계산했다(기존 14셀 보고값 2.98 은 500회).")
    L.append("- 정보 t·INFORMATION 판정은 기존 `family()`/`judge()` 를 그대로 썼다. 새로 더한 것: 일자 부트스트랩 신뢰구간, 가족 백분위, 사건일<30 판정불가 규칙, 손익분기(= 방향 gross).")
    L.append("- 종가 동시 체결형(신호 = 최종 종가·최종 CLV)이라 경제성 통과는 낙관이다 — 15:20 재검증 전 채택 후보 아님.")
    return "\n".join(L) + "\n"


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        print(("PASS " if c else "FAIL ") + n)
        ok = ok and bool(c)

    # 합성 유니버스: 갭≤-2% ∧ CLV≥0.8 만 골라내는가, 상한(28%)·NaN CLV 제외
    df = pd.DataFrame({
        "ticker": list("AAAAB"), "date": pd.to_datetime(["2020-01-02"] * 5), "open": [98, 99, 98, 90, 98.5],
        "high": [110, 110, 110, 100, 100], "low": [95, 95, 95, 90, 98], "close": [108, 100, 108, 100, 99.9],
        "gap": [-0.02, -0.02, -0.01, -0.10, -0.03], "clv": [0.87, 0.33, 0.87, 1.0, np.nan],
        "ret": [0.05, 0.0, 0.05, 0.30, 0.0], "on": [10, 10, 10, 10, 10.0], "ocn": [0] * 5, "amt": [1] * 5})
    m = O5[0](df)
    check("O5 조건: 갭≤-2% ∧ CLV≥0.8 (경계 포함, NaN 제외)", list(m) == [True, False, False, True, False])
    d, n = daily(df.assign(liq=3e9), m, "on")
    check("상한(ret≥28%) 제외 후 사건 1", n == 1)
    x = np.random.default_rng(0).normal(5, 1, 200)
    lo, hi = boot_ci(x, np.random.default_rng(1), 500)
    check("부트스트랩 CI 가 평균을 감싼다", lo < x.mean() < hi)
    rng = np.random.default_rng(2)
    noise = [rng.normal(0, 1, 300) for _ in range(5)]
    frac, bar = null_rank(noise, 0.5, np.random.default_rng(3), 200)
    check("잡음 t 0.5 는 null 최대에 자주 묻힌다(p 큼)", frac > 0.8)
    frac2, _ = null_rank(noise, 8.0, np.random.default_rng(3), 200)
    check("t 8 은 null 밖(p 0)", frac2 == 0.0)
    check("비용 상수 23.54", abs(p5.FIXED_BP - 23.54) < 0.01)
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        sys.exit(selftest())
    main()
