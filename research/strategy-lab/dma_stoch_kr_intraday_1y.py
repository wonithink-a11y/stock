#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DMA + Stochastic-50 (영상 유래) — 분봉 1년 별도 검증 (intraday_1y).

일봉 proxy(`dma_stoch_kr_smoke.py`, REJECT)와 **섞지 않는다.** 목적이 다르다:
장기 성과 판정이 아니라 **영상 규칙의 단기매매 구조가 분봉에서 실제로 작동하는지**
— 특히 일봉에서 나온 '노출 0.999 / 평균 보유 26~117 bar' 가 해소되는지 —를 본다.

데이터: research/strategy-lab/.cache/minute_raw (2025-08-08 ~ 2026-08-21, 252 거래일).
1년·단일 국면이므로 **KEEP 판정은 원리적으로 불가능하다**(설계상 그렇게 만들지 않았다).

규칙·파라미터는 일봉 SMOKE 와 동일한 후보를 그대로 쓴다(최적값 하나를 고르지 않는다).
기간 5/10/20 은 분봉이므로 5/10/20 **분**이다.

  지표      매 세션 시작에서 리셋한다. 연속 계산하면 오버나이트 갭이 09:00 에
            가짜 돌파를 만든다 - 그건 규칙이 아니라 갭이다.
  포지션    두 해석을 나란히 잰다.
              carry     : 규칙대로만. 청산신호가 안 나오면 오버나이트로 넘어간다
              flat_eod  : 단타 실장. 매일 종가(15:30 단일가)에 강제 청산
  체결      신호는 bar t 종가 확정 -> bar t+1 OPEN 체결 (same-bar 0 을 assert)
  세션      09:00~15:19 연속세션에서만 신호. 15:30 은 종가단일가라 청산가로만 쓴다

  python dma_stoch_kr_intraday_1y.py --selftest
  python dma_stoch_kr_intraday_1y.py --universe 200
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dma_stoch_kr_smoke import build_variants, cross_flags, moving_average, stochastic  # noqa: E402
from intraday import loader  # noqa: E402

OUT_DIR = HERE / "findings" / "dma-stoch50-kr-intraday-1y"

SIGNAL_END_HHMM = 1519      # 연속세션 마지막 분. 1530 은 종가단일가
COST_GRIDS = {"gross": 0, "net30bp": 30, "net60bp": 60}   # 왕복 bp
ANNUAL_DAYS = 252


# --- 유니버스 -----------------------------------------------------------------
def pick_universe(dates, n, warmup_days=20):
    """앞 20 거래일의 거래대금 상위 n 종목으로 고정한다(선정에 미래를 안 쓴다).

    단타는 유동성 없는 종목에서 성립하지 않고, 분봉 결측(체결 없는 분)도 그쪽에
    몰린다. 고정 유니버스라 포지션이 날짜를 넘어 이어져도 종목이 사라지지 않는다.
    """
    amt = defaultdict(float)
    for d in dates[:warmup_days]:
        df = loader.read_day(d, columns=("ticker", "close", "volume"))
        if df is None:
            continue
        g = (df["close"] * df["volume"]).groupby(df["ticker"]).sum()
        for t, v in g.items():
            amt[t] += float(v)
    top = sorted(amt.items(), key=lambda kv: -kv[1])[:n]
    return [t for t, _ in top], {t: round(v / warmup_days / 1e8, 1) for t, v in top[:5]}


# --- 하루치 wide 행렬 ---------------------------------------------------------
def day_matrices(date, tickers):
    df = loader.read_day(date)
    if df is None:
        return None
    df = df[df["ticker"].isin(tickers)]
    if df.empty:
        return None
    grid = sorted(h for h in df["hhmm"].unique() if h <= SIGNAL_END_HHMM or h == 1530)
    out = {}
    for col in ("open", "high", "low", "close"):
        m = df.pivot_table(index="hhmm", columns="ticker", values=col, aggfunc="last")
        out[col] = m.reindex(index=grid, columns=tickers)
    traded = df.pivot_table(index="hhmm", columns="ticker", values="volume", aggfunc="sum")
    traded = traded.reindex(index=grid, columns=tickers)
    out["traded"] = traded.notna()
    out["volume"] = traded.fillna(0.0)      # 체결 없는 분은 거래량 0 (결측 아님)
    # 체결 없는 분은 직전 체결가로 채운다(가격은 존재, 거래는 없음). staleness 는 감사로 센다.
    for col in ("open", "high", "low", "close"):
        out[col] = out[col].ffill()
    out["grid"] = grid
    return out


def benchmark_monthly(tickers, dates):
    """같은 기간 시장 맥락: 같은 200종목 동일가중(일별 리밸런싱)과 KOSPI 의 월별.

    전략이 '살아남았는가' 는 시장이 그 달에 무엇을 했는지와 같이 봐야 한다.
    """
    from engine.data.a2aProvider import A2aProvider
    root = HERE.parents[1]
    bars = A2aProvider(repo_root=root).load(set(tickers), dates[0], dates[-1])
    acc = defaultdict(list)
    for df in bars.values():
        df = df[(df.index.map(str) >= dates[0]) & (df.index.map(str) <= dates[-1])]
        c = df["close"].values
        if len(c) < 2 or c.min() <= 0:
            continue
        for d, r in zip([str(x)[:10] for x in df.index[1:]], c[1:] / c[:-1] - 1.0):
            acc[d].append(float(r))
    eq, curve = 100.0, []
    for d in sorted(acc):
        eq *= (1 + float(np.mean(acc[d])))
        curve.append((d, eq))
    kos = pd.read_parquet(HERE / "data" / "market-regime" / "krkospi_raw.parquet")
    kos = kos[(kos["date"] >= dates[0]) & (kos["date"] <= dates[-1])]
    kcurve = [(str(d)[:10], float(v)) for d, v in zip(kos["date"], kos["value"])]
    return {
        "universeEW": {"totalReturn": round(curve[-1][1] - 100, 2) if curve else None,
                       "monthly": _monthly(curve), "note": "같은 200종목 동일가중 일별 리밸런싱(비용 0)"},
        "KOSPI": {"totalReturn": round(100 * (kcurve[-1][1] / kcurve[0][1] - 1), 2) if kcurve else None,
                  "monthly": _monthly(kcurve, start=kcurve[0][1] if kcurve else 100.0)},
    }


def day_signals(mats, v):
    c, h, l = mats["close"], mats["high"], mats["low"]
    ma = moving_average(c, v["ma"], v["n"])
    k, d = stochastic(h, l, c, *v["stoch"])
    line = k if v["line"] == "k" else d
    ma_up, ma_dn = cross_flags(c, ma)
    st_up, st_dn = cross_flags(line, 50.0)
    entry = ma_up & st_up if v["entry"] == "AND" else (ma_up if v["entry"] == "DMA" else st_up)
    if v["exit"] == "AND":
        ex = ma_dn & st_dn
    elif v["exit"] == "OR":
        ex = ma_dn | st_dn
    elif v["exit"] == "DMA":
        ex = ma_dn
    else:
        ex = st_dn
    valid = ma.notna() & line.notna()
    late = np.array([g > SIGNAL_END_HHMM for g in mats["grid"]])[:, None]   # 15:30 단일가엔 신호 없음
    return (entry & valid).values & ~late, (ex & valid).values & ~late


def held_from_signals(entry, exit_, state_prev, flat_eod):
    """신호 -> 보유 상태. 구간 i = [open_i, open_{i+1}) 를 보유하려면 state[i-1]==1.

    ffill 한 state 가 그 자체로 상태기계다 - 보유 중 재진입 신호는 무시되고
    (이미 1), 무포지션 중 청산 신호도 무시된다(이미 0).
    """
    s = np.where(entry, 1.0, np.where(exit_, 0.0, np.nan))
    s = np.vstack([state_prev.astype(float)[None, :], s])
    idx = np.where(~np.isnan(s), np.arange(s.shape[0])[:, None], 0)
    np.maximum.accumulate(idx, axis=0, out=idx)
    state = np.nan_to_num(np.take_along_axis(s, idx, axis=0)[1:])       # T x N, ffill
    if flat_eod:
        state[-2:, :] = 0.0            # 마지막 구간(-> 15:30 단일가)에서 청산되도록
    held = np.vstack([state_prev.astype(float)[None, :], state[:-1, :]])
    return held, state[-1, :]


# --- 실행 ---------------------------------------------------------------------
def run(n_universe, max_days):
    t0 = time.time()
    dates = loader.list_dates()
    if max_days:
        dates = dates[:max_days]
    tickers, top5 = pick_universe(dates, n_universe)
    N = len(tickers)
    print("universe=%d (앞 20일 거래대금 상위) dates=%d %s~%s top5 일평균 억원=%s (%.0fs)"
          % (N, len(dates), dates[0], dates[-1], top5, time.time() - t0), flush=True)

    variants = build_variants()
    modes = ("carry", "flat_eod")
    st = {(v["id"], m): {"state": np.zeros(N), "open_px": np.zeros(N), "open_ts": [None] * N,
                         "open_bars": np.zeros(N, dtype=int), "open_idx": np.zeros(N, dtype=int),
                         "trades": [],
                         "daily": {lb: [] for lb in COST_GRIDS},
                         "eq": {lb: 100.0 for lb in COST_GRIDS},
                         "act_sum": 0.0, "act_bars": 0}
          for v in variants for m in modes}
    audit = {"staleFillBars": 0, "totalFillBars": 0, "days": 0, "skippedDays": 0, "gapForcedExits": 0}
    prev_last_open = None
    prev_date = None

    for di, date in enumerate(dates):
        mats = day_matrices(date, tickers)
        if mats is None or len(mats["grid"]) < 30:
            audit["skippedDays"] += 1
            continue
        audit["days"] += 1
        O = mats["open"].values
        traded = mats["traded"].values
        grid = mats["grid"]
        T = len(grid)
        priced = np.isfinite(O)                                  # T x N, 체결 가능한 bar
        with np.errstate(invalid="ignore", divide="ignore"):
            r_in = np.nan_to_num(O[1:] / O[:-1] - 1.0)          # (T-1) x N, 구간 i
        r_on = np.nan_to_num(O[0] / prev_last_open - 1.0) if prev_last_open is not None else None

        for v in variants:
            en, ex = day_signals(mats, v)
            for mode in modes:
                s = st[(v["id"], mode)]
                # 오늘 09:00 에 값이 없는 종목(장 시작 후에야 첫 체결)에 포지션을
                # 이월했다면 오늘 가격으로 체결할 수 없다. 어제 마지막 가격에
                # 청산해 둔다 - 그냥 두면 NaN 가격으로 체결돼 통계가 오염된다.
                dead = np.nonzero((~priced[0]) & (s["state"] > 0))[0]
                for j in dead:
                    if (s["open_ts"][j] is not None and np.isfinite(prev_last_open[j])
                            and s["open_ts"][j] != (prev_date, 1530)):   # 0분 트레이드 방지
                        s["trades"].append(_mk_trade(tickers[j], s, j, prev_date, 1530,
                                                     float(prev_last_open[j]),
                                                     int(s["open_bars"][j]), forced=True))
                    s["open_ts"][j] = None
                    audit["gapForcedExits"] += 1
                s["state"][dead] = 0.0

                held, end_state = held_from_signals(en, ex, s["state"], mode == "flat_eod")
                prev_h = np.vstack([s["state"][None, :], held[:-1, :]])
                opened = (held == 1) & (prev_h == 0)
                closed = (held == 0) & (prev_h == 1)
                n_act = held.sum(axis=1)

                # 오버나이트 구간(전일 마지막 open -> 오늘 첫 open): 어제 넘긴 포지션만
                day_mult = 1.0
                if r_on is not None and s["state"].any():
                    day_mult = 1 + float(np.mean(r_on[np.nonzero(s["state"])[0]]))

                # 진입/청산은 **시간순으로** 처리한다. 전부-진입 후 전부-청산으로 처리하면
                # 같은 날 재진입한 종목이 이전 청산과 잘못 짝지어진다(보유시간 음수).
                oi, oj = np.nonzero(opened)
                ci, cj = np.nonzero(closed)
                ev_i = np.concatenate([oi, ci])
                ev_j = np.concatenate([oj, cj])
                ev_k = np.concatenate([np.zeros(len(oi), dtype=int), np.ones(len(ci), dtype=int)])
                for e in np.argsort(ev_i, kind="stable"):
                    i, j, is_close = int(ev_i[e]), int(ev_j[e]), bool(ev_k[e])
                    audit["totalFillBars"] += 1
                    audit["staleFillBars"] += 0 if traded[i, j] else 1
                    if is_close:
                        if s["open_ts"][j] is None:
                            continue
                        bars = int(s["open_bars"][j] + (i - s["open_idx"][j]))
                        s["trades"].append(_mk_trade(tickers[j], s, j, date, grid[i], O[i, j], bars))
                        s["open_ts"][j] = None
                    else:
                        s["open_px"][j] = O[i, j]
                        s["open_ts"][j] = (date, grid[i])
                        s["open_bars"][j] = 0
                        s["open_idx"][j] = i

                # 분단위 동일가중 포트폴리오 수익 + 체결비용(진입/청산 각 왕복의 절반)
                fills = (opened.sum(axis=1) + closed.sum(axis=1)).astype(float)
                safe = np.where(n_act > 0, n_act, 1.0)
                port_r = (held[:-1] * r_in).sum(axis=1) / safe[:-1]
                cost_units = fills / safe
                for lb, bps in COST_GRIDS.items():
                    step = 1 + port_r - cost_units[:-1] * ((bps / 2) / 1e4)
                    s["eq"][lb] *= day_mult * float(np.prod(step))
                    s["daily"][lb].append((date, s["eq"][lb]))
                still = np.nonzero(end_state)[0]          # 오늘 안 닫힌 포지션의 보유 bar 이월
                if len(still):
                    s["open_bars"][still] += T - s["open_idx"][still]
                    s["open_idx"][still] = 0
                s["act_sum"] += float(n_act[:-1].sum())
                s["act_bars"] += (T - 1) * N
                s["state"] = end_state
        prev_last_open = O[-1]
        prev_date = date
        if di % 25 == 0:
            print("  [%d/%d] %s (%.0fs)" % (di, len(dates), date, time.time() - t0), flush=True)

    for (vid, mode), s in st.items():                 # 종료 시점 미청산 강제청산
        for j in np.nonzero(s["state"])[0]:
            # 마지막 날 15:19 신호는 15:30 에 체결되고 그 뒤 구간이 없다 - 가격이
            # 매겨진 적 없는 포지션이라 트레이드로 세지 않는다(0분 트레이드 방지).
            if s["open_ts"][j] == (prev_date, 1530) or not np.isfinite(prev_last_open[j]):
                continue
            if s["open_ts"][j] is not None:
                s["trades"].append(_mk_trade(tickers[j], s, j, prev_date, 1530,
                                             float(prev_last_open[j]),
                                             int(s["open_bars"][j]), forced=True))

    results = [summarize(v["id"], m, st[(v["id"], m)], variants, audit["days"], N)
               for v in variants for m in modes]
    bad = sum(r["badDurations"] for r in results)
    assert bad == 0, "same-bar/역방향 체결 %d 건 - 체결 규칙이 깨졌다" % bad
    nf = sum(r["nonFiniteTrades"] for r in results)
    assert nf == 0, "가격 없는 bar 체결 %d 건 - 트레이드 통계가 오염된다" % nf
    out = {
        "experiment": "DMA + Stochastic-50 (영상 유래) 분봉 1년 검증 (intraday_1y)",
        "separateFrom": "dma-stoch50-daily-proxy (일봉 REJECT) - 결과를 섞지 않는다",
        "sourceCaveat": "Claude 는 원본 영상을 보지 못했다. 사용자가 옮겨 적은 규칙만 입력이다.",
        "verdictCeiling": "1년·단일국면 표본이라 KEEP 판정 불가. 구조 확인 전용.",
        "data": {"dir": "research/strategy-lab/.cache/minute_raw",
                 "dates": len(dates), "from": dates[0], "to": dates[-1], "universe": N,
                 "universeRule": "앞 20 거래일 거래대금 상위 (미래 미사용·연중 고정)",
                 "top5AvgAmountEok": top5},
        "session": {"signalWindow": "0900-1519", "closeAuctionBar": 1530,
                    "indicatorReset": "매 세션 시작", "execution": "signal bar t close -> bar t+1 open"},
        "costGridsBpsRoundTrip": COST_GRIDS,
        "audit": audit,
        "benchmarks": benchmark_monthly(tickers, dates),
        "variants": sorted(results, key=lambda r: -(r["net30bp"]["totalReturn"]
                                                    if r["net30bp"]["totalReturn"] is not None else -999)),
        "elapsedSeconds": round(time.time() - t0, 1),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "intraday_1y_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nwritten: %s (%ss)" % (OUT_DIR / "intraday_1y_result.json", out["elapsedSeconds"]))
    return out


def _mk_trade(symbol, s, j, date, hhmm, px, bars, forced=False):
    d0, h0 = s["open_ts"][j]
    return {"symbol": symbol, "entry_date": d0, "entry_hhmm": int(h0), "entry_px": float(s["open_px"][j]),
            "exit_date": date, "exit_hhmm": int(hhmm), "exit_px": float(px),
            "bars": int(bars), "forced": forced,
            "gross_ret": float(px / s["open_px"][j] - 1.0) if s["open_px"][j] else 0.0,
            "overnight": d0 != date}


def _minutes(t):
    def _m(hhmm):
        return int(hhmm) // 100 * 60 + int(hhmm) % 100
    d0 = pd.Timestamp(t["entry_date"]) + pd.to_timedelta(_m(t["entry_hhmm"]), unit="m")
    d1 = pd.Timestamp(t["exit_date"]) + pd.to_timedelta(_m(t["exit_hhmm"]), unit="m")
    return (d1 - d0).total_seconds() / 60.0


def _monthly(daily, start=100.0):
    """월말 잔고 -> 월별 수익률(%). 곡선을 산출물에 같이 남긴다 - 시계열이 없어
    나중에 재집계를 못 했던 전례(09-07 QCOMP)를 되풀이하지 않는다."""
    last = {}
    for d, eq in daily:
        last[d[:7]] = eq
    out, prev = {}, start
    for ym in sorted(last):
        out[ym] = round((last[ym] / prev - 1) * 100, 2)
        prev = last[ym]
    return out


def _monthly_trades(trs, cost):
    agg = defaultdict(list)
    for t in trs:
        agg[t["exit_date"][:7]].append((1 + t["gross_ret"]) * (1 - cost) - 1.0)
    return {ym: {"n": len(v),
                 "winRate": round(100 * float(np.mean([x > 0 for x in v])), 1),
                 "avgTradePct": round(100 * float(np.mean(v)), 4),
                 "profitFactor": (round(float(sum(x for x in v if x > 0) / -sum(x for x in v if x < 0)), 3)
                                  if any(x < 0 for x in v) else None)}
            for ym, v in sorted(agg.items())}


def _curve_metrics(daily):
    v = np.array([x[1] for x in daily], dtype=float) if len(daily) > 1 else np.array([100.0, 100.0])
    dr = v[1:] / v[:-1] - 1.0
    yrs = max(len(daily), 1) / ANNUAL_DAYS
    return {
        "totalReturn": round((v[-1] / v[0] - 1) * 100, 2),
        "CAGR_보조": round(((max(v[-1], 1e-9) / v[0]) ** (1 / yrs) - 1) * 100, 2),
        "MDD": round(float((v / np.maximum.accumulate(v) - 1).min()) * 100, 2),
        "Sharpe": (round(float(np.sqrt(ANNUAL_DAYS) * dr.mean() / dr.std()), 3)
                   if len(dr) > 1 and dr.std() > 0 else None),
    }


def summarize(vid, mode, s, variants, n_days, n_tickers):
    spec = next(v for v in variants if v["id"] == vid)
    trs = s["trades"]
    per_cost = {}
    for label, bps in COST_GRIDS.items():
        c = bps / 1e4
        rets = np.array([(1 + t["gross_ret"]) * (1 - c) - 1.0 for t in trs]) if trs else np.array([])
        wins, losses = rets[rets > 0], rets[rets < 0]
        per_cost[label] = {
            "winRate": round(100 * float((rets > 0).mean()), 1) if len(rets) else None,
            "profitFactor": (round(float(wins.sum() / -losses.sum()), 3)
                             if len(losses) and losses.sum() < 0 else None),
            "avgTradePct": round(100 * float(rets.mean()), 4) if len(rets) else None,
            "medTradePct": round(100 * float(np.median(rets)), 4) if len(rets) else None,
        }
        per_cost[label].update(_curve_metrics(s["daily"][label]))
        per_cost[label]["monthly"] = _monthly(s["daily"][label])
    bars = [t["bars"] for t in trs]
    mins = [_minutes(t) for t in trs] if trs else []
    c30 = COST_GRIDS["net30bp"] / 1e4
    by_sym = defaultdict(float)
    for t in trs:
        by_sym[t["symbol"]] += (1 + t["gross_ret"]) * (1 - c30) - 1.0
    ranked = sorted(by_sym.items(), key=lambda kv: -kv[1])
    tot = sum(by_sym.values())
    tot = tot if tot > 0 else None      # 총합이 음이면 '기여 비중'은 정의되지 않는다(교훈57)
    return {
        "id": vid, "mode": mode, "group": spec["group"],
        "spec": {k: spec[k] for k in ("ma", "n", "stoch", "line", "entry", "exit")},
        "trades": len(trs),
        # 체결 무결성: 아래 둘은 0 이어야 한다 (아니면 통계가 조용히 오염된다)
        "badDurations": sum(1 for t in trs if _minutes(t) <= 0),
        "nonFiniteTrades": sum(1 for t in trs if not np.isfinite(t["gross_ret"])),
        "tradesPerDayPerSymbol": round(len(trs) / max(n_days, 1) / max(n_tickers, 1), 3),
        "avgHoldBars": round(float(np.mean(bars)), 1) if bars else None,
        "medHoldBars": int(np.median(bars)) if bars else None,
        "avgHoldMinutes": round(float(np.mean(mins)), 1) if mins else None,
        "medHoldMinutes": round(float(np.median(mins)), 1) if mins else None,
        "overnightTradePct": round(100 * float(np.mean([t["overnight"] for t in trs])), 1) if trs else None,
        "exposure": round(s["act_sum"] / max(s["act_bars"], 1), 4),
        "gross": per_cost["gross"], "net30bp": per_cost["net30bp"], "net60bp": per_cost["net60bp"],
        "monthlyTradesNet30": _monthly_trades(trs, c30),
        "dailyCurveNet30": [[d, round(eq, 4)] for d, eq in s["daily"]["net30bp"]],
        "perSymbol": {
            "symbolsWithTrades": len(by_sym),
            "positivePct": (round(100 * float(np.mean([x > 0 for x in by_sym.values()])), 1)
                            if by_sym else None),
            "top1SharePct": round(100 * ranked[0][1] / tot, 1) if ranked and tot else None,
            "top5SharePct": round(100 * sum(x for _, x in ranked[:5]) / tot, 1) if ranked and tot else None,
            "top10SharePct": round(100 * sum(x for _, x in ranked[:10]) / tot, 1) if ranked and tot else None,
            "best3": [[k, round(100 * x, 2)] for k, x in ranked[:3]],
            "worst3": [[k, round(100 * x, 2)] for k, x in ranked[-3:]],
        },
    }


def selftest():
    # held_from_signals 가 상태기계인지: 보유 중 재진입 무시, 무포지션 중 청산 무시
    T, N = 6, 1
    en = np.zeros((T, N), bool)
    ex = np.zeros((T, N), bool)
    en[1] = True
    en[2] = True          # 보유 중 재진입
    ex[0] = True          # 무포지션 중 청산
    ex[4] = True
    held, end = held_from_signals(en, ex, np.zeros(N), flat_eod=False)
    assert list(held[:, 0]) == [0, 0, 1, 1, 1, 0], held[:, 0]
    assert end[0] == 0.0

    # same-bar lookahead 없음: 신호 bar i 의 보유는 i+1 구간부터다
    en2 = np.zeros((4, 1), bool)
    en2[0] = True
    h2, _ = held_from_signals(en2, np.zeros((4, 1), bool), np.zeros(1), False)
    assert h2[0, 0] == 0 and h2[1, 0] == 1, h2[:, 0]

    # flat_eod 는 마지막 구간을 반드시 비운다 (그 전 구간은 보유 유지)
    h3, e3 = held_from_signals(en2, np.zeros((4, 1), bool), np.zeros(1), True)
    assert h3[-1, 0] == 0 and e3[0] == 0.0 and h3[1, 0] == 1, (h3[:, 0], e3)

    # carry 는 넘어온 상태를 첫 구간부터 보유로 읽는다
    h4, _ = held_from_signals(np.zeros((3, 1), bool), np.zeros((3, 1), bool), np.ones(1), False)
    assert list(h4[:, 0]) == [1, 1, 1], h4[:, 0]

    # 열이 서로 독립인지 (분봉 wide 행렬에서 종목이 섞이면 안 된다)
    e5 = np.zeros((5, 2), bool)
    x5 = np.zeros((5, 2), bool)
    e5[0, 0] = True
    x5[2, 1] = True
    h5, _ = held_from_signals(e5, x5, np.array([0.0, 1.0]), False)
    assert list(h5[:, 0]) == [0, 1, 1, 1, 1] and list(h5[:, 1]) == [1, 1, 1, 0, 0], h5

    # 보유시간
    assert _minutes({"entry_date": "2026-01-05", "entry_hhmm": 931,
                     "exit_date": "2026-01-05", "exit_hhmm": 1005}) == 34.0
    assert _minutes({"entry_date": "2026-01-05", "entry_hhmm": 1500,
                     "exit_date": "2026-01-06", "exit_hhmm": 930}) == 18.5 * 60

    # 2D 지표가 열별로 1D 와 동일한지
    idx = list(range(40))
    a = pd.Series(np.linspace(10, 20, 40), index=idx)
    b = pd.Series(np.linspace(20, 10, 40), index=idx)
    wide = pd.DataFrame({"A": a + np.sin(np.arange(40)), "B": b + np.cos(np.arange(40))})
    k2, _ = stochastic(wide, wide, wide, 5, 3, 3)
    k1, _ = stochastic(wide["A"], wide["A"], wide["A"], 5, 3, 3)
    assert np.allclose(k2["A"].dropna().values, k1.dropna().values), "2D stochastic != 1D"
    up2, dn2 = cross_flags(wide, wide.rolling(5).mean())
    up1, dn1 = cross_flags(wide["A"], wide["A"].rolling(5).mean())
    assert up2["A"].equals(up1) and dn2["A"].equals(dn1), "cross_flags 2D != 1D"
    assert up2["A"].sum() > 0 and not (up2 & dn2).any().any(), "cross_flags 2D 신호 없음/충돌"

    # MTM 검증: 100 -> 50 -> 100 의 MDD 는 -50%
    m = _curve_metrics([("d1", 100.0), ("d2", 50.0), ("d3", 100.0)])
    assert m["MDD"] == -50.0 and m["totalReturn"] == 0.0, m

    # 월별: 월말 잔고를 이어붙인 것이지 일별 평균이 아니다
    mo = _monthly([("2025-08-01", 110.0), ("2025-08-29", 120.0),
                   ("2025-09-30", 60.0), ("2025-10-31", 66.0)])
    assert mo == {"2025-08": 20.0, "2025-09": -50.0, "2025-10": 10.0}, mo
    mt = _monthly_trades([{"exit_date": "2025-08-11", "gross_ret": 0.02},
                          {"exit_date": "2025-08-20", "gross_ret": -0.01},
                          {"exit_date": "2025-09-02", "gross_ret": 0.05}], 0.0)
    assert mt["2025-08"]["n"] == 2 and mt["2025-08"]["winRate"] == 50.0
    assert mt["2025-08"]["profitFactor"] == 2.0 and mt["2025-09"]["profitFactor"] is None, mt
    print("selftest ok (17 assertions)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", type=int, default=200)
    ap.add_argument("--days", type=int, default=0, help="0=전체")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    else:
        run(a.universe, a.days)
