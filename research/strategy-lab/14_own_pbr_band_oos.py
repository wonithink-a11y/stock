"""국내 자기 과거 대비 PBR 밴드 — 사전등록 findings/kr-own-pbr-band-preregistration-2026-09.md (동결 ae2ab2b9) 1회 실행.

  python research/strategy-lab/14_own_pbr_band_oos.py --selftest   # 합성 데이터, 네트워크·실데이터 없음
  python research/strategy-lab/14_own_pbr_band_oos.py              # 1회 실행 → findings/kr-own-pbr-band-results-2026-09.{md,json}

입력(수집기 산출, gitignore): data/krx-pbr-history/daily/*.parquet(Open API 일별) · pbr/*.parquet(KRX PBR 월말 단면).
사전등록에 없는 구현 선택(결과 전 고정, 여기 적는다):
  - 형성월 t = 2010-01 ~ 2015-12, 보유 = t+1 달(2010-02 ~ 2016-01). TRAIN = t ≤ 2012-12, TEST = t ≥ 2013-01.
  - 월 수익률 = 그 달 일별 (1 + FLUC_RT/100) 복리. 그 달 중 폐지면 마지막 거래일까지(나머지 0). t+1 달 행이 없으면 제외.
  - 유동성 = 월말까지 최근 20거래일 ACC_TRDVAL 평균(20일 미만이면 있는 날로) ≥ 1억원. 2010-01 은 19거래일.
  - 백분위 = (평균 순위 − 1)/(n − 1), n = 창 안 PBR>0 인 달 수(현재 달 포함) ≥ 36.
  - 회전율(편도) = 1 − |S_t ∩ S_{t−1}| / |S_t| (첫 달 1). 비용 = 회전율 × 33.5bp. EW 대조는 비용 없이(보수적).
  - PBR 단면 날짜(pykrx 달력)와 Open API 월말 거래일이 다르면 멈춘다.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "krx-pbr-history"
FIND = HERE / "findings"
F0, F1, SPLIT = "2010-01", "2015-12", "2013-01"
LOOKBACK, MIN_VALID, THRESH = 60, 36, 0.20
COST_BP = 33.5
LIQ = 1e8
SEED, REPS, BOOT = 20260926, 1000, 2000
GATE_N, GATE_MONTHS = 30, 24


# ── 재료 ──────────────────────────────────────────────────────────────
def monthly_from_daily(d):
    """일별 → (ticker, month) 월 수익률 · 월말 행(종가·이름·시장·유동성·시총). d: BAS_DD·ISU_CD·ISU_NM·FLUC_RT·ACC_TRDVAL·MKTCAP·market."""
    d = d.copy()
    d["date"] = pd.to_datetime(d["BAS_DD"])
    d["month"] = d["date"].dt.strftime("%Y-%m")
    d = d.sort_values(["ISU_CD", "date"])
    d["g"] = 1 + d["FLUC_RT"] / 100
    ret = d.groupby(["ISU_CD", "month"])["g"].prod() - 1
    d["liq20"] = d.groupby("ISU_CD")["ACC_TRDVAL"].transform(lambda s: s.rolling(20, min_periods=1).mean())
    cal = d.groupby("month")["date"].max()                       # 월말 거래일(시장 전체)
    last = d[d["date"] == d["month"].map(cal)]                   # 월말 거래일에 행이 있는 종목 = 그날 상장
    me = last.set_index(["ISU_CD", "month"])[["ISU_NM", "market", "liq20", "MKTCAP"]]
    return ret.rename("ret"), me, cal


def band_position(pbr_wide, lookback=LOOKBACK, min_valid=MIN_VALID):
    """pbr_wide: index=월(정렬), columns=ticker, 값=PBR(>0 만 유효). 반환 같은 모양의 백분위(정의 안 되면 NaN)."""
    v = pbr_wide.where(pbr_wide > 0)
    out = pd.DataFrame(np.nan, index=v.index, columns=v.columns)
    arr = v.to_numpy()
    for i in range(len(v)):
        w = arr[max(0, i - lookback + 1): i + 1]
        cur = arr[i]
        n = np.sum(~np.isnan(w), axis=0)
        less = np.sum(w < cur, axis=0)
        eq = np.sum(w == cur, axis=0)                            # 자기 자신 포함
        pct = (less + (eq - 1) / 2) / np.where(n > 1, n - 1, np.nan)
        pct[(n < min_valid) | np.isnan(cur)] = np.nan
        out.iloc[i] = pct
    return out


def is_spac(name):
    return pd.Series(name).str.contains("스팩|기업인수목적", regex=True).to_numpy()


# ── 포트폴리오 ────────────────────────────────────────────────────────
def build_panel(ret, me, pbr_long, band):
    """형성월 t 의 유니버스·신호·t+1 수익률 한 표."""
    months = sorted(me.index.get_level_values("month").unique())
    nxt = {m: n for m, n in zip(months[:-1], months[1:])}
    df = me.reset_index().rename(columns={"ISU_CD": "ticker"})
    df = df[df["month"].isin(nxt)]
    rd = ret.to_dict()
    df["ret_next"] = [rd.get((t, nxt[m]), np.nan) for t, m in zip(df["ticker"], df["month"])]
    df["ret_this"] = [rd.get((t, m), np.nan) for t, m in zip(df["ticker"], df["month"])]
    df = df.merge(pbr_long, on=["ticker", "month"], how="left")
    b = band.stack().rename("band").reset_index().rename(columns={"level_0": "month", "level_1": "ticker"})
    b.columns = ["month", "ticker", "band"]
    df = df.merge(b, on=["ticker", "month"], how="left")
    u = (df["market"].isin(["KOSPI", "KOSDAQ"]) & ~is_spac(df["ISU_NM"]) & df["ticker"].str.endswith("0")
         & (df["PBR"] > 0) & (df["liq20"] >= LIQ) & df["ret_next"].notna())
    return df[u].copy()


def portfolio_series(panel, mask_col):
    """월별: 셀 평균 t+1 수익률·종목 수·회전율 · EW."""
    rows, prev = [], set()
    for m, g in panel.groupby("month"):
        s = g[g[mask_col]]
        cur = set(s["ticker"])
        to = 1.0 if not prev else (1 - len(cur & prev) / len(cur) if cur else np.nan)
        rows.append({"month": m, "n": len(s), "cell": s["ret_next"].mean() if len(s) else np.nan,
                     "ew": g["ret_next"].mean(), "turnover": to})
        prev = cur
    r = pd.DataFrame(rows).set_index("month")
    r["excess"] = r["cell"] - r["ew"]
    r["cost"] = r["turnover"] * COST_BP / 1e4
    r["cell_net"] = r["cell"] - r["cost"]
    return r


def random_floor(panel, cells, rng, reps=REPS):
    """매월 유니버스에서 셀과 같은 수를 무작위로 뽑은 포트폴리오의 TRAIN 월평균 초과 — 셀별 → 반복마다 최대 → p95."""
    tr = panel[panel["month"] < SPLIT]
    groups = [(g["ret_next"].to_numpy(), {c: int(g[c].sum()) for c in cells}) for _, g in tr.groupby("month")]
    best = np.empty(reps)
    for k in range(reps):
        vals = []
        for c in cells:
            ex = [rng.choice(r, n, replace=False).mean() - r.mean() for r, nn in groups if (n := nn[c]) > 0]
            vals.append(np.mean(ex))
        best[k] = max(vals)
    return float(np.percentile(best, 95))


def stats(x):
    x = pd.Series(x).dropna()
    if not len(x):
        return {}
    cagr = (1 + x).prod() ** (12 / len(x)) - 1
    eq = (1 + x).cumprod()
    return {"months": len(x), "cagr": cagr, "sharpe": x.mean() / x.std() * np.sqrt(12) if x.std() > 0 else np.nan,
            "mdd": float((eq / eq.cummax() - 1).min())}


def boot_ci(x, rng):
    x = pd.Series(x).dropna().to_numpy()
    b = [rng.choice(x, len(x), replace=True).mean() for _ in range(BOOT)]
    return float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))


def judge(r, floor):
    tr, te = r[r.index < SPLIT], r[r.index >= SPLIT]
    gate = int((tr["n"] >= GATE_N).sum()) >= GATE_MONTHS and int((te["n"] >= GATE_N).sum()) >= GATE_MONTHS
    info = tr["excess"].mean() >= floor and te["excess"].mean() > 0
    econ = info and stats(te["cell_net"]).get("cagr", -9) > stats(te["ew"]).get("cagr", 9)
    ex = r["excess"].dropna()
    t = ex.mean() / (ex.std() / np.sqrt(len(ex))) if ex.std() > 0 else 0
    yearly = ex.groupby(ex.index.str[:4]).sum()
    conc = yearly.max() / ex.sum() if ex.sum() > 0 else np.inf
    robust = econ and t >= 2 and conc < 0.5
    v = "INCONCLUSIVE" if not gate else "ROBUST" if robust else "ECONOMIC" if econ else "INFORMATION" if info else "REJECT"
    return v, {"gate": gate, "train_excess": tr["excess"].mean(), "test_excess": te["excess"].mean(), "floor": floor,
               "t_all": t, "top_year_share": conc, "yearly_excess": yearly.to_dict()}


# ── 실행 ──────────────────────────────────────────────────────────────
def load():
    daily = pd.concat([pd.read_parquet(f) for f in sorted((DATA / "daily").glob("*.parquet"))], ignore_index=True)
    pbr = pd.concat([pd.read_parquet(f).assign(month=f.stem) for f in sorted((DATA / "pbr").glob("*.parquet"))], ignore_index=True)
    return daily, pbr


def run():
    daily, pbr = load()
    ret, me, cal = monthly_from_daily(daily)
    pdates = pbr.groupby("month")["date"].first()
    common = [m for m in cal.index if F0 <= m <= F1]
    bad = [m for m in common if m not in pdates or str(pdates[m]) != cal[m].date().isoformat()]
    if bad:
        raise SystemExit(f"PBR 단면 날짜 ≠ Open API 월말 거래일: {bad[:5]} — 멈춘다")
    wide = pbr.pivot_table(index="month", columns="ticker", values="PBR", aggfunc="first").sort_index()
    band = band_position(wide).loc[F0:F1]
    panel = build_panel(ret, me, pbr[["ticker", "month", "PBR"]], band)
    panel = panel[(panel["month"] >= F0) & (panel["month"] <= F1)]
    panel["A"] = panel["band"] <= THRESH
    panel["B"] = panel["A"] & (panel["ret_this"] > 0)
    cs_cut = panel.groupby("month")["PBR"].transform(lambda s: s.quantile(0.20))
    panel["CS"] = panel["PBR"] <= cs_cut
    for th in (0.10, 0.30):
        panel[f"A{int(th * 100)}"] = panel["band"] <= th
    rng = np.random.default_rng(SEED)
    floor = random_floor(panel, ["A", "B"], rng)
    out = {"floor": floor, "cells": {}, "record": {}}
    series = {c: portfolio_series(panel, c) for c in ["A", "B", "CS", "A10", "A30"]}
    for c in ["A", "B"]:
        r = series[c]
        v, d = judge(r, floor)
        per = {}
        for name, sl in (("TRAIN", r.index < SPLIT), ("TEST", r.index >= SPLIT), ("ALL", r.index == r.index)):
            x = r[sl]
            per[name] = {"avg_n": x["n"].mean(), "gross_excess_bp": x["excess"].mean() * 1e4,
                         "ci95_bp": [v_ * 1e4 for v_ in boot_ci(x["excess"], rng)],
                         "net_excess_bp": (x["excess"] - x["cost"]).mean() * 1e4, "turnover": x["turnover"].mean(),
                         "breakeven_rt_bp": (x["excess"].mean() / x["turnover"].mean() * 1e4) if x["turnover"].mean() > 0 else None,
                         "cell_net": stats(x["cell_net"]), "ew": stats(x["ew"])}
        out["cells"][c] = {"verdict": v, "detail": d, "periods": per}
    a, cs = series["A"], series["CS"]
    diff = a["cell"] - cs["cell"]
    out["contrast2"] = {"train_bp": diff[diff.index < SPLIT].mean() * 1e4, "test_bp": diff[diff.index >= SPLIT].mean() * 1e4,
                        "incremental": bool(diff[diff.index < SPLIT].mean() > 0 and diff[diff.index >= SPLIT].mean() > 0)}
    jac = [len(set(g[g.A].ticker) & set(g[g.CS].ticker)) / max(1, len(set(g[g.A].ticker) | set(g[g.CS].ticker)))
           for _, g in panel.groupby("month")]
    out["record"] = {"thresholds_excess_bp": {k: series[k]["excess"].mean() * 1e4 for k in ("A10", "A", "A30")},
                     "jaccard_A_CS_mean": float(np.mean(jac)),
                     "mcap_median_cell_vs_universe": [float(panel[panel.A]["MKTCAP"].median()), float(panel["MKTCAP"].median())],
                     "market_share_cellA": panel[panel.A]["market"].value_counts(normalize=True).to_dict(),
                     "universe_avg_n": float(panel.groupby("month").size().mean()),
                     "note_2016_plus": "§5.1 2016~ 기록은 일별 데이터 미수집(사전등록 §1 범위 밖) — 별도 수집 후 기록"}
    return out


def write(out):
    (FIND / "kr-own-pbr-band-results-2026-09.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(json.dumps({c: out["cells"][c]["verdict"] for c in out["cells"]}, ensure_ascii=False), "floor", out["floor"])


# ── 셀프테스트 ────────────────────────────────────────────────────────
def selftest():
    w = pd.DataFrame({"X": [1.0] * 40 + [0.5], "Y": [np.nan] * 1 + [2.0] * 40}, index=[f"m{i:02d}" for i in range(41)])
    b = band_position(w, lookback=60, min_valid=36)
    assert b.loc["m40", "X"] == 0.0, "현재가 창에서 최저 → 0"
    assert np.isnan(b.loc["m34", "X"]), "유효 35개월 → 정의 안 됨"
    assert abs(b.loc["m40", "Y"] - 0.5) < 1e-9, "전부 같은 값 → 평균 순위 0.5"
    assert list(is_spac(["하나금융스팩3호", "삼성전자", "기업인수목적7호"])) == [True, False, True]
    d = pd.DataFrame({"BAS_DD": ["20100104", "20100105", "20100201"], "ISU_CD": ["000010"] * 3, "ISU_NM": "a",
                      "FLUC_RT": [10.0, -10.0, 5.0], "ACC_TRDVAL": [2e8] * 3, "MKTCAP": [1] * 3, "market": "KOSPI"})
    ret, me, cal = monthly_from_daily(d)
    assert abs(ret[("000010", "2010-01")] - (1.1 * 0.9 - 1)) < 1e-12, "일별 복리"
    assert ("000010", "2010-01") in me.index
    r = pd.DataFrame({"n": [40] * 72, "excess": [0.01] * 72, "cell_net": [0.02] * 72, "ew": [0.01] * 72},
                     index=[f"{y}-{m:02d}" for y in range(2010, 2016) for m in range(1, 13)])
    v, _ = judge(r.assign(excess=r["excess"] + np.random.default_rng(1).normal(0, 1e-4, 72)), floor=0.005)
    assert v == "ROBUST", v
    v, _ = judge(r.assign(n=10), floor=0.0)
    assert v == "INCONCLUSIVE"
    v, _ = judge(r.assign(excess=-0.01), floor=0.0)
    assert v == "REJECT"
    print("14_own_pbr_band_oos selftest: 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    if ap.parse_args().selftest:
        sys.exit(selftest())
    write(run())
