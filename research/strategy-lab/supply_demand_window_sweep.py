#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""수급 축 정의 수정(B층) — 5일 창이 문제인가, 축 자체가 문제인가.

축 가중치 스윕(axis-weight-sweep-2026-09.md)에서 TRAIN IC 상위 10개가 전부
supplyDemand=0 으로 나왔다. 그러나 2026-08-19 slot-marginal 은 원인을
"5일 창 정의가 역방향"으로 지목했고 A4 연구의 20일 누적은 양(+) IC 였다.
**축을 버릴 것인가 정의를 고칠 것인가**를 가른다.

현재 정의(lib/a5/supplyDemandFrom.js + scoringEngine.js):
    최근 5거래일 외국인/기관 순매수량 -> netBuysToTrend -> 점수
    consistentBuy(전일 순매수) 100 · netBuy(합>0) 70 · neutral 50 ·
    netSell(합<0) 30 · consistentSell(전일 순매도) 0

★ 이 분류는 창 길이에 따라 성질이 바뀐다 - 5일 연속 순매수는 곧잘 나오지만
20일 연속은 거의 없다. 창만 늘리면 100/0 극단이 사라지고 70/30 으로 뭉개진다.
그래서 세 가지를 같이 잰다:
    (a) 5일 라벨(현행)  (b) 20일 라벨  (c) 20일 누적 순매수 연속값(횡단면 랭크)

  python supply_demand_window_sweep.py --selftest
  python supply_demand_window_sweep.py --validate-year 2024
  python supply_demand_window_sweep.py
"""
import argparse
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np   # noqa: E402
import pandas as pd  # noqa: E402

import axis_weight_sweep as AW  # noqa: E402

LAB = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(LAB))
A4 = os.path.join(REPO_ROOT, "data", "backfill", "supplyDemand", "a4")
SCORES = os.path.join(REPO_ROOT, "data", "backfill", "scores")
OUT_DIR = os.path.join(LAB, "reports", "2026-09-04-supply-demand-window")

# lib/a5/supplyDemandFrom.js 와 같은 매핑 - 원본이 바뀌면 여기도 같이 본다
FOREIGN = ["외국인"]
INSTITUTION = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금", "기타법인"]
TREND_SCORE = {"consistentBuy": 100.0, "netBuy": 70.0, "neutral": 50.0,
               "netSell": 30.0, "consistentSell": 0.0}
W_FOREIGN, W_INST = 0.40, 0.35     # criteria KR-2.3 supplyDemand.metrics


def net_buys_to_trend(v):
    """scripts/collect.js netBuysToTrend 그대로. 빈 배열이면 None."""
    if v is None or len(v) == 0:
        return None
    buy_days = int((np.asarray(v) > 0).sum())
    total = float(np.asarray(v).sum())
    if buy_days == len(v):
        return "consistentBuy"
    if buy_days == 0:
        return "consistentSell"
    if total > 0:
        return "netBuy"
    if total < 0:
        return "netSell"
    return "neutral"


def load_a4(years=None):
    """A4 -> (ticker, date, foreignNet, instNet). 수량 기준(운영과 동일)."""
    rows = []
    for fn in sorted(os.listdir(A4)):
        if not fn.endswith(".jsonl.gz"):
            continue
        if years and fn[:4] not in years:
            continue
        with gzip.open(os.path.join(A4, fn), "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if "_meta" in r:
                    continue
                bv, sv = r.get("buyVolume") or {}, r.get("sellVolume") or {}
                fn_ = sum(bv.get(c, 0) - sv.get(c, 0) for c in FOREIGN)
                in_ = sum(bv.get(c, 0) - sv.get(c, 0) for c in INSTITUTION)
                rows.append((r["ticker"], r["date"], fn_, in_))
    return pd.DataFrame(rows, columns=["ticker", "date", "fNet", "iNet"])


def load_score_panel(years=None, horizon="d20"):
    """A5 -> (ticker, date, cSupply, presentAxes, fwd, axisScores)."""
    out = []
    for fn in sorted(os.listdir(SCORES)):
        if not fn.endswith(".jsonl.gz"):
            continue
        if years and fn[:4] not in years:
            continue
        with gzip.open(os.path.join(SCORES, fn), "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if "_meta" in r or r.get("raw") is None:
                    continue
                if (r.get("fwdStatus") or {}).get(horizon) != "OK":
                    continue
                fw = (r.get("fwd") or {}).get(horizon)
                if fw is None:
                    continue
                a = AW.axis_matrix(r.get("c") or {})
                if not a:
                    continue
                out.append((r["t"], r["d"], a.get("supplyDemand"),
                            a.get("fundamental"), a.get("valuation"), a.get("technical"),
                            float(fw)))
    return pd.DataFrame(out, columns=["ticker", "date", "sd", "fu", "va", "te", "fwd"])


def axis_from_trends(f_trend, i_trend):
    """외국인·기관 두 지표만으로 축 점수. 나머지 둘(대주주변동·자사주)은 A5 에서
    입력이 없어 항상 결측이므로 존재 지표끼리 재정규화된다 - 엔진과 같은 동작."""
    fs = TREND_SCORE.get(f_trend)
    isc = TREND_SCORE.get(i_trend)
    num = den = 0.0
    if fs is not None:
        num += W_FOREIGN * fs
        den += W_FOREIGN
    if isc is not None:
        num += W_INST * isc
        den += W_INST
    return num / den if den > 0 else np.nan


def _trend_score_vec(pos_cnt, total, n_eff):
    """롤링 집계 -> 라벨 점수. netBuysToTrend 와 같은 분기를 벡터로."""
    out = np.full(len(total), np.nan)
    valid = n_eff > 0
    out[valid & (pos_cnt == n_eff)] = TREND_SCORE["consistentBuy"]
    out[valid & (pos_cnt == 0)] = TREND_SCORE["consistentSell"]
    mid = valid & (pos_cnt > 0) & (pos_cnt < n_eff)
    out[mid & (total > 0)] = TREND_SCORE["netBuy"]
    out[mid & (total < 0)] = TREND_SCORE["netSell"]
    out[mid & (total == 0)] = TREND_SCORE["neutral"]
    return out


def rolling_variants(a4, windows=(5, 20)):
    """종목별 일별 시계열에 롤링을 한 번만 걸고 (ticker, date) 별 축 점수를 낸다.
    키마다 전체 이력을 다시 훑던 방식은 1,200,000키 x 2,600일이라 못 쓴다."""
    a4 = a4.sort_values(["ticker", "date"], kind="stable").reset_index(drop=True)
    g = a4.groupby("ticker", sort=False)
    out = a4[["ticker", "date"]].copy()
    for w in windows:
        cols = {}
        for side, col in (("f", "fNet"), ("i", "iNet")):
            r = g[col].rolling(w, min_periods=1)
            tot = r.sum().reset_index(level=0, drop=True).to_numpy()
            pos = g[col].apply(lambda x: (x > 0).rolling(w, min_periods=1).sum())                         .reset_index(level=0, drop=True).to_numpy()
            neff = g[col].rolling(w, min_periods=1).count()                          .reset_index(level=0, drop=True).to_numpy()
            cols[side] = _trend_score_vec(pos, tot, neff)
        num = np.zeros(len(a4)); den = np.zeros(len(a4))
        for side, wt in (("f", W_FOREIGN), ("i", W_INST)):
            ok = ~np.isnan(cols[side])
            num[ok] += wt * cols[side][ok]
            den[ok] += wt
        v = np.full(len(a4), np.nan)
        v[den > 0] = num[den > 0] / den[den > 0]
        out["sd{}".format(w)] = v
    # 20일 누적 순매수(연속값) - 라벨 분류를 안 거친 원값
    f20 = g["fNet"].rolling(20, min_periods=1).sum().reset_index(level=0, drop=True).to_numpy()
    i20 = g["iNet"].rolling(20, min_periods=1).sum().reset_index(level=0, drop=True).to_numpy()
    out["cum20"] = W_FOREIGN * f20 + W_INST * i20
    return out


def compute_variants(a4, keys, windows=(5, 20)):
    """selftest 용 참조 구현(느리다). 본 계산은 rolling_variants 를 쓴다 -
    둘이 같은 값을 내는지 selftest 가 확인한다."""
    a4 = a4.sort_values(["ticker", "date"], kind="stable")
    by = {t: g for t, g in a4.groupby("ticker", sort=False)}
    res = {w: [] for w in windows}
    cum20 = []
    for t, d in keys:
        g = by.get(t)
        if g is None:
            for w in windows:
                res[w].append(np.nan)
            cum20.append(np.nan)
            continue
        m = g["date"].to_numpy() <= d
        f_all, i_all = g["fNet"].to_numpy()[m], g["iNet"].to_numpy()[m]
        for w in windows:
            fw_, iw_ = f_all[-w:], i_all[-w:]
            res[w].append(axis_from_trends(net_buys_to_trend(fw_), net_buys_to_trend(iw_)))
        f20, i20 = f_all[-20:], i_all[-20:]
        cum20.append(W_FOREIGN * f20.sum() + W_INST * i20.sum() if len(f20) else np.nan)
    return res, np.array(cum20, dtype=float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate-year", default="")
    ap.add_argument("--years", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    years = set(a.validate_year.split(",")) if a.validate_year else (
        set(a.years.split(",")) if a.years else None)
    print("A5 점수 패널 로드 ...", flush=True)
    panel = load_score_panel(years)
    print("  {:,}행".format(len(panel)))
    print("A4 수급 로드 ...", flush=True)
    a4 = load_a4(years)
    print("  {:,}행  {:,}종목".format(len(a4), a4["ticker"].nunique()))

    print("변형 계산(롤링) ...", flush=True)
    rv = rolling_variants(a4)
    # 스냅샷일이 그 종목의 거래일이 아닐 수 있다 - 직전 거래일 값을 쓴다(운영의
    # "date <= asOf 중 최근 5개"와 같은 의미).
    # merge_asof 는 문자열 키를 못 받는다 - datetime 으로 바꿔 붙이고 되돌린다
    panel["_d"] = pd.to_datetime(panel["date"])
    rv["_d"] = pd.to_datetime(rv["date"])
    panel = pd.merge_asof(panel.sort_values("_d"),
                          rv.drop(columns=["date"]).sort_values("_d"),
                          on="_d", by="ticker", direction="backward")
    panel = panel.drop(columns=["_d"])

    ok = panel["sd"].notna() & panel["sd5"].notna()
    diff = (panel.loc[ok, "sd5"] - panel.loc[ok, "sd"]).abs()
    print("\n★ 재현 검증 - 5일 라벨로 만든 축 점수 vs A5 저장값")
    print("  비교 가능 {:,}행 / {:,}".format(int(ok.sum()), len(panel)))
    print("  |차이| 중앙 {:.3f}  p95 {:.3f}  1.0 초과 {:,}건 ({:.2%})".format(
        diff.median(), diff.quantile(0.95), int((diff > 1.0).sum()),
        float((diff > 1.0).mean())))

    print("\n라벨 분포(창 길이별)")
    for w, col in ((5, "sd5"), (20, "sd20")):
        vc = panel[col].value_counts(normalize=True).sort_index()
        print("  {:>2}일: ".format(w) + "  ".join(
            "{:.0f}점 {:.1%}".format(k, v) for k, v in vc.items()))

    # cum20 은 원단위 금액이라 0~100 축점수로 못 쓴다 - 날짜별 백분위로 바꾼다.
    panel["cum20pct"] = panel.groupby("date")["cum20"].rank(pct=True) * 100.0

    print("\n[IC] 수급 축 정의별 - 날짜별 횡단면 Spearman + Newey-West(lag 4)")
    uniq = sorted(panel["date"].unique())
    nt = int(round(len(uniq) * 0.60)); nv = int(round(len(uniq) * 0.15))
    segd = {"TRAIN": set(uniq[:nt]), "VALID": set(uniq[nt:nt + nv]), "TEST": set(uniq[nt + nv:])}

    def ic_of(sub, col):
        ics = []
        for _, g in sub.groupby("date"):
            x, y = g[col].to_numpy(), g["fwd"].to_numpy()
            m = np.isfinite(x) & np.isfinite(y)
            if m.sum() < 5:
                continue
            xr, yr = AW._rank(x[m]), AW._rank(y[m])
            if xr.std() == 0 or yr.std() == 0:
                continue
            ics.append(float(np.corrcoef(xr, yr)[0, 1]))
        ics = np.array(ics)
        return (ics.mean() if len(ics) else None, AW.nw_t(ics) if len(ics) else None)

    # 축 단독 IC
    print("  ── 수급 축 단독")
    for col, lab in (("sd", "현행(A5 저장값)"), ("sd5", "5일 라벨(재현)"),
                      ("sd20", "20일 라벨"), ("cum20pct", "20일 누적(연속·백분위)")):
        cells = []
        for k in ("TRAIN", "VALID", "TEST"):
            sub = panel[panel["date"].isin(segd[k])]
            ic, t = ic_of(sub, col)
            cells.append("{:+.4f}(t{:.1f})".format(ic, t) if ic is not None else "     -")
        print("    {:24} ".format(lab) + "  ".join(cells))

    # 전체 점수 IC - 수급 정의만 갈아끼운다
    print("  ── 전체 점수(35/30/15/20)에 수급 정의만 교체")
    W = AW.CURRENT
    for col, lab in (("sd", "현행 5일"), ("sd20", "20일 라벨"), ("cum20pct", "20일 누적")):
        cells = []
        for k in ("TRAIN", "VALID", "TEST"):
            sub = panel[panel["date"].isin(segd[k])].copy()
            A = sub[["fu", "va", "te", col]].to_numpy(dtype=float)
            sub["_s"] = AW.rescore(A, W)
            ic, t = ic_of(sub, "_s")
            cells.append("{:+.4f}(t{:.1f})".format(ic, t) if ic is not None else "     -")
        print("    {:24} ".format(lab) + "  ".join(cells))
    # 수급 제외(30/50/20/0) 기준선
    cells = []
    Wno = {"fundamental": .3, "valuation": .5, "technical": .2, "supplyDemand": 0.0}
    for k in ("TRAIN", "VALID", "TEST"):
        sub = panel[panel["date"].isin(segd[k])].copy()
        A = sub[["fu", "va", "te", "sd"]].to_numpy(dtype=float)
        sub["_s"] = AW.rescore(A, Wno)
        ic, t = ic_of(sub, "_s")
        cells.append("{:+.4f}(t{:.1f})".format(ic, t) if ic is not None else "     -")
    print("    {:24} ".format("수급 제외 30/50/20/0") + "  ".join(cells))

    os.makedirs(OUT_DIR, exist_ok=True)
    panel.to_parquet(os.path.join(OUT_DIR, "panel_variants.parquet"), index=False)
    print("\n저장: " + os.path.join(OUT_DIR, "panel_variants.parquet"))


def selftest():
    assert net_buys_to_trend([1, 2, 3]) == "consistentBuy"
    assert net_buys_to_trend([-1, -2]) == "consistentSell"
    assert net_buys_to_trend([3, -1]) == "netBuy"
    assert net_buys_to_trend([1, -3]) == "netSell"
    assert net_buys_to_trend([1, -1]) == "neutral"     # 합 0, 혼재
    assert net_buys_to_trend([]) is None and net_buys_to_trend(None) is None
    # 0 은 순매수로 안 센다(원본 v > 0)
    assert net_buys_to_trend([0, 0]) == "consistentSell"

    # 축 점수: 두 지표만 있으면 0.40/0.35 로 재정규화
    exp = (0.40 * 100 + 0.35 * 30) / 0.75
    assert abs(axis_from_trends("consistentBuy", "netSell") - exp) < 1e-9
    # 한쪽만 있으면 그쪽 점수 그대로
    assert abs(axis_from_trends("netBuy", None) - 70.0) < 1e-9
    # 둘 다 없으면 지어내지 않는다
    assert np.isnan(axis_from_trends(None, None))

    # compute_variants: 20일 연속 순매수는 100, 5일 창은 뒤 5개만 본다
    a4 = pd.DataFrame({"ticker": ["A"] * 6,
                       "date": ["2024-01-0%d" % i for i in range(1, 7)],
                       "fNet": [-5, 1, 1, 1, 1, 1], "iNet": [1] * 6})
    res, cum = compute_variants(a4, [("A", "2024-01-06")], windows=(5, 6))
    assert abs(res[5][0] - 100.0) < 1e-9, res      # 뒤 5일은 전부 순매수
    # 6일 창은 -5 를 포함해 fNet 합이 정확히 0 -> neutral(50), iNet 은 consistentBuy(100)
    assert abs(res[6][0] - (0.40 * 50 + 0.35 * 100) / 0.75) < 1e-9, res
    assert abs(cum[0] - (0.40 * 0 + 0.35 * 6)) < 1e-9, cum   # fNet 합 0, iNet 합 6
    # asOf 이후는 안 본다(PIT). 01-02 까지면 fNet=[-5,1] -> netSell(30)
    res2, _ = compute_variants(a4, [("A", "2024-01-02")], windows=(5,))
    assert abs(res2[5][0] - (0.40 * 30 + 0.35 * 100) / 0.75) < 1e-9, res2
    # 없는 종목은 지어내지 않는다
    res3, cum3 = compute_variants(a4, [("ZZZ", "2024-01-06")], windows=(5,))
    assert np.isnan(res3[5][0]) and np.isnan(cum3[0])

    # ★ 롤링 구현이 참조 구현과 같은 값을 내는가 - 이게 속도 최적화의 안전장치다
    rng = np.random.default_rng(0)
    big = pd.DataFrame({
        "ticker": np.repeat(["A", "B"], 60),
        "date": list(pd.date_range("2024-01-01", periods=60).strftime("%Y-%m-%d")) * 2,
        "fNet": rng.integers(-100, 100, 120), "iNet": rng.integers(-100, 100, 120)})
    rv = rolling_variants(big)
    keys = [(t, d) for t, d in zip(big["ticker"], big["date"])]
    ref, refc = compute_variants(big, keys)
    m = rv.set_index(["ticker", "date"])
    for j, (t, d) in enumerate(keys):
        r = m.loc[(t, d)]
        for w in (5, 20):
            assert abs(r["sd{}".format(w)] - ref[w][j]) < 1e-9, (t, d, w, r, ref[w][j])
        assert abs(r["cum20"] - refc[j]) < 1e-6, (t, d, r["cum20"], refc[j])
    print("selftest ok (15건)")


if __name__ == "__main__":
    main()
