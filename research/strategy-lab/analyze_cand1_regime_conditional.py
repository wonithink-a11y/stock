#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CAND1(PMCRASH_REVERSAL) — regime-conditional 성과 (Risk-On/Neutral/Risk-Off).

지시(2026-08-23): regime 정의(고정본, market-regime-definition-2026-08.md)를
바꾸지 않고, CAND1의 기존 신호·체결 규칙을 그대로 써서 baseline과 3개 regime을
비교한다. 데이터 가용 기간을 먼저 확인한다.

신호·체결 규칙은 `run_strategy_validation.py`의 `load_frame()`을 **그대로
import**해서 쓴다(원본 무변경 — 이 파일은 이미 임포트 가능한 함수라 복사할
필요가 없다, cand1_regime_decomposition.py와 같은 방식). 동결 파라미터는
이 프로젝트가 이미 여러 세션에 걸쳐 써 온 값 그대로: thr=0.02, vthr=1.5,
mthr=None, entry=n_open(익일 시가), exit=n_c0935(익일 09:35), cost=20bps
(intraday-final-report.md "20bps 비용 반영 후 +0.369%/일(t=3.94)"와 동일
가정). 새 파라미터를 고르지 않았다.

데이터 가용 기간(확인 결과, §0): load_frame() 산출이 250세션·
2025-08-08~2026-08-21뿐이다 — Opening Fade와 동일한 제약. regime 정의는
2016년부터 있지만 CAND1 신호(intraday_panel.parquet 기반)도 Opening Fade와
같은 이유로 그 이전 구간이 없다.

PIT: CAND1은 신호일 T(오후급락 관측일)의 **다음 거래일** 시가에 진입한다 —
그래서 regime은 신호일 T가 아니라 진입일(T+1, calendar.json으로 산출)의
`usableFromDate`로 조인한다. 신호일로 조인하면 "아직 진입 전인 T일에 이미
알던 정보"보다 하루 이른(진입일 기준으로도 여전히 미래 아님) 값을 쓰게 돼
불필요하게 보수적이거나, 반대로 T와 진입일 regime이 다른 경계일에는 틀린
regime을 붙이게 된다 — 진입 시점 기준이 맞다.

산출: findings/cand1-regime-conditional-2026-08.md

사용:
    python analyze_cand1_regime_conditional.py --selftest
    python analyze_cand1_regime_conditional.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
REGIME_LABELS_PATH = HERE / "data" / "market-regime" / "regime_labels.parquet"
CALENDAR_PATH = REPO_ROOT / "data" / "backfill" / "calendar.json"
OUT_MD = HERE / "findings" / "cand1-regime-conditional-2026-08.md"

sys.path.insert(0, str(HERE))

THR, VTHR, MTHR = 0.02, 1.5, None   # 기존 동결 파라미터(변경 안 함)
ENTRY_COL, EXIT_COL = "n_open", "n_c0935"
COST_BPS = 20.0                      # intraday-final-report.md와 동일 가정

HALVES = [("전반(2025-08~2026-02)", "2025-08-08", "2026-02-28"),
          ("후반(2026-03~2026-08)", "2026-03-01", "2026-08-21")]


def next_trading_day_map():
    cal = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
    days = cal["tradingDays"]
    return {days[i]: days[i + 1] for i in range(len(days) - 1)}


def build_signal_trades(f):
    """run_strategy_validation.sig_pmcrash()와 동일 마스크(그대로 이식, 무변경)."""
    mask = (f["r_1400_close"] <= -THR) & (f["rel_v_w1400_1500"] < VTHR)
    mask = mask.fillna(False)
    if MTHR is not None:
        mask &= f["reg_kospi_ret"] <= MTHR
    sub = f.loc[mask, ["date", "ticker", ENTRY_COL, EXIT_COL]].copy()
    sub = sub[sub[ENTRY_COL].notna() & sub[EXIT_COL].notna()]
    sub["pnlGross"] = sub[EXIT_COL] / sub[ENTRY_COL] - 1.0
    sub["pnlNet"] = sub["pnlGross"] - COST_BPS / 1e4
    return sub.rename(columns={"date": "signalDate"})


def attach_entry_date_and_regime(trades, nxt_map, regime_lut):
    trades = trades.copy()
    trades["entryDate"] = trades["signalDate"].map(nxt_map)
    trades = trades.merge(regime_lut, left_on="entryDate", right_on="date",
                           how="left").drop(columns=["date"])
    return trades


def load_regime_lookup():
    rl = pd.read_parquet(REGIME_LABELS_PATH)
    lut = rl.dropna(subset=["usableFromDate"])[["usableFromDate", "regime"]]
    return lut.drop_duplicates("usableFromDate").rename(columns={"usableFromDate": "date"})


def trade_stats(trades):
    if len(trades) == 0:
        return None
    n = trades["pnlNet"].to_numpy()
    win = n > 0
    pos = n[n > 0].sum()
    neg = -n[n < 0].sum()
    return {
        "trades": int(len(trades)),
        "tickers": int(trades["ticker"].nunique()),
        "signalDays": int(trades["signalDate"].nunique()),
        "winRate": round(float(win.mean()), 4),
        "profitFactor": round(float(pos / neg), 3) if neg > 0 else None,
    }


def daily_portfolio_series(trades, col):
    """신호일(entryDate) 단위 동일가중 평균 — run_strategy_validation.daily_series()와
    같은 집계 단위(신호당 종목수 변동과 무관하게 날짜별 동일가중)."""
    return trades.groupby("entryDate")[col].mean().sort_index()


def mdd_from_returns(returns_sorted):
    if len(returns_sorted) == 0:
        return None
    cum = np.cumprod(1 + returns_sorted.to_numpy())
    peak = np.maximum.accumulate(cum)
    return round(float((cum / peak - 1).min()) * 100, 2)


def period_of(date_str):
    for name, lo, hi in HALVES:
        if lo <= date_str <= hi:
            return name
    return None


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    f = pd.DataFrame({
        "date": ["2026-01-05", "2026-01-06", "2026-01-06"],
        "ticker": ["A", "B", "C"],
        "r_1400_close": [-0.03, -0.03, -0.01],   # C는 임계 미달
        "rel_v_w1400_1500": [1.0, 1.0, 1.0],
        "reg_kospi_ret": [0.0, 0.0, 0.0],
        "n_open": [100.0, 100.0, 100.0],
        "n_c0935": [103.0, 97.0, 100.0],
    })
    tr = build_signal_trades(f)
    check("임계 미달(C)는 신호에서 빠진다", "C" not in set(tr["ticker"]))
    check("신호 통과(A,B)만 남는다", set(tr["ticker"]) == {"A", "B"})
    check("pnlGross가 exit/entry-1로 정확히 계산된다",
          np.isclose(tr.loc[tr["ticker"] == "A", "pnlGross"].iloc[0], 0.03))
    check("cost가 정확히 차감된다",
          np.isclose(tr.loc[tr["ticker"] == "A", "pnlNet"].iloc[0],
                     0.03 - COST_BPS / 1e4))

    nxt_map = {"2026-01-05": "2026-01-06", "2026-01-06": "2026-01-07"}
    lut = pd.DataFrame({"date": ["2026-01-06", "2026-01-07"],
                        "regime": ["Risk-On", "Neutral"]})
    trw = attach_entry_date_and_regime(tr, nxt_map, lut)
    check("신호일(01-05)의 진입일은 다음 거래일(01-06)로 매핑된다",
          trw.loc[trw["ticker"] == "A", "entryDate"].iloc[0] == "2026-01-06")
    check("regime은 신호일이 아니라 진입일 기준으로 붙는다",
          trw.loc[trw["ticker"] == "A", "regime"].iloc[0] == "Risk-On")
    check("신호일 01-06의 진입일(01-07) regime도 정확히 붙는다",
          trw.loc[trw["ticker"] == "B", "regime"].iloc[0] == "Neutral")

    dps = daily_portfolio_series(trw, "pnlNet")
    check("신호일 그룹핑이 entryDate 기준(날짜별 동일가중)",
          len(dps) == trw["entryDate"].nunique())

    mdd = mdd_from_returns(pd.Series([0.01, -0.02, 0.03]))
    check("MDD는 0 이하 값", mdd is not None and mdd <= 0)

    # 감사(§2) 정렬 버그 회귀 방지: signalDate로 그룹핑해야 원본 daily_series()/
    # bench_daily()와 같은 날짜 라벨로 정렬된다(entryDate 그룹핑은 하루 어긋남).
    strat_by_signal = trw.groupby("signalDate")["pnlNet"].mean()
    check("audit용 strat 그룹핑은 signalDate 기준이라야 신호일수와 일치",
          len(strat_by_signal) == trw["signalDate"].nunique())
    check("entryDate 그룹핑과는 인덱스(날짜)가 실제로 다르다(정렬 오차 존재 증거)",
          set(strat_by_signal.index) != set(dps.index))

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
    print("가용 세션: %d, 범위 %s~%s" % (len(dates), dates[0], dates[-1]))

    nxt_map = next_trading_day_map()
    regime_lut = load_regime_lookup()

    trades = build_signal_trades(f)
    trades = attach_entry_date_and_regime(trades, nxt_map, regime_lut)
    n_no_regime = int(trades["regime"].isna().sum())

    lines = []
    lines.append("# CAND1(PMCRASH_REVERSAL) — regime-conditional 성과 (2026-08)\n\n")
    lines.append(
        "지시: regime 정의(2026-08-23 고정본)를 바꾸지 않고, CAND1의 기존 "
        "신호·체결 규칙(thr=%.2f, vthr=%.1f, entry=%s, exit=%s, cost=%dbp)을 "
        "바꾸지 않은 채 baseline과 Risk-On/Neutral/Risk-Off를 비교한다.\n\n"
        % (THR, VTHR, ENTRY_COL, EXIT_COL, COST_BPS))
    lines.append(
        "## 0. 데이터 가용 기간 확인\n\n"
        "`load_frame()` 산출: **%d세션, %s~%s**. Opening Fade와 동일한 제약 — "
        "regime 정의는 2016년부터 있지만 CAND1 신호(intraday_panel.parquet 기반)"
        "는 이 구간 밖에 없다. 2016-2018/2019-2021/2022-2024 구간별 안정성은 "
        "**표본 0으로 원리적으로 산출 불가**(계산 실수 아님) — §3은 가용 구간을 "
        "전/후반으로만 나눈다.\n\n"
        "PIT: 신호일 T(오후급락 관측일)가 아니라 **진입일(T+1, 익일 시가)**의 "
        "regime을 쓴다 — `entryDate`를 calendar.json으로 산출해 그 날짜의 "
        "`usableFromDate` regime에 조인.\n\n---\n\n"
        % (len(dates), dates[0], dates[-1]))

    lines.append("## 1. Regime-conditional 성과\n\n")
    buckets = [("전체(baseline)", trades)]
    for r in ("Risk-On", "Neutral", "Risk-Off"):
        buckets.append((r, trades[trades["regime"] == r]))

    rows = []
    for name, sub in buckets:
        s = trade_stats(sub)
        if s is None:
            rows.append({"구간": name})
            continue
        dpg = daily_portfolio_series(sub, "pnlGross")
        dpn = daily_portfolio_series(sub, "pnlNet")
        s["grossMeanBp"] = round(float(dpg.mean()) * 10000, 2) if len(dpg) else None
        s["netMeanBp"] = round(float(dpn.mean()) * 10000, 2) if len(dpn) else None
        s["mddPct"] = mdd_from_returns(dpn)
        s["구간"] = name
        rows.append(s)
    tdf = pd.DataFrame(rows).set_index("구간")
    lines.append("| 구간 | 거래수 | 종목수 | 신호일수 | 승률 | Profit Factor | "
                  "gross(bp) | net(bp) | MDD(%) |\n")
    lines.append("|---|---|---|---|---|---|---|---|---|\n")
    for name, row in tdf.iterrows():
        def fmt(v, f_):
            return "" if pd.isna(v) else f_(v)
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s |\n" % (
            name,
            fmt(row.get("trades"), lambda v: str(int(v))),
            fmt(row.get("tickers"), lambda v: str(int(v))),
            fmt(row.get("signalDays"), lambda v: str(int(v))),
            fmt(row.get("winRate"), lambda v: "%.1f%%" % (v * 100)),
            fmt(row.get("profitFactor"), lambda v: "%.2f" % v),
            fmt(row.get("grossMeanBp"), lambda v: "%.2f" % v),
            fmt(row.get("netMeanBp"), lambda v: "%.2f" % v),
            fmt(row.get("mddPct"), lambda v: "%.2f" % v),
        ))
    lines.append("\nregime 매칭 안 된 거래수(캘린더 밖 등): %d / %d\n\n"
                  % (n_no_regime, len(trades)))

    lines.append("## 2. 감사(audit) — 기존 보고값과 대조\n\n")
    lines.append(
        "`findings/intraday-final-report/report.md`가 인용한 값: TEST 구간(walk-"
        "forward) 20bps 비용 반영 후 **+0.369%/일(t=3.94)** — 이건 EW 벤치마크 "
        "대비 초과수익(excess)이지 raw net이 아니다. 같은 TEST 구간(마지막 25%)"
        "만 골라 동일하게 재현한다.\n\n")
    n = len(dates)
    te_dates = set(dates[int(n * 0.75):])
    te_trades = trades[trades["signalDate"].isin(te_dates)]
    if len(te_trades):
        # 원본 daily_series()/bench_daily()는 둘 다 신호일(signalDate=T)로
        # groupby한다 — entryDate(T+1)로 그룹핑하면 strat/bench 날짜 정렬이
        # 하루 어긋나 t통계가 무너진다(최초 구현에서 실측: t=1.41로 붕괴,
        # signalDate로 고친 뒤 재검증).
        strat_daily = te_trades.groupby("signalDate")["pnlNet"].mean()
        bench = f[f["date"].isin(te_dates)].copy()
        bench["ewRet"] = bench[EXIT_COL] / bench[ENTRY_COL] - 1.0
        bench_daily = bench.dropna(subset=["ewRet"]).groupby("date")["ewRet"].mean()
        j = pd.concat([strat_daily, bench_daily], axis=1, join="inner").dropna()
        j.columns = ["strat", "bench"]
        excess = j["strat"] - j["bench"]
        t = float(excess.mean() / (excess.std(ddof=1) / len(excess) ** 0.5)) if len(excess) > 1 else None
        lines.append("재현 결과: TEST %d일, meanExcess=**%.4f%%/일**, t=**%.2f** "
                      "(기존 보고 +0.369%%/일, t=3.94)\n\n"
                      % (len(excess), float(excess.mean()) * 100, t if t else float("nan")))
    else:
        lines.append("TEST 구간에 regime-매칭 거래 없음(재현 불가)\n\n")

    lines.append("## 3. 기간별 안정성 (가용 %d일 전/후반)\n\n" % len(dates))
    trades["half"] = trades["signalDate"].map(period_of)
    rows = []
    for name, _, _ in HALVES:
        sub = trades[trades["half"] == name]
        s = trade_stats(sub)
        if s is None:
            continue
        dpg = daily_portfolio_series(sub, "pnlGross")
        dpn = daily_portfolio_series(sub, "pnlNet")
        s["grossMeanBp"] = round(float(dpg.mean()) * 10000, 2) if len(dpg) else None
        s["netMeanBp"] = round(float(dpn.mean()) * 10000, 2) if len(dpn) else None
        s["구간"] = name
        rows.append(s)
    tdf = pd.DataFrame(rows).set_index("구간")
    lines.append("| 구간 | 거래수 | 종목수 | 승률 | Profit Factor | gross(bp) | net(bp) |\n")
    lines.append("|---|---|---|---|---|---|---|\n")
    for name, row in tdf.iterrows():
        lines.append("| %s | %d | %d | %.1f%% | %s | %.2f | %.2f |\n" % (
            name, row["trades"], row["tickers"], row["winRate"] * 100,
            "%.2f" % row["profitFactor"] if row["profitFactor"] else "N/A",
            row["grossMeanBp"], row["netMeanBp"]))

    lines.append(
        "\n## 검증 가능한 근거 목록\n\n"
        "- `run_strategy_validation.py` `load_frame()`/`sig_pmcrash()` — 신호·"
        "체결 규칙 원출처(무변경, import로 재사용)\n"
        "- `findings/cand1-regime-decomposition/study.md` — 동일 동결 파라미터"
        "(thr=0.02, vthr=1.5) 사용 전례\n"
        "- `findings/intraday-final-report/report.md` — cost=20bp, 감사 대상 "
        "+0.369%/일 원출처\n"
        "- `data/market-regime/regime_labels.parquet` — regime 원천(PIT: "
        "진입일 usableFromDate로 조인)\n"
        "- `data/backfill/calendar.json` — 신호일→진입일(다음 거래일) 산출\n"
        "- 본 스크립트 `analyze_cand1_regime_conditional.py` — 재실행하면 동일 결과\n")

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("wrote", OUT_MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
