#!/usr/bin/env python3
"""고정 비중 자산 혼합의 되맞춤 규칙 비교 — 사전등록 findings/rebalance-rule-mix-preregistration-2026-10.md 그대로.

    python research/strategy-lab/rebalance_rule_mix.py --selftest
    python research/strategy-lab/rebalance_rule_mix.py      # → findings/rebalance-rule-mix-results-2026-10.{md,json}

모든 행동(납입·되맞춤)은 매월 초 = 직전 월말 종가에 한다. 비용은 사고판 금액 전부에 편도로 붙인다(납입 매수 포함 — 규칙 간 같다).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
D = HERE / "data" / "pension-test"
OUT = HERE / "findings" / "rebalance-rule-mix-results-2026-10"
END = "2026-09"
COST, STRESS = 0.0005, 0.0025
RULES = ["R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"]
LABEL = {"R0": "안 함", "R1": "매월", "R2": "분기", "R3": "반기", "R4": "연 1회(기준)", "R5": "밴드 ±5%p",
         "R6": "밴드 ±25%(상대)", "R7": "납입금만", "R8": "납입금+밴드 ±5%p"}
KR6 = ["069500", "143850", "133690", "132030", "148070", "138230"]
SLICES = {"2005~15": ("2005-01", "2015-12"), "2016~23": ("2016-01", "2023-12"), "2024": ("2024-01", "2024-12"), "2025~": ("2025-01", END)}


def us_krw(tickers):
    def m(t):
        return pd.read_parquet(D / f"{t}.parquet")["close"].resample("ME").last()
    fx = m("KRW_X")
    df = pd.concat({t: m(t) for t in tickers}, axis=1)
    r = ((1 + df.pct_change()).mul(1 + fx.pct_change(), axis=0) - 1).dropna()
    return r.loc["2005-01":END]


def kr6():
    import etf_timing_lab as e
    p = e.load_panel()
    cal = pd.DatetimeIndex(sorted(p["date"].unique()))
    R = pd.concat({c: e.tr_returns(p, c, cal) for c in KR6}, axis=1)
    m = (1 + R).resample("ME").prod(min_count=1) - 1
    return m.loc["2011-11":END].dropna()


def due(rule, month_prev):
    """직전 월말(month_prev)이 달력 되맞춤 시점인가."""
    return {"R1": True, "R2": month_prev % 3 == 0, "R3": month_prev % 6 == 0, "R4": month_prev == 12}.get(rule, False)


def simulate(R: pd.DataFrame, tw, rule, contrib=True, cost=COST):
    tw = np.asarray(tw, float)
    X = R.to_numpy()
    T, N = X.shape
    h = np.zeros(N)
    ret = np.zeros(T)
    sells = 0.0
    events = 0
    maxdev = 0.0
    paid = 0.0
    for t in range(T):
        f = 1.0 if (contrib or t == 0) else 0.0
        paid += f
        V0 = h.sum()
        # 1) 납입 배분
        if rule in ("R7", "R8") and V0 > 0:
            d = np.maximum(tw * (V0 + f) - h, 0)
            buy = f * d / d.sum() if d.sum() >= f else d + (f - d.sum()) * tw
        else:
            buy = f * tw
        h = h + buy * (1 - cost)
        V = h.sum()
        # 2) 되맞춤 판단 (직전 월말 비중 기준)
        w = h / V
        prev_m = R.index[t - 1].month if t else None
        if t == 0:
            do = False
        elif rule in ("R5", "R8"):
            do = bool((np.abs(w - tw) > 0.05).any())
        elif rule == "R6":
            do = bool((np.abs(w - tw) > 0.25 * tw).any())
        else:
            do = due(rule, prev_m)
        if do:
            tgt = tw * V
            tr = np.abs(tgt - h).sum()
            sells += np.maximum(h - tgt, 0).sum() / V
            events += tr > 1e-9 * V
            h = tw * (V - cost * tr)
        maxdev = max(maxdev, float(np.abs(h / h.sum() - tw).max()))
        start = V0 + f
        h = h * (1 + X[t])
        ret[t] = h.sum() / start - 1
    yrs = T / 12
    return dict(ret=pd.Series(ret, R.index), sell_turn=sells / yrs, events=events / yrs, maxdev=maxdev,
                multiple=float(h.sum() / paid))


def sharpe(x):
    x = np.asarray(x)
    return float(x.mean() * 12 / (x.std(ddof=1) * math.sqrt(12)))


def summ(r: pd.Series):
    w = (1 + r).cumprod()
    return dict(cagr=float(w.iloc[-1] ** (12 / len(r)) - 1), sharpe=sharpe(r), mdd=float((w / w.cummax() - 1).min()))


def boot(a, b, n=2000, block=12, seed=11):
    a, b = np.asarray(a), np.asarray(b)
    T = len(a)
    rng = np.random.default_rng(seed)
    nb = math.ceil(T / block)
    ds = np.empty(n)
    for k in range(n):
        idx = np.concatenate([np.arange(s, s + block) % T for s in rng.integers(0, T, nb)])[:T]
        ds[k] = sharpe(a[idx]) - sharpe(b[idx])
    return float(np.percentile(ds, 2.5)), float(np.percentile(ds, 97.5))


def mixes():
    us = us_krw(["SPY", "IEF", "GLD"])
    return {
        "PA SPY60/IEF40": (us[["SPY", "IEF"]], [0.6, 0.4]),
        "PB SPY60/IEF20/GLD20": (us[["SPY", "IEF", "GLD"]], [0.6, 0.2, 0.2]),
        "PC SPY80/GLD20": (us[["SPY", "GLD"]], [0.8, 0.2]),
        "PK 국내 6종 1/6": (kr6(), [1 / 6] * 6),
    }


def run_mode(M, contrib, cost):
    out = {}
    for name, (R, tw) in M.items():
        sims = {r: simulate(R, tw, r, contrib, cost) for r in RULES if contrib or r not in ("R7", "R8")}
        base = sims["R4"]["ret"]
        rows = {}
        for r, s in sims.items():
            row = dict(summ(s["ret"]), sell_turn=s["sell_turn"], events=s["events"], maxdev=s["maxdev"], multiple=s["multiple"])
            if r != "R4":
                row["dS"] = row["sharpe"] - sharpe(base)
                row["ci"] = boot(s["ret"], base)
                row["slices"] = {k: (sharpe(s["ret"].loc[a:b]) - sharpe(base.loc[a:b])) if len(base.loc[a:b]) > 6 else None
                                 for k, (a, b) in SLICES.items()}
            rows[r] = row
        out[name] = dict(start=str(R.index[0].date()), end=str(R.index[-1].date()), months=len(R), rows=rows)
    return out


def judge(res):
    names = list(res)
    verdict = {}
    for r in RULES:
        if r == "R4" or r not in res[names[0]]["rows"]:
            continue
        lo = sum(res[n]["rows"][r]["ci"][0] > 0 for n in names)
        hi = sum(res[n]["rows"][r]["ci"][1] < 0 for n in names)
        verdict[r] = "우위" if lo >= 3 else "열위" if hi >= 3 else "구분 불가"
    verdict["R4"] = "기준"
    sup = [r for r, v in verdict.items() if v == "우위"]
    ok = [r for r, v in verdict.items() if v != "열위"
          and sum(res[n]["rows"][r]["maxdev"] <= 0.10 for n in names) >= 3]
    pool = sup or ok
    key = lambda r: (np.mean([res[n]["rows"][r]["sell_turn"] for n in names]), np.mean([res[n]["rows"][r]["events"] for n in names]))
    pick = min(pool, key=key) if pool else None
    return verdict, ok, pick


def pct(x, d=1):
    return "" if x is None else f"{x * 100:+.{d}f}%"


def render(o):
    L = ["---", "track: kr", "factor: rebalance-rule-mix", "date: 2026-10-10", f"verdict: {o['headline']}",
         "criteria_version: research-only (rebalance-rule-mix-preregistration-2026-10)",
         'conditions: ["고정 비중 혼합 4개 × 규칙 9개", "월 납입(판정) · 일시금(기록)", "기준 연 1회", "12개월 블록 부트스트랩 2,000회", "편도 5bp(스트레스 25bp)"]',
         "reason: >-", f"  {o['reason']} (스크립트 판정)", "---", "",
         "# 고정 비중 자산 혼합의 되맞춤 규칙 — 결과", "",
         "투자 자문이 아니다. 과거 한 경로. 수치는 `rebalance_rule_mix.py` 출력 그대로. 원화 기준(미국 ETF 는 환노출).", ""]
    for mode, title in (("contrib", "월 납입(판정)"), ("lump", "일시금(기록)")):
        L += [f"## {title} — 편도 5bp", ""]
        for name, m in o[mode].items():
            L += [f"### {name} ({m['start'][:7]} ~ {m['end'][:7]}, {m['months']}개월)", "",
                  "| 규칙 | 판정 | 샤프 | ΔSharpe vs 연1회 [95%] | CAGR | MDD | 연 매도회전율 | 연 되맞춤 | 최대 이탈 | 최종 배수 | 2005~15 / 2016~23 / 2024 / 2025~ ΔSharpe |",
                  "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|"]
            for r, row in m["rows"].items():
                ci = f"{row['dS']:+.3f} [{row['ci'][0]:+.3f}, {row['ci'][1]:+.3f}]" if "dS" in row else "—"
                sl = " / ".join("—" if v is None else f"{v:+.2f}" for v in row.get("slices", {}).values()) or "—"
                v = o["verdict"].get(r, "") if mode == "contrib" else ""
                L.append(f"| {r} {LABEL[r]} | {v} | {row['sharpe']:.3f} | {ci} | {pct(row['cagr'])} | {pct(row['mdd'])} | "
                         f"{row['sell_turn'] * 100:.1f}% | {row['events']:.2f} | {row['maxdev'] * 100:.1f}%p | {row['multiple']:.2f} | {sl} |")
            L.append("")
    L += ["## 판정", "", f"- 규칙별: " + " · ".join(f"{r} {o['verdict'][r]}" for r in RULES if r in o["verdict"]),
          f"- 권고 후보(열위 아님 + 최대 이탈 ≤10%p 3/4 이상): {', '.join(o['eligible'])}",
          f"- **권고 규칙(5bp): {o['pick']} {LABEL.get(o['pick'], '')}** · 스트레스 25bp: {o['pick_stress']} {LABEL.get(o['pick_stress'], '')}",
          f"- 스트레스 25bp 규칙별: " + " · ".join(f"{r} {v}" for r, v in o["verdict_stress"].items()), ""]
    return "\n".join(L)


def run():
    M = mixes()
    c = run_mode(M, True, COST)
    v, ok, pick = judge(c)
    cs = run_mode(M, True, STRESS)
    vs, _, pick_s = judge(cs)
    lump = run_mode(M, False, COST)
    sup = [r for r, x in v.items() if x == "우위"]
    worse = [r for r, x in v.items() if x == "열위"]
    head = "INFORMATION" if sup else "INCONCLUSIVE"
    reason = (f"신호: {'있음' if sup else '없음'}(연 1회 대비 우위 {', '.join(sup) or '0개'}, 열위 {', '.join(worse) or '0개'}) · "
              f"경제성: 해당 없음(같은 혼합의 운용 방식 비교) — 권고 규칙 {pick} {LABEL.get(pick, '')}")
    o = dict(headline=head, reason=reason, verdict=v, eligible=ok, pick=pick, verdict_stress=vs, pick_stress=pick_s,
             contrib=c, lump=lump, contrib_stress=cs)
    js = json.loads(json.dumps(o, default=lambda x: None))
    for mode in ("contrib", "lump", "contrib_stress"):
        for m in js[mode].values():
            for row in m["rows"].values():
                row.pop("ret", None)
    OUT.with_suffix(".json").write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(o), encoding="utf-8")
    print(render(o)[-1500:])


def selftest():
    idx = pd.date_range("2020-01-31", periods=36, freq="ME")
    flat = pd.DataFrame(0.01, index=idx, columns=["a", "b"])
    for r in RULES:  # 같은 수익이면 비중이 안 움직인다 → 되맞춤·매도 0
        s = simulate(flat, [0.5, 0.5], r, True, 0.0)
        assert s["events"] == 0 and s["sell_turn"] == 0 and s["maxdev"] < 1e-12, r
    up = pd.DataFrame({"a": 0.10, "b": 0.0}, index=idx)
    s0 = simulate(up, [0.5, 0.5], "R0", False, 0.0)
    s1 = simulate(up, [0.5, 0.5], "R1", False, 0.0)
    assert s0["maxdev"] > 0.3 and s1["maxdev"] < 1e-12 and s1["events"] == 35 / 3
    s5 = simulate(up, [0.5, 0.5], "R5", False, 0.0)
    assert 0 < s5["events"] < s1["events"]
    s7 = simulate(up, [0.5, 0.5], "R7", True, 0.0)
    assert s7["sell_turn"] == 0 and s7["events"] == 0
    s8 = simulate(up, [0.5, 0.5], "R8", True, 0.0)
    assert s8["maxdev"] <= simulate(up, [0.5, 0.5], "R7", True, 0.0)["maxdev"]
    s4 = simulate(up, [0.5, 0.5], "R4", False, 0.0)
    assert abs(s4["events"] * 3 - 2) < 1e-9  # 2020·2021 12월 말 뒤 (연율 = 횟수 / 3년)
    # 비용: 일시금 첫 매수 5bp → 첫 달 수익 = (1-c)*1.05-1
    c = simulate(pd.DataFrame({"a": [0.05] * 3}, index=idx[:3]), [1.0], "R0", False, 0.0005)
    assert abs(c["ret"].iloc[0] - (0.9995 * 1.05 - 1)) < 1e-12
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    selftest() if a.selftest else run()
