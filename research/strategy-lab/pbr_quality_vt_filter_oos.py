#!/usr/bin/env python
"""Quality as PBR Value-Trap Filter OOS (2026-09-06).

실험 설계 (MD: Quality as PBR Value-Trap Filter OOS)
--------------------------------------------------
목적: Quality 가 독립 알파인지가 아니라, PBR 포트폴리오의 value trap 을
제거해 위험조정성과를 개선하는지 검증한다. 06(Quality Composite OOS) 결과를
참고하되 재최적화하지 않는다.

사전 고정 규칙 (성과 계산 전)
------------------------------
- PBR ranking: 기존 pbr_value_v1 과 동일 — valuation-panel pbr, 오름차순,
  Top-N=30 (policy factor.topN=30, 엔진 maxPositions=30, sector-neutral
  pbr-top30 finding 과 동일 N).
- 유니버스: liquid(dv20>=1e8) + pbr>0, 월별 스냅샷.
- QCOMP: 06 과 동일 정의 — 7개 팩터(roe·op_margin·net_margin·debt_ratio·current_ratio
  ·roe_consistency·op_margin_trend)를 각 팩터 자기 non-NaN 집합(전체 liquid
  유니버스 내)에서 pct-rank 후 방향 적용 동일가중 평균. retention 제외(06 과 동일).
- Quality 필터: 매달 PBR 적격 유니버스(liquid+pbr>0) 중 QCOMP 스코어가 있는
  종목의 하위 20%(최저 quintile) 제외. 스코어 없는 종목은 quintile 로 제외하지
  않는다(랭킹 불가). 그 뒤 PBR 오름차순 상위 30.
- "PBR score 에 Quality 를 더하지 않는다" — 스코어 합산 없음, 제외 필터로만 사용.
- 매개변수(멤버·가중·cutoff·N·유동성 게이트) 3구간 동일. TEST 보고 후 조건 변경 없음.

비교군 (Top-N 을 동일 N=30 으로 고정):
  A) PBR Top-30 baseline
  B) PBR Top-30 + Quality 하위 20% 제외

측정 (실측만 기록):
  - 월별 EW 포트폴리오 수익률(fwd1m) → CAGR / Sharpe / MDD / WinRate / N(월) / T-stat
  - turnover(월별 보유 종목 교체율) 로 비용 반영: 왕복비용 = turnover * 30bp
  - IC: PBR·QCOMP 각각의 월별 Spearman(factor, fwd1m)
  - what improves: 제외된 하위 QCOMP 종목의 fwd1m 평균을 나머지 적격집합과 비교
"""
import json
import math
import os

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
PANEL_PATH = os.path.join(LAB, "data", "factor-panel", "kr-monthly-v1.parquet")
MANIFEST_PATH = os.path.join(LAB, "data", "factor-panel", "_manifest_kr_monthly.json")

TOP_N = 30                     # pbr_value_v1 과 동일
QUALITY_CUTOFF_PCT = 0.20      # 하위 20% 제외 (설계에 명시된 고정값)
ROUNDTRIP_BPS = 30.0           # policy cost: entry 15bp + exit 15bp
QUALITY_MEMBERS = [("roe", 1.0), ("op_margin", 1.0), ("net_margin", 1.0),
                   ("debt_ratio", -1.0), ("current_ratio", 1.0),
                   ("roe_consistency", 1.0), ("op_margin_trend", 1.0)]


def qcomp_column(panel):
    """06 과 동일: 전체 liquid 유니버스 내에서 각 팩터 pct-rank 후 방향 적용 동일가중.
    월별 크로스섹션을 기준으로 랭킹한다."""
    sc = None
    members = {}
    for f, sign in QUALITY_MEMBERS:
        g = panel.groupby("date", group_keys=False)
        r = g[f].rank(pct=True) * sign
        members[f] = r
        sc = r if sc is None else sc + r
    return sc / len(QUALITY_MEMBERS)


def select_portfolio(panel_with_qsc, monthly, mode, top_n=TOP_N):
    """월별 PBR 상위 top_n EW 포트폴리오의 월별 fwd1m 시계열.
    mode: 'baseline' | 'filtered'. panel_with_qsc 는 'qcomp' 열을 가져야 함."""
    out = []
    for date, g in monthly:
        elig = g[g["pbr"] > 0].copy()
        if len(elig) < top_n:
            continue
        if mode == "filtered":
            # QCOMP 스코어 있는 종목의 하위 20% 제외 → 그 뒤 PBR 상위.
            # 스코어가 없는 종목은 랭킹 불가 → quintile 로 제외하지 않는다.
            scored = elig.dropna(subset=["qcomp"])
            if len(scored) == 0:
                continue
            cutoff = scored["qcomp"].quantile(QUALITY_CUTOFF_PCT)
            elig = elig[elig["qcomp"].isna() | (elig["qcomp"] > cutoff)]
        top = elig.sort_values("pbr", ascending=True).head(top_n)
        out.append((date, top, elig))
    return out


def monthly_series(selections, monthly_benchmark):
    """월별 EW 수익·벤치(적격집합 EW)·턴오버·IC."""
    rows = []
    prev_hold = None
    for date, top, elig in selections:
        holds = set(top["ticker"])
        r = float(top["fwd1m"].mean())
        bench = float(elig["fwd1m"].mean())
        if prev_hold is not None:
            turn = 1.0 - len(holds & prev_hold) / len(holds) if holds else 0.0
        else:
            turn = float("nan")
        prev_hold = holds
        rows.append({"date": date, "return": r, "bench": bench, "turnover": turn})
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["turnover"])
    return df


def stats(df, roundtrip_bps=ROUNDTRIP_BPS):
    net = df["return"] - (df["turnover"].fillna(0.0) * roundtrip_bps / 10000.0)
    excess = df["return"] - df["bench"]
    n = len(df)
    esd = float(excess.std(ddof=1))
    t = float(excess.mean() / (esd / math.sqrt(n))) if esd > 0 else 0.0
    sd = float(net.std(ddof=1))
    cum = float(np.prod(1.0 + net))
    span = n / 12.0
    cagr = cum ** (1.0 / span) - 1.0 if cum > 0 else float("nan")
    sharpe = float(net.mean() / sd * math.sqrt(12)) if sd > 0 else 0.0
    peak, cc, mdd = 1.0, 1.0, 0.0
    for r_ in net:
        cc *= (1.0 + r_)
        peak = max(peak, cc)
        mdd = min(mdd, cc / peak - 1.0)
    years = np.array([d[:4] for d in df["date"]])
    tot = float(excess.sum())
    max_year = None
    if tot > 0:
        by = {y: float(excess[years == y].sum()) for y in np.unique(years)}
        max_year = round(100.0 * max(by.values()) / tot, 1)
    return {
        "nMonths": n, "cagr": round(cagr * 100, 2), "sharpe": round(sharpe, 3),
        "mdd": round(mdd * 100, 1), "winRate": round(float((net > 0).mean()) * 100, 1),
        "excessT": round(t, 3), "meanExcessPct": round(float(excess.mean()) * 100, 3),
        "turnover": round(float(df["turnover"].mean()), 3),
        "avgHeld": TOP_N,
        "maxSingleYearPct": max_year,
    }


def monthly_ic(selections, factor_fields):
    """월별 Spearman(factor, fwd1m) — factor 별로 적격집합(elig)에서 계산."""
    res = {f: {"ics": [], "dates": []} for f in factor_fields}
    for date, top, elig in selections:
        for f in factor_fields:
            s = elig[["fwd1m", f]].dropna()
            if len(s) >= 5:
                res[f]["ics"].append(float(s[f].corr(s["fwd1m"], method="spearman")))
                res[f]["dates"].append(date)
    out = {}
    for f in factor_fields:
        ics = np.array(res[f]["ics"])
        ics = ics[np.isfinite(ics)]
        t = float(ics.mean() / (ics.std(ddof=1) / math.sqrt(len(ics)))) if len(ics) > 1 else 0.0
        out[f] = {"meanIC": round(float(ics.mean()), 4), "t": round(t, 3),
                  "nMonths": len(ics)}
    return out


def main():
    manifest = json.load(open(MANIFEST_PATH, encoding="utf-8"))
    panel = pd.read_parquet(PANEL_PATH)
    panel = panel[panel["liquid"]].copy()
    panel = panel.assign(qcomp=qcomp_column(panel))
    missing_members = [f for f, _ in QUALITY_MEMBERS if f not in panel.columns]
    if missing_members:
        raise SystemExit(f"패널에 팩터 누락: {missing_members}")
    names = len(panel[panel["pbr"] > 0]["ticker"].unique())
    print(f"패널 {len(panel):,}행 liquid, {manifest['panelVersion']}, TopN={TOP_N}, "
          f"PBR적격종목 {names:,}", flush=True)

    out = {"experiment": "PBR-QUALITY-VALUETRAP-FILTER-OOS-KR",
           "panelVersion": manifest["panelVersion"], "date": "2026-09-06",
           "preSpecified": "PBR TopN=30(pbr_value_v1 고정) · Quality cutoff=하위20% · "
                           "QCOMP 7종 동일가중(06과 동일) · liquid+pbr>0 · 3구간 매개변수 동일. "
                           "성과 보고 후 조건 변경 안 함.",
           "rows": {}}

    for period in ["TRAIN", "VALID", "TEST"]:
        sub = panel[panel["period"] == period]
        monthly = list(sub.groupby("date"))
        sel_b = select_portfolio(panel, monthly, "baseline")
        sel_f = select_portfolio(panel, monthly, "filtered")
        # 두 모드가 같은 달을 공유하도록 교집합 보정은 하지 않는다 — 매달 M>=30 인
        # 달만 두 모드 공통으로 줬기 때문에 날짜가 거의 같다. 공통 달만으로 맞춘다.
        dates_b = {d for d, _, _ in sel_b}
        dates_f = {d for d, _, _ in sel_f}
        common = sorted(dates_b & dates_f)
        sel_b = [(d, t, e) for d, t, e in sel_b if d in common]
        sel_f = [(d, t, e) for d, t, e in sel_f if d in common]

        mb = monthly_series(sel_b, None)
        mf = monthly_series(sel_f, None)
        sb = stats(mb)
        sf = stats(mf)

        icb = monthly_ic(sel_b, ["pbr"])
        # QCOMP IC 는 baseline 적격집합을 기준으로 (filter 가 무엇을 차단하는지)
        icf = monthly_ic(sel_f, ["qcomp"])
        ic_filtered_pbr = monthly_ic(sel_f, ["pbr"])

        # value trap 진단: baseline 적격집합에서 제외 대상(하위 20% QCOMP) vs 나머지
        ex_l = []
        rest_l = []
        for d, top, elig in sel_b:
            scored = elig.dropna(subset=["qcomp"])
            if len(scored) < 10:
                continue
            cutoff = scored["qcomp"].quantile(QUALITY_CUTOFF_PCT)
            ex = scored[scored["qcomp"] <= cutoff]
            rest = scored[scored["qcomp"] > cutoff]
            ex_l.append(float(ex["fwd1m"].mean()))
            rest_l.append(float(rest["fwd1m"].mean()))
        ex_l, rest_l = np.array(ex_l), np.array(rest_l)
        vt = None
        if len(ex_l) > 1 and len(rest_l) > 1:
            diff = ex_l - rest_l
            tdiff = float(diff.mean() / (diff.std(ddof=1) / math.sqrt(len(diff)))) if diff.std(ddof=1) > 0 else 0.0
            vt = {
                "excludedMeanFwdPct": round(float(ex_l.mean()) * 100, 3),
                "restMeanFwdPct": round(float(rest_l.mean()) * 100, 3),
                "spreadExclMinusRestPct": round(float(diff.mean()) * 100, 3),
                "spreadT": round(tdiff, 3),
                "nMonths": len(ex_l),
            }
        print(f"\n--- {period} ---")
        print(f"baseline: {json.dumps(sb)}")
        print(f"filtered: {json.dumps(sf)}")
        print("IC baseline적격: pbr", icb["pbr"])
        print("IC filtered적격: pbr", ic_filtered_pbr["pbr"], "| qcomp", icf["qcomp"])
        print("vt진단:", json.dumps(vt))
        out["rows"][period] = {"baseline": sb, "filtered": sf,
                               "ic_baseline": icb, "ic_filtered": icf,
                               "ic_filtered_pbr": ic_filtered_pbr,
                               "vtDiagnostic": vt}

    out_path = os.path.join(LAB, "reports", "2026-09-06-pbr-quality-vt-filter",
                            "pbr-quality-vt-filter-oos.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {out_path}")


if __name__ == "__main__":
    main()