#!/usr/bin/env python
"""성장주 스크리닝(자산·매출·영업이익 3년증가율 TOP20 교집합 + 부채비율 필터)
전면 백테스트 - 사용자 원본 스펙 §1~15(growth_screen_opencode_brief.md 참고).
OpenCode 위임이 인프라 타임아웃으로 실패해 Claude가 직접 구현(2026-08-28).

확정된 정책(사용자 승인):
  - growth_3y 계산 시 base(t-3)<=0이면 계산불가로 순위 제외
  - revenue/opProfit 절대값이 4e14원(400조, 삼성전자 실측보다 여유)을 넘으면
    이상치로 제외(032680/FY2022, 039230/FY2021 등 A3 파싱 버그 발견됨)

유니버스 방법론(§4 - 스펙이 "모호하면 임의결정 말고 보고"라 명시, 여기 보고):
  A1b(상장폐지)에 listedAt이 없고 exitAt도 대부분 null이라, "정확한 상장~
  폐지 구간"을 재구성할 근거 데이터가 없다. 대신 **가격 데이터 존재 여부
  자체를 투자가능성 proxy로 쓴다** - A2a(상장)+A2b(폐지) 가격이 asOf 근방
  ±10거래일 안에 있으면 그 시점에 거래 가능했다고 본다. A2b 커버리지가
  이미 알려진 대로 불완전(GATE-EP-1 조사, ~19% 결측)하므로 이 방식은
  survivorship bias를 완전히 제거하지 못하고 일부 남긴다 - 결과 보고 시
  이 한계를 명시한다.

리밸런싱(§5): 사업연도 재무제표 법정공시기한(3월말)에서 3개월 여유를 둔
매년 6/25를 기본 as_of로 쓴다(사용자 스펙 §2 예시와 같은 날짜) - 이 프로젝트
PIT 인프라(pitSelector.js 동일 규칙)가 "명확한 단일 기준일"을 강제하지
않으므로 이 선택은 파라미터이지 스펙 위반이 아니다. 분기 민감도(§5 "가능하면")
는 이번 1차 구현에서는 생략 - 후속 실험으로 미룬다(사용자 스펙 §15의
"결과를 보고 사후변경 금지, 후속제안으로만"과 같은 이유로 지금 범위를
불필요하게 늘리지 않는다).

포트폴리오(§6): 교집합 전체 동일가중 보유, 교집합 0이면 현금 100%.
Ranking score(§7 Top10/Top3 민감도용) = 3개 growth 지표 percentile rank의
평균(높을수록 상위) - 별도 근거 없이 임의로 정한 단순 정의, 보고서에 명시.

비용: 30bps 왕복(이 저장소 관례).
"""
import gzip
import json
import os
from collections import defaultdict

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
A3_DIR = os.path.join(REPO_ROOT, "data", "backfill", "fundamentals", "a3")
A1A_PATH = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
A1B_PATH = os.path.join(REPO_ROOT, "data", "backfill", "universe", "a1b", "delisted.jsonl")
A2A_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2a")
A2B_DIR = os.path.join(REPO_ROOT, "data", "backfill", "price", "a2b")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports",
                        "2026-08-28-growth-screen")

OUTLIER_CEILING = 4e14
DEBT_LIMIT = 120.0
TOP_N = 20
COST_RT_BPS = 30.0
REBAL_DATES = [f"{y}-06-25" for y in range(2016, 2027)]  # 11 dates -> 10 holding periods


# ---------------------------------------------------------------- fundamentals

def load_a3():
    by_ticker = defaultdict(dict)
    n_outlier = 0
    outlier_log = []
    for fname in sorted(os.listdir(A3_DIR)):
        if not fname.endswith(".jsonl.gz"):
            continue
        with gzip.open(os.path.join(A3_DIR, fname), "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                rev, op = d.get("revenue"), d.get("opProfit")
                if (rev is not None and abs(rev) > OUTLIER_CEILING) or \
                   (op is not None and abs(op) > OUTLIER_CEILING):
                    n_outlier += 1
                    outlier_log.append({"ticker": d["ticker"], "fiscalYear": d["fiscalYear"],
                                         "revenue": rev, "opProfit": op})
                    continue
                liab, eq = d.get("liabilities"), d.get("equity")
                d["assets"] = (liab + eq) if (liab is not None and eq is not None) else None
                by_ticker[d["ticker"]][d["fiscalYear"]] = d
    return by_ticker, {"count": n_outlier, "records": outlier_log}


def latest_fy_asof(recs_by_fy, as_of):
    candidates = [r for r in recs_by_fy.values() if r["availableFrom"] <= as_of]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["fiscalYear"])


def growth_3y(recs_by_fy, latest, metric):
    prev = recs_by_fy.get(latest["fiscalYear"] - 3)
    if prev is None or prev["availableFrom"] > latest["availableFrom"]:
        return None
    base, cur = prev.get(metric), latest.get(metric)
    if base is None or cur is None or base <= 0:
        return None
    return cur / base - 1.0


def debt_ratio(latest):
    eq, liab = latest.get("equity"), latest.get("liabilities")
    if eq is None or liab is None or eq <= 0:
        return None
    return liab / eq * 100.0


# ---------------------------------------------------------------- universe / price

def load_universe():
    with open(A1A_PATH, encoding="utf-8") as f:
        a1a = [json.loads(l) for l in f]
    with open(A1B_PATH, encoding="utf-8") as f:
        a1b = [json.loads(l) for l in f]
    names = {u["ticker"]: u["name"] for u in a1a}
    names.update({u["ticker"]: u.get("corpName", u["ticker"]) for u in a1b})
    all_tickers = set(names.keys())
    return all_tickers, names


def load_price_on_dates(tickers, dates):
    """각 티커에 대해 dates 각각의 '그 날짜 이후 첫 거래일' 종가를 찾는다.
    A2a(상장) 우선, 없으면 A2b(폐지) - 이 존재 여부 자체가 유니버스
    eligibility proxy다(위 docstring 참고)."""
    tickers = set(tickers)
    price_by_ticker_date = defaultdict(dict)  # ticker -> {date_str_exact: close}
    years = sorted({int(d[:4]) for d in dates} | {int(d[:4]) + 1 for d in dates})
    for src_dir in (A2A_DIR, A2B_DIR):
        for y in years:
            path = os.path.join(src_dir, f"{y}.jsonl.gz")
            if not os.path.exists(path):
                continue
            with gzip.open(path, "rt", encoding="utf-8") as f:
                for line in f:
                    d = json.loads(line)
                    if d["ticker"] in tickers:
                        price_by_ticker_date[d["ticker"]][d["date"]] = d["close"]
    # 각 ticker의 정렬된 날짜 배열로 '이후 첫 거래일' 탐색 준비
    sorted_dates = {t: sorted(dd.keys()) for t, dd in price_by_ticker_date.items()}
    result = {}
    for t in tickers:
        sd = sorted_dates.get(t)
        if not sd:
            continue
        dd = price_by_ticker_date[t]
        for target in dates:
            import bisect
            i = bisect.bisect_left(sd, target)
            # target 이후 10거래일 이내 첫 거래일만 인정(너무 먼 미래 가격 매칭 방지)
            if i < len(sd) and sd[i] <= _add_days(target, 15):
                result[(t, target)] = dd[sd[i]]
    return result


def _add_days(date_str, n):
    from datetime import datetime, timedelta
    return (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- snapshot

def compute_snapshot(a3, all_tickers, names, price_lookup, as_of):
    rows = []
    for tk in all_tickers:
        if (tk, as_of) not in price_lookup:
            continue  # 그 시점에 가격이 없다 = 투자 불가능(상장 전 또는 이미 폐지)
        recs = a3.get(tk)
        if not recs:
            continue
        latest = latest_fy_asof(recs, as_of)
        if latest is None:
            continue
        rows.append({
            "ticker": tk, "name": names.get(tk, tk), "fiscalYear": latest["fiscalYear"],
            "assetGrowth": growth_3y(recs, latest, "assets"),
            "revenueGrowth": growth_3y(recs, latest, "revenue"),
            "opProfitGrowth": growth_3y(recs, latest, "opProfit"),
            "debtRatio": debt_ratio(latest),
        })
    return rows


def top20(rows, key, top_n=TOP_N):
    ranked = sorted([r for r in rows if r[key] is not None], key=lambda r: r[key], reverse=True)
    return ranked[:top_n]


def rank_score(rows):
    """Top10/Top3 민감도용 - 3개 지표 percentile rank 평균(임의 정의, 보고서에 명시)."""
    for key in ("assetGrowth", "revenueGrowth", "opProfitGrowth"):
        vals = [(i, r[key]) for i, r in enumerate(rows) if r[key] is not None]
        vals.sort(key=lambda x: x[1])
        n = len(vals)
        pct = {}
        for rank, (i, _) in enumerate(vals):
            pct[i] = rank / (n - 1) if n > 1 else 0.5
        for i, r in enumerate(rows):
            r.setdefault("_pct", {})[key] = pct.get(i)
    scores = []
    for r in rows:
        pcts = [v for v in r.get("_pct", {}).values() if v is not None]
        r["rankScore"] = sum(pcts) / len(pcts) if pcts else None
    return rows


def selection_at(a3, all_tickers, names, price_lookup, as_of, top_n=TOP_N):
    rows = compute_snapshot(a3, all_tickers, names, price_lookup, as_of)
    t_asset = top20(rows, "assetGrowth", top_n)
    t_rev = top20(rows, "revenueGrowth", top_n)
    t_op = top20(rows, "opProfitGrowth", top_n)
    set_a, set_b, set_c = ({r["ticker"] for r in t} for t in (t_asset, t_rev, t_op))
    intersection = set_a & set_b & set_c
    by_ticker = {r["ticker"]: r for r in rows}
    inter_rows = [by_ticker[tk] for tk in intersection]
    rank_score(inter_rows)
    final_a = {tk for tk in intersection if by_ticker[tk]["debtRatio"] is not None
               and by_ticker[tk]["debtRatio"] <= DEBT_LIMIT}
    dropped_by_debt = intersection - final_a
    return {
        "as_of": as_of, "universeSize": len(rows), "rows": rows,
        "assetTop20": [r["ticker"] for r in t_asset], "revenueTop20": [r["ticker"] for r in t_rev],
        "opProfitTop20": [r["ticker"] for r in t_op],
        "intersection": sorted(intersection), "final_A_debtFiltered": sorted(final_a),
        "final_B_noFilter": sorted(intersection), "droppedByDebt": sorted(dropped_by_debt),
        "byTicker": by_ticker, "interRows": inter_rows,
    }


# ---------------------------------------------------------------- portfolios / backtest

def portfolio_members(sel, mode):
    if mode == "A_debtFilter":
        return sel["final_A_debtFiltered"]
    if mode == "B_noFilter":
        return sel["final_B_noFilter"]
    ranked = sorted(sel["interRows"], key=lambda r: (r["rankScore"] is None, -(r["rankScore"] or 0)))
    if mode == "Top10":
        return [r["ticker"] for r in ranked[:10]]
    if mode == "Top3":
        return [r["ticker"] for r in ranked[:3]]
    raise ValueError(mode)


def run_strategy(selections, price_lookup, mode, cost_bps=COST_RT_BPS):
    periods = []
    prev_members = set()
    for k in range(len(selections) - 1):
        t, t1 = selections[k]["as_of"], selections[k + 1]["as_of"]
        members = portfolio_members(selections[k], mode)
        if not members:
            periods.append({"start": t, "end": t1, "ret": 0.0, "n": 0, "members": [], "turnover": None})
            prev_members = set()
            continue
        rets = []
        held = []
        for tk in members:
            p0, p1 = price_lookup.get((tk, t)), price_lookup.get((tk, t1))
            if p0 is None or p1 is None or p0 <= 0:
                continue
            rets.append(p1 / p0 - 1.0)
            held.append(tk)
        if not held:
            periods.append({"start": t, "end": t1, "ret": 0.0, "n": 0, "members": [], "turnover": None})
            prev_members = set()
            continue
        turnover = None
        if prev_members:
            changed = len(set(held) - prev_members) + len(prev_members - set(held))
            turnover = changed / (2 * max(len(prev_members), len(held)))
        gross = float(np.mean(rets))
        net = gross - cost_bps / 1e4
        periods.append({"start": t, "end": t1, "ret": net, "n": len(held), "members": held,
                         "turnover": turnover})
        prev_members = set(held)
    return periods


def universe_ew_strategy(selections, price_lookup, cost_bps=COST_RT_BPS):
    """벤치마크 - 매 시점 전체 투자가능 유니버스(가격 존재하는 전 종목) 동일가중."""
    periods = []
    for k in range(len(selections) - 1):
        t, t1 = selections[k]["as_of"], selections[k + 1]["as_of"]
        rets = []
        for r in selections[k]["rows"]:
            tk = r["ticker"]
            p0 = price_lookup.get((tk, t))
            p1 = price_lookup.get((tk, t1))
            if p0 and p1 and p0 > 0:
                rets.append(p1 / p0 - 1.0)
        gross = float(np.mean(rets)) if rets else 0.0
        periods.append({"start": t, "end": t1, "ret": gross - cost_bps / 1e4, "n": len(rets)})
    return periods


def index_strategy(parquet_path, value_col, dates, datecol="date"):
    df = pd.read_parquet(parquet_path)
    if datecol not in df.columns:
        datecol = "usableFromDate"
    df = df.sort_values(datecol).reset_index(drop=True)
    idx = df[datecol].to_numpy()
    vals = df[value_col].to_numpy()
    import bisect
    price_at = {}
    for d in dates:
        i = bisect.bisect_left(idx, d)
        if i < len(idx):
            price_at[d] = vals[i]
    periods = []
    for k in range(len(dates) - 1):
        t, t1 = dates[k], dates[k + 1]
        p0, p1 = price_at.get(t), price_at.get(t1)
        if p0 and p1:
            periods.append({"start": t, "end": t1, "ret": p1 / p0 - 1.0})
        else:
            periods.append({"start": t, "end": t1, "ret": None})
    return periods


# ---------------------------------------------------------------- metrics

def compute_metrics(periods):
    rets = [p["ret"] for p in periods if p.get("ret") is not None]
    if not rets:
        return {}
    eq = np.cumprod([1 + r for r in rets])
    total_return = float(eq[-1] - 1)
    n_years = len(rets)
    cagr = float(eq[-1] ** (1 / n_years) - 1) if n_years else None
    running_max = np.maximum.accumulate(eq)
    mdd = float((eq / running_max - 1).min())
    vol = float(np.std(rets))
    sharpe = float(np.mean(rets) / vol) if vol > 0 else None
    downside = [r for r in rets if r < 0]
    dstd = float(np.std(downside)) if downside else 0.0
    sortino = float(np.mean(rets) / dstd) if dstd > 0 else None
    calmar = float(cagr / abs(mdd)) if mdd < 0 and cagr is not None else None
    winrate = float(np.mean([r > 0 for r in rets]))
    max_consec_loss = 0
    cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        max_consec_loss = max(max_consec_loss, cur)
    yearly = {p["start"][:4]: round(p["ret"], 4) for p in periods if p.get("ret") is not None}
    ns = [p["n"] for p in periods if "n" in p]
    turnovers = [p["turnover"] for p in periods if p.get("turnover") is not None]
    return {
        "totalReturn": round(total_return, 4), "cagr": round(cagr, 4) if cagr is not None else None,
        "mdd": round(mdd, 4), "sharpe": round(sharpe, 3) if sharpe is not None else None,
        "sortino": round(sortino, 3) if sortino is not None else None,
        "calmar": round(calmar, 3) if calmar is not None else None,
        "volatility": round(vol, 4), "winRate": round(winrate, 3),
        "maxConsecutiveLossPeriods": max_consec_loss, "yearlyReturns": yearly,
        "avgHoldings": round(float(np.mean(ns)), 1) if ns else None,
        "minHoldings": min(ns) if ns else None, "maxHoldings": max(ns) if ns else None,
        "avgTurnover": round(float(np.mean(turnovers)), 3) if turnovers else None,
        "nPeriods": len(rets),
    }


# ---------------------------------------------------------------- diagnostics

def debt_filter_dropped_analysis(selections, all_tickers):
    """§12 - Debt Filter로 탈락한 종목의 이후 1/3/6/12개월 수익률."""
    horizons_days = {"1m": 30, "3m": 91, "6m": 182, "12m": 365}
    targets = set()
    dropped_events = []
    for sel in selections:
        for tk in sel["droppedByDebt"]:
            for label, days in horizons_days.items():
                d = _add_days(sel["as_of"], days)
                targets.add((tk, d))
            targets.add((tk, sel["as_of"]))
            dropped_events.append({"ticker": tk, "as_of": sel["as_of"]})
    fwd_price = load_price_on_dates({tk for tk, _ in targets}, sorted({d for _, d in targets}))
    results = []
    for ev in dropped_events:
        tk, t0 = ev["ticker"], ev["as_of"]
        p0 = fwd_price.get((tk, t0))
        row = {"ticker": tk, "as_of": t0}
        for label, days in horizons_days.items():
            d = _add_days(t0, days)
            p1 = fwd_price.get((tk, d))
            row[f"fwd_{label}"] = round(p1 / p0 - 1, 4) if (p0 and p1 and p0 > 0) else None
        results.append(row)
    summary = {}
    for label in horizons_days:
        vals = [r[f"fwd_{label}"] for r in results if r[f"fwd_{label}"] is not None]
        summary[label] = {"n": len(vals), "meanReturn": round(float(np.mean(vals)), 4) if vals else None}
    return {"events": results, "summary": summary}


def load_shared_data():
    print("loading A3 fundamentals...")
    a3, outlier_info = load_a3()
    print(f"  outliers excluded: {outlier_info['count']}")
    print("loading universe...")
    all_tickers, names = load_universe()
    print(f"  A1a+A1b union: {len(all_tickers)} tickers")
    print("loading price snapshots at rebalance dates...")
    price_lookup = load_price_on_dates(all_tickers, REBAL_DATES)
    print(f"  price points matched: {len(price_lookup)}")
    return a3, all_tickers, names, price_lookup, outlier_info


def run_for_topn(top_n, a3, all_tickers, names, price_lookup, outlier_info):
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports",
                            f"2026-08-28-growth-screen-top{top_n}")
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n===== TOP{top_n} =====")
    print("computing selections at each as_of...")
    selections = [selection_at(a3, all_tickers, names, price_lookup, t, top_n) for t in REBAL_DATES]
    for sel in selections:
        print(f"  {sel['as_of']}: universe={sel['universeSize']} intersection={len(sel['intersection'])} "
              f"final_A={len(sel['final_A_debtFiltered'])} droppedByDebt={len(sel['droppedByDebt'])}")

    print("running strategies + benchmarks...")
    strat_results = {}
    for mode in ("A_debtFilter", "B_noFilter", "Top10", "Top3"):
        periods = run_strategy(selections, price_lookup, mode)
        strat_results[mode] = {"periods": periods, "metrics": compute_metrics(periods)}

    strat_results["UniverseEW"] = {
        "periods": (p := universe_ew_strategy(selections, price_lookup)),
        "metrics": compute_metrics(p),
    }

    kospi_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "market-regime",
                               "krkospi_raw.parquet")
    kosdaq_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "market-regime",
                                "krkosdaq_raw.parquet")
    strat_results["KOSPI"] = {"periods": (p := index_strategy(kospi_path, "value", REBAL_DATES)),
                               "metrics": compute_metrics(p)}
    strat_results["KOSDAQ"] = {"periods": (p := index_strategy(kosdaq_path, "value", REBAL_DATES)),
                                "metrics": compute_metrics(p)}

    print("=== 요약 ===")
    for name, r in strat_results.items():
        m = r["metrics"]
        print(f"  {name:12s} CAGR={m.get('cagr')} MDD={m.get('mdd')} Sharpe={m.get('sharpe')} "
              f"avgHold={m.get('avgHoldings')} nPeriods={m.get('nPeriods')}")

    dropped_analysis = debt_filter_dropped_analysis(selections, all_tickers)

    from collections import Counter
    freq = Counter()
    for sel in selections:
        for tk in sel["final_B_noFilter"]:
            freq[tk] += 1
    most_frequent = freq.most_common(20)

    inter_sizes = [len(sel["intersection"]) for sel in selections]

    out = {
        "generatedAt": pd.Timestamp.now().isoformat(),
        "topN": top_n,
        "rebalanceDates": REBAL_DATES,
        "outlierFilter": {"ceiling": OUTLIER_CEILING, **outlier_info},
        "universeMethodologyNote": "A1b에 listedAt·exitAt(대부분 null)이 없어 정확한 상장~폐지 "
                                    "구간을 재구성 못 함 - 가격데이터 존재 여부(A2a/A2b, asOf+15일 "
                                    "이내 첫 거래일)를 투자가능성 proxy로 사용. A2b 커버리지가 "
                                    "이미 알려진 대로 불완전(~19% 결측)해 survivorship bias가 "
                                    "완전히 제거되지 않았을 수 있음.",
        "rebalanceDateNote": "연 1회, 매년 06-25 고정(3월말 법정공시기한+3개월 여유). "
                              "분기 민감도는 이번 1차 구현에서 생략(후속 실험 제안).",
        "rankScoreDefinition": "Top10/Top3 민감도: 3개 growth 지표 percentile rank의 평균 "
                                "(사전 근거 없는 단순 정의, 결과 해석 시 이 점 감안할 것)",
        "selections": [
            {"as_of": s["as_of"], "universeSize": s["universeSize"],
             "assetTop20": s["assetTop20"], "revenueTop20": s["revenueTop20"],
             "opProfitTop20": s["opProfitTop20"], "intersection": s["intersection"],
             "final_A_debtFiltered": s["final_A_debtFiltered"], "droppedByDebt": s["droppedByDebt"]}
            for s in selections
        ],
        "intersectionSizeStats": {"mean": round(float(np.mean(inter_sizes)), 1),
                                   "min": min(inter_sizes), "max": max(inter_sizes)},
        "mostFrequentlySelected": most_frequent,
        "strategies": {k: v["metrics"] for k, v in strat_results.items()},
        "strategyPeriods": {k: v["periods"] for k, v in strat_results.items()},
        "debtFilterDroppedAnalysis": dropped_analysis,
    }
    out_path = os.path.join(out_dir, f"growth-screen-top{top_n}-results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print("saved:", out_path)
    return out


if __name__ == "__main__":
    import sys
    top_ns = [int(x) for x in sys.argv[1:]] or [20]
    shared = load_shared_data()
    for n in top_ns:
        run_for_topn(n, *shared)
