#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Step 46 — Cross-Sectional Relative Strength Test (Real Backtest)

절대 추세(Donchian/mom)가 아닌 **종목 간 상대강도(Cross-Sectional Relative
Strength)**에 독립적 알파가 있는지 검증한다.

신호 (T일 종가 기준, T 종가에 진입, T+1부터 수익 반영 — 기존 프레임과 동일):
  - rel_ret_x = (sym x일 수익률) - (BTC x일 수익률), x ∈ {7, 20, 60}
  - CS rank_x = 일별 종단면 순위(상대수익률 순위 == raw 모멘텀 순위, BTC가
    상수라 동일 서열) → top 20% / bottom 20% Long-only 북
  - 가중: 동일가중 vs 변동성역가중(1/σ20)
  - 레짐: all / bull(BTC mom30>0, Step 43~45 정의) / bear

검증:
  1. Train(2023-05~2024-04) → Valid(2024-05~2024-12) → Test(2025-01~2026-08)
     OOS 엄격 적용. Test 결과로 config 선택 금지 (Train 기준 최선만 보고).
  2. CAGR/Sharpe/MDD/PF/turnover/median 종목 CAGR·Sharpe.
  3. ZEC/WLD 의존성: LOO + 종목별 분포 + ZEC·WLD 개별 제외.
  4. mom30(종목 30d)·funding(일별 basis premium) 상관 + 통제 후 잔차 예측력
     (Fama-MacBeth 횡단면 회귀).
  5. 연도별·Bull/Bear별 방향 일관성.
  6. 날짜별 CS IC (Spearman, pooled 아님) — 연도·레짐 조건별.

비용: 왕복 20bp (기존과 동일). 기존 파일 수정 없음. 커밋·push 없음.
"""
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import price_structure_sweep_v2 as base

HERE = Path(__file__).resolve().parent
OUT_JSON = HERE / "findings" / "cross-sectional-relative-strength-2026-08.json"
OUT_MD = HERE / "findings" / "cross-sectional-relative-strength-2026-08.md"

DATA = HERE / "data" / "crypto" / "basis" / "1h"
WINDOWS = base.WINDOWS
ENTRY_COST = base.ENTRY_COST
EXIT_COST = base.EXIT_COST

SYMBOLS = base.SYMBOLS
ALTS = [s for s in SYMBOLS if s != "BTCUSDT"]  # 27종 (BTC는 벤치마크/레짐)

HORIZONS = [7, 20, 60]
BUCKETS = ["top20", "bottom20"]
WEIGHTS = ["equal", "vol"]
REGIMES = ["all", "bull", "bear"]

_DAILY_CACHE = {}


def get_daily(sym):
    if sym not in _DAILY_CACHE:
        _DAILY_CACHE[sym] = base.load_daily(sym)
    return _DAILY_CACHE[sym]


def load_funding_daily(symbol):
    """1h premium_close -> 일별 mean (funding/basis 프록시)."""
    p = DATA / f"{symbol}_1h.parquet"
    if not p.exists():
        return None
    h1 = pd.read_parquet(p)
    tz = getattr(h1["time"].dtype, "tz", None)
    if tz is not None:
        dt = h1["time"].dt.tz_convert("Asia/Seoul")
    else:
        dt = h1["time"] + pd.Timedelta(hours=9)
    h1["kst_date"] = dt.dt.tz_localize(None).dt.normalize()
    s = h1.groupby("kst_date")["premium_close"].mean()
    s.index.name = "date"
    return s.sort_index()


def load_panel():
    """cross-sectional panel: close/mom30/funding/vol per alt(+BTC 모멘텀)."""
    closes = {}
    mom30s = {}
    fundings = {}
    vols = {}
    for sym in SYMBOLS:
        d = base.load_daily(sym)
        if d is None:
            continue
        closes[sym] = d["close"].rename(sym)
        mom30s[sym] = d["mom30"].rename(sym)
        ret = d["close"].pct_change()
        vols[sym] = ret.rolling(20, min_periods=10).std().rename(sym)
        f = load_funding_daily(sym)
        fundings[sym] = f if f is not None else pd.Series(index=d.index, dtype=float)
    close = pd.DataFrame(closes).sort_index()
    mom30 = pd.DataFrame(mom30s).sort_index()
    funding = pd.DataFrame(fundings).sort_index().reindex(close.index).ffill()
    vol = pd.DataFrame(vols).sort_index().reindex(close.index).ffill()
    btc_close = close["BTCUSDT"]
    btc_mom30 = mom30["BTCUSDT"]

    rel = {x: close.div(close.shift(x)).sub(1).sub(
        (btc_close.div(btc_close.shift(x)).sub(1)), axis=0) for x in HORIZONS}
    mom = {x: close.div(close.shift(x)).sub(1) for x in HORIZONS}
    return {"close": close, "mom30": mom30, "funding": funding, "vol": vol,
            "btc_mom30": btc_mom30, "rel": rel, "mom": mom}


def cs_rank(frame):
    """행(날짜)별 횡단면 백분위 순위. min_periods=8."""
    return frame.rank(axis=1, pct=True, method="average")


def bucket_position(rank_pct, bucket):
    if bucket == "top20":
        pos = (rank_pct >= 0.80).astype(int)
    else:
        pos = (rank_pct <= 0.20).astype(int)
    return pos


def forward_rets(close, h):
    """fwd_h[t] = close[t+h]/close[t]-1 (미래 수익, IC용)."""
    return close.shift(-h).div(close).sub(1)


def spearman_series(x, y):
    """날짜별 Spearman (행별 순위 상관). x,y: DataFrame(날짜×심볼)."""
    out = {}
    for ts in x.index:
        a = x.loc[ts]
        b = y.loc[ts]
        m = a.notna() & b.notna()
        if m.sum() < 8:
            continue
        ra = a[m].rank(method="average").values
        rb = b[m].rank(method="average").values
        ra = ra - ra.mean()
        rb = rb - rb.mean()
        den = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
        if den == 0:
            continue
        rho = float((ra * rb).sum() / den)
        out[ts] = rho
    return pd.Series(out)


def ic_stats(ic_series):
    v = ic_series.dropna()
    if len(v) == 0:
        return None
    mean = v.mean()
    std = v.std(ddof=1)
    icir = mean / std if std > 0 else 0.0
    t = mean / (std / np.sqrt(len(v))) if std > 0 else 0.0
    return {"n_days": int(len(v)), "mean_ic": round(float(mean), 4),
            "icir": round(float(icir), 4), "t_stat": round(float(t), 3),
            "pct_positive": round(float((v > 0).mean()), 4)}


def run_position_backtest(symbol, position, ws, daily=None):
    """특정 position 시리즈로 단일 심볼 윈도우 지표 (비용 포함)."""
    daily = daily if daily is not None else get_daily(symbol)
    if daily is None:
        return None
    pos = position.reindex(daily.index).fillna(0).astype(int)
    daily_ret, trades = base.backtest_window(daily, pos, {})
    s, e = ws
    win_trades = [t for t in trades if s <= t["entry_ts"] <= e]
    dm = base.metrics_from_daily(daily_ret, s, e, len(win_trades))
    if dm is None:
        return None
    return {"daily_ret": daily_ret, "position": pos, "metrics": dm}


def invested_during(pos):
    return ((pos == 1) | (pos.shift(1) == 1)).fillna(False).astype(bool)


def portfolio_return(sym_res, wmode, ws, vol_series_dict=None):
    """동일가중/변동성역가중 포트폴리오 일별 순수익 (윈도우만, 벡터화)."""
    rets = {}
    inv = {}
    for s, r in sym_res.items():
        dr = r["daily_ret"]
        msk = (dr.index >= ws[0]) & (dr.index <= ws[1])
        rets[s] = dr.loc[msk]
        inv[s] = invested_during(r["position"]).loc[msk]
    idx = pd.DatetimeIndex(sorted(set().union(*[r.index for r in rets.values()])))
    ret_mat = pd.DataFrame(rets).reindex(idx)
    inv_mat = pd.DataFrame(inv).reindex(idx).fillna(False).astype(bool)
    n_inv = inv_mat.sum(axis=1)
    rv = ret_mat.fillna(0.0).values
    iv = inv_mat.values
    port = np.zeros(len(idx))
    if wmode == "equal":
        for i in range(len(idx)):
            n = int(n_inv.iloc[i])
            if n == 0:
                continue
            port[i] = rv[i][iv[i]].sum() / n
    else:
        vol_df = pd.DataFrame({s: vol_series_dict[s] for s in rets}).reindex(idx)
        vol_med = vol_df.median(axis=1)
        vv = np.where(np.isfinite(vol_df.values) & (vol_df.values > 0),
                      vol_df.values, vol_med.values[:, None])
        for i in range(len(idx)):
            n = int(n_inv.iloc[i])
            if n == 0:
                continue
            v = vv[i][iv[i]]
            v = np.where(np.isfinite(v) & (v > 0), v, np.nan)
            if not np.any(np.isfinite(v)):
                port[i] = rv[i][iv[i]].sum() / n
                continue
            w = (1.0 / v)
            w[~np.isfinite(w)] = 0.0
            wsum = w.sum()
            if wsum <= 0:
                port[i] = rv[i][iv[i]].sum() / n
            else:
                port[i] = np.sum(rv[i][iv[i]] * w) / wsum
    return pd.Series(port, index=idx)


def portfolio_metrics(port, ws):
    if port is None or len(port) == 0 or port.abs().sum() == 0:
        return None
    year_frac = (ws[1] - ws[0]).days / 365.25
    cagr = ((1 + port).prod()) ** (1 / year_frac) - 1 if year_frac > 0 else 0.0
    ann_vol = np.std(port.values) * np.sqrt(365.25)
    sharpe = cagr / ann_vol if ann_vol > 0 else 0.0
    curve = (1 + port).cumprod()
    dd = (curve / curve.cummax() - 1).min()
    calmar = cagr / abs(dd) if dd != 0 else (np.inf if cagr > 0 else 0.0)
    pos = port[port > 0].sum()
    neg = -port[port < 0].sum()
    pf = (pos / neg) if neg > 0 else (np.inf if pos > 0 else 0.0)
    yearly = {int(y): float(((1 + g).prod() - 1))
              for y, g in port.groupby(port.index.year)}
    return {"cagr": cagr, "sharpe": sharpe, "max_dd": dd, "calmar": calmar,
            "pf": pf, "yearly": yearly, "n_invested_days": int((port != 0).sum())}


def regime_days(btc_mom30, reg):
    if reg == "all":
        return None
    if reg == "bull":
        return (btc_mom30.fillna(0) > 0)
    return (btc_mom30.fillna(0) <= 0)


def main():
    t0 = time.time()
    print(f"[0.0s] Step 46 — Cross-Sectional Relative Strength Test")
    print(f"Universe: {len(ALTS)} alts (BTC=benchmark). Costs 20bp rt.")
    print(f"OOS: Train {WINDOWS['train'][0].date()}~{WINDOWS['train'][1].date()} / "
          f"Valid {WINDOWS['valid'][0].date()}~{WINDOWS['valid'][1].date()} / "
          f"Test {WINDOWS['test'][0].date()}~{WINDOWS['test'][1].date()}")

    panel = load_panel()
    close = panel["close"]
    distinct = panel["btc_mom30"]
    vol_series = {s: panel["vol"][s] for s in ALTS}

    # --- 1) 날짜별 CS IC (풀 히스토리 + 연도·레짐 조건) ---
    ic = {}
    fwd_rets = {20: forward_rets(close[ALTS], 20)}
    for x in HORIZONS:
        sig = panel["rel"][x][ALTS]
        ic20 = spearman_series(sig, fwd_rets[20])
        ic[x] = {"fwd20_all": ic_stats(ic20)}
        # 연도별
        yrs = {}
        for y in sorted(set(ic20.index.year)):
            yrs[str(y)] = ic_stats(ic20[ic20.index.year == y])
        ic[x]["fwd20_by_year"] = yrs
        # 레짐별 (풀 히스토리; 레짐은 BTC mom30)
        bull_mask = distinct.fillna(0) > 0
        ic[x]["fwd20_bull"] = ic_stats(ic20[bull_mask.reindex(ic20.index).fillna(False)])
        ic[x]["fwd20_bear"] = ic_stats(ic20[(~bull_mask).reindex(ic20.index).fillna(True)])

    # --- 2) Fama-MacBeth 통제 회귀 (fwd20 ~ rel_x + mom30 + funding) ---
    # 대표 신호 x=20d. 날짜별 횡단면 회귀, 계수 수집.
    controls = {}
    rel20 = panel["rel"][20][ALTS]
    mom30 = panel["mom30"][ALTS]
    fund = panel["funding"][ALTS]
    fwd20 = fwd_rets[20]
    betas, resid_ics = [], []
    for ts in rel20.index:
        y = fwd20.loc[ts].astype(float)
        x = rel20.loc[ts].astype(float)
        m = mom30.loc[ts].astype(float)
        f = fund.loc[ts].astype(float)
        df = pd.DataFrame({"y": y, "x": x, "m": m, "f": f}).dropna()
        if len(df) < 10:
            continue
        X = np.column_stack([np.ones(len(df)), df["x"].values, df["m"].values, df["f"].values])
        Y = df["y"].values
        try:
            beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
        except np.linalg.LinAlgError:
            continue
        df["resid"] = Y - X @ beta
        betas.append(beta[1])
        row = pd.DataFrame({"x": df["x"], "m": df["m"], "f": df["f"], "y": df["y"]})
        Xc = np.column_stack([np.ones(len(df)), df["m"].values, df["f"].values])
        try:
            bc, *_ = np.linalg.lstsq(Xc, df["x"].values, rcond=None)
        except np.linalg.LinAlgError:
            continue
        x_resid = df["x"].values - Xc @ bc
        msk = np.isfinite(x_resid) & np.isfinite(df["y"].values)
        if msk.sum() < 8:
            continue
        ra = pd.Series(x_resid[msk]).rank(method="average").values
        rb = pd.Series(df["y"].values[msk]).rank(method="average").values
        ra = ra - ra.mean(); rb = rb - rb.mean()
        den = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
        if den > 0:
            resid_ics.append(float((ra * rb).sum() / den))
    betas = np.array(betas); resid_ics = np.array(resid_ics)
    controls = {
        "x=20d": {
            "n_dates": int(len(betas)),
            "beta_mean": round(float(betas.mean()), 5),
            "beta_t": round(float(betas.mean() / (betas.std(ddof=1) / np.sqrt(len(betas)))), 3),
            "beta_pct_positive": round(float((betas > 0).mean()), 4),
            "resid_ic_mean": round(float(resid_ics.mean()), 4),
            "resid_ic_t": round(float(resid_ics.mean() /
                                      (resid_ics.std(ddof=1) / np.sqrt(len(resid_ics)))), 3)
            if len(resid_ics) > 1 else None,
        }
    }
    # mom30·funding 상관 (풀드)
    pooled = pd.DataFrame({
        "rel20": rel20.stack(), "mom30": mom30.stack(), "funding": fund.stack()
    }).replace([np.inf, -np.inf], np.nan).dropna()
    controls["corr_rel20_mom30"] = round(float(pooled["rel20"].corr(pooled["mom30"])), 4)
    controls["corr_rel20_funding"] = round(float(pooled["rel20"].corr(pooled["funding"])), 4)

    # --- 3) 포트폴리오 config (bulk) ---
    print("[build] CS momentum book + portfolios...", flush=True)
    result = {}
    for x in HORIZONS:
        rank_pct = cs_rank(panel["rel"][x][ALTS])
        for buc in BUCKETS:
            pos_all = bucket_position(rank_pct, buc)
            for reg in REGIMES:
                rmask = regime_days(distinct, reg)
                pos = pos_all.copy()
                if rmask is not None:
                    pos = pos.mul(rmask.reindex(pos.index).astype(int), axis=0)
                sym_res = {}
                for sym in ALTS:
                    r = run_position_backtest(sym, pos[sym], WINDOWS["test"])
                    if r is not None:
                        sym_res[sym] = r
                if not sym_res:
                    continue
                for wm in WEIGHTS:
                    name = f"x{x}_buc{buc}_w{wm}_reg{reg}"
                    result[name] = {}
                    for wk in ["train", "valid", "test"]:
                        port = portfolio_return(sym_res, wm, WINDOWS[wk], vol_series)
                        pm = portfolio_metrics(port, WINDOWS[wk]) if port is not None else None
                        dsub = {s: r["metrics"] for s, r in sym_res.items()}
                        cagrs = [m["cagr"] for m in dsub.values()]
                        sharps = [m["sharpe"] for m in dsub.values()]
                        trades = [m["n_trades"] for m in dsub.values()]
                        turnovers = [m["turnover"] for m in dsub.values()]
                        result[name][wk] = {
                            "n_symbols": len(dsub),
                            "portfolio": pm,
                            "median_cagr": round(float(np.median(cagrs)), 4) if cagrs else None,
                            "median_sharpe": round(float(np.median(sharps)), 4) if sharps else None,
                            "n_positive_cagr": int(sum(1 for c in cagrs if c > 0)),
                            "n_positive_sharpe": int(sum(1 for s in sharps if s > 0)),
                            "mean_turnover": round(float(np.mean(turnovers)), 4) if turnovers else None,
                        }

    # --- 4) LOO (Test) — 핵심 config들에서 종목 의존성 ---
    loo_candidates = {}
    for cfg_key in ["x20_buctop20_wequal_regall", "x20_buctop20_wequal_regbull",
                    "x20_bucbottom20_wequal_regall", "x20_buctop20_wvol_regall"]:
        print(f"[loo] {cfg_key} ...", flush=True)
        x = 20
        rank_pct = cs_rank(panel["rel"][x][ALTS])
        buc = "top20" if "top20" in cfg_key else "bottom20"
        reg = "bull" if "regbull" in cfg_key else ("bear" if "regbear" in cfg_key else "all")
        wm = "vol" if "wvol" in cfg_key else "equal"
        base_res = result[cfg_key]["test"] if cfg_key in result else None
        loo = {}
        pos_base = bucket_position(rank_pct, buc)
        rmask = regime_days(distinct, reg)
        for leave in ALTS:
            alts_rm = [s for s in ALTS if s != leave]
            pos = pos_base[alts_rm].copy()
            if rmask is not None:
                pos = pos.mul(rmask.reindex(pos.index).astype(int), axis=0)
            sym_res = {}
            for sym in alts_rm:
                r = run_position_backtest(sym, pos[sym], WINDOWS["test"])
                if r is not None:
                    sym_res[sym] = r
            if not sym_res:
                continue
            port = portfolio_return(sym_res, wm, WINDOWS["test"], vol_series)
            pm = portfolio_metrics(port, WINDOWS["test"])
            loo[leave] = pm["sharpe"] if pm else None
        sh_vals = [v for v in loo.values() if v is not None]
        loo_candidates[cfg_key] = {
            "n_loo": int(len(sh_vals)),
            "base_test_sharpe": base_res["portfolio"]["sharpe"] if base_res else None,
            "mean_sharpe": round(float(np.mean(sh_vals)), 4) if sh_vals else None,
            "min_sharpe": round(float(np.min(sh_vals)), 4) if sh_vals else None,
            "max_sharpe": round(float(np.max(sh_vals)), 4) if sh_vals else None,
            "span": round(float(np.max(sh_vals) - np.min(sh_vals)), 4) if sh_vals else None,
            "worst_leave": min(loo, key=lambda s: loo[s] if loo[s] is not None else np.inf)
            if loo else None
        }

    # --- 5) ZEC/WLD 개별 제외 (Test, top20 equal all/bull) ---
    zec_wld = {}
    for cfg_base in ["x20_buctop20_wequal_regall", "x20_buctop20_wequal_regbull"]:
        x = 20
        rank_pct = cs_rank(panel["rel"][x][ALTS])
        reg = "bull" if "regbull" in cfg_base else "all"
        pos_base = bucket_position(rank_pct, "top20")
        rmask = regime_days(distinct, reg)
        out = {}
        for notrade in ["ZECUSDT", "WLDUSDT"]:
            sym_res = {}
            for sym in ALTS:
                if sym == notrade:
                    continue
                pos = pos_base[sym].copy()
                if rmask is not None:
                    pos = pos.mul(rmask.reindex(pos.index).astype(int), axis=0)
                r = run_position_backtest(sym, pos, WINDOWS["test"])
                if r is not None:
                    sym_res[sym] = r
            port = portfolio_return(sym_res, "equal", WINDOWS["test"], vol_series)
            pm = portfolio_metrics(port, WINDOWS["test"])
            out[notrade] = {"test_sharpe": pm["sharpe"] if pm else None,
                            "test_cagr": pm["cagr"] if pm else None}
        zec_wld[cfg_base] = out

    payload = {
        "design": {
            "purpose": "Cross-Sectional Relative Strength Test (Step 46)",
            "universe": f"{len(ALTS)} alts, BTC benchmark",
            "signals": {str(x): f"rel{x}d = sym return - BTC return; CS rank among alts" for x in HORIZONS},
            "oos_split": {k: [str(v[0].date()), str(v[1].date())] for k, v in WINDOWS.items()},
            "costs": "10bp rt + 5bp slippage/side (=20bp)",
            "buckets": ["top20", "bottom20"],
            "weights": ["equal", "vol (1/sigma20)"],
            "regimes": ["all", "bull(mom30>0)", "bear"],
            "selection_rule": "config 선택은 Train 기준으로만; Test 재선택 금지",
        },
        "ic": ic,
        "controls": controls,
        "results": result,
        "loo": loo_candidates,
        "zec_wld_removal": zec_wld,
        "runtime_sec": None,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")

    print(f"\n=== IC (fwd20, 풀 히스토리) ===")
    for x in HORIZONS:
        s = ic[x]["fwd20_all"]
        if s:
            print(f"  rel{x}d: meanIC={s['mean_ic']:+.4f} ICIR={s['icir']:+.3f} "
                  f"t={s['t_stat']:+.2f} pos%={s['pct_positive']:.1%} n={s['n_days']}")
    print(f"  rel20d by year:", {k: v['mean_ic'] for k, v in ic[20]['fwd20_by_year'].items()})
    print(f"  rel20d bull/bear:", ic[20]['fwd20_bull']['mean_ic'], ic[20]['fwd20_bear']['mean_ic'])
    print(f"  FM x rel20: beta_t={controls['x=20d']['beta_t']}, residIC={controls['x=20d']['resid_ic_mean']}"
          f" (corr mom30={controls['corr_rel20_mom30']}, funding={controls['corr_rel20_funding']})")

    print(f"\n=== Train 기준 config 리더보드 (Test 수치는 참고만, 선택은 Train) ===")
    rows = []
    for name, r in result.items():
        tr = r["train"]["portfolio"]
        va = r["valid"]["portfolio"]
        te = r["test"]["portfolio"]
        if tr is None:
            continue
        rows.append((name, tr, va, te, r["test"]["median_sharpe"], r["test"]["n_positive_cagr"]))
    rows.sort(key=lambda z: z[1]["sharpe"], reverse=True)
    for name, tr, va, te, medsh, npos in rows[:10]:
        print(f"  {name:30s} TRAIN sh={tr['sharpe']:+.3f} | VALID sh={va['sharpe'] if va else 0:+.3f} "
              f"| TEST sh={te['sharpe'] if te else 0:+.3f} cagr={te['cagr'] if te else 0:+.2%} "
              f"medSh={medsh:+.3f} posC={npos}")

    print(f"\n=== LOO (Test) ===")
    for k, v in loo_candidates.items():
        bs = v["base_test_sharpe"]
        bs_s = "-" if bs is None else f"{bs:.3f}"
        print(f"  {k}: base={bs_s} min={v['min_sharpe']:.3f} "
              f"max={v['max_sharpe']:.3f} span={v['span']:.3f} worst={v['worst_leave']}")
    print(f"  ZEC/WLD 제거: {zec_wld}")
    print(f"\nJSON: {OUT_JSON}  (runtime {round(time.time() - t0, 1)}s)")


if __name__ == "__main__":
    main()