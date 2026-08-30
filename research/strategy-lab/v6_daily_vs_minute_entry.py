#!/usr/bin/env python
"""V6 일봉 close-to-close vs 분봉 09:00~09:01 진입 비교 study.

배경: V1~V9 signal study 전부가 "실거래 계약은 signal t→t+1 시가 체결인데 본
수치는 종가-종가 근사"라는 한계를 매번 명시해왔다. 이 스터디는 그 근사가 실제로
얼마나 왜곡됐는지를 잰다 — "V6이 맞는지"를 보는 게 아니다.

방법 (같은 신호 집합에서 두 가지 측정):
  (a) 기존 방식 — 신호일 t 종가 → t+h째 패널 행 종가 (A2a adjusted,
      close-to-close). v5/v6 스터디와 동일 관례 그대로.
  (b) 분봉 기반 — t+1 거래일 09:00~09:01 분봉 평균가(진입) → t+h+1 거래일
      같은 시각 평균가(청산). 즉 "실제 계약대로 익일 시가 진입"을 분봉으로 재현.
      데이터: MinuteProvider(research/strategy-lab/.cache/minute_raw/, 읽기 전용
      VM 미러).

★ 표본 한계: 분봉 미러는 2025-08-08~2026-08-21(252거래일)만 있다. 전체 10년
기준이 아니며 이 표본 기간에만 성립하는 관측치다. a4 패널 자체는 2026-08-03까지라
(a) 쪽 유효 표본은 사실상 2025-08-08~2026-08-03이다.

[UNSPECIFIED]->임시 채택:
  - "09:00~09:01 평균가" = ts 시각이 09:00:00~09:01:00에 들어오는 분봉 close의
    등가중 평균(최대 2개 봉). 분봉은 체결 있을 때만 존재(희소)라 해당 구간에
    봉이 없으면 NaN -> 그 신호는 (b)에서 탈락(탈락 수 보고).
  - 벤치마크도 같은 방식으로 계산해 (a)/(b) 벤치 정의를 맞춘다:
      benchA_mirror = 패널 fwd_h 의 미러종목 한정 동일가중
      benchB        = 미러 분봉수익의 동일가중(단, 신호일 패널 멤버로 한정)
    1차 비교는 (a-mirror) vs (b) — 신호·벤치 종목 집합을 최대한 같게 해서
    "가격 규약" 차이만 남긴다. benchA_native(패널 전체)는 원본 수치 대조용 참고.
  - 민감도: 평균가 대신 분봉 VWAP(close*volume 가중) 변형도 함께 계산.

  python v6_daily_vs_minute_entry.py
"""
import glob
import json
import os
import sys
import time
from datetime import time as dtime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from engine.data.minuteProvider import MinuteProvider  # noqa: E402
from v5_divergence_signal_study import HORIZONS, load_panel  # noqa: E402
from v6_acc_price_signal_study import PRICE_CAP, load_buy_flows  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "v6-daily-vs-minute-entry")
WINDOW_START, WINDOW_END = "2025-08-08", "2026-08-21"
ENTRY_T0, ENTRY_T1 = dtime(9, 0), dtime(9, 1)
EXPECTED_FULLSAMPLE_COUNTS = {
    "baseline_divBoth_noFilter": 1156228,
    "v6_divBoth_plus5pctCap": 955832,
}


def extract_open_prices_fast(mdir, mdates):
    """09:00~09:01 봉만 추출 + 당일 마지막 봉 종가(raw close 근사).
    MinuteProvider.load()를 날짜별로 252회 돌리면 per-ticker to_datetime 병목으로
    ~78분이 걸려(실측 18.6s/일), 동일 파티션 parquet에서 ts 문자열 접두어
    ({date}T09:00/{date}T09:01)로 선별하는 fast path를 쓴다. 정합성은
    verify_against_provider()로 표본 날짜를 MinuteProvider 실출력과 대조해 검증."""
    frames = []
    t0 = time.time()
    for k_i, d in enumerate(mdates):
        parts = sorted(glob.glob(os.path.join(mdir, f"date={d}", "part-*.parquet")))
        if not parts:
            continue
        df = pd.concat((pd.read_parquet(p, columns=["ticker", "ts", "close", "volume"])
                        for p in parts), ignore_index=True)
        sel = df[df["ts"].str.startswith((f"{d}T09:00", f"{d}T09:01"))].copy()
        last = df.sort_values("ts").groupby("ticker")["close"].last().rename("lastClose")
        if sel.empty:
            continue
        sel["cv"] = sel["close"] * sel["volume"]
        agg = sel.groupby("ticker").agg(avg=("close", "mean"), vol=("volume", "sum"),
                                        cv=("cv", "sum")).reset_index()
        agg["vwap"] = np.where(agg["vol"] > 0, agg["cv"] / agg["vol"], np.nan)
        agg = agg.merge(last.reset_index(), on="ticker")
        agg["date"] = d
        frames.append(agg[["ticker", "date", "avg", "vwap", "lastClose"]])
        if (k_i + 1) % 42 == 0 or k_i + 1 == len(mdates):
            print(f"  minute extraction {k_i+1}/{len(mdates)} ({time.time()-t0:.0f}s)")
    return pd.concat(frames, ignore_index=True)


def verify_against_provider(provider, open_df, mdates, tickers, n_samples=5):
    """fast path 결과를 MinuteProvider.load() 실출력과 표본 날짜로 대조."""
    picks = sorted({mdates[0], mdates[len(mdates) // 3], mdates[len(mdates) // 2],
                    mdates[2 * len(mdates) // 3], mdates[-1]})[:n_samples]
    checks = []
    for d in picks:
        bars = provider.load(tickers, d, d)
        recs = []
        for tkr, bdf in bars.items():
            idx = bdf.index
            sel = bdf[(idx.time >= ENTRY_T0) & (idx.time <= ENTRY_T1)]
            if sel.empty:
                continue
            vol = float(sel["volume"].sum())
            recs.append({"ticker": tkr,
                         "avg": float(sel["close"].mean()),
                         "vwap": float((sel["close"] * sel["volume"]).sum() / vol)
                         if vol > 0 else np.nan})
        ref = pd.DataFrame(recs)
        mine = open_df[open_df["date"] == d][["ticker", "avg", "vwap"]]
        m = ref.merge(mine, on="ticker", suffixes=("_prov", "_fast"))
        da = float((m["avg_prov"] - m["avg_fast"]).abs().max()) if len(m) else None
        dv = float((m["vwap_prov"] - m["vwap_fast"]).abs().max()) if len(m) else None
        checks.append({"date": d, "tickersProvider": int(len(ref)),
                       "tickersMatched": int(len(m)), "maxAbsDiffAvg": da,
                       "maxAbsDiffVwap": dv})
        print(f"  verify {checks[-1]}")
    return checks


def build_adjust_factor(open_df, mdates, panel):
    """일자별 조정계수 K[ticker, date] = 패널 close(A2a adjusted) / 당일 마지막 봉
    종가(raw). 패널 종료(2026-08-03) 이후는 종목별 마지막 계수를 앞으로 운반(ffill).
    분봉 raw 가격에 K를 곱하면 패널 adjusted 단위와 정렬된다."""
    kp = panel[["ticker", "date", "close"]].merge(
        open_df[["ticker", "date", "lastClose"]], on=["ticker", "date"], how="inner")
    kp = kp[kp["lastClose"] > 0]
    kp["k"] = kp["close"] / kp["lastClose"]
    kw = kp.pivot_table(index="ticker", columns="date", values="k").reindex(columns=mdates)
    return kw.ffill(axis=1)


def minute_return_matrices(open_df, mdates, kw):
    """raw/조정(avg·vwap) 진입·청산 수익 행렬과 갭 행렬.
    반환: ({kind: {h: R_h}}, {kind: E}, gap_mat, stable_mask) —
    R_h[ticker, 신호일t] = W.shift(-(1+h))/W.shift(-1) - 1,
    gap_mat = E_rawAvg(t+1) / rawLastClose(t) - 1 (K 안정일에만 유효)."""
    w_avg = open_df.pivot_table(index="ticker", columns="date", values="avg").reindex(columns=mdates)
    w_vwap = open_df.pivot_table(index="ticker", columns="date", values="vwap").reindex(columns=mdates)
    w_last = open_df.pivot_table(index="ticker", columns="date", values="lastClose").reindex(columns=mdates)
    kinds = {"rawAvg": w_avg, "adjAvg": w_avg * kw,
             "rawVwap": w_vwap, "adjVwap": w_vwap * kw}
    entry_mats = {name: w.shift(-1, axis=1) for name, w in kinds.items()}
    entry_mats["rawLastClose"] = w_last
    rets = {name: {h_name: w.shift(-(1 + h), axis=1) / entry_mats[name] - 1
                   for h_name, h in HORIZONS.items()} for name, w in kinds.items()}
    gap_mat = entry_mats["rawAvg"] / entry_mats["rawLastClose"] - 1
    k_next = kw.shift(-1, axis=1)
    stable = ((k_next / kw - 1).abs() < 1e-3) & gap_mat.notna()
    return rets, entry_mats, gap_mat.where(stable), stable


def stack_long(mat, value_name):
    s = mat.stack(future_stack=True).dropna().rename(value_name)
    return s.reset_index()


def stats_for(d, col_ret, bench_by_date):
    """v5/v6 스터디의 stats_for 관례 그대로 (신호행 결합 벤치 차이의 평균)."""
    dd = d.dropna(subset=[col_ret])
    if dd.empty:
        return {"n": 0}
    joined = dd.set_index("date")[col_ret].rename("sig").to_frame().join(bench_by_date.rename("bench"))
    daily_excess = joined["sig"] - joined["bench"]
    years = dd["date"].str[:4]
    yearly = {}
    for y in sorted(years.unique()):
        m = (years == y).values
        yearly[y] = {
            "n": int(m.sum()),
            "excessMean": round(float(daily_excess[m].mean()), 5),
            "sigMean": round(float(dd.loc[m, col_ret].mean()), 5),
        }
    return {
        "n": int(len(dd)),
        "nDates": int(dd["date"].nunique()),
        "avgPerDay": round(len(dd) / max(1, dd["date"].nunique()), 1),
        "mean": round(float(dd[col_ret].mean()), 5),
        "median": round(float(dd[col_ret].median()), 5),
        "winRate": round(float((dd[col_ret] > 0).mean()), 4),
        "benchMean": round(float(joined["bench"].mean()), 5),
        "excessPerDateMatched": round(float(daily_excess.mean()), 5),
        "yearly": yearly,
    }


def quantiles(s, qs=(0.1, 0.25, 0.5, 0.75, 0.9)):
    s = s.dropna()
    if s.empty:
        return {}
    return {str(q): round(float(s.quantile(q)), 5) for q in qs}


def main():
    t0 = time.time()
    panel = load_panel()
    print(f"panel rows={len(panel)}, tickers={panel['ticker'].nunique()}, "
          f"dates {panel['date'].min()}~{panel['date'].max()} ({time.time()-t0:.0f}s)")

    flows = load_buy_flows()
    df = panel.merge(flows, on=["ticker", "date"], how="left")
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker")
    amt5 = g["buyAmt"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
    vol5 = g["buyVol"].transform(lambda s: s.fillna(0).rolling(5, min_periods=1).sum())
    df["accPrice"] = np.where(vol5 > 0, amt5 / vol5, np.nan)
    df["priceRatio"] = df["close"] / df["accPrice"]
    both = (df["foreign_nb_5d"] > 0) & (df["inst_nb_5d"] > 0)
    variants = {
        "baseline_divBoth_noFilter": both,
        "v6_divBoth_plus5pctCap": both & (df["priceRatio"] <= PRICE_CAP),
    }
    repro = {name: int(m.sum()) for name, m in variants.items()}
    print("full-sample repro counts:", repro,
          "(expected:", EXPECTED_FULLSAMPLE_COUNTS, ")")

    win_mask = (df["date"] >= WINDOW_START) & (df["date"] <= WINDOW_END)

    provider = MinuteProvider(repo_root=REPO_ROOT)
    mdir = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache", "minute_raw")
    mdates = sorted(e.split("=", 1)[1] for e in os.listdir(mdir) if e.startswith("date="))
    print(f"minute mirror dates={len(mdates)} {mdates[0]}~{mdates[-1]} "
          f"manifest={provider.manifest_hash} ({time.time()-t0:.0f}s)")

    cache_path = os.path.join(REPO_ROOT, "research", "strategy-lab", ".cache",
                              f"minute_open_09_01_{len(mdates)}.parquet")
    if os.path.exists(cache_path):
        open_df = pd.read_parquet(cache_path)
        print(f"open-price cache loaded: {cache_path}")
    else:
        open_df = extract_open_prices_fast(mdir, mdates)
        open_df.to_parquet(cache_path)
    mirror_tickers = set(open_df["ticker"].unique())
    print(f"minute rows={len(open_df)}, tickers={len(mirror_tickers)} ({time.time()-t0:.0f}s)")

    have_open = set(open_df["date"].unique())
    hole_dates = [d for d in mdates if d not in have_open]
    mdates_pos = {d: i for i, d in enumerate(mdates)}
    print("mirror opening-data hole dates:", hole_dates)
    verify_checks = verify_against_provider(provider, open_df, mdates,
                                            sorted(df["ticker"].unique()))

    kwide = build_adjust_factor(open_df, mdates, panel)
    k_first = kwide.bfill(axis=1).iloc[:, 0]
    k_diag = {
        "tickersWithFactor": int(k_first.notna().sum()),
        "shareKOff1_gt0pct5": round(float((k_first.sub(1).abs() > 0.005).mean()), 4),
        "quantiles": {str(q): round(float(k_first.quantile(q)), 4)
                      for q in (0.01, 0.25, 0.5, 0.75, 0.99)},
        "min": round(float(k_first.min()), 4), "max": round(float(k_first.max()), 4),
    }
    print("adjust factor k diag:", k_diag)

    rets, entry_mats, gap_mat, _ = minute_return_matrices(open_df, mdates, kwide)
    rb_long = {h: stack_long(rets["adjAvg"][h], "rbAdj") for h in HORIZONS}
    rr_long = {h: stack_long(rets["rawAvg"][h], "rbRaw") for h in HORIZONS}
    rv_long = {h: stack_long(rets["adjVwap"][h], "rvAdj") for h in HORIZONS}
    gap_long = stack_long(gap_mat, "entryGap")

    bench_a_native, bench_a_mirror, benches_minute = {}, {}, {}
    panel_in_mirror = df[df["ticker"].isin(mirror_tickers)]
    for h_name, h in HORIZONS.items():
        fwd = f"fwd_{h}"
        bench_a_native[h_name] = panel.dropna(subset=[fwd]).groupby("date")[fwd].mean()
        bench_a_mirror[h_name] = (
            panel_in_mirror.dropna(subset=[fwd]).groupby("date")[fwd].mean())

    members_by_date = df.groupby("date")["ticker"].apply(set).to_dict()
    for kind in ("adjAvg", "rawAvg", "adjVwap"):
        store = {}
        for h_name in HORIZONS:
            r = rets[kind][h_name]
            vals = {}
            for d in mdates:
                if d not in r.columns:
                    continue
                col = r[d]
                mem = members_by_date.get(d)
                if mem:
                    col = col[col.index.isin(mem)]
                vals[d] = float(col.mean()) if col.notna().any() else np.nan
            store[h_name] = pd.Series(vals)
        benches_minute[kind] = store

    results = {"reproCheckFullSample": repro, "adjustFactorK_firstDate": k_diag}
    for name, mask in variants.items():
        sig = df[mask & win_mask].copy()
        gaps = sig.merge(gap_long, on=["ticker", "date"], how="left")["entryGap"]
        block = {
            "signalRowsWindowRaw": int(len(sig)),
            "overnightGapRaw_kStable": {
                "n": int(gaps.notna().sum()),
                "mean": round(float(gaps.mean()), 5),
                **quantiles(gaps),
            },
        }
        print(f"{name}: window signals={len(sig)} "
              f"overnightGap(raw,kStable) mean={block['overnightGapRaw_kStable']['mean']}")
        for h_name in HORIZONS:
            fwd = f"fwd_{h_name.replace('T+', '')}"
            d = sig[["ticker", "date", fwd]].copy()
            d = d.merge(rb_long[h_name], on=["ticker", "date"], how="left")
            d = d.merge(rr_long[h_name], on=["ticker", "date"], how="left")
            d = d.merge(rv_long[h_name], on=["ticker", "date"], how="left")

            a_native = stats_for(d, fwd, bench_a_native[h_name])
            a_mirror = stats_for(d, fwd, bench_a_mirror[h_name])
            b_adj = stats_for(d, "rbAdj", benches_minute["adjAvg"][h_name])
            b_raw = stats_for(d, "rbRaw", benches_minute["rawAvg"][h_name])
            b_vwap = stats_for(d, "rvAdj", benches_minute["adjVwap"][h_name])

            paired = d.dropna(subset=[fwd, "rbAdj"])
            corr_ab = float(paired[fwd].corr(paired["rbAdj"])) if len(paired) > 1 else None

            inv = d[d[fwd].notna() & d["rbAdj"].isna()]
            n_inv = int(len(inv))
            att_hole = None
            if n_inv:
                def _leg(dd_, off):
                    i = mdates_pos.get(dd_)
                    return mdates[i + off] if i is not None and i + off < len(mdates) else None
                e_leg = inv["date"].map(lambda x: _leg(x, 1))
                x_leg = inv["date"].map(lambda x: _leg(x, 1 + HORIZONS[h_name]))
                att_hole = round(float((e_leg.isin(hole_dates) | x_leg.isin(hole_dates)).mean()), 4)
            excluded_diag = {
                "nInvalid": n_inv,
                "shareLegOnHoleDate": att_hole,
                "fwdMeanValid": round(float(d.loc[d["rbAdj"].notna(), fwd].mean()), 5),
                "fwdMeanInvalid": round(float(inv[fwd].mean()), 5) if n_inv else None,
            }
            a_pair = stats_for(paired, fwd, bench_a_mirror[h_name]) if len(paired) else {"n": 0}
            b_pair = stats_for(paired, "rbAdj", benches_minute["adjAvg"][h_name]) if len(paired) else {"n": 0}
            diff_excess = (round(b_pair["excessPerDateMatched"] - a_pair["excessPerDateMatched"], 5)
                           if a_pair.get("n") and b_pair.get("n") else None)
            block[h_name] = {
                "a_dailyCloseToClose_nativeBench": a_native,
                "a_dailyCloseToClose_mirrorBench": a_mirror,
                "b_minuteOpenAdj": b_adj,
                "b_minuteOpenRaw_noEventFix": b_raw,
                "b_minuteVwapAdjSensitivity": b_vwap,
                "pairedRows": {
                    "n": int(len(paired)),
                    "aMirrorBench": a_pair,
                    "bMinuteAdj": b_pair,
                    "corrAB": round(corr_ab, 4) if corr_ab is not None else None,
                    "excessDiff_b_minus_aMirror": diff_excess,
                },
                "excludedRowComposition": excluded_diag,
                "coverageN": {
                    "raw": int(len(sig)), "aValid": a_native.get("n", 0),
                    "bValidAdj": b_adj.get("n", 0), "paired": int(len(paired)),
                },
            }
            print(f"  {h_name}: excess a_native={a_native.get('excessPerDateMatched')} "
                  f"a_mir={a_mirror.get('excessPerDateMatched')} "
                  f"b_adj={b_adj.get('excessPerDateMatched')} "
                  f"| paired a={a_pair.get('excessPerDateMatched')} "
                  f"b={b_pair.get('excessPerDateMatched')} diff={diff_excess} "
                  f"n={len(paired)} corr={corr_ab}")
        results[name] = block

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, "comparison_results.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "context": "V6 일봉 close-to-close vs 분봉 익일 09:00~09:01 진입 비교 — "
                       "signal study 근사(종가-종가)의 왜곡 측정. V6 적합성 검증 아님.",
            "sampleLimitation": "분봉 미러는 2025-08-08~2026-08-21 252거래일뿐 — 전체 10년 기준 아님. "
                                "패널은 2026-08-03까지라 (a) 유효 구간은 사실상 ~2026-08-03.",
            "window": {"start": WINDOW_START, "end": WINDOW_END},
            "dataCoverage": {
                "minuteDates": len(mdates), "minuteRange": [mdates[0], mdates[-1]],
                "minuteTickers": len(mirror_tickers), "manifestHash": provider.manifest_hash,
                "panelEnd": str(panel["date"].max()),
                "mirrorOpeningHoleDates": hole_dates,
                "fastPathVerification": verify_checks,
            },
            "conventions": {
                "aMethod": "t 종가 -> t+h째 패널 행 종가 (A2a adjusted, v5/v6 관례)",
                "bMethod": "t+1거래일 09:00~09:01 분봉 raw close 등가중 평균 -> t+h+1거래일 "
                           "같은 시각. 조정계수 K=패널close/당일 마지막봉 raw종가를 곱해 "
                           "패널 adjusted 단위로 정렬(b_minuteOpenAdj) — 배당·분할이 홀딩 중에 "
                           "있어도 (a)와 같은 총수익 관례로 비교 가능. K 미보정 raw 변형은 "
                           "b_minuteOpenRaw_noEventFix(참고용).",
                "unspecifiedProvisional": {
                    "openAvgDefinition": "ts가 09:00:00~09:01:00인 봉(희소, 보통 1~2개) close 등가중 평균",
                    "missingLegRule": "구간 내 봉이 없으면 NaN -> 해당 다리 탈락 (페어 표본 축소)",
                    "adjustFactorK": "K=패널 adjusted close / 분봉 마지막 봉 raw close (같은 날짜). "
                                     "패널 종료 2026-08-03 이후는 종목별 마지막 K를 ffill — 그 구간의 "
                                     "신규 기업편입 이벤트는 반영 불가(데이터 한계).",
                    "overnightGapDiagnostic": "raw-to-raw로 재정의: t일 마지막 봉 종가 -> t+1 09:00~"
                                              "09:01 평균가. K가 t->t+1 사이 변한 종목(|dK/K|>=0.1%)는 "
                                              "제외해 조정 오염 차단.",
                    "benchMatching": "1차 비교는 pairedRows: (a-mirror bench) vs (b-minute bench)를 "
                                     "양쪽 모두 유효한 동일 신호 행에서 계산. benchA_mirror=미러종목 "
                                     "한정 패널 fwd 동일가중, benchB=신호일 패널 멤버 중 양다리 유효 "
                                     "종목 동일가중",
                    "aggregationNote": "stats_for 관례(v5/v6와 동일)는 날짜별 스프레드를 신호행 수로 "
                                       "가중 평균한다 — 명칭과 달리 날짜 동일가중이 아니나, (a)(b)가 "
                                       "같은 방식이라 비교(차이)에는 영향 없음",
                },
                "vwapSensitivity": "평균가 대신 봉 VWAP(close*volume, 조정 적용) 사용 변형",
            },
            "results": results,
        }, fh, ensure_ascii=False, indent=2)
    print("saved:", out_path)


if __name__ == "__main__":
    main()
