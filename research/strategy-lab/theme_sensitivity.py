#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""테마 민감도 히트맵 — 정의 고정 v1.0(67577fe3) 그대로 구현. 판정 없음, 관찰용.

정본: research/strategy-lab/findings/theme-sensitivity-definition-2026-09.md. 문서와 다르면 문서가 맞다.

  python research/strategy-lab/theme_sensitivity.py --selftest   # 네트워크·데이터 없음
  python research/strategy-lab/theme_sensitivity.py              # FRED·yfinance 수집 + 계산(수 분)
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import theme_leadlag as LL  # noqa: E402  (테마·시장·PIT 규모 — 선행관계 v1.0 §3 그대로)

OUT_DIR = os.path.join(LL.ROOT, "reports", "2026-09-theme-sensitivity")
# (이름, 원천, 코드, 변환) — 정의 §2
FACTORS = [("Nasdaq-100", "fred", "NASDAQ100", "pct"),
           ("SOX", "yf", "^SOX", "pct"),
           ("USD/KRW", "fred", "DEXKOUS", "pct"),
           ("US10Y", "fred", "DGS10", "bp"),
           ("VIX", "fred", "VIXCLS", "diff"),
           ("WTI", "fred", "DCOILWTICO", "pct_pos")]
NW_LAG = 5
MIN_N = 120
WINDOWS = [("2016-2022", "2016-01-04", "2022-12-29"), ("2023-", "2023-01-02", None)] + \
          [(str(y), f"{y}-01-01", f"{y}-12-31") for y in range(2016, 2027)]


def fetch_factor(src, code):
    if src == "fred":
        import macro_common as MC
        rows = MC._retry(lambda: MC.fred(code), f"FRED {code}")
        if not rows:
            raise RuntimeError(f"FRED {code} 수집 실패")
        s = pd.Series({pd.Timestamp(d): v for d, v in rows})
    else:
        import yfinance as yf
        h = yf.Ticker(code).history(start="2015-01-01", auto_adjust=False)
        if h.empty:
            raise RuntimeError(f"yfinance {code} 수집 실패")
        s = pd.Series(h["Close"].values, index=pd.to_datetime(h.index.tz_localize(None).date))
    return s.sort_index()[lambda x: ~x.index.duplicated(keep="last")]


def align(kr_dates, us, kind):
    """한국 t 에 u(t) = t 보다 엄격히 이전 최신 미국 관측. f_t = u(t_prev)→u(t) 변화, 같은 관측이면 결측(0 금지)."""
    kr = pd.DataFrame({"date": pd.DatetimeIndex(kr_dates)})
    u = pd.DataFrame({"u": us.index, "lvl": us.values})
    j = pd.merge_asof(kr, u, left_on="date", right_on="u", direction="backward", allow_exact_matches=False)
    lvl, prev, same = j["lvl"], j["lvl"].shift(1), j["u"].eq(j["u"].shift(1))
    if kind == "pct":
        f = lvl / prev - 1
    elif kind == "pct_pos":
        f = (lvl / prev - 1).where((lvl > 0) & (prev > 0))
    elif kind == "bp":
        f = (lvl - prev) * 100.0
    elif kind == "diff":
        f = lvl - prev
    else:
        raise ValueError(kind)
    f = f.mask(same | j["u"].isna() | j["u"].shift(1).isna())
    return pd.Series(f.values, index=pd.DatetimeIndex(kr_dates)), pd.Series(j["u"].values, index=pd.DatetimeIndex(kr_dates))


def ols_nw(y, X, L=NW_LAG):
    """OLS 계수와 NW(Bartlett lag L) t."""
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    g = X * (y - X @ b)[:, None]
    S = g.T @ g
    for l in range(1, L + 1):
        G = g[l:].T @ g[:-l]
        S += (1 - l / (L + 1)) * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    return b, b / np.sqrt(np.diag(V))


def fit(y, F, ctrl):
    """complete-case. F: 요인 DataFrame, ctrl: 통제 DataFrame 또는 None. 반환 {요인: (bp/1σ, t, n)}."""
    parts = [y.rename("y"), F] + ([ctrl] if ctrl is not None else [])
    D = pd.concat(parts, axis=1).dropna()
    if len(D) < MIN_N:
        return None
    cols = list(F.columns)
    X = np.column_stack([np.ones(len(D))] + ([D[c].values for c in ctrl.columns] if ctrl is not None else [])
                        + [D[c].values for c in cols])
    b, t = ols_nw(D["y"].values, X)
    k0 = 1 + (len(ctrl.columns) if ctrl is not None else 0)
    return {c: {"bp": round(float(b[k0 + i] * D[c].std() * 1e4), 2), "t": round(float(t[k0 + i]), 2), "n": len(D)}
            for i, c in enumerate(cols)}


def heatmap(M, Tm, rows, cols, title, path, vmax=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for fnt in ("Malgun Gothic", "AppleGothic", "NanumGothic"):
        if any(fnt in x.name for x in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = fnt
            break
    plt.rcParams["axes.unicode_minus"] = False
    vmax = vmax or max(1.0, float(np.nanpercentile(np.abs(M), 98)))
    cmap = plt.get_cmap("RdBu_r")
    rgba = cmap((np.clip(np.nan_to_num(M), -vmax, vmax) + vmax) / (2 * vmax))
    rgba[..., 3] = np.where(np.abs(np.nan_to_num(Tm)) >= 2, 1.0, 0.22)     # 밝기 = |t|
    rgba[np.isnan(M)] = (0.85, 0.85, 0.85, 1)
    fig, ax = plt.subplots(figsize=(1.1 * len(cols) + 3.5, 0.28 * len(rows) + 1.6))
    ax.imshow(rgba, aspect="auto")
    for i in range(len(rows)):
        for j in range(len(cols)):
            if not np.isnan(M[i, j]):
                ax.text(j, i, f"{M[i, j]:+.0f}", ha="center", va="center", fontsize=6.5,
                        color="black" if abs(Tm[i, j]) >= 2 else "#888")
    ax.set_xticks(range(len(cols)), cols, fontsize=8)
    ax.set_yticks(range(len(rows)), rows, fontsize=7)
    ax.set_title(title, fontsize=10)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(-vmax, vmax))
    fig.colorbar(sm, ax=ax, shrink=0.5, label="1σ 충격당 bp (흐린 칸 = |t|<2)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    tree, members, names, R, C, m = LL.build_inputs()
    cap = LL.pit_cap(R.index, LL.load_vwap(), C, LL.load_a3c_records())
    LL.check_samsung(cap)
    s = LL.size_factor(R, cap, m)
    T = LL.CM.theme_returns(R, members)
    ctrl = pd.DataFrame({"m": m, "s": s})

    raw, F, U = [], {}, {}
    for name, src, code, kind in FACTORS:
        us = fetch_factor(src, code)
        raw.append(pd.DataFrame({"factor": name, "code": code, "usDate": us.index.strftime("%Y-%m-%d"), "value": us.values}))
        F[name], U[name] = align(R.index, us, kind)
    F = pd.DataFrame(F)
    os.makedirs(OUT_DIR, exist_ok=True)
    rawdf = pd.concat(raw)
    buf = rawdf.to_csv(index=False, lineterminator="\n")
    open(os.path.join(OUT_DIR, "factors_raw.csv"), "w", encoding="utf-8", newline="").write(buf)
    rawsha = hashlib.sha256(buf.encode("utf-8")).hexdigest()[:16]

    keys = list(members)
    res = {"primary": {}, "secondary": {}}
    for wname, lo, hi in WINDOWS:
        sl = (T.index >= lo) & ((T.index <= hi) if hi else True)
        for kind, cc in (("primary", ctrl), ("secondary", None)):
            res[kind][wname] = {k: fit(T.loc[sl, k], F.loc[sl], None if cc is None else cc.loc[sl]) for k in keys}

    cols = [f[0] for f in FACTORS]
    short = [k.split(" · ")[-1] for k in keys]
    summary = {}
    for kind in ("primary", "secondary"):
        for wname, _, _ in WINDOWS:
            M = np.array([[np.nan if res[kind][wname][k] is None else res[kind][wname][k][c]["bp"] for c in cols] for k in keys])
            Tm = np.array([[np.nan if res[kind][wname][k] is None else res[kind][wname][k][c]["t"] for c in cols] for k in keys])
            summary[f"{kind}:{wname}"] = {"cells": int(np.isfinite(Tm).sum()), "absT_gt2": int((np.abs(Tm) > 2).sum()),
                                          "expectedByChance": round(0.05 * int(np.isfinite(Tm).sum()), 1)}
            if wname in ("2016-2022", "2023-"):
                lab = "시장·규모 통제 후 추가 노출" if kind == "primary" else "통제 없음(총노출, 보조)"
                heatmap(M, Tm, short, cols, f"테마 민감도 · {lab} · {wname}  (|t|>2 {summary[f'{kind}:{wname}']['absT_gt2']}칸 / 우연 기대 {summary[f'{kind}:{wname}']['expectedByChance']})",
                        os.path.join(OUT_DIR, f"heatmap-{kind}-{wname}.png"))
    years = [w[0] for w in WINDOWS[2:]]
    for c in cols:
        M = np.array([[np.nan if res["primary"][y][k] is None else res["primary"][y][k][c]["bp"] for y in years] for k in keys])
        Tm = np.array([[np.nan if res["primary"][y][k] is None else res["primary"][y][k][c]["t"] for y in years] for k in keys])
        heatmap(M, Tm, short, years, f"{c} 민감도 연도별 · 시장·규모 통제 후(1σ당 bp)",
                os.path.join(OUT_DIR, f"yearly-{c.replace('/', '')}.png"))

    meta = {"definition": "research/strategy-lab/findings/theme-sensitivity-definition-2026-09.md", "definitionCommit": "67577fe3",
            "dataTo": str(R.index[-1].date()), "factors": [{"name": n, "source": s_, "code": c_, "transform": k_} for n, s_, c_, k_ in FACTORS],
            "factorObs": {c: int(F[c].notna().sum()) for c in cols}, "factorsRawSha256": rawsha,
            "factorLastUsDate": {c: str(U[c].dropna().iloc[-1].date()) for c in cols},
            "summary": summary, "nwLag": NW_LAG, "minN": MIN_N}
    json.dump({"meta": meta, "results": res}, open(os.path.join(OUT_DIR, "sensitivity.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    for k, v in summary.items():
        if k.split(":")[1] in ("2016-2022", "2023-"):
            print(k, v)
    print("factorObs", meta["factorObs"], "saved", OUT_DIR)


def selftest():
    # 시점 규칙: 엄격히 이전 · 새 관측 없으면 결측 · WTI 음수 결측
    kr = pd.to_datetime(["2020-04-20", "2020-04-21", "2020-04-22", "2020-04-23"])
    us = pd.Series([10.0, 12.0, -5.0, 8.0], index=pd.to_datetime(["2020-04-17", "2020-04-20", "2020-04-21", "2020-04-22"]))
    f, u = align(kr, us, "pct")
    assert u.iloc[0] == pd.Timestamp("2020-04-17") and u.iloc[1] == pd.Timestamp("2020-04-20")   # 같은 날짜 미사용
    assert np.isnan(f.iloc[0]) and abs(f.iloc[1] - 0.2) < 1e-12
    fp, _ = align(kr, us, "pct_pos")
    assert np.isnan(fp.iloc[2]) and np.isnan(fp.iloc[3])                                       # 음수 가격 결측
    hol = pd.Series([1.0, 2.0], index=pd.to_datetime(["2020-04-16", "2020-04-17"]))
    fh, _ = align(pd.to_datetime(["2020-04-20", "2020-04-21"]), hol, "diff")
    assert np.isnan(fh.iloc[1])                                                                # 새 관측 없음 → 결측(0 아님)
    fb, _ = align(kr[:2], pd.Series([4.0, 4.1], index=pd.to_datetime(["2020-04-17", "2020-04-20"])), "bp")
    assert abs(fb.iloc[1] - 10.0) < 1e-9                                                       # 4.0%→4.1% = 10bp
    # 계수 복원 · NW lag0 = White
    rng = np.random.default_rng(3)
    n = 2000
    idx = pd.bdate_range("2016-01-01", periods=n)
    Fx = pd.DataFrame(rng.normal(0, 0.01, (n, 2)), index=idx, columns=["a", "b"])
    ctrl = pd.DataFrame({"m": rng.normal(0, 0.01, n), "s": rng.normal(0, 0.005, n)}, index=idx)
    y = pd.Series(0.5 * ctrl["m"] + 2.0 * Fx["a"] + rng.normal(0, 0.005, n), index=idx)
    r = fit(y, Fx, ctrl)
    assert abs(r["a"]["bp"] / (Fx["a"].std() * 1e4) - 2.0) < 0.1 and abs(r["b"]["t"]) < 3.5
    X = np.column_stack([np.ones(n), Fx["a"]])
    b, t0 = ols_nw(y.values, X, L=0)
    e = y.values - X @ b
    V = np.linalg.inv(X.T @ X) @ (X.T * e ** 2) @ X @ np.linalg.inv(X.T @ X)
    assert np.allclose(t0, b / np.sqrt(np.diag(V)))
    print("selftest ok")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    selftest() if ap.parse_args().selftest else main()
