#!/usr/bin/env python3
"""M2 갭 잔차 지속 forward 그림자 — 사전등록 findings/us-overnight-m2-shadow-preregistration-2026-09.md

**반사실 계산이다. 주문은 한 줄도 안 낸다.** 신호·수익 계산은 futures/us_overnight_study.py 함수 그대로.
  python research/strategy-lab/run_us_overnight_shadow.py            # 선물 증분 수집 → 미국 4종 새로 받기 → 관측 추가
  python research/strategy-lab/run_us_overnight_shadow.py --no-collect
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
sys.path.insert(0, str(HERE / "futures"))
import us_overnight_study as S  # noqa: E402

OUT = HERE / "reports" / "2026-09-us-overnight-shadow" / "observations.jsonl"
FORWARD_START = "2026-09-28"   # 사전등록 상수 — 결과 표본 끝(2026-09-23) 다음 거래일
COST_BP = 1.4


def us_fresh():
    import yfinance as yf
    df = yf.download(S.TICKERS, start="2024-01-01", auto_adjust=True, progress=False)["Close"]
    if df.empty or df[S.TICKERS].dropna(how="all").empty:
        raise RuntimeError("미국 자료를 못 받았다 — 관측하지 않는다")
    f = S.CACHE / "us_close_shadow.csv"
    S.CACHE.mkdir(parents=True, exist_ok=True)
    df.to_csv(f)
    return df[S.TICKERS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-collect", action="store_true")
    a = ap.parse_args()
    if not a.no_collect:
        import collect_kospi200_daily_krx as C
        C.main()
    us = us_fresh()
    kr = S.kr_panel()
    kr = kr[kr.index >= "2024-01-01"]
    cum, ndays = S.overnight(us, kr.index)
    z = pd.concat({k: S.zpast(cum[k]) for k in S.TICKERS}, axis=1)
    kr["U"] = z.mean(axis=1).where(z.notna().sum(axis=1) >= 2)
    gv, uv, gh = kr["g"].to_numpy(), kr["U"].to_numpy(), np.full(len(kr), np.nan)
    for i in range(len(kr)):                       # us_overnight_study.main 의 갭 회귀와 같은 계산
        lo = max(0, i - 400)
        m = np.isfinite(gv[lo:i]) & np.isfinite(uv[lo:i])
        idx = np.where(m)[0][-252:]
        if len(idx) == 252 and np.isfinite(uv[i]):
            b, c = np.polyfit(uv[lo:i][idx], gv[lo:i][idx], 1)
            gh[i] = c + b * uv[i]
    kr["gh"], kr["e"], kr["ndays"] = gh, kr["g"] - gh, ndays
    seen = {json.loads(l)["date"] for l in OUT.read_text(encoding="utf-8").splitlines()} if OUT.exists() else set()
    rows = []
    for t, r in kr[kr.index >= FORWARD_START].iterrows():
        d = str(t.date())
        if d in seen or not np.isfinite(r["e"]) or not np.isfinite(r["y"]) or r["e"] == 0:
            continue
        pos = float(np.sign(r["e"]))
        gross = pos * (np.exp(r["y"]) - 1) * 1e4
        rows.append({"date": d, "U": round(r["U"], 4), "g": round(r["g"], 6), "gh": round(r["gh"], 6), "e": round(r["e"], 6),
                     "pos": pos, "gross_bp": round(gross, 2), "net_bp": round(gross - COST_BP, 2), "us_days": int(r["ndays"])})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = len(seen) + len(rows)
    print(f"새 관측 {len(rows)}일 · 누적 {n}일 / 판정 250일 — 그 전엔 기록만(중간 판정 금지)")


if __name__ == "__main__":
    main()
