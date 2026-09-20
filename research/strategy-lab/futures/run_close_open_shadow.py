#!/usr/bin/env python3
"""O2b 종가→익일 시가 그림자 관측 — 사전등록: docs/control/O2b-그림자-설계-2026-09-20.md

**반사실 계산이다. 주문은 한 줄도 안 낸다.** 규칙 O2b(종가 > 전일 고가 · 거래량비 ≥ 1.5 · 유동 종목)를 forward 창에서
'T 종가 매수 → T+1 시가 매도' 로 재고, 날짜별 관측을 observations.jsonl 에 쌓는다. 판정은 1회.

  python research/strategy-lab/futures/run_close_open_shadow.py --selftest
  python research/strategy-lab/futures/run_close_open_shadow.py          # A2a 월간 증분 직후
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
REPO = HERE.parent.parent.parent
sys.path.insert(0, str(HERE))
from short_horizon_study import tstat  # noqa: E402
from close_open_phase5 import (features, CELLS, FIXED_BP, EVENT_BP, LIQ_MIN, LIMIT_UP)  # noqa: E402
from structure_phase4 import tick_bp  # noqa: E402

OUT = HERE.parent / "reports" / "2026-09-o2b-shadow" / "observations.jsonl"

# ---- 사전등록 상수 (결과를 본 뒤 바꾸지 않는다) -------------------------------------------
FORWARD_START = "2026-08-22"      # 근거 데이터(일봉 ~08-03, 분봉 격자 ~08-21) 끝의 다음 날 — 신호일 기준
MIN_DAYS, EXTEND_DAYS = 250, 500
T_KEEP = 2.0


def load_recent(years=(2025, 2026)) -> pd.DataFrame:
    rows = []
    for y in years:
        p = REPO / "data" / "backfill" / "price" / "a2a" / f"{y}.jsonl.gz"
        if not p.exists():
            continue
        with gzip.open(p, "rt", encoding="utf-8") as f:
            rows.extend(json.loads(l) for l in f)
    a = pd.DataFrame(rows)
    a = a[(a.open > 0) & (a.close > 0) & (a.high > 0) & (a.low > 0)].copy()
    a["date"] = pd.to_datetime(a["date"])
    a = a.sort_values(["ticker", "date"]).reset_index(drop=True)
    return features(a)


def daily_observations(a: pd.DataFrame, start: str = FORWARD_START) -> list[dict]:
    """신호일 >= start 인 날마다 O2b 관측 1행. 익일이 없는(마지막) 날은 아직 실현 전이라 뺀다."""
    u = a[a.liq >= LIQ_MIN]
    mkt = u.groupby("date")["on"].mean()
    cond = CELLS["O2b"][0]
    ev = u[cond(u)].dropna(subset=["on"])
    ev = ev[(ev.ret < LIMIT_UP) & (ev.date >= pd.Timestamp(start))]
    out = []
    for d, g in ev.groupby("date"):
        tk = float(tick_bp(g["close"]).mean())
        gross = float(g["on"].mean())
        out.append({"date": d.strftime("%Y-%m-%d"), "names": int(len(g)), "gross_bp": round(gross, 2),
                    "market_bp": round(float(mkt.loc[d]), 2), "info_bp": round(gross - float(mkt.loc[d]), 2),
                    "net_durable_bp": round(gross - FIXED_BP, 2), "net_event_bp": round(gross - EVENT_BP, 2),
                    "net_stress_bp": round(gross - FIXED_BP - tk, 2)})
    return out


def judge(net_durable, net_stress, prior=()):
    """반환 (verdict, reasons). 판정은 1회 — 끝났으면 DONE, 연장 뒤엔 EXTEND_DAYS 에서만."""
    if any(v in ("KEEP-CANDIDATE", "REJECT", "INCONCLUSIVE") for v in prior):
        return "DONE", []
    n = len(net_durable)
    extended = "INCONCLUSIVE-EXTEND" in prior
    if n < (EXTEND_DAYS if extended else MIN_DAYS):
        return "PENDING", []
    nd, ns = np.asarray(net_durable, float), np.asarray(net_stress, float)
    t = tstat(nd)
    reasons = [f"days={n}", f"net_durable={nd.mean():.2f}bp t={t:.2f}", f"net_stress={ns.mean():.2f}bp"]
    if nd.mean() <= 0:
        return "REJECT", reasons
    if t >= T_KEEP and ns.mean() > 0:
        return "KEEP-CANDIDATE", reasons
    return ("INCONCLUSIVE" if extended else "INCONCLUSIVE-EXTEND"), reasons


def read_log(path=OUT):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def append_new(path, rows):
    """이미 기록된 신호일은 건너뛴다(재실행 안전). 반환: 새로 쓴 행 수."""
    have = {r["date"] for r in read_log(path) if "names" in r}
    new = [r for r in rows if r["date"] not in have]
    if new:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for r in new:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(new)


def summarize(path=OUT):
    days = [r for r in read_log(path) if "names" in r]
    nd = [r["net_durable_bp"] for r in days]
    ns = [r["net_stress_bp"] for r in days]
    prior = [r["verdict"] for r in read_log(path) if "verdict" in r]
    v, why = judge(nd, ns, prior)
    s = {"days": len(days), "names_per_day": round(float(np.mean([r["names"] for r in days])), 1) if days else None,
         "gross_bp": round(float(np.mean([r["gross_bp"] for r in days])), 2) if days else None,
         "net_durable_bp": round(float(np.mean(nd)), 2) if days else None,
         "net_event_bp": round(float(np.mean([r["net_event_bp"] for r in days])), 2) if days else None,
         "net_stress_bp": round(float(np.mean(ns)), 2) if days else None,
         "t_net_durable": round(tstat(np.asarray(nd, float)), 2) if len(days) > 2 else None,
         "verdict": v, "reasons": why}
    if v in ("KEEP-CANDIDATE", "REJECT", "INCONCLUSIVE", "INCONCLUSIVE-EXTEND"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"verdict": v, "days": len(days), "reasons": why}, ensure_ascii=False) + "\n")
    return s


def selftest():
    assert FIXED_BP > 23.5 and EVENT_BP == 20.0 and LIQ_MIN == 2e9 and LIMIT_UP == 0.28    # 사전등록 상수가 바뀌면 여기서 걸린다
    z = np.zeros(10)
    assert judge(z, z)[0] == "PENDING"                                            # 250일 전엔 판정 안 함
    big = np.full(250, 20.0) + np.tile([-30.0, 30.0], 125)
    assert judge(big, big - 8)[0] == "KEEP-CANDIDATE"                             # 평균 +20, t>2, 스트레스>0
    assert judge(big, big - 30)[0] == "INCONCLUSIVE-EXTEND"                       # 스트레스 음이면 유보
    assert judge(np.full(250, -1.0), np.full(250, -5.0))[0] == "REJECT"           # 평균 ≤ 0
    assert judge(big, big, ["INCONCLUSIVE-EXTEND"])[0] == "PENDING"               # 연장은 500일에서만
    assert judge(np.tile([-30.0, 30.4], 250), np.full(500, 1.0), ["INCONCLUSIVE-EXTEND"])[0] == "INCONCLUSIVE"   # 두 번째는 유보 없음
    assert judge(big, big, ["KEEP-CANDIDATE"])[0] == "DONE"                       # 판정은 1회
    import tempfile
    p = Path(tempfile.mkdtemp()) / "o.jsonl"
    r = {"date": "2026-09-01", "names": 5, "gross_bp": 10.0, "net_durable_bp": -13.5, "net_stress_bp": -20.0, "net_event_bp": -10.0}
    assert append_new(p, [r]) == 1 and append_new(p, [r]) == 0                    # 같은 신호일 재실행은 중복 없음
    # 관측: 합성 일봉에서 O2b 조건(종가>전일고가·거래량비≥1.5)만 잡고 익일 시가로 잰다
    rows = []
    for t in ("A", "B"):
        for i, d in enumerate(pd.bdate_range("2026-01-05", periods=30)):
            base = 10000.0 if t == "A" else 20000.0
            o = base * (1 + 0.001 * i)
            rows.append({"ticker": t, "date": d, "open": o, "high": o * 1.01, "low": o * 0.99, "close": o, "volume": 1e6})
    df = pd.DataFrame(rows)
    d25 = pd.bdate_range("2026-01-05", periods=30)[25]
    mask = (df.ticker == "A") & (df.date == d25)
    df.loc[mask, ["close", "high", "volume"]] = [df.loc[mask, "close"].iloc[0] * 1.05, df.loc[mask, "high"].iloc[0] * 1.05, 5e6]
    f = features(df)
    f["liq"] = 5e9                                                                # 유동성 조건 충족으로 고정(합성 표본)
    obs = daily_observations(f, start="2026-01-05")
    hit = [o for o in obs if o["date"] == d25.strftime("%Y-%m-%d")]
    assert len(hit) == 1 and hit[0]["names"] == 1, obs
    a = f[(f.ticker == "A") & (f.date == d25)].iloc[0]
    assert abs(hit[0]["gross_bp"] - round(float(a.on), 2)) < 0.01                 # 종가 -> 익일 시가
    print("selftest ok (10건)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    rows = daily_observations(load_recent())
    n = append_new(OUT, rows)
    s = summarize()
    print(f"신규 {n}일 기록 · 누적 {s['days']}일")
    print(json.dumps(s, ensure_ascii=False))


if __name__ == "__main__":
    main()
