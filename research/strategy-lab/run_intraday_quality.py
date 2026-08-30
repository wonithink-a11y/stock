#!/usr/bin/env python
"""Research-scope data-quality verification over the intraday panel.

The full 159M-row raw audit exists (findings/minute-data-quality-2026-08.md,
critical defects 0). This script re-verifies integrity ON THE RESEARCH SAMPLE
(the Stage-A panel/grid caches every downstream study will actually use) and
adds research-specific checks the raw audit did not cover:

  R1  duplicate ticker-day rows in panel
  R2  non-positive prices (open/day_close/w_high/w_low/p_at30m)
  R3  inverted ranges (w_high<w_low, day_high<day_low)
  R4  open/close outside [low,high] of their own window
  R5  return beyond KRX +/-30% limit (r30, day_ret_oc, overnight gap) ->
      corporate-action / axis-mismatch suspects on the adjusted axis
  R6  session coverage: late start, early end, thin bars, halt-like days
  R7  OPEN30 research eligibility rate (n_bars_30>=20 & prices valid)
  R8  relative-volume outliers (>50x trailing baseline)
  R9  lunchtime bucket presence profile from the 5m grid (known liquidity
      hole must be visible so slot studies can handle it)
  R10 market/sector join coverage

Writes findings/intraday-quality-research/{study_results.json,study.md}.
Read-only over .cache/*.parquet and minute_raw.
"""
import glob
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from intraday import loader, session  # noqa: E402

SLAB = os.path.join(loader.REPO_ROOT, "research", "strategy-lab")
PANEL_PATH = os.path.join(SLAB, ".cache", "intraday_panel.parquet")
GRID_PATH = os.path.join(SLAB, ".cache", "intraday_grid5m.parquet")
OUT_DIR = os.path.join(SLAB, "findings", "intraday-quality-research")

LIMIT = 0.30          # KRS daily price limit (+/-30%) on one price axis
ELIG_MIN_BARS_30 = 20


def main():
    t0 = time.time()
    panel = pd.read_parquet(PANEL_PATH)
    res = {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "panelRows": int(len(panel)), "panelDates": int(panel["date"].nunique()),
           "checks": {}}
    C = res["checks"]

    # R1 duplicates
    dup = panel.duplicated(subset=["date", "ticker"]).sum()
    C["R1_duplicateTickerDays"] = int(dup)

    # R2 non-positive prices
    price_cols = ["open_price", "day_close", "day_open", "w_high", "w_low", "p_at30m"]
    bad = {}
    for c in price_cols:
        bad[c] = int((panel[c] <= 0).sum())
    C["R2_nonPositivePrices"] = bad

    # R3 inverted ranges
    inv_w = int((panel["w_high"] < panel["w_low"]).sum())
    inv_d = int((panel["day_high"] < panel["day_low"]).sum())
    C["R3_invertedRange"] = {"open30": inv_w, "day": inv_d}

    # R4 open/close outside own window range
    o_out = ((panel["open_price"] > panel["w_high"]) |
             (panel["open_price"] < panel["w_low"]))
    c_out = ((panel["p_at30m"] > panel["w_high"]) |
             (panel["p_at30m"] < panel["w_low"]))
    d_out = ((panel["day_open"] > panel["day_high"]) |
             (panel["day_close"] > panel["day_high"]) |
             (panel["day_open"] < panel["day_low"]) |
             (panel["day_close"] < panel["day_low"]))
    C["R4_priceOutsideWindow"] = {
        "openOutsideOpen30": int(o_out.sum()),
        "p30OutsideOpen30": int(c_out.sum()),
        "dayOpenCloseOutsideDayRange": int(d_out.sum()),
        "note": "09:00~09:05 opening-auction prints can sit outside the "
                "continuous bar H/L (raw audit MEDIUM item 2, 69 rows)",
    }

    # R5 returns beyond the daily limit -> corp-action/axis suspects
    r30_bad = panel["r30"].abs() > LIMIT
    oc_bad = panel["day_ret_oc"].abs() > LIMIT * 1.05
    panel_sorted = panel.sort_values(["ticker", "date"])
    prev_close = panel_sorted.groupby("ticker")["day_close"].shift(1)
    prev_date = panel_sorted.groupby("ticker")["date"].shift(1)
    cur_open = panel_sorted["day_open"]
    same_next = prev_date == panel_sorted["date"]
    with np.errstate(all="ignore"):
        gap = cur_open / prev_close - 1
    gap = gap.where(same_next)
    ov_bad = gap.abs() > LIMIT * 1.05
    C["R5_limitBreachOrCorpActionSuspects"] = {
        "r30_beyond_30pct": int(r30_bad.sum()),
        "oc_beyond_30pct": int(oc_bad.sum()),
        "overnightGap_beyond_30pct": int(ov_bad.sum()),
    }
    # top-10 worst gaps listed explicitly (deterministic order)
    idx = gap.abs().sort_values(ascending=False).head(10).index
    C["R5_limitBreachOrCorpActionSuspects"]["top10WorstOvernightGaps"] = [
        {"ticker": panel_sorted.loc[i, "ticker"], "date": panel_sorted.loc[i, "date"],
         "prevCloseDate": prev_date.loc[i], "gap": round(float(gap.loc[i]), 4)}
        for i in idx if np.isfinite(gap.loc[i])
    ]
    # r30 offenders detail (first 10)
    off = panel.loc[r30_bad, ["ticker", "date", "open_price", "p_at30m", "r30"]]
    C["R5_limitBreachOrCorpActionSuspects"]["r30OffendersSample"] = [
        {"ticker": rr.ticker, "date": rr.date, "r30": round(float(rr.r30), 4)}
        for rr in off.head(10).itertuples(index=False)
    ]

    # R6 session coverage
    C["R6_sessionCoverage"] = {
        "lateStart_firstBar_after_0910_pct": round(
            float((panel["first_bar"] > 910).mean()), 5),
        "earlyEnd_lastBar_before_1520_pct": round(
            float((panel["last_bar"] < 1520).mean()), 5),
        "thinDays_nBars_lt_50_pct": round(
            float((panel["n_bars_day"] < 50).mean()), 5),
        "haltLikeDays_nBars_le_5": int((panel["n_bars_day"] <= 5).sum()),
        "medianBarsPerTickerDay": float(panel["n_bars_day"].median()),
    }

    # R7 OPEN30 eligibility (incl. price FRESHNESS: last formation trade
    # at/after 09:25 so p_at30m is not a stale print from early morning)
    elig = ((panel["n_bars_30"] >= ELIG_MIN_BARS_30) &
            (panel["open_price"] > 0) & (panel["p_at30m"] > 0) &
            (panel["w_high"] >= panel["w_low"]) &
            (panel["last_bar_30"] >= 925))
    C["R7_open30Eligibility"] = {
        "minBarsInWindow": ELIG_MIN_BARS_30,
        "freshnessMinLastBar": 925,
        "eligibleRows": int(elig.sum()),
        "eligibleRate": round(float(elig.mean()), 4),
        "excludedRows": int((~elig).sum()),
    }

    # R8 relative-volume outliers
    rv = panel["rel_w_amt"]
    outl = (rv > 50).sum()
    C["R8_relVolumeOutliers"] = {
        "gt50x_baseline": int(outl),
        "gt50x_sample": [
            {"ticker": rr.ticker, "date": rr.date, "relVol": round(float(rr.relVol), 1)}
            for rr in panel.loc[rv > 50, ["ticker", "date", "rel_w_amt"]]
            .rename(columns={"rel_w_amt": "relVol"}).head(8).itertuples(index=False)
        ],
        "finiteRelVolShare": round(float(np.isfinite(rv.fillna(np.nan)).mean()), 4),
    }

    # R9 lunchtime hole profile from grid bucket volumes
    vcols = [f"v{m:04d}" for m in session.GRID_MARKS]
    gv = pd.read_parquet(GRID_PATH, columns=["date"] + vcols)
    presence = gv[vcols].notna().mean().to_numpy()
    weak = [(int(session.GRID_MARKS[k]), round(float(presence[k]), 3))
            for k in range(len(presence)) if presence[k] < 0.75]
    C["R9_gridBucketPresence"] = {
        "bucketsBelow75pctPresence": weak,
        "minPresenceBucket": int(session.GRID_MARKS[int(np.argmin(presence))]),
        "minPresence": round(float(np.min(presence)), 3),
        "note": "expected structural liquidity hole around 1204-1227 "
                "(raw audit INFO item 4b); not a defect",
    }

    # R10 universe join coverage
    unk_mkt = panel["market"].isna().mean()
    C["R10_universeJoin"] = {
        "marketUnknownPct": round(float(unk_mkt), 5),
        "sectorUnknownPct": round(float(panel["sector"].isna().mean()), 5),
        "markets": {str(k): int(v) for k, v in
                    panel["market"].value_counts(dropna=False).items()},
    }

    # Verdict: rows unusable for ANY research (hard integrity failures)
    hard_bad = (panel[price_cols] <= 0).any(axis=1) | \
        (panel["w_high"] < panel["w_low"]) | r30_bad | oc_bad
    res["verdict"] = {
        "hardIntegrityFailures": int(hard_bad.sum()),
        "failureRate": round(float(hard_bad.mean()), 6),
        "conclusion": ("no critical defects; research proceeds with eligibility "
                       "filter R7" if int(hard_bad.sum()) == 0 else
                       "flagged rows must be excluded by studies"),
        "runtimeSec": round(time.time() - t0, 1),
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "study_results.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)

    # markdown summary
    md = []
    md.append("# 연구범위 분봉 품질 검증 (research-scope)\n")
    md.append(f"- 대상: Stage-A 패널 {res['panelRows']:,} ticker-days / "
              f"{res['panelDates']}일 (원본 전량 감사는 "
              f"findings/minute-data-quality-2026-08.md, 치명 결함 0)")
    md.append(f"- 실행: {res['generatedAt']} ({res['verdict']['runtimeSec']}s)\n")
    md.append("| 검사 | 결과 |")
    md.append("|---|---|")
    md.append(f"| R1 중복 ticker-day | {C['R1_duplicateTickerDays']}건 |")
    r2tot = sum(C["R2_nonPositivePrices"].values())
    md.append(f"| R2 가격<=0 | {r2tot}건 |")
    md.append(f"| R3 high<low | OPEN30 {inv_w} / 일 {inv_d} |")
    md.append(f"| R4 창 범위 밖 가격 | open {C['R4_priceOutsideWindow']['openOutsideOpen30']} / "
              f"p30 {C['R4_priceOutsideWindow']['p30OutsideOpen30']} / "
              f"일 {C['R4_priceOutsideWindow']['dayOpenCloseOutsideDayRange']} |")
    r5 = C["R5_limitBreachOrCorpActionSuspects"]
    md.append(f"| R5 제한폭 초과/기업행위 의심 | r30 {r5['r30_beyond_30pct']} / "
              f"OC {r5['oc_beyond_30pct']} / 갭 {r5['overnightGap_beyond_30pct']} |")
    md.append(f"| R6 세션 커버리지 | 지각시작 {C['R6_sessionCoverage']['lateStart_firstBar_after_0910_pct']*100:.2f}% / "
              f"조기종료 {C['R6_sessionCoverage']['earlyEnd_lastBar_before_1520_pct']*100:.2f}% / "
              f"박스 {C['R6_sessionCoverage']['thinDays_nBars_lt_50_pct']*100:.2f}% / "
              f"정지의심 {C['R6_sessionCoverage']['haltLikeDays_nBars_le_5']} |")
    md.append(f"| R7 OPEN30 연구 가용 | {C['R7_open30Eligibility']['eligibleRows']:,}행 "
              f"({C['R7_open30Eligibility']['eligibleRate']*100:.1f}%) |")
    md.append(f"| R8 상대거래량 이상치(>50x) | {C['R8_relVolumeOutliers']['gt50x_baseline']}건 |")
    md.append(f"| R9 점심 공동(최저 존재율) | {C['R9_gridBucketPresence']['minPresenceBucket']}슬롯 "
              f"{C['R9_gridBucketPresence']['minPresence']*100:.0f}% (구조적, 결함 아님) |")
    md.append(f"| R10 유니버스 조인 | market 미상 {C['R10_universeJoin']['marketUnknownPct']*100:.3f}% |\n")
    md.append(f"**판정**: {res['verdict']['conclusion']} "
              f"(하드 무결성 실패 {res['verdict']['hardIntegrityFailures']}건, "
              f"{res['verdict']['failureRate']*100:.4f}%)\n")
    if r5["top10WorstOvernightGaps"]:
        md.append("최악 오버나잇 갭 TOP10 (기업행위 축 점검용):\n")
        md.append("| ticker | date | 직전종가일 | 갭 |")
        md.append("|---|---|---|---:|")
        for x in r5["top10WorstOvernightGaps"]:
            md.append(f"| {x['ticker']} | {x['date']} | {x['prevCloseDate']} | {x['gap']*100:+.1f}% |")
    with open(os.path.join(OUT_DIR, "study.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md))
    print(json.dumps(res["checks"], ensure_ascii=False)[:2000])
    print("VERDICT:", json.dumps(res["verdict"], ensure_ascii=False))
    print("saved:", OUT_DIR)


if __name__ == "__main__":
    main()
