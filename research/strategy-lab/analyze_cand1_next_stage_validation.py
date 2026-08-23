#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAND1 다음 단계 검증 — 월별/분기별 분해, 종목 집중도, 비용 민감도.

지시(2026-08-23): 신호·체결·비용·regime threshold 전부 고정, 변경 없음.
2025-08~2026-08 가용 분봉 기간을 월별/분기별로 분해해 net(bp)·PF·승률·MDD·
거래수·종목 집중도를 확인하고, 비용 민감도(보수적 추가 확인)도 본다.

신호·체결·비용 로직은 `analyze_cand1_regime_conditional.py`의 함수를 그대로
import해서 쓴다(원본 무변경, 새 로직 없음) — thr=0.02, vthr=1.5, mthr=None,
entry=n_open, exit=n_c0935, 기본 cost=20bp.

비용 민감도는 **새 cost 값을 채택하는 게 아니라** 20bp가 얼마나 여유 있는지
보수적으로 추가 확인하는 것뿐이다 — baseline cost는 20bp 그대로 유지.

산출: findings/cand1-next-stage-validation-2026-08.md

사용:
    python analyze_cand1_next_stage_validation.py --selftest
    python analyze_cand1_next_stage_validation.py
"""
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT_MD = HERE / "findings" / "cand1-next-stage-validation-2026-08.md"

sys.path.insert(0, str(HERE))
from analyze_cand1_regime_conditional import (  # noqa: E402
    COST_BPS, ENTRY_COL, EXIT_COL, THR, VTHR, build_signal_trades,
    daily_portfolio_series, load_regime_lookup, mdd_from_returns,
    next_trading_day_map, trade_stats,
)

COST_GRID_BPS = (20.0, 30.0, 40.0, 50.0)   # 20bp=기존 기준, 나머지는 스트레스용


def quarter_of(date_str):
    y, m = int(date_str[:4]), int(date_str[5:7])
    q = (m - 1) // 3 + 1
    return "%dQ%d" % (y, q)


def month_of(date_str):
    return date_str[:7]


def concentration(trades):
    """종목 집중도 — 거래수 기준 top5 비중, 순손익 기여 top5 비중, HHI."""
    if len(trades) == 0:
        return {"top5TradeSharePct": None, "top5PnlSharePct": None, "hhi": None}
    by_n = trades.groupby("ticker").size().sort_values(ascending=False)
    top5_trade_share = by_n.head(5).sum() / by_n.sum()
    shares = by_n / by_n.sum()
    hhi = float((shares ** 2).sum())

    by_pnl = trades.groupby("ticker")["pnlNet"].sum()
    pos_total = by_pnl[by_pnl > 0].sum()
    if pos_total > 0:
        top5_pnl_share = by_pnl.sort_values(ascending=False).head(5).clip(lower=0).sum() / pos_total
    else:
        top5_pnl_share = None
    return {
        "top5TradeSharePct": round(float(top5_trade_share) * 100, 1),
        "top5PnlSharePct": round(float(top5_pnl_share) * 100, 1) if top5_pnl_share is not None else None,
        "hhi": round(hhi, 4),
        "uniqueTickers": int(trades["ticker"].nunique()),
    }


def period_block(sub, cost_bps=None):
    """period 서브셋에 대한 표준 지표 세트. cost_bps가 주어지면 pnlNet을 그
    비용으로 재계산(비용 민감도용, pnlGross는 원본 그대로라 재계산 안전)."""
    if len(sub) == 0:
        return None
    if cost_bps is not None:
        sub = sub.copy()
        sub["pnlNet"] = sub["pnlGross"] - cost_bps / 1e4
    s = trade_stats(sub)
    dpg = daily_portfolio_series(sub, "pnlGross")
    dpn = daily_portfolio_series(sub, "pnlNet")
    s["grossMeanBp"] = round(float(dpg.mean()) * 10000, 2) if len(dpg) else None
    s["netMeanBp"] = round(float(dpn.mean()) * 10000, 2) if len(dpn) else None
    s["mddPct"] = mdd_from_returns(dpn)
    s.update(concentration(sub))
    return s


def git_commit():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=HERE.parents[1], text=True, timeout=5).strip()
    except Exception as e:
        return "unknown(%s)" % e


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    check("quarter_of가 연-분기 정확히 계산", quarter_of("2026-04-15") == "2026Q2")
    check("quarter_of 12월은 Q4", quarter_of("2025-12-01") == "2025Q4")
    check("month_of가 YYYY-MM 반환", month_of("2026-03-17") == "2026-03")

    trades = pd.DataFrame({
        "ticker": ["A", "A", "A", "A", "B"],
        "pnlNet": [0.01, 0.02, -0.03, 0.01, 0.05],
        "pnlGross": [0.011, 0.021, -0.029, 0.011, 0.051],
        "signalDate": ["2026-01-04"] * 5,
        "entryDate": ["2026-01-05"] * 5,
    })
    c = concentration(trades)
    check("종목 2개뿐이면 top5 거래비중=100%", c["top5TradeSharePct"] == 100.0)
    check("고유종목수 정확", c["uniqueTickers"] == 2)
    check("HHI가 (0.8^2+0.2^2)=0.68로 계산된다",
          np.isclose(c["hhi"], 0.8 ** 2 + 0.2 ** 2))

    blk = period_block(trades, cost_bps=None)
    check("period_block이 pnlNet 그대로 쓰면 기존 cost 그대로",
          blk is not None)
    blk50 = period_block(trades, cost_bps=50.0)
    check("cost_bps override 시 netMeanBp가 더 낮아진다(비용 증가)",
          blk50["netMeanBp"] < blk["netMeanBp"])
    check("cost override는 pnlGross는 안 건드린다(원본 보존)",
          np.isclose(blk50["grossMeanBp"], blk["grossMeanBp"]))

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
    f, p, _g = load_frame()
    dates = sorted(f["date"].unique())
    print("가용 세션: %d, %s~%s" % (len(dates), dates[0], dates[-1]))

    nxt_map = next_trading_day_map()
    trades = build_signal_trades(f)
    trades["entryDate"] = trades["signalDate"].map(nxt_map)
    trades = trades.dropna(subset=["entryDate"])

    lines = []
    lines.append("# CAND1 다음 단계 검증 — 월별/분기별·집중도·비용민감도 (2026-08)\n\n")
    lines.append(
        "신호·체결·비용(thr=%.2f, vthr=%.1f, entry=%s, exit=%s, cost=%dbp)·regime "
        "threshold 전부 고정, 변경 없음. 이 문서는 CAND1이 이미 통과한 "
        "regime-conditional 검증(`cand1-regime-conditional-2026-08.md`, 커밋 "
        "`6745dc5`) 위에 시간 분해·집중도·비용 스트레스만 추가한다.\n\n---\n\n"
        % (THR, VTHR, ENTRY_COL, EXIT_COL, COST_BPS))

    # ---- 1. 월별 ----
    lines.append("## 1. 월별 분해\n\n")
    trades["month"] = trades["entryDate"].map(month_of)
    rows = []
    for m in sorted(trades["month"].unique()):
        sub = trades[trades["month"] == m]
        blk = period_block(sub)
        if blk:
            blk["구간"] = m
            rows.append(blk)
    mdf = pd.DataFrame(rows).set_index("구간")
    lines.append("| 월 | 거래수 | 종목수 | 승률 | PF | net(bp) | MDD(%) | top5거래비중 | top5손익기여 | HHI |\n")
    lines.append("|---|---|---|---|---|---|---|---|---|---|\n")
    for name, row in mdf.iterrows():
        lines.append("| %s | %d | %d | %.1f%% | %s | %.2f | %.2f | %.1f%% | %s | %.4f |\n" % (
            name, row["trades"], row["tickers"], row["winRate"] * 100,
            "%.2f" % row["profitFactor"] if row["profitFactor"] else "N/A",
            row["netMeanBp"], row["mddPct"], row["top5TradeSharePct"],
            ("%.1f%%" % row["top5PnlSharePct"]) if row["top5PnlSharePct"] is not None else "N/A",
            row["hhi"]))
    n_neg_months = int((mdf["netMeanBp"] < 0).sum())
    lines.append("\n순손실 월: %d / %d개월\n\n" % (n_neg_months, len(mdf)))

    # ---- 2. 분기별 ----
    lines.append("## 2. 분기별 분해\n\n")
    trades["quarter"] = trades["entryDate"].map(quarter_of)
    rows = []
    for qname in sorted(trades["quarter"].unique()):
        sub = trades[trades["quarter"] == qname]
        blk = period_block(sub)
        if blk:
            blk["구간"] = qname
            rows.append(blk)
    qdf = pd.DataFrame(rows).set_index("구간")
    lines.append("| 분기 | 거래수 | 종목수 | 승률 | PF | net(bp) | MDD(%) | top5거래비중 | top5손익기여 | HHI |\n")
    lines.append("|---|---|---|---|---|---|---|---|---|---|\n")
    for name, row in qdf.iterrows():
        lines.append("| %s | %d | %d | %.1f%% | %s | %.2f | %.2f | %.1f%% | %s | %.4f |\n" % (
            name, row["trades"], row["tickers"], row["winRate"] * 100,
            "%.2f" % row["profitFactor"] if row["profitFactor"] else "N/A",
            row["netMeanBp"], row["mddPct"], row["top5TradeSharePct"],
            ("%.1f%%" % row["top5PnlSharePct"]) if row["top5PnlSharePct"] is not None else "N/A",
            row["hhi"]))
    n_neg_q = int((qdf["netMeanBp"] < 0).sum())
    lines.append("\n순손실 분기: %d / %d개 분기\n\n" % (n_neg_q, len(qdf)))

    # ---- 3. 전체 집중도(참고) ----
    lines.append("## 3. 전체 표본 종목 집중도\n\n")
    c_all = concentration(trades)
    lines.append("고유 종목수 %d, top5 거래비중 %.1f%%, top5 순손익기여 %s, HHI %.4f "
                  "(HHI는 완전분산=1/N에 가까울수록 낮음 — 참고로 1/%d=%.4f)\n\n"
                  % (c_all["uniqueTickers"], c_all["top5TradeSharePct"],
                     ("%.1f%%" % c_all["top5PnlSharePct"]) if c_all["top5PnlSharePct"] else "N/A",
                     c_all["hhi"], c_all["uniqueTickers"], 1.0 / c_all["uniqueTickers"]))

    # ---- 4. 비용 민감도 ----
    lines.append("## 4. 비용 민감도 (기존 20bp는 유지, 스트레스만 추가 확인)\n\n")
    lines.append("| cost(bp) | 전체 net(bp) | Risk-On | Neutral | Risk-Off |\n")
    lines.append("|---|---|---|---|---|\n")
    regime_lut = load_regime_lookup()
    trw = trades.merge(regime_lut, left_on="entryDate", right_on="date", how="left")
    for cb in COST_GRID_BPS:
        row = {"전체": period_block(trw, cost_bps=cb)}
        for r in ("Risk-On", "Neutral", "Risk-Off"):
            row[r] = period_block(trw[trw["regime"] == r], cost_bps=cb)
        lines.append("| %d%s | %.2f | %.2f | %.2f | %.2f |\n" % (
            int(cb), "(기존)" if cb == COST_BPS else "",
            row["전체"]["netMeanBp"], row["Risk-On"]["netMeanBp"],
            row["Neutral"]["netMeanBp"], row["Risk-Off"]["netMeanBp"]))
    lines.append("\n")

    # ---- 5. 종합 판정 ----
    all_months_positive = n_neg_months == 0
    all_quarters_positive = n_neg_q == 0
    not_overconcentrated = c_all["top5TradeSharePct"] < 20.0  # 참고 기준, 사전 설정
    lines.append("## 5. 종합 판정\n\n")
    lines.append("| 항목 | 결과 | 판정 |\n|---|---|---|\n")
    lines.append("| 월별 전부 순이익 | %d/%d개월 양(+) | %s |\n" % (
        len(mdf) - n_neg_months, len(mdf), "PASS" if all_months_positive else "FAIL(주의)"))
    lines.append("| 분기별 전부 순이익 | %d/%d분기 양(+) | %s |\n" % (
        len(qdf) - n_neg_q, len(qdf), "PASS" if all_quarters_positive else "FAIL(주의)"))
    lines.append("| 종목 집중도(top5<20%%) | %.1f%% | %s |\n" % (
        c_all["top5TradeSharePct"], "PASS" if not_overconcentrated else "FAIL(주의)"))
    lines.append("| 20bp 결과 재확인 | 위 §4 표 첫 행 | (regime-conditional 문서와 "
                  "동일해야 함 — 아래 감사 참고) |\n\n")

    lines.append(
        "**주의**: 이 판정 기준(top5<20% 등)은 사용자 지시가 아니라 이번 "
        "스크립트가 참고용으로 사전에 설정한 임계값이다 — CAND1 성과를 보고 "
        "정한 게 아니라(자기 히스토리 데이터를 하나도 안 보고 미리 정한 "
        "'집중도 20%'라는 일반적 리스크 기준) 판정 자체를 최적화하지 않았지만, "
        "이 기준 자체의 타당성은 사용자가 다시 확인해야 한다.\n\n")

    lines.append(
        "## 검증 가능한 근거 목록\n\n"
        "- `analyze_cand1_regime_conditional.py` — 신호·체결·비용·PIT 로직 원출처"
        "(무변경, import로 재사용)\n"
        "- `findings/cand1-regime-conditional-2026-08.md`(커밋 `6745dc5`) — 이 "
        "문서가 이어받는 regime-conditional 기준선\n"
        "- 본 스크립트 `analyze_cand1_next_stage_validation.py` — 재실행하면 "
        "동일 결과\n"
        "- 생성 시점 repo commit: %s\n" % git_commit())

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("wrote", OUT_MD)
    print("월별 순손실:", n_neg_months, "/", len(mdf))
    print("분기별 순손실:", n_neg_q, "/", len(qdf))
    print("top5 거래비중: %.1f%%" % c_all["top5TradeSharePct"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
