#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAND1 — 익일 종가 근사(exit=n_close) vs 검증된 익일 09:35(exit=n_c0935).

지시(2026-08-24): `findings/cand1-next-stage-validation-2026-08.md` §6이 확정한
구조적 공백 — Strategy Lab 엔진은 세션 단위(일봉) 청산만 계약에 있고, CAND1이
검증받은 "익일 09:35 청산"(일중 특정 시각)은 표현이 안 된다. §7 SMOKE 계획의
옵션 1("익일 종가로 근사해 먼저 순양 여부만 본다")을 엔진 접점 없이 먼저
research 레벨에서 확인한다 — 09:35 청산을 지원하도록 엔진을 확장하는 건
모든 전략이 공유하는 핵심 루프를 건드리는 큰 결정(🔴)이라, 그 전에 근사가
순양인지부터 싸게 알아본다.

신호·체결 규칙은 이 프로젝트가 이미 여러 세션에 걸쳐 써 온 동결값 그대로:
thr=0.02, vthr=1.5, mthr=None, entry=n_open — `analyze_cand1_regime_
conditional.py`와 동일 패턴(load_frame() 재사용, 무변경 이식), EXIT_COL만
n_c0935(baseline, 기존 결과 재현용) vs n_close(근사)로 나란히 비교한다.

주의(원본 발견 과정과의 관계): `run_strategy_validation.py`의 원래 TRAIN
sweep(72config)에도 exit 후보에 n_close가 이미 있었고, 그 sweep에서 최종
선택된 것은 n_c0935였다 — 즉 n_close가 "안 써본 값"이 아니라 "train에서
09:35보다 못해서 탈락한 값"이다. 그러므로 이 스크립트의 목적은 "n_close가
더 낫다"를 보이는 게 아니라 **"n_close로도 최소한 순양(net>0)은 유지되는가"**
다 — 유지되면 엔진 확장 없이 SMOKE를 먼저 돌려볼 근거가 되고, 마이너스면
09:35 청산 지원 없이는 이 전략을 엔진에 못 얹는다는 뜻이라 그 비싼 결정을
안 해도 된다.

산출: findings/cand1-close-exit-approximation-2026-08.md

사용:
    python analyze_cand1_close_exit_approx.py --selftest
    python analyze_cand1_close_exit_approx.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

HERE = Path(__file__).resolve().parent
OUT_MD = HERE / "findings" / "cand1-close-exit-approximation-2026-08.md"

sys.path.insert(0, str(HERE))

THR, VTHR, MTHR = 0.02, 1.5, None   # 기존 동결 파라미터(변경 안 함)
ENTRY_COL = "n_open"
COST_BPS = 20.0                      # intraday-final-report.md와 동일 가정


def build_signal_trades(f, exit_col):
    mask = (f["r_1400_close"] <= -THR) & (f["rel_v_w1400_1500"] < VTHR)
    mask = mask.fillna(False)
    sub = f.loc[mask, ["date", "ticker", ENTRY_COL, exit_col]].copy()
    sub = sub[sub[ENTRY_COL].notna() & sub[exit_col].notna()]
    sub["pnlGross"] = sub[exit_col] / sub[ENTRY_COL] - 1.0
    sub["pnlNet"] = sub["pnlGross"] - COST_BPS / 1e4
    return sub.rename(columns={"date": "signalDate"})


def daily_series(trades, col):
    return trades.groupby("signalDate")[col].mean().sort_index()


def mdd_from_returns(returns_sorted):
    if len(returns_sorted) == 0:
        return None
    cum = np.cumprod(1 + returns_sorted.to_numpy())
    peak = np.maximum.accumulate(cum)
    return round(float((cum / peak - 1).min()) * 100, 2)


def summary_stats(trades):
    n = trades["pnlNet"].to_numpy()
    win = n > 0
    pos = n[n > 0].sum()
    neg = -n[n < 0].sum()
    dpg = daily_series(trades, "pnlGross")
    dpn = daily_series(trades, "pnlNet")
    return {
        "trades": int(len(trades)),
        "tickers": int(trades["ticker"].nunique()),
        "signalDays": int(trades["signalDate"].nunique()),
        "winRate": round(float(win.mean()), 4),
        "profitFactor": round(float(pos / neg), 3) if neg > 0 else None,
        "grossMeanBp": round(float(dpg.mean()) * 10000, 2) if len(dpg) else None,
        "netMeanBp": round(float(dpn.mean()) * 10000, 2) if len(dpn) else None,
        "mddPct": mdd_from_returns(dpn),
    }


def test_quarter_excess(f, trades, exit_col, dates):
    """§2 audit 패턴과 동일 — TEST(마지막 25%)에서 EW 벤치마크 대비 초과."""
    n = len(dates)
    te_dates = set(dates[int(n * 0.75):])
    te_trades = trades[trades["signalDate"].isin(te_dates)]
    if not len(te_trades):
        return None
    strat_daily = te_trades.groupby("signalDate")["pnlNet"].mean()
    bench = f[f["date"].isin(te_dates)].copy()
    bench["ewRet"] = bench[exit_col] / bench[ENTRY_COL] - 1.0
    bench_daily = bench.dropna(subset=["ewRet"]).groupby("date")["ewRet"].mean()
    j = pd.concat([strat_daily, bench_daily], axis=1, join="inner").dropna()
    j.columns = ["strat", "bench"]
    excess = j["strat"] - j["bench"]
    if len(excess) <= 1:
        return {"days": len(excess), "meanExcessPct": None, "t": None}
    t, _ = sps.ttest_1samp(excess.to_numpy(), 0.0) if excess.std(ddof=1) > 0 else (None, None)
    return {"days": int(len(excess)), "meanExcessPct": round(float(excess.mean()) * 100, 4),
            "t": round(float(t), 2) if t is not None else None}


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    f = pd.DataFrame({
        "date": ["2026-01-05", "2026-01-05", "2026-01-05"],
        "ticker": ["A", "B", "C"],
        "r_1400_close": [-0.03, -0.03, -0.01],   # C는 임계 미달
        "rel_v_w1400_1500": [1.0, 1.0, 1.0],
        "n_open": [100.0, 100.0, 100.0],
        "n_c0935": [103.0, 97.0, 100.0],
        "n_close": [101.0, 99.0, 100.0],
    })
    tr0935 = build_signal_trades(f, "n_c0935")
    trclose = build_signal_trades(f, "n_close")
    check("임계 미달(C)는 두 exit 모두에서 신호 제외", "C" not in set(tr0935["ticker"]) and "C" not in set(trclose["ticker"]))
    check("exit 컬럼만 다르고 같은 신호(A,B)를 씀", set(tr0935["ticker"]) == set(trclose["ticker"]) == {"A", "B"})
    check("n_close pnlGross가 close/open-1로 계산됨(A: 1%)",
          np.isclose(trclose.loc[trclose["ticker"] == "A", "pnlGross"].iloc[0], 0.01))
    check("n_c0935 pnlGross는 그대로(A: 3%)",
          np.isclose(tr0935.loc[tr0935["ticker"] == "A", "pnlGross"].iloc[0], 0.03))
    check("cost는 두 exit에 동일하게 20bp 차감",
          np.isclose(trclose.loc[trclose["ticker"] == "A", "pnlNet"].iloc[0], 0.01 - COST_BPS / 1e4))

    s = summary_stats(tr0935)
    check("summary_stats가 trades=2를 센다", s["trades"] == 2)
    check("MDD는 0 이하", s["mddPct"] is not None and s["mddPct"] <= 0)

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print()
    print("통과 %d · 실패 %d" % (sum(c for _, c in checks), sum(not c for _, c in checks)))
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        return selftest()

    from run_strategy_validation import load_frame
    print("load_frame() 로드 중...")
    f, _p, _g = load_frame()
    dates = sorted(f["date"].unique())
    print("가용 세션: %d, 범위 %s~%s" % (len(dates), dates[0], dates[-1]))

    lines = []
    lines.append("# CAND1 — 익일 종가 근사(n_close) vs 검증된 익일 09:35(n_c0935) (2026-08)\n\n")
    lines.append(
        "목적: `cand1-next-stage-validation-2026-08.md` §7 SMOKE 계획의 옵션 1을 "
        "엔진 접점 없이 먼저 확인 — Strategy Lab 엔진이 지원 못 하는 '일중 특정 "
        "시각(09:35) 청산'을 '익일 종가' 청산으로 근사했을 때도 순양(net>0)이 "
        "유지되는가. 신호·체결 파라미터(thr=%.2f, vthr=%.1f, entry=%s, cost=%dbp)는 "
        "전부 동결값 그대로, exit 컬럼만 바꾼다.\n\n"
        "**주의**: n_close는 원래 발견 과정(`run_strategy_validation.py` TRAIN "
        "72config sweep)에도 이미 후보로 있었고 그때 09:35보다 못해서 탈락한 값이다 "
        "— 이 문서는 'n_close가 낫다'가 아니라 'n_close로도 최소 순양은 유지되는가'"
        "만 묻는다.\n\n---\n\n" % (THR, VTHR, ENTRY_COL, COST_BPS))

    lines.append("## 1. 전체 구간 비교\n\n")
    lines.append("| exit | 거래수 | 종목수 | 신호일수 | 승률 | Profit Factor | "
                  "gross(bp) | net(bp) | MDD(%) |\n")
    lines.append("|---|---|---|---|---|---|---|---|---|\n")
    trades_by_exit = {}
    for exit_col, label in (("n_c0935", "n_c0935(검증됨, baseline)"), ("n_close", "n_close(근사)")):
        tr = build_signal_trades(f, exit_col)
        trades_by_exit[exit_col] = tr
        s = summary_stats(tr)
        lines.append("| %s | %d | %d | %d | %.1f%% | %s | %.2f | %.2f | %s |\n" % (
            label, s["trades"], s["tickers"], s["signalDays"], s["winRate"] * 100,
            "%.2f" % s["profitFactor"] if s["profitFactor"] else "N/A",
            s["grossMeanBp"], s["netMeanBp"],
            "%.2f" % s["mddPct"] if s["mddPct"] is not None else "N/A"))

    lines.append(
        "\n## 2. TEST 구간(마지막 25%) — 기존 보고값 재현 + n_close 대조\n\n"
        "`findings/intraday-final-report/report.md`가 인용한 값: 20bps 비용 반영 "
        "후 **+0.369%%/일(t=3.94)**(exit=n_c0935). 같은 TEST 구간, 같은 신호로 "
        "exit만 바꿔 나란히 계산한다.\n\n"
        "| exit | TEST일수 | meanExcess(%%/일) | t |\n"
        "|---|---|---|---|\n")
    for exit_col, label in (("n_c0935", "n_c0935(검증됨)"), ("n_close", "n_close(근사)")):
        r = test_quarter_excess(f, trades_by_exit[exit_col], exit_col, dates)
        if r is None:
            lines.append("| %s | 0 | 재현 불가(매칭 거래 없음) | |\n" % label)
        else:
            me = "%.4f" % r["meanExcessPct"] if r["meanExcessPct"] is not None else "N/A"
            t = "%.2f" % r["t"] if r["t"] is not None else "N/A"
            lines.append("| %s | %d | %s | %s |\n" % (label, r["days"], me, t))

    s_base = summary_stats(trades_by_exit["n_c0935"])
    s_close = summary_stats(trades_by_exit["n_close"])
    erosion_pct = (1 - (s_close["netMeanBp"] or 0) / s_base["netMeanBp"]) * 100 if s_base["netMeanBp"] else None
    if (s_close["netMeanBp"] or 0) <= 0:
        verdict = "순음(음수) — 09:35 청산 지원 없이는 엔진에 못 얹는다, 큰 엔진 확장(옵션 2)의 근거 약함"
    elif erosion_pct is not None and erosion_pct >= 80:
        verdict = ("이론상 순양이나 net이 baseline 대비 %.0f%% 침식되어 %.0f%%만 남는다(오차범위에 가깝다), "
                   "MDD도 %.2f%%→%.2f%%로 악화 — '엔진에 얹을 만한 근사'가 아니다. CAND1의 edge는 신호 후 "
                   "첫 09:35까지의 짧은 창에 집중돼 있고, 익일 종가까지 들고 가면 거의 다 사라진다는 뜻으로 "
                   "읽는다. SMOKE를 옵션 1로 미리 돌려도 이 결과를 엔진 레벨에서 재확인하는 것 이상의 새 "
                   "정보는 없을 가능성이 높다"
                   % (erosion_pct, 100 - erosion_pct, s_base["mddPct"], s_close["mddPct"]))
    else:
        verdict = "순양 유지, baseline 대비 %.0f%% 수준 — SMOKE(엔진 접점) 시도 근거 있음" % (100 - (erosion_pct or 0))
    lines.append("\n## 3. 판정\n\n**%s**\n\n(baseline net=%.2fbp → 근사 net=%.2fbp, TEST 구간 재현치는 위 §2 참고)\n\n" %
                  (verdict, s_base["netMeanBp"], s_close["netMeanBp"] or 0.0))

    lines.append(
        "## 검증 가능한 근거 목록\n\n"
        "- `run_strategy_validation.py` `load_frame()` — n_open/n_c0935/n_close "
        "원출처(무변경, import로 재사용)\n"
        "- `analyze_cand1_regime_conditional.py` — 같은 패턴(동결 파라미터, "
        "signalDate 그룹핑)의 exit=n_c0935 버전, 이 문서의 baseline 열과 값이 "
        "일치해야 함\n"
        "- `findings/intraday-final-report/report.md` — cost=20bp, "
        "+0.369%%/일(t=3.94) 원출처, exit=n_c0935\n"
        "- 본 스크립트 `analyze_cand1_close_exit_approx.py` — 재실행하면 동일 결과\n")

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("wrote", OUT_MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
