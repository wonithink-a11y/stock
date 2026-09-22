#!/usr/bin/env python3
"""ETF 종가→익일 시가 forward 그림자 — 사전등록: findings/etf-close-open-shadow-preregistration-2026-09.md

**반사실 계산이다. 주문은 한 줄도 안 낸다.** 국내주식형 ETF(유니버스 CSV 동결)에서 O2b·O0 를 'T 종가 매수 → T+1 시가 매도'로
재고, 신호일별 관측을 observations.jsonl 에 쌓는다. 판정은 셀별 250 신호일에 1회(연장은 500일 1회).

  python research/strategy-lab/run_etf_close_open_shadow.py --selftest
  python research/strategy-lab/run_etf_close_open_shadow.py            # 수집 증분(KRX Open API) → 관측 추가
  python research/strategy-lab/run_etf_close_open_shadow.py --no-collect
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))
import etf_cross_section as X  # noqa: E402

OUT = HERE / "reports" / "2026-09-etf-shadow" / "observations.jsonl"

# ---- 사전등록 상수 (결과를 본 뒤 바꾸지 않는다) -------------------------------------------
FORWARD_START = "2026-09-22"      # 결과 실험의 표본 끝(2026-09-21) 다음 날 — 신호일 기준
MIN_DAYS, EXTEND_DAYS = 250, 500
T_KEEP = 2.24                     # 셀 2개(O2b·O0) — 단일 셀 그림자(2.0)보다 엄격하게
CELLS = ("O2b", "O0")
LOOKBACK_START = "2026-06-01"     # 직전 20거래일·전일 값을 채우기 위한 읽기 시작(관측 창이 아니다)


def tstat(x) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else 0.0


def judge(obs: list) -> dict:
    """셀 하나의 관측(신호일별 net_durable·net_stress) → 판정 상태. 250일 전에는 기록만."""
    n = len(obs)
    if n < MIN_DAYS:
        return {"state": "기록 중", "days": n}
    use = obs[:EXTEND_DAYS] if n >= EXTEND_DAYS else obs[:MIN_DAYS]
    nd = np.array([o["net_durable"] for o in use]); ns = np.array([o["net_stress"] for o in use])
    t = tstat(nd)
    if nd.mean() > 0 and t >= T_KEEP and ns.mean() > 0:
        v = "KEEP 후보"
    elif nd.mean() <= 0:
        v = "REJECT"
    else:
        v = "INCONCLUSIVE" if n >= EXTEND_DAYS else "INCONCLUSIVE-EXTEND"
    if n < EXTEND_DAYS and v == "INCONCLUSIVE-EXTEND":
        return {"state": v, "days": n, "at_days": MIN_DAYS, "mean_net": round(float(nd.mean()), 2), "t": round(t, 2)}
    return {"state": v, "days": n, "at_days": len(use), "mean_net": round(float(nd.mean()), 2), "t": round(t, 2),
            "mean_stress": round(float(ns.mean()), 2)}


def observe(u) -> list:
    """패널(build_panel 결과) → 신호일·셀별 관측. forward 창·다음 날 시가가 있는 날만."""
    u = u[(u.date >= FORWARD_START) & u.on.notna() & (u.ret < 0.28)]
    if u.empty:
        return []
    mkt = u.groupby("date").on.mean()
    conds = {"O0": u.ret.notna(), "O2b": (u.close > u.pdh) & (u.volr >= 1.5)}
    out = []
    for cid in CELLS:
        ev = u[conds[cid]]
        for dt, g in ev.groupby("date"):
            gross = float(g.on.mean())
            out.append({"cell": cid, "date": dt.strftime("%Y-%m-%d"), "n": int(len(g)), "gross": round(gross, 2),
                        "info": round(gross - float(mkt[dt]), 2), "net_durable": round(gross - X.FIXED_BP, 2),
                        "net_stress": round(gross - X.FIXED_BP - float(g.tk.mean()), 2)})
    return out


def append_new(obs: list, path: Path = OUT) -> int:
    have = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            have.add((r["cell"], r["date"]))
    new = [o for o in obs if (o["cell"], o["date"]) not in have]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for o in sorted(new, key=lambda o: (o["date"], o["cell"])):
                f.write(json.dumps(o, ensure_ascii=False) + "\n")
    return len(new)


def report(path: Path = OUT) -> dict:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    return {c: judge(sorted([r for r in rows if r["cell"] == c], key=lambda r: r["date"])) for c in CELLS}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--no-collect", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.no_collect:
        import collect_etf_ohlc_krx as col
        sys.argv = ["collect", "--start", LOOKBACK_START]
        if col.main() != 0:
            print("수집 실패 — 관측하지 않는다(구멍 = 실패)")
            return 1
    dom = {r["code"] for r in csv.DictReader(X.UNIV.open(encoding="utf-8")) if r["class"] == "국내주식형"}
    import collect_etf_ohlc_krx as col
    end = max(col.done_days())
    u, _, _ = X.build_panel(dom, LOOKBACK_START, end)
    n = append_new(observe(u))
    print(f"관측 추가 {n}건 (데이터 끝 {end}) · 상태 {json.dumps(report(), ensure_ascii=False)}")
    return 0


def selftest() -> int:
    import tempfile
    import pandas as pd
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)
    ck("사전등록 상수 고정", (FORWARD_START, MIN_DAYS, EXTEND_DAYS, T_KEEP, CELLS) == ("2026-09-22", 250, 500, 2.24, ("O2b", "O0")))
    ck("비용 3.54bp(세금 0)", abs(X.FIXED_BP - 3.54) < 0.01)
    ck("250일 전에는 판정 안 함", judge([{"net_durable": 50, "net_stress": 40}] * 249)["state"] == "기록 중")
    rng = np.random.default_rng(1)
    good = [{"net_durable": float(v), "net_stress": float(v) - 4} for v in rng.normal(30, 100, 250)]
    ck("평균 +30·t 충분 → KEEP 후보", judge(good)["state"] == "KEEP 후보")
    ck("평균 ≤ 0 → REJECT", judge([{"net_durable": -1.0 + (i % 2) * 0.5, "net_stress": -5} for i in range(250)])["state"] == "REJECT")
    weak = [{"net_durable": float(v), "net_stress": float(v) - 4} for v in rng.normal(5, 100, 250)]
    ck("양이지만 t 부족 → 500일까지 연장", judge(weak)["state"] in ("INCONCLUSIVE-EXTEND", "REJECT"))
    weak500 = [{"net_durable": 5.0 + (1 if i % 2 else -1) * 100, "net_stress": 1.0} for i in range(500)]
    ck("500일에도 부족 → INCONCLUSIVE 로 종결", judge(weak500)["state"] == "INCONCLUSIVE")
    # 합성 패널로 관측·중복 방지
    d = pd.to_datetime(["2026-09-21", "2026-09-22", "2026-09-23"])
    u = pd.DataFrame({"date": d.repeat(2), "ticker": ["A", "B"] * 3, "on": [10, 20, 30, 40, np.nan, np.nan],
                      "ret": [0.01] * 6, "close": [100, 100, 110, 90, 100, 100], "pdh": [99, 101, 105, 95, 100, 100],
                      "volr": [2, 2, 2, 1, 1, 1], "tk": [5.0] * 6})
    obs = observe(u)
    ck("forward 창 이전(09-21)과 다음 시가 없는 날(09-23)은 관측 안 함", {o["date"] for o in obs} == {"2026-09-22"})
    o2b = [o for o in obs if o["cell"] == "O2b"]
    ck("O2b = 종가>전일고가·거래량비≥1.5 (A 만)", len(o2b) == 1 and o2b[0]["n"] == 1 and o2b[0]["gross"] == 30.0)
    ck("net = gross − 3.54, 스트레스 − 한 호가", o2b[0]["net_durable"] == round(30 - X.FIXED_BP, 2) and o2b[0]["net_stress"] == round(30 - X.FIXED_BP - 5, 2))
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "o.jsonl"
        ck("같은 신호일은 두 번 안 쌓는다", append_new(obs, p) == 2 and append_new(obs, p) == 0)
    print(f"\nselftest {len(fails)} fail")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
