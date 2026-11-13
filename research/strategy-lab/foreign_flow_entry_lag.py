"""외국인 수급 5일 — 진입 지연 점검. 사전등록 findings/foreign-flow-entry-lag-preregistration-2026-11.md (a8159589).

L0 = 원 정의 close(t+5)/close(t)-1, L1 = 다음 거래일 종가 진입 close(t+6)/close(t+1)-1. 같은 표본·같은 5분위 스프레드·같은 NW t. 기록 전용.

    python research/strategy-lab/foreign_flow_entry_lag.py [--selftest]
산출: findings/foreign-flow-entry-lag-results-2026-11.{md,json}
"""
import json
import os
import sys

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import verify_flow_basic_effect_independent as v  # noqa: E402

OUT = os.path.join(LAB, "findings", "foreign-flow-entry-lag-results-2026-11")
COST = 33.5
PERIODS = {"2016~23": ("2016-01-01", "2024-01-01"), "2024": ("2024-01-01", "2025-01-01"), "2025~": ("2025-01-01", "2026-12-31")}


def label(res):
    m = [res[p]["mean"] for p in v.SPLIT]
    t = [res[p]["nw_t"] for p in v.SPLIT]
    if any(x <= 0 for x in m):
        return "소멸"
    return "유지" if all(x is not None and x >= 2 for x in t) else "약화"


def stats(df, col, lo, hi):
    mask = (df["date"] >= lo) & (df["date"] < hi)
    q = v.compute_quintile_spread(df[mask], "foreign_flow_ratio", col)
    s = v.spread_stats(q)
    return {k: (None if s[k] is None else float(s[k])) for k in ("mean", "t_stat", "nw_t")} | {"n_days": int(s["n_days"])}


def run():
    price, flow = v.load_a2a_price(), v.load_a4_flow()
    df = price.merge(flow, on=["ticker", "date"], how="inner").sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")["close"]
    df["fwd_l0"] = g.transform(lambda s: s.shift(-5) / s - 1)
    df["fwd_l1"] = g.transform(lambda s: s.shift(-6) / s.shift(-1) - 1)
    df["foreign_flow_ratio"] = df["foreign_net"] / df["total_amount"].replace(0, np.nan)
    out = {"rows": int(len(df)), "tickers": int(df["ticker"].nunique()), "dateRange": [df["date"].min(), df["date"].max()]}
    for col in ("fwd_l0", "fwd_l1"):
        out[col] = {"all": stats(df, col, "2000-01-01", "2100-01-01"),
                    **{p: stats(df, col, *rng) for p, rng in v.SPLIT.items()},
                    "periods": {p: stats(df, col, *rng) for p, rng in PERIODS.items()}}
    out["label"] = label({p: out["fwd_l1"][p] for p in v.SPLIT})
    return out


def write(o):
    l0, l1 = o["fwd_l0"], o["fwd_l1"]
    bp = lambda x: f"{x * 1e4:+.1f}"  # noqa: E731
    reason = (f"신호: {'있음' if o['label'] != '소멸' else '없음'}({o['label']}: L1 전체 mean {bp(l1['all']['mean'])}bp NW t {l1['all']['nw_t']:.2f}) · 경제성: 해당 없음(비용 33.5bp 왕복 대비 "
              f"{bp(l1['all']['mean'] - COST / 1e4)}bp). 진입을 다음 거래일 종가로 옮긴 결과. 기록 전용.")
    L = ["---", "track: kr", "factor: foreign-flow-entry-lag", "date: 2026-11-14", f"verdict: {o['label']}",
         "criteria_version: research-only (foreign-flow-entry-lag-preregistration-2026-11, 사전등록 a8159589)", "reason: >-", f"  {reason}", "---", "",
         "# 외국인 수급 5일 — 진입 지연 점검 — 결과", "",
         f"사전등록 a8159589 그대로. 병합 {o['rows']:,}행 · 종목 {o['tickers']} · {o['dateRange'][0]} ~ {o['dateRange'][1]}. 현재 상장 종목 + A2a (폐지 없음, 원 한계 그대로).", "",
         "| 구간 | L0 mean bp (NW t) | L1 mean bp (NW t) | 일수 | L1 − 33.5bp |", "|---|---|---|---:|---:|"]
    for p in ["all", *v.SPLIT]:
        a, b = l0[p], l1[p]
        L.append(f"| {p} | {bp(a['mean'])} ({a['nw_t']:.2f}) | {bp(b['mean'])} ({b['nw_t']:.2f}) | {b['n_days']} | {bp(b['mean'] - COST / 1e4)} |")
    L += ["", "## 시기 세 칸 (기록)", "", "| 구간 | L0 mean bp (NW t) | L1 mean bp (NW t) |", "|---|---|---|"]
    for p in PERIODS:
        a, b = l0["periods"][p], l1["periods"][p]
        L.append(f"| {p} | {bp(a['mean'])} ({a['nw_t']:.2f}) | {bp(b['mean'])} ({b['nw_t']:.2f}) |")
    L += ["", f"**라벨 {o['label']}** (L1 기준: 세 구간 평균 모두 양 ∧ NW t ≥ 2 = 유지).",
          "재현 점검: 원 독립재현 값(전체 mean +37.9bp NW t 15.53 · TRAIN/VALID/TEST NW t 15.16/3.26/5.91)과 L0 이 어긋나면 데이터가 늘어난 때문이다(A4 갱신).",
          "한계: 스프레드는 롱숏 Q5−Q1 이라 실제 롱온리·비용 구조와 다르다. 같은 표본 재절단·지연/보유일 변경 금지. 수급 라인은 종결 유지."]
    open(OUT + ".md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    json.dump(o, open(OUT + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def selftest():
    assert label({"TRAIN": {"mean": 1, "nw_t": 3}, "VALID": {"mean": 1, "nw_t": 2}, "TEST": {"mean": 1, "nw_t": 5}}) == "유지"
    assert label({"TRAIN": {"mean": 1, "nw_t": 3}, "VALID": {"mean": 1, "nw_t": 1.9}, "TEST": {"mean": 1, "nw_t": 5}}) == "약화"
    assert label({"TRAIN": {"mean": 1, "nw_t": 3}, "VALID": {"mean": -1, "nw_t": 4}, "TEST": {"mean": 1, "nw_t": 5}}) == "소멸"
    d = pd.DataFrame({"ticker": ["A"] * 8, "close": [1, 2, 4, 8, 16, 32, 64, 128.0]})
    g = d.groupby("ticker")["close"]
    assert abs(g.transform(lambda s: s.shift(-6) / s.shift(-1) - 1).iloc[0] - (64 / 2 - 1)) < 1e-12     # 진입 = 다음 행 종가
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        o = run()
        write(o)
        print(o["label"], o["fwd_l1"]["all"])
