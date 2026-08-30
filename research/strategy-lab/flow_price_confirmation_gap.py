#!/usr/bin/env python
"""Step 8 — Foreign Flow Step 6 vs Step 7 Gap Diagnosis.

목적: Step 6의 외국인 강매수 × 가격 미상승 5D cross-sectional(C−D) 효과가
Step 7 portfolio에서 TEST 손실로 전환된 원인을 분해한다.

Step 6 정의(그대로):
  - foreign_flow_ratio = foreign_net / total_amount
  - daily_return = close[t]/close[t-1] - 1
  - C 그룹 = foreign_flow_ratio 상위 20% ∩ daily_return 하위 50%
  - D 그룹 = foreign_flow_ratio 상위 20% ∩ daily_return 상위 50%
  - fwd_d5 = close[t+5]/close[t] - 1 (A4 close)
  - C−D spread: signal-date 단위 C평균 − D평균, 시간평균(daily equal-weight)

Step 7 정의(그대로):
  - signal universe = C 그룹(전체), 그중 foreign_flow_ratio 상위 Top 10, 동일가중
  - entry: signal일 다음 거래일 OPEN(A2a adjusted), exit: entry 후 5거래일 종가
  - cost: 30bps RT/포지션, 보유 5D

새 feature/임계값 최적화/새 전략 없음. 분석만.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.data.a2aProvider import A2aProvider  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA = os.path.join(REPO_ROOT, "research", "strategy-lab", "data", "a4", "a4-research-dataset.parquet")
OUT = os.path.join(REPO_ROOT, "research", "strategy-lab", "findings", "flow-price-confirmation-gap-diagnosis-2026-08.md")

COST_BPS = 30.0
HOLD = 5

SPLIT = {
    "TRAIN": ("2016-01-01", "2022-07-01"),
    "VALID": ("2022-07-01", "2024-01-01"),
    "TEST":  ("2024-01-01", "2026-12-31"),
}


def newey_west_tstat(series):
    x = series.dropna().values
    n = len(x)
    if n < 3:
        return np.nan
    lags = int(np.floor(4 * (n / 100) ** (2 / 9)))
    mean = x.mean()
    demeaned = x - mean
    gamma0 = np.mean(demeaned ** 2)
    nw_var = gamma0
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)
        gamma_l = np.mean(demeaned[l:] * demeaned[:-l])
        nw_var += 2 * w * gamma_l
    se = np.sqrt(nw_var / n)
    return mean / se if se > 0 else np.nan


def series_stats(s):
    s = s.dropna()
    n = len(s)
    if n == 0:
        return {"mean": np.nan, "t_stat": np.nan, "nw_t": np.nan, "n_days": 0}
    mean = s.mean()
    std = s.std(ddof=1)
    t = mean / (std / np.sqrt(n)) if std > 0 and n > 1 else np.nan
    return {"mean": float(mean), "t_stat": float(t) if not np.isnan(t) else np.nan,
            "nw_t": newey_west_tstat(s), "n_days": int(n)}


def load_a4():
    df = pd.read_parquet(DATA, columns=["ticker", "date", "foreign_net", "total_amount", "close"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    df["fwd_d5"] = df.groupby("ticker")["close"].transform(lambda s: s.shift(-5) / s - 1)
    df["fwd_d20"] = df.groupby("ticker")["close"].transform(lambda s: s.shift(-20) / s - 1)
    df["fwd_d60"] = df.groupby("ticker")["close"].transform(lambda s: s.shift(-60) / s - 1)
    df["foreign_flow_ratio"] = df["foreign_net"] / df["total_amount"].replace(0, np.nan)
    df["daily_return"] = df.groupby("ticker")["close"].transform(lambda s: s / s.shift(1) - 1)
    return df


class PriceIndex:
    """티커별 정렬된 가격시계열 인덱스로 벡터화된 날짜/수익 매핑 제공."""

    def __init__(self, prices):
        self.tickers = {}
        for tk, px in prices.items():
            dts = list(px.index)
            o = px["open"].to_numpy()
            c = px["close"].to_numpy()
            self.tickers[tk] = {
                "dates": dts,
                "idx": {d: i for i, d in enumerate(dts)},
                "open": o.astype(np.float64),
                "close": c.astype(np.float64),
            }

    def get(self, tk):
        return self.tickers.get(tk)


def build_c_group_panel(a4, price_idx):
    """C 그룹 각 (ticker, signal_date)에 대해 entry timing별 5D 수익 계산(벡터화)."""
    sub = a4.dropna(subset=["foreign_flow_ratio", "daily_return"]).copy()
    sub["f_rank"] = sub.groupby("date")["foreign_flow_ratio"].rank(pct=True)
    sub["p_rank"] = sub.groupby("date")["daily_return"].rank(pct=True)
    c = sub[(sub["f_rank"] > 0.80) & (sub["p_rank"] < 0.50)][
        ["ticker", "date", "foreign_flow_ratio", "daily_return", "fwd_d5"]].copy()
    c = c.rename(columns={"date": "signal_date"})

    recs = []
    for tk, g in c.groupby("ticker"):
        p = price_idx.get(tk)
        if p is None:
            continue
        idx_map = p["idx"]
        dts = p["dates"]
        o = p["open"]
        cl = p["close"]
        n = len(dts)
        sig_idx = np.array([idx_map[d] for d in g["signal_date"] if d in idx_map], dtype=np.int64)
        if len(sig_idx) == 0:
            continue
        valid = sig_idx + 1 + (HOLD - 1) < n
        sig_idx = sig_idx[valid]
        entry = sig_idx + 1
        ex = sig_idx + HOLD
        if len(sig_idx) == 0:
            continue
        # close2close, open2close, close1_2close
        c0 = cl[sig_idx]
        c1 = cl[sig_idx + 1]
        c5 = cl[sig_idx + HOLD]
        o1 = o[entry]
        ok = np.isfinite(c0) & (c0 > 0) & np.isfinite(c1) & np.isfinite(c5) & (c5 > 0) & np.isfinite(o1) & (o1 > 0)
        sig_idx = sig_idx[ok]
        if len(sig_idx) == 0:
            continue
        entry = sig_idx + 1
        c0 = cl[sig_idx]; c1 = cl[sig_idx + 1]; c5 = cl[sig_idx + HOLD]; o1 = o[entry]
        g2 = g.set_index("signal_date").loc[[dts[i] for i in sig_idx]]
        frame = pd.DataFrame({
            "ticker": tk,
            "signal_date": [dts[i] for i in sig_idx],
            "f_ratio": g2["foreign_flow_ratio"].to_numpy(),
            "close2close": c5 / c0 - 1.0,
            "open2close": c5 / o1 - 1.0,
            "close1_2close": c5 / c1 - 1.0,
        })
        recs.append(frame)
    return pd.concat(recs, ignore_index=True)


def portfolio_daily(panel, price_idx, top_n, cost_bp):
    """C그룹 선택(foreign_flow_ratio desc를 signal_date별 상위 top_n) → open entry 5D hold
    일별 return 시뮬레이션. cost_bp는 exit day에 차감. (벡터화)
    returns: (daily_Series, positions DataFrame)"""
    sel = panel.sort_values(["signal_date", "f_ratio"], ascending=[True, False])
    if top_n is not None:
        sel = sel.groupby("signal_date", group_keys=False).head(top_n)
    # 각 행 -> (ticker, entry_date, 5일 close/open). 벡터 구성
    recs = {"date": [], "ret": []}
    pos = {"ticker": [], "entry_date": [], "exit_date": [], "o": [], "closes": []}
    for tk, g in sel.groupby("ticker"):
        p = price_idx.get(tk)
        if p is None:
            continue
        idx_map = p["idx"]
        dts = p["dates"]
        o = p["open"]
        cl = p["close"]
        n = len(dts)
        sig_idx = np.array([idx_map[d] for d in g["signal_date"] if d in idx_map], dtype=np.int64)
        if len(sig_idx) == 0:
            continue
        valid = sig_idx + HOLD < n
        sig_idx = sig_idx[valid]
        if len(sig_idx) == 0:
            continue
        entry = sig_idx + 1
        o1 = o[entry]
        closes = np.stack([cl[entry + k] for k in range(HOLD)], axis=1)  # (m,5)
        ok = np.isfinite(o1) & (o1 > 0) & np.all(np.isfinite(closes), axis=1) & np.all(closes > 0, axis=1)
        sig_idx = sig_idx[ok]
        if len(sig_idx) == 0:
            continue
        entry = sig_idx + 1
        o1 = o[entry]
        closes = np.stack([cl[entry + k] for k in range(HOLD)], axis=1)
        # 일별 return
        ret0 = closes[:, 0] / o1 - 1.0
        rets = [ret0]
        for k in range(1, HOLD):
            r = closes[:, k] / closes[:, k - 1] - 1.0
            if k == HOLD - 1:
                r = r - cost_bp / 1e4
            rets.append(r)
        for k in range(HOLD):
            dates_k = [dts[e + k] for e in entry]
            recs["date"].extend(dates_k)
            recs["ret"].extend(rets[k].tolist())
        pos["ticker"].extend([tk] * len(sig_idx))
        pos["entry_date"].extend([dts[e] for e in entry])
        pos["exit_date"].extend([dts[e + HOLD - 1] for e in entry])
        pos["o"].extend(o1.tolist())
        pos["closes"].extend([rows for rows in closes.tolist()])
    dd = pd.DataFrame(recs)
    dret = dd.groupby("date")["ret"].mean()
    posdf = pd.DataFrame(pos)
    return dret, posdf


def main():
    print("Loading A4 + A2a...")
    a4 = load_a4()
    tickers = set(a4["ticker"].unique())
    a2a = A2aProvider(repo_root=REPO_ROOT, use_cache=True)
    start = a4["date"].min().strftime("%Y-%m-%d")
    end = a4["date"].max().strftime("%Y-%m-%d")
    bars = a2a.load(tickers, start, end, universe_hash="flow-gap-diagnosis")
    prices = {t: df[["open", "close"]].copy() for t, df in bars.items()}
    pi = PriceIndex(prices)
    print(f"  A4 rows={len(a4)} tickers={len(tickers)} | A2a tickers={len(prices)}")

    # universe EW daily return
    bh = []
    for tk, g in a4.groupby("ticker"):
        g = g.sort_values("date")
        bh.append(pd.DataFrame({"date": g["date"], "ret": (g["close"].shift(-1) / g["close"] - 1).values}))
    bh = pd.concat(bh, ignore_index=True).dropna()
    bh_ret = bh.groupby("date")["ret"].mean()

    panel = build_c_group_panel(a4, pi)
    print(f"  C-group panel rows = {len(panel)}")

    lines = []
    lines.append("# Flow Price Confirmation — Step 6 vs Step 7 Gap Diagnosis")
    lines.append("")
    lines.append("> 분석 일시: 2026-08-28 | 데이터: A4 + A2a adjusted")
    lines.append(f"> 기간: {a4['date'].min().date()} ~ {a4['date'].max().date()} | 종목: {a4['ticker'].nunique()}")
    lines.append("> 목적: Step 6 cross-sectional C−D 효과가 Step 7 portfolio TEST 손실로 전환된 원인 분해")
    lines.append("> 設定: 신규 feature·임계값 최적화·새 전략·Step6/7 정의 변경 없음")
    lines.append("")

    # ── 1. Step 6 C-D 재현 ──
    lines.append("## 1. Step 6 C−D spread 재현 (signal-day close→forward close)")
    lines.append("")
    lines.append("| Horizon | Period | C−D | NW t | N |")
    lines.append("|---|---:|---:|---:|---:|")
    for hname, fwd in [("5D", "fwd_d5"), ("20D", "fwd_d20"), ("60D", "fwd_d60")]:
        for pname, (s, e) in SPLIT.items():
            sub = a4[(a4["date"] >= s) & (a4["date"] < e)]
            # foreign top 내부 price bottom - price top
            sub = sub.dropna(subset=["foreign_flow_ratio", "daily_return", fwd]).copy()
            sub["f_rank"] = sub.groupby("date")["foreign_flow_ratio"].rank(pct=True)
            sub["p_rank"] = sub.groupby("date")["daily_return"].rank(pct=True)
            top = sub[sub["f_rank"] > 0.80]
            c = top[top["p_rank"] < 0.50].groupby("date")[fwd].mean()
            d = top[top["p_rank"] >= 0.50].groupby("date")[fwd].mean()
            cd = c.sub(d)
            st = series_stats(cd)
            lines.append(f"| {hname} | {pname} | {st['mean']:+.4f} | {st['nw_t']:+.3f} | {st['n_days']} |")
    lines.append("")
    lines.append("> Step 6 §3(5D)와 대조: TRAIN +0.0038(NW+12.24) / VALID +0.0021(+3.17) / TEST +0.0012(+2.01) — 아래와 일치해야 재현.")
    lines.append("")

    # ── 2. Entry timing ──
    lines.append("## 2. Entry timing decomposition (C 그룹, signal-date 평균 5D)")
    lines.append("")
    lines.append("| Period | close[t]→close[t+5] | open[t+1]→close[t+5] | close[t+1]→close[t+5] |")
    lines.append("|---|---:|---:|---:|")
    for pname, (s, e) in SPLIT.items():
        sub = panel[(panel["signal_date"] >= s) & (panel["signal_date"] < e)]
        st_c = series_stats(sub.groupby("signal_date")["close2close"].mean())
        st_o = series_stats(sub.groupby("signal_date")["open2close"].mean())
        st_1 = series_stats(sub.groupby("signal_date")["close1_2close"].mean())
        lines.append(f"| {pname} | {st_c['mean']:+.4f}(NW {st_c['nw_t']:+.2f}) | "
                     f"{st_o['mean']:+.4f}(NW {st_o['nw_t']:+.2f}) | "
                     f"{st_1['mean']:+.4f}(NW {st_1['nw_t']:+.2f}) |")
    lines.append("")
    lines.append("> close2close − open2close = '다음날 OPEN 진입'으로 잃는 갭·overnight·첫날분." )
    lines.append("")

    # ── 3. Concentration ──
    lines.append("## 3. Concentration decomposition (open[t+1] entry, 0bps gross, 일평균)")
    lines.append("")
    lines.append("| Period | 전체 C그룹 | Top 10 | Top 20 | Top 50 |")
    lines.append("|---|---:|---:|---:|---:|")
    for pname, (s, e) in SPLIT.items():
        sub = panel[(panel["signal_date"] >= s) & (panel["signal_date"] < e)]
        cells = []
        for tn in [None, 10, 20, 50]:
            d, _ = portfolio_daily(sub, pi, tn, 0.0)
            cells.append(series_stats(d))
        lines.append(f"| {pname} | {cells[0]['mean']:+.4f}(NW {cells[0]['nw_t']:+.2f}) | "
                     f"{cells[1]['mean']:+.4f}(NW {cells[1]['nw_t']:+.2f}) | "
                     f"{cells[2]['mean']:+.4f}(NW {cells[2]['nw_t']:+.2f}) | "
                     f"{cells[3]['mean']:+.4f}(NW {cells[3]['nw_t']:+.2f}) |")
    lines.append("")

    # ── 4. Cost ──
    lines.append("## 4. Cost decomposition (Top 10, open[t+1] entry, 일평균)")
    lines.append("")
    lines.append("| Period | 0bps | 10bps | 30bps | 30bps(CAGR) |")
    lines.append("|---|---:|---:|---:|---:|")
    for pname, (s, e) in SPLIT.items():
        sub = panel[(panel["signal_date"] >= s) & (panel["signal_date"] < e)]
        cells = []
        for cost in [0.0, 10.0, 30.0]:
            d, _ = portfolio_daily(sub, pi, 10, cost)
            st = series_stats(d)
            # CAGR 간이
            n = st["n_days"]
            eq = np.prod(1 + d.dropna().values)
            cagr = eq ** (252.0 / n) - 1 if n > 0 else np.nan
            cells.append((st, cagr))
        lines.append(f"| {pname} | {cells[0][0]['mean']:+.4f}(NW {cells[0][0]['nw_t']:+.2f}) | "
                     f"{cells[1][0]['mean']:+.4f}(NW {cells[1][0]['nw_t']:+.2f}) | "
                     f"{cells[2][0]['mean']:+.4f}(NW {cells[2][0]['nw_t']:+.2f}) | "
                     f"{cells[2][1]:+.4f} |")
    lines.append("")

    # ── 5. Market-relative (TEST) ──
    lines.append("## 5. Market-relative decomposition (TEST)")
    lines.append("")
    lines.append("| Portfolio 정의 | C raw 일평균 | Universe EW 일평균 | Excess 일평균 |")
    lines.append("|---|---:|---:|---:|")
    test_panel = panel[(panel["signal_date"] >= SPLIT["TEST"][0]) & (panel["signal_date"] < SPLIT["TEST"][1])]
    for label, topn in [("C그룹 전체(open,0bp)", None), ("Top10(open,0bp)", 10), ("Top10(open,30bp)", 10)]:
        cost = 30.0 if "30" in label else 0.0
        d, _ = portfolio_daily(test_panel, pi, topn, cost)
        raw = d.mean()
        mkt = bh_ret.reindex(d.index).mean()
        exc = raw - mkt
        lines.append(f"| {label} | {raw:+.4f} | {mkt:+.4f} | {exc:+.4f} |")
    lines.append("")

    # ── 6. Cross-sectional vs time-series ──
    lines.append("## 6. Cross-sectional vs time-series (signal-date C그룹 mean 5D vs universe mean 5D)")
    lines.append("")
    lines.append("| Period | C mean | Universe mean | Spread=C−U | median | 양(+)ratio | P5 | P95 | N |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    u5 = a4.dropna(subset=["fwd_d5"]).groupby("date")["fwd_d5"].mean()
    for pname, (s, e) in SPLIT.items():
        sub = panel[(panel["signal_date"] >= s) & (panel["signal_date"] < e)]
        c_mean = sub.groupby("signal_date")["close2close"].mean().dropna()
        uni = u5.reindex(c_mean.index)
        sp = c_mean - uni
        lines.append(f"| {pname} | {c_mean.mean():+.4f} | {uni.mean():+.4f} | {sp.mean():+.4f} | "
                     f"{sp.median():+.4f} | {(sp>0).mean():.3f} | {sp.quantile(0.05):+.4f} | "
                     f"{sp.quantile(0.95):+.4f} | {len(sp)} |")
    lines.append("")

    # ── 7. Ticker concentration (TEST, Top10, 30bps net) ──
    test10_d, test10_pos = portfolio_daily(test_panel, pi, 10, COST_BPS)
    pos_pnl = pd.DataFrame({
        "ticker": test10_pos["ticker"],
        "o": test10_pos["o"].astype(float),
        "closes": test10_pos["closes"],
    })
    pnl_rows = []
    for _, r in pos_pnl.iterrows():
        gr = r["closes"][-1] / r["o"] - 1.0
        pnl_rows.append({"ticker": r["ticker"], "gross": gr, "net": gr - COST_BPS / 1e4})
    pp = pd.DataFrame(pnl_rows)
    by_tk = pp.groupby("ticker").agg(n=("net", "count"), gross=("gross", "sum"),
                                     net=("net", "sum")).sort_values("net")
    total_net = by_tk["net"].sum()
    lines.append("## 7. 종목 집중 — TEST Top10 portfolio (30bps net) ticker 분해")
    lines.append("")
    lines.append(f"- TEST Net PnL 합 = {total_net:+.4f} ({len(pp)} 포지션, {by_tk.shape[0]} 종목)")
    if total_net != 0:
        lines.append(f"- 최대 손실 종목 = {by_tk['net'].min():+.4f} ({by_tk['net'].idxmin()}), "
                     f"최대 이익 종목 = {by_tk['net'].max():+.4f} ({by_tk['net'].idxmax()})")
        lines.append(f"- 상위 5 손실 종목 net 합 = {by_tk['net'].head(5).sum():+.4f} "
                     f"(기여 {by_tk['net'].head(5).sum()/total_net:.3f})")
        lines.append(f"- 상위 5 이익 종목 net 합 = {by_tk['net'].tail(5).sum():+.4f} "
                     f"(기여 {by_tk['net'].tail(5).sum()/total_net:.3f})")
    lines.append("")
    lines.append("### 상위 5 손실 종목")
    lines.append("")
    lines.append("| ticker | n | gross | net |")
    lines.append("|---|---:|---:|---:|")
    for tk, r in by_tk.head(5).iterrows():
        lines.append(f"| {tk} | {int(r['n'])} | {r['gross']:+.4f} | {r['net']:+.4f} |")
    lines.append("")
    lines.append("### 상위 5 이익 종목")
    lines.append("")
    lines.append("| ticker | n | gross | net |")
    lines.append("|---|---:|---:|---:|")
    for tk, r in by_tk.tail(5).iterrows():
        lines.append(f"| {tk} | {int(r['n'])} | {r['gross']:+.4f} | {r['net']:+.4f} |")
    lines.append("")

    lines.append("## 8. 최종 원인 분류")
    lines.append("")
    lines.append("(위 수치를 종합해 아래 판정 섹션에 채운다 — 스크립트가 자동으로 채우지 않음)")
    lines.append("")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nSaved: {OUT}")

    print("\n=== 1. Step6 C-D 재현 (5D) ===")
    for pname, (s, e) in SPLIT.items():
        sub = a4[(a4["date"] >= s) & (a4["date"] < e)].dropna(subset=["foreign_flow_ratio", "daily_return", "fwd_d5"])
        sub["f_rank"] = sub.groupby("date")["foreign_flow_ratio"].rank(pct=True)
        sub["p_rank"] = sub.groupby("date")["daily_return"].rank(pct=True)
        top = sub[sub["f_rank"] > 0.80]
        c = top[top["p_rank"] < 0.50].groupby("date")["fwd_d5"].mean()
        d = top[top["p_rank"] >= 0.50].groupby("date")["fwd_d5"].mean()
        st = series_stats(c.sub(d))
        print(f"  {pname:6s} C-D5D={st['mean']:+.4f}(NW {st['nw_t']:+.2f})")
    print("\n=== 2. Entry timing (C그룹 일평균) ===")
    for pname, (s, e) in SPLIT.items():
        sub = panel[(panel["signal_date"] >= s) & (panel["signal_date"] < e)]
        c2 = series_stats(sub.groupby("signal_date")["close2close"].mean())
        o2 = series_stats(sub.groupby("signal_date")["open2close"].mean())
        c1 = series_stats(sub.groupby("signal_date")["close1_2close"].mean())
        print(f"  {pname:6s} c2c={c2['mean']:+.4f} o2c={o2['mean']:+.4f} c1c={c1['mean']:+.4f}")
    print("\n=== 3. Concentration (open,0bp 일평균) ===")
    for pname, (s, e) in SPLIT.items():
        sub = panel[(panel["signal_date"] >= s) & (panel["signal_date"] < e)]
        row = []
        for tn in [None, 10, 20, 50]:
            d, _ = portfolio_daily(sub, pi, tn, 0.0)
            row.append(f"{'all' if tn is None else 'T'+str(tn)}={series_stats(d)['mean']:+.4f}")
        print(f"  {pname:6s} | {' '.join(row)}")
    print("\n=== 4. Cost (Top10, open 일평균) ===")
    for pname, (s, e) in SPLIT.items():
        sub = panel[(panel["signal_date"] >= s) & (panel["signal_date"] < e)]
        row = []
        for cost in [0.0, 10.0, 30.0]:
            d, _ = portfolio_daily(sub, pi, 10, cost)
            row.append(f"{cost:.0f}bp={series_stats(d)['mean']:+.4f}")
        print(f"  {pname:6s} | {' '.join(row)}")
    print("\n=== 5. Market-relative TEST ===")
    d, _ = portfolio_daily(test_panel, pi, 10, 30.0)
    print(f"  Top10 30bp raw={d.mean():+.4f} mkt={bh_ret.reindex(d.index).mean():+.4f} exc={d.mean()-bh_ret.reindex(d.index).mean():+.4f}")


if __name__ == "__main__":
    main()
