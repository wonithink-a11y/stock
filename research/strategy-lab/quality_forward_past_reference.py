#!/usr/bin/env python3
"""수익성 forward 정의(해시 a7ca0a2c37)의 과거 참고 계산 — 사전등록 개정 1(§9). **판정 불사용.**

    python research/strategy-lab/quality_forward_past_reference.py

run_quality_forward.py 의 build_signal·stock_returns·cell_outcome 을 그대로 부른다(정의 재구현 없음).
신호 2016-01 ~ 가격이 있는 마지막 달, 폐지 종목 포함(A2a ∪ A2b).
산출: reports/2026-10-quality-forward-past/{monthly.csv, summary.json}
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_quality_forward as q  # noqa: E402

OUT = HERE / "reports" / "2026-10-quality-forward-past"
START = "2016-04"   # 2016-01~03 은 FY2015 공시 전이라 모집단 ~25종목(재무 A3 가 FY2015 부터) - 제외
PERIODS = {"2016~23": ("2016-01", "2023-12"), "2024": ("2024-01", "2024-12"), "2025~": ("2025-01", "2099-12")}
N_BOOT, BLOCK, SEED = 2000, 6, 20261017


def block_ci(x, rng):
    x = np.asarray(x, float)
    n = len(x)
    if n < BLOCK * 2:
        return [float("nan"), float("nan")]
    starts = np.arange(n - BLOCK + 1)
    k = int(np.ceil(n / BLOCK))
    means = [x[np.concatenate([np.arange(s, s + BLOCK) for s in rng.choice(starts, k)])[:n]].mean() for _ in range(N_BOOT)]
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


def summarize(df, rng):
    out = {}
    for name, (a, b) in PERIODS.items():
        d = df[(df.month >= a) & (df.month <= b)]
        row = {"months": int(len(d))}
        for col in ("q1_ex", "q1_net", "q2_ex", "q2_net", "bot_ex", "ic", "q1_ex_xsemi", "q2_ex_xsemi"):
            m, t, _p = q.t_one_sided(d[col].dropna())
            row[col] = {"mean": m, "t": t}
        for cell in ("q1", "q2"):
            rep = float(d[f"{cell}_rep"].mean())
            row[f"{cell}_ex"]["ci95"] = block_ci(d[f"{cell}_ex"], rng)
            row[f"{cell}_breakeven_rt_bp"] = float(d[f"{cell}_ex"].mean() / rep * 1e4) if rep > 0 else None
            row[f"{cell}_replaced_mean"] = rep
        out[name] = row
    return out


def main():
    trading_days, month_first = q.load_calendar()
    C, V = q.load_prices(2015)
    a3 = q.load_a3()
    semi = q.semi_set()
    months = [m for m in sorted(month_first) if m >= START]
    rows, prev = [], None
    for i, m in enumerate(months[:-1]):
        s, exit_ = month_first[m], month_first[months[i + 1]]
        if not (q.date_ready(C, s) and q.date_ready(C, exit_)):
            break
        sig = q.build_signal(s, C, V, a3)
        entry = trading_days[trading_days.index(s) + 1]
        pop = [p[0] for p in sig["pop"]]
        ret, flags = q.stock_returns(C, pop, entry, exit_)
        o = q.cell_outcome(sig, prev, ret)
        r = pd.Series(ret)
        comp = pd.Series({p[0]: p[4] for p in sig["pop"]})
        keep = [t for t in pop if t not in semi]
        bx = r[keep].mean()
        q1x = [t for t in sig["q1"] if t not in semi]
        excl = set(sig["excl"])
        rows.append({
            "month": m, "signal": s, "n_pop": sig["n_pop"], "n_q1_semi": len(sig["q1"]) - len(q1x),
            "bench": o["bench"],
            "q1_ex": o["Q1"]["excess"], "q1_rep": o["Q1"]["replaced"], "q1_net": o["Q1"]["excess"] - o["Q1"]["cost"],
            "q2_ex": o["Q2"]["excess"], "q2_rep": o["Q2"]["replaced"], "q2_net": o["Q2"]["excess"] - o["Q2"]["cost"],
            "bot_ex": float(r[sig["excl"]].mean() - o["bench"]),
            "ic": float(comp.rank().corr(r[comp.index].rank())),
            "q1_ex_xsemi": float(r[q1x].mean() - bx) if q1x else np.nan,
            "q2_ex_xsemi": float(r[[t for t in keep if t not in excl]].mean() - bx),
            "lastAvail": flags["lastAvail"], "noPrice": flags["noPrice"],
        })
        prev = sig
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / "monthly.csv", index=False, float_format="%.6f")
    rng = np.random.default_rng(SEED)
    summ = {"def": q.DEF_HASH, "note": "참고 - 판정 불사용 (사전등록 개정 1)", "first": rows[0]["signal"], "last": rows[-1]["signal"],
            "months": len(rows), "pop_median": float(df.n_pop.median()), "lastAvail_total": int(df.lastAvail.sum()),
            "noPrice_total": int(df.noPrice.sum()), "q1_semi_names_mean": {k: float(df[(df.month >= a) & (df.month <= b)].n_q1_semi.mean()) for k, (a, b) in PERIODS.items()},
            "periods": summarize(df, rng),
            "all": summarize(df.assign(month="2020-01"), rng)["2016~23"]}   # 전 구간을 한 칸에 넣어 같은 함수로 요약
    (OUT / "summary.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n완료: {len(rows)}달 ({rows[0]['signal']} ~ {rows[-1]['signal']}) -> {OUT}")


if __name__ == "__main__":
    main()
