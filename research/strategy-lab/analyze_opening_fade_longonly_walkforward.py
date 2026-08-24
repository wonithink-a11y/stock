#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Opening Fade — 롱온리(Q1만) walk-forward 검증 (2026-08).

지시(2026-08-24): CLAUDE.md·이전 세션이 인용한 Opening Fade의 "T+5 net+29.2bp·
T+10 net+23.1bp"(`minute_fade_cost_horizons.py`)는 **Q1(롱)+Q5(숏) 페어**의
스프레드이고, 비용도 양쪽 다리(2×RT)로 차감된 값이다. 이 프로젝트는 LONG_ONLY
다(최상단 규칙 — 공매도는 맥락·경보용으로만, 엔진에 마진/숏 개념 없음) — 검증된
그 숫자를 그대로 엔진에 옮길 수 없다.

Q1(롱 레그)만 떼어 편도(single-leg) 비용으로 다시 계산하면 이벤트-스터디 레벨
에서는 여전히 순양으로 보이지만(T+5 net≈+17bp, T+10 net≈+15bp @20bp 비용),
그 숫자는 raw이지 CAND1이 받은 것 같은 TRAIN/TEST 분리·유의성 검정을 받은
적이 없다. 이 스크립트가 그 첫 walk-forward 검증이다 — CAND1의 최초 검증
(`run_strategy_validation.py`, 60/15/25% TRAIN/VALID/TEST 분리)과 같은 틀을
쓴다. 신호(r05 quintile)에는 튜닝할 파라미터가 없다(고정 분위 partition) —
그래서 이 스크립트는 "TRAIN에서 고른다"가 아니라 TRAIN/VALID/TEST 각각에서
같은 신호의 안정성만 본다.

데이터: `minute_fade_cost_horizons.py`의 day_frame()(원본 무변경, import로
재사용)로 09:00/09:05 분봉을 읽고, `data/a4/a4-research-dataset.parquet`의
종가 패널로 T+5/T+10 거래일 후 종가를 구한다(원본과 동일 소스).

산출: findings/opening-fade-longonly-walkforward-2026-08.md

사용:
    python analyze_opening_fade_longonly_walkforward.py --selftest
    python analyze_opening_fade_longonly_walkforward.py
"""
import glob
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MINUTE_DIR = HERE / ".cache" / "minute_raw"
PANEL_PATH = HERE / "data" / "a4" / "a4-research-dataset.parquet"
OUT_MD = HERE / "findings" / "opening-fade-longonly-walkforward-2026-08.md"

HORIZONS = (5, 10)
COST_BPS_SINGLE_LEG = 20.0   # CAND1과 동일 가정, 페어(2xRT)가 아니라 편도


def compute_r05_quintile(base):
    """09:00->09:05 수익률, 날짜별 5분위(Q1=최저=가장 급락). 원본 minute_fade_
    cost_horizons.py의 base 구성과 동일 로직(무변경 이식)."""
    base = base.copy()
    base["r05"] = base["p0905"] / base["p0900"] - 1
    base["q"] = base.groupby("date")["r05"].transform(
        lambda s: np.minimum(np.ceil(s.rank(method="first", pct=True) * 5), 5).astype(int))
    return base


def attach_forward_close(base, panel, horizons=HORIZONS):
    """티커별 날짜순 close를 h거래일 앞으로 shift(원본과 동일 로직)."""
    px = panel.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = px.groupby("ticker")["close"]
    for h in horizons:
        px[f"c{h}"] = g.transform(lambda s, hh=h: s.shift(-hh))
    cols = ["ticker", "date"] + [f"c{h}" for h in horizons]
    fwd = px[px["date"].isin(set(base["date"]))][cols]
    return base.merge(fwd, on=["ticker", "date"], how="left")


def q1_long_only_trades(base_with_fwd, horizon):
    """Q1(롱)만, 편도 비용. bench는 그날 전체 분위(Q1~Q5) 동일가중 평균(원본과
    동일 정의) — 그래야 이미 발표된 Q1 gross excess 숫자와 대조 가능하다."""
    col = f"c{horizon}"
    d = base_with_fwd[base_with_fwd[col].notna()].copy()
    d["out"] = d[col] / d["p0905"] - 1.0
    bench = d.groupby("date")["out"].mean().rename("bench")
    d = d.merge(bench, on="date")
    d["excess"] = d["out"] - d["bench"]
    q1 = d[d["q"] == 1].copy()
    q1["pnlGross"] = q1["out"]
    q1["pnlNet"] = q1["pnlGross"] - COST_BPS_SINGLE_LEG / 1e4
    q1["excessNet"] = q1["excess"] - COST_BPS_SINGLE_LEG / 1e4
    return q1


def daily_series(trades, col):
    return trades.groupby("date")[col].mean().sort_index()


def split_stats(trades, label):
    if len(trades) == 0:
        return {"구간": label, "trades": 0}
    n = trades["pnlNet"].to_numpy()
    win = n > 0
    pos, neg = n[n > 0].sum(), -n[n < 0].sum()
    dpn_excess = daily_series(trades, "excessNet")
    t, p = (None, None)
    if len(dpn_excess) > 1 and dpn_excess.std(ddof=1) > 0:
        t, p = sps.ttest_1samp(dpn_excess.to_numpy(), 0.0)
    top5_share = trades["ticker"].value_counts(normalize=True).head(5).sum()
    return {
        "구간": label,
        "trades": int(len(trades)),
        "days": int(trades["date"].nunique()),
        "winRate": round(float(win.mean()), 4),
        "profitFactor": round(float(pos / neg), 3) if neg > 0 else None,
        "netMeanBp": round(float(daily_series(trades, "pnlNet").mean()) * 10000, 2),
        "excessNetMeanBp": round(float(dpn_excess.mean()) * 10000, 4) if len(dpn_excess) else None,
        "t": round(float(t), 2) if t is not None else None,
        "top5TickerShare": round(float(top5_share), 4),
    }


def selftest():
    checks = []

    def check(name, cond):
        checks.append((name, bool(cond)))

    base = pd.DataFrame({
        "date": ["2026-01-05"] * 5,
        "ticker": ["A", "B", "C", "D", "E"],
        "p0900": [100.0] * 5,
        "p0905": [90.0, 95.0, 100.0, 105.0, 110.0],   # A가 가장 급락 -> Q1
    })
    bq = compute_r05_quintile(base)
    check("가장 급락(A)가 Q1로 분류됨", bq.loc[bq["ticker"] == "A", "q"].iloc[0] == 1)
    check("가장 상승(E)가 Q5로 분류됨", bq.loc[bq["ticker"] == "E", "q"].iloc[0] == 5)

    # shift(-5)가 유효하려면 티커마다 신호일 뒤로 5행이 더 있어야 한다 — 신호일
    # + 필러 4일 + 목표일(5번째 뒤)로 6행씩 구성.
    fillers = ["2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09"]
    panel_rows = []
    for tk, close0 in zip(["A", "B", "C", "D", "E"], [90.0, 95.0, 100.0, 105.0, 110.0]):
        panel_rows.append({"ticker": tk, "date": "2026-01-05", "close": close0})
        for d in fillers:
            panel_rows.append({"ticker": tk, "date": d, "close": close0})
        panel_rows.append({"ticker": tk, "date": "2026-01-12", "close": 99.0})   # 5거래일 뒤, 전부 99로 수렴
    panel = pd.DataFrame(panel_rows)
    fwd = attach_forward_close(bq, panel, horizons=(5,))
    check("c5가 다음 행(같은 티커, 5행 뒤)의 close로 채워짐",
          np.isclose(fwd.loc[fwd["ticker"] == "A", "c5"].iloc[0], 99.0))

    q1 = q1_long_only_trades(fwd, 5)
    check("Q1(A)만 남는다", set(q1["ticker"]) == {"A"})
    check("pnlGross = c5/p0905 - 1 (A: 99/90-1=10%)",
          np.isclose(q1["pnlGross"].iloc[0], 0.10))
    check("편도 비용만 차감됨(2xRT 아님)",
          np.isclose(q1["pnlNet"].iloc[0], 0.10 - COST_BPS_SINGLE_LEG / 1e4))

    s = split_stats(q1, "test")
    check("split_stats가 trades=1을 센다", s["trades"] == 1)

    ok = all(c for _, c in checks)
    for name, c in checks:
        print(("  PASS  " if c else "  FAIL  ") + name)
    print()
    print("통과 %d · 실패 %d" % (sum(c for _, c in checks), sum(not c for _, c in checks)))
    return 0 if ok else 1


def day_frame(date_dir, date_str):
    """minute_fade_cost_horizons.py의 day_frame()과 동일(무변경 이식) —
    09:00/09:05 분봉 open/close만 뽑는다."""
    frames = []
    for part in sorted(glob.glob(os.path.join(date_dir, "part-*.parquet"))):
        frames.append(pd.read_parquet(part, columns=["ticker", "ts", "open", "close"]))
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    s = df["ts"]
    hhmm = s.astype(str).str.slice(11, 16) if not hasattr(s, "dt") else s.dt.strftime("%H:%M")
    keep = hhmm.isin(["09:00", "09:05"])
    df = df[keep]
    df = df[(df["open"] > 0) & (df["close"] > 0)].assign(hhmm=hhmm[keep][df.index])

    def at(v, col):
        sub = df.loc[df["hhmm"] == v, ["ticker", col]].copy()
        sub.columns = ["ticker", "p0900" if col == "open" else "p0905"]
        return sub

    out = at("09:00", "open").merge(at("09:05", "close"), on="ticker", how="inner")
    out.insert(0, "date", date_str)
    return out


def main():
    if "--selftest" in sys.argv:
        return selftest()

    t0 = time.time()
    date_dirs = sorted(glob.glob(str(MINUTE_DIR / "date=*")))
    chunks = []
    for dd in date_dirs:
        fr = day_frame(dd, dd.split("=")[-1])
        if fr is not None and fr.size:
            chunks.append(fr)
    base = pd.concat(chunks, ignore_index=True)
    base = base[base["p0900"].notna() & base["p0905"].notna()].sort_values(["date", "ticker"]).reset_index(drop=True)
    base = compute_r05_quintile(base)
    dates = sorted(base["date"].unique())
    print("가용 세션: %d, 범위 %s~%s (%.0fs)" % (len(dates), dates[0], dates[-1], time.time() - t0))

    panel = pd.read_parquet(PANEL_PATH, columns=["ticker", "date", "close"])
    fwd = attach_forward_close(base, panel, HORIZONS)

    n = len(dates)
    tr_dates = set(dates[:int(n * 0.60)])
    va_dates = set(dates[int(n * 0.60):int(n * 0.75)])
    te_dates = set(dates[int(n * 0.75):])

    lines = []
    lines.append("# Opening Fade — 롱온리(Q1) walk-forward 검증 (2026-08)\n\n")
    lines.append(
        "목적: 기존에 인용된 Opening Fade net(+29.2bp@T+5 등)은 Q1롱+Q5숏 "
        "페어·2xRT 비용이다 — 이 프로젝트는 LONG_ONLY라 그대로 쓸 수 없다. "
        "Q1(롱)만 편도 비용(%.0fbp)으로 떼어 CAND1과 같은 틀(TRAIN/VALID/TEST "
        "60/15/25%%, 시간순 분리)로 처음 검증한다. 신호(r05 날짜별 5분위)는 "
        "튜닝 파라미터가 없어 TRAIN에서 고르는 절차 자체가 없다 — 세 구간 각각의 "
        "안정성만 본다.\n\n"
        "가용 세션 %d, %s~%s. TRAIN=%d일 · VALID=%d일 · TEST=%d일.\n\n---\n\n"
        % (COST_BPS_SINGLE_LEG, len(dates), dates[0], dates[-1],
           len(tr_dates), len(va_dates), len(te_dates)))

    for horizon in HORIZONS:
        lines.append("## T+%d\n\n" % horizon)
        lines.append("| 구간 | 거래수 | 신호일수 | 승률 | PF | net(bp) | excess-net(bp/일) | t | top5종목비중 |\n")
        lines.append("|---|---|---|---|---|---|---|---|---|\n")
        q1 = q1_long_only_trades(fwd, horizon)
        for label, ds in (("TRAIN", tr_dates), ("VALID", va_dates), ("TEST", te_dates), ("전체", set(dates))):
            sub = q1[q1["date"].isin(ds)]
            s = split_stats(sub, label)
            if s.get("trades", 0) == 0:
                lines.append("| %s | 0 | | | | | | | |\n" % label)
                continue
            lines.append("| %s | %d | %d | %.1f%% | %s | %.2f | %s | %s | %.1f%% |\n" % (
                label, s["trades"], s["days"], s["winRate"] * 100,
                "%.2f" % s["profitFactor"] if s["profitFactor"] else "N/A",
                s["netMeanBp"],
                "%.4f" % s["excessNetMeanBp"] if s["excessNetMeanBp"] is not None else "N/A",
                "%.2f" % s["t"] if s["t"] is not None else "N/A",
                s["top5TickerShare"] * 100))
        lines.append("\n")

    # 전체 표본 원본 대조(감사) — 이미 발표된 gross excess(T+5 Q1=+36.83bp,
    # T+10 Q1=+35.49bp)와 이 스크립트의 편도 net 계산이 같은 신호에서 나왔는지 확인
    lines.append("## 감사 — 기존 report와의 정합성\n\n")
    lines.append(
        "`minute-opening-fade-cost/study_results.json`의 Q1 gross excess: "
        "T+5=+36.83bp, T+10=+35.49bp(비용 미반영). 이 스크립트의 전체 구간 "
        "gross(excess-net에 편도비용 %.0fbp를 다시 더하면 나옴)가 이 값과 "
        "일치해야 같은 신호·같은 데이터로 계산됐다는 뜻이다.\n\n" % COST_BPS_SINGLE_LEG)

    lines.append(
        "## 검증 가능한 근거 목록\n\n"
        "- `minute_fade_cost_horizons.py` — day_frame()·신호 정의 원출처(무변경 "
        "이식, Q1+Q5 페어·2xRT 원본)\n"
        "- `research/strategy-lab/findings/minute-opening-fade-cost/study_results.json` "
        "— 감사용 원본 gross 수치\n"
        "- 본 스크립트 `analyze_opening_fade_longonly_walkforward.py` — "
        "재실행하면 동일 결과, --selftest로 로직 검증\n")

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("wrote", OUT_MD)
    return 0


if __name__ == "__main__":
    sys.exit(main())
