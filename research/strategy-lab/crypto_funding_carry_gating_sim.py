#!/usr/bin/env python3
"""BTC 펀딩 캐리 Stage 1 — 진입·퇴출 게이트의 순수익 시뮬레이션 (읽기 전용, 주문 없음).

    python research/strategy-lab/crypto_funding_carry_gating_sim.py
    python research/strategy-lab/crypto_funding_carry_gating_sim.py --selftest

★ 결과를 보기 전에 커밋한다. 아래 사전 선언은 결과 뒤에 바꾸지 않는다.

질문: Stage 0 모니터의 알림 규칙("90일 연환산이 낮으면 진입 중단/퇴출")을 실제 이력에 적용하면, 항상 들고 있는 것보다
수수료 반영 후 나은가?

모델: 수익 = 보유 중인 결제 시점의 펀딩률 합(명목 대비, 단순합). 진입/퇴출마다 왕복 비용(현물·선물 4다리 수수료+슬리피지)을
명목의 CYCLE_COST 만큼 뺀다. 시장 밖에서는 수익 0(대기 자본의 대체수익은 넣지 않는다 — 보수적).
미실현 손익·마진·uniMMR 은 여기서 다루지 않는다(정적 보유의 uniMMR 은 설계 문서 §5.1 에서 확인).

사전 선언 (주 규칙 = 임계 제안값, 조정하지 않는다):
  진입: 결제 시점 t 에서 (최근 90일 연환산 ≥ 5%) AND (최근 30일 연환산 > 0). 신호는 t 까지의 데이터만 쓰고 t+1 결제부터 보유.
  퇴출: (최근 30일 연환산 < 0) OR (최근 90일 연환산 < 2%).
  비교 대상: 항상 보유(첫 결제 진입, 마지막 결제 청산 = 1 왕복).
  비용 격자: 왕복 0.15% / 0.30% / 0.60% (0.30% = 현물 테이커 0.1%×2 + 선물 테이커 0.05%×2 의 대략치, 실제 수수료는 미확인).
  민감도(참고, 판정에 안 씀): 진입 90일 ≥ 3%/8%.
판정: GATING-USEFUL = 주 규칙의 순연수익이 **세 비용 수준 모두** 항상 보유보다 높고 **최근 3년**(마지막 1095일)에서도 그렇다.
      그 밖은 GATING-NOT-USEFUL. (게이트가 낫지 않아도 알림은 유지할 수 있다 — 알림은 사람의 검토 신호이지 자동 규칙이 아니다.)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = HERE / ".cache" / "funding_monitor" / "BTCUSDT_funding.parquet"
COSTS = (0.0015, 0.0030, 0.0060)
ENTRY_90, ENTRY_30, EXIT_30, EXIT_90 = 5.0, 0.0, 0.0, 2.0


def rolling_ann(f: pd.Series, days: int) -> pd.Series:
    n = days * 3
    return f.rolling(n, min_periods=n).sum() * 365 / days * 100


def positions(f: pd.Series, entry90=ENTRY_90, exit90=EXIT_90) -> pd.Series:
    """결제 i 를 보유하는가(1/0). 결정은 i-1 까지의 데이터로 한다(한 결제 지연)."""
    a90, a30 = rolling_ann(f, 90), rolling_ann(f, 30)
    held = np.zeros(len(f), dtype=int)
    inpos = False
    for i in range(1, len(f)):
        x90, x30 = a90.iloc[i - 1], a30.iloc[i - 1]
        if np.isnan(x90) or np.isnan(x30):
            held[i] = 0
            continue
        if inpos and (x30 < EXIT_30 or x90 < exit90):
            inpos = False
        elif not inpos and x90 >= entry90 and x30 > ENTRY_30:
            inpos = True
        held[i] = int(inpos)
    return pd.Series(held, index=f.index)


def evaluate(f: pd.Series, held: pd.Series, cost: float) -> dict:
    gross = f * held
    entries = held.diff().fillna(held.iloc[0]) == 1
    n_round = int(entries.sum())          # 왕복 = 진입 1회당 1회(진입 비용+청산 비용을 CYCLE_COST 하나로 묶는다)
    total_cost = n_round * cost
    net = gross.sum() - total_cost
    yrs = (f.index[-1] - f.index[0]).total_seconds() / (365.25 * 86400)
    cum = gross.cumsum() - np.where(held.diff().fillna(held.iloc[0]) == 1, cost, 0).cumsum()
    dd = float((cum - np.maximum.accumulate(cum)).min()) * 100
    return {"netAnnPct": net / yrs * 100, "grossAnnPct": gross.sum() / yrs * 100, "cycles": n_round,
            "timeInMarketPct": float(held.mean() * 100), "maxDdPctPoints": dd}


def window(f, held, days):
    cut = f.index[-1] - pd.Timedelta(days=days)
    return f[f.index > cut], held[held.index > cut]


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    idx = pd.date_range("2024-01-01", periods=3 * 400, freq="8h", tz="UTC")
    f = pd.Series(0.0002, index=idx)                        # 연 21.9%
    h = positions(f)
    ck("좋은 국면이면 워밍업 뒤 계속 보유", h.iloc[300:].min() == 1 and h.iloc[:270].max() == 0)
    r = evaluate(f, h, 0.003)
    ck("왕복 1회 비용이 순수익에 반영", r["cycles"] == 1 and r["netAnnPct"] < r["grossAnnPct"])
    g = f.copy()
    g.iloc[600:] = -0.0002                                  # 이후 음수 국면
    hg = positions(g)
    ck("음수 국면에서 퇴출하고 다시 안 들어간다", hg.iloc[-1] == 0 and hg.iloc[600:900].max() == 1 and hg.sum() > 0)
    ck("한 결제 지연(첫 결제는 절대 보유 아님)", positions(f).iloc[0] == 0)
    print(f"\nselftest {4 - len(fails)}/4" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    f = pd.read_parquet(SRC)["fundingRate"].astype(float)
    print(f"이력 {len(f):,}건  {f.index[0]:%Y-%m-%d} ~ {f.index[-1]:%Y-%m-%d}")
    always = pd.Series(1, index=f.index)
    always.iloc[0] = 0
    rows = {}
    grids = {"주(90일≥5%)": positions(f), "민감도(≥3%)": positions(f, entry90=3.0), "민감도(≥8%)": positions(f, entry90=8.0),
             "항상 보유": always}
    print(f"{'규칙':14} {'비용':>6} | {'전체 순연%':>9} {'총연%':>7} {'왕복':>4} {'시장내%':>7} {'MDD%p':>6} | "
          f"{'최근3년 순연%':>12} {'최근1년 순연%':>12}")
    for name, h in grids.items():
        for c in COSTS:
            r = evaluate(f, h, c)
            f3, h3 = window(f, h, 1095)
            f1, h1 = window(f, h, 365)
            r3 = evaluate(f3, h3, c)["netAnnPct"]
            r1 = evaluate(f1, h1, c)["netAnnPct"]
            rows[(name, c)] = (r, r3, r1)
            print(f"{name:14} {c * 100:5.2f}% | {r['netAnnPct']:9.2f} {r['grossAnnPct']:7.2f} {r['cycles']:4d} "
                  f"{r['timeInMarketPct']:7.1f} {r['maxDdPctPoints']:6.2f} | {r3:12.2f} {r1:12.2f}")
    main_name = "주(90일≥5%)"
    useful = all(rows[(main_name, c)][0]["netAnnPct"] > rows[("항상 보유", c)][0]["netAnnPct"]
                 and rows[(main_name, c)][1] > rows[("항상 보유", c)][1] for c in COSTS)
    print("\n판정:", "GATING-USEFUL" if useful else "GATING-NOT-USEFUL")
    print("\n연도별 순수익(비용 0.30%, 명목 대비 %):")
    for name in (main_name, "항상 보유"):
        h = grids[name]
        line = []
        for y in sorted(set(f.index.year)):
            m = f.index.year == y
            ff, hh = f[m], h[m]
            cyc = int(((hh.diff().fillna(hh.iloc[0]) == 1)).sum())
            line.append(f"{y}:{(ff * hh).sum() * 100 - cyc * 0.30:6.2f}")
        print(f"  {name:12} " + " ".join(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else main())
