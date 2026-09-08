#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""DMA + Stochastic-50 (영상 유래 단타 규칙) 일봉 proxy SMOKE.

출처: 사용자가 본 Instagram 영상의 구두 규칙. Claude 는 영상을 보지 못했고,
사용자가 옮겨 적은 규칙만 입력으로 쓴다. 영상에 없는 값(DMA 산식/기간,
Stochastic 파라미터, smoothing line 이 %K-slow 인지 %D 인지)은 확정하지 않고
후보를 나란히 돌린다.

  Entry : close 가 DMA 를 상향돌파  AND  같은 bar 에서 stoch 선이 50 상향돌파
  Exit  : close 가 DMA 를 하향이탈  AND  같은 bar 에서 stoch 선이 50 하향이탈
  체결  : 신호는 t 종가 확정, 체결은 next session OPEN (same-bar 체결 0 을 assert)

회계는 **일별 MTM** 이다. 이 저장소의 옛 드라이버(run_supertrend_kr_v1_smoke 등)가
쓰는 '청산일 실현손익 누적' 은 미실현 낙폭이 곡선에 안 나타나 MDD·Sharpe 를
왜곡한다(CLAUDE.md 함정 5). 여기서는 보유구간을 open->open 일별 수익률로 분해해
매일 평가한다.

포트폴리오는 **슬롯 상한 없는 동일가중 신호 포트폴리오**다(활성 N개면 각 1/N,
N=0 이면 현금). 신호의 정보량을 재는 것이 목적이고 capacity 는 재지 않는다.
벤치마크(EW 유니버스)도 같은 가중규약이라 사과-사과 비교가 된다.

  python dma_stoch_kr_smoke.py --selftest
  python dma_stoch_kr_smoke.py --tickers 500
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
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

OUT_DIR = HERE / "findings" / "dma-stoch50-kr-smoke"

# --- 확정값 (영상 근거 아님 · 저장소 관례) ------------------------------------
RAW_START = "2014-05-13"          # 지표 워밍업 (A2a 시작)
PERF_START = "2016-01-01"         # 성과 측정 시작
END = "2026-08-14"                # market-regime 산출물이 usable 한 마지막 일자
ENTRY_BPS, EXIT_BPS = 15, 15      # supertrend/macd/squeeze 스모크와 동일
# build_factor_panel.py:728 과 같은 분할 - 새 경계를 만들지 않는다
TRAIN_END, VALID_END = "2022-06-30", "2024-01-01"


def period_of(d):
    return "TRAIN" if d <= TRAIN_END else ("VALID" if d <= VALID_END else "TEST")


# --- 지표 --------------------------------------------------------------------
def moving_average(close, kind, n, shift=3):
    if kind == "ema":
        return close.ewm(span=n, adjust=False).mean()
    if kind == "sma":
        return close.rolling(n).mean()
    if kind == "dsma":                      # displaced SMA: 인과적인 방향(+) 으로만
        return close.rolling(n).mean().shift(shift)
    raise ValueError(kind)


def stochastic(high, low, close, p, k_smooth, d_smooth):
    """Series(일봉 1종목) 와 DataFrame(분봉 wide, 열=종목) 양쪽에서 동작한다."""
    ll = low.rolling(p).min()
    hh = high.rolling(p).max()
    rng = hh - ll
    denom = np.where(rng.values > 0, rng.values, 1.0)
    raw = np.where(rng.values > 0, (close.values - ll.values) / denom * 100.0, 50.0)
    wrap = (pd.DataFrame(raw, index=close.index, columns=close.columns)
            if close.ndim == 2 else pd.Series(raw, index=close.index))
    raw = wrap.where(rng.notna())
    k = raw.rolling(k_smooth).mean()        # "smoothing line" 1순위 해석
    d = k.rolling(d_smooth).mean()
    return k, d


def cross_flags(series, ref):
    """(상향돌파, 하향이탈) - t 와 t-1 만 본다."""
    prev, cur = series.shift(1), series
    prev_r = ref.shift(1) if isinstance(ref, (pd.Series, pd.DataFrame)) else ref
    up = (prev <= prev_r) & (cur > ref)
    dn = (prev >= prev_r) & (cur < ref)
    return up.fillna(False), dn.fillna(False)


# --- variant 정의 -------------------------------------------------------------
def build_variants():
    vs = []
    for ma in ("ema", "sma", "dsma"):
        for n in (5, 10, 20):
            for st in ((5, 3, 3), (14, 3, 3)):
                vs.append(dict(id=f"{ma}{n}_st{st[0]}", ma=ma, n=n, stoch=st,
                               line="k", entry="AND", exit="AND", group="core"))
    ref = dict(ma="ema", n=10, stoch=(5, 3, 3), line="k", entry="AND", exit="AND")
    vs.append({**ref, "id": "abl_exit_OR", "exit": "OR", "group": "ablation"})
    vs.append({**ref, "id": "abl_dma_only", "entry": "DMA", "exit": "DMA", "group": "ablation"})
    vs.append({**ref, "id": "abl_stoch_only", "entry": "STOCH", "exit": "STOCH", "group": "ablation"})
    vs.append({**ref, "id": "abl_line_D", "line": "d", "group": "ablation"})
    return vs


def signal_frame(bars, v):
    c, h, l = bars["close"], bars["high"], bars["low"]
    ma = moving_average(c, v["ma"], v["n"])
    k, d = stochastic(h, l, c, *v["stoch"])
    line = k if v["line"] == "k" else d
    ma_up, ma_dn = cross_flags(c, ma)
    st_up, st_dn = cross_flags(line, 50.0)
    if v["entry"] == "AND":
        entry = ma_up & st_up
    elif v["entry"] == "DMA":
        entry = ma_up
    else:
        entry = st_up
    if v["exit"] == "AND":
        ex = ma_dn & st_dn
    elif v["exit"] == "OR":
        ex = ma_dn | st_dn
    elif v["exit"] == "DMA":
        ex = ma_dn
    else:
        ex = st_dn
    valid = ma.notna() & line.notna()
    return (entry & valid).values, (ex & valid).values


# --- 심볼 단위 상태기계 -------------------------------------------------------
def trades_for_symbol(symbol, bars, entry_sig, exit_sig, listed_at):
    """신호 t -> 체결 t+1 open. 데이터 끝에서 열려 있으면 마지막 bar open 강제청산."""
    dates = bars.index
    opens = bars["open"].values
    out, long_i = [], None
    n = len(dates)
    idxs = np.nonzero(entry_sig | exit_sig)[0]
    for i in idxs:
        ds = dates[i]
        if ds < PERF_START or i + 1 >= n:
            continue
        if listed_at and ds < listed_at:
            continue
        if long_i is None and entry_sig[i]:
            long_i = (i + 1, ds)
        elif long_i is not None and exit_sig[i]:
            e_i, e_sig = long_i
            if i + 1 > e_i:
                out.append(dict(symbol=symbol, entry_i=e_i, exit_i=i + 1,
                                signal_date=e_sig, exit_signal_date=ds, forced=False))
                long_i = None
    if long_i is not None and long_i[0] < n - 1:
        out.append(dict(symbol=symbol, entry_i=long_i[0], exit_i=n - 1,
                        signal_date=long_i[1], exit_signal_date=None, forced=True))
    for t in out:
        t["entry_date"] = dates[t["entry_i"]]
        t["exit_date"] = dates[t["exit_i"]]
        t["entry_price"] = float(opens[t["entry_i"]])
        t["exit_price"] = float(opens[t["exit_i"]])
        t["gross_ret"] = t["exit_price"] / t["entry_price"] - 1.0
        t["net_ret"] = (1 + t["gross_ret"]) * (1 - ENTRY_BPS / 1e4) * (1 - EXIT_BPS / 1e4) - 1.0
        t["hold_bars"] = t["exit_i"] - t["entry_i"]
    return out


def daily_legs(trade, bars, with_cost=True):
    """보유구간을 open->open 일별 수익률로 분해. 구간 d 의 수익은 d 에 귀속."""
    o = bars["open"].values[trade["entry_i"]: trade["exit_i"] + 1]
    days = bars.index[trade["entry_i"]: trade["exit_i"]]
    if len(o) < 2:
        return []
    r = o[1:] / o[:-1]
    if with_cost:
        r = r.copy()
        r[0] *= (1 - ENTRY_BPS / 1e4)
        r[-1] *= (1 - EXIT_BPS / 1e4)
    return list(zip(days, r - 1.0))


# --- 곡선/지표 ---------------------------------------------------------------
def curve_from_daily(day_ret, sessions):
    eq, curve = 100.0, []
    for d in sessions:
        eq *= (1 + day_ret.get(d, 0.0))
        curve.append((d, eq))
    return curve


def metrics(curve):
    if len(curve) < 3:
        return {}
    v = np.array([x[1] for x in curve], dtype=float)
    yrs = (pd.Timestamp(curve[-1][0]) - pd.Timestamp(curve[0][0])).days / 365.25
    r = v[1:] / v[:-1] - 1.0
    return {
        "totalReturn": round((v[-1] / v[0] - 1) * 100, 2),
        "CAGR": round(((v[-1] / v[0]) ** (1 / yrs) - 1) * 100, 2) if yrs > 0 else None,
        "MDD": round(float((v / np.maximum.accumulate(v) - 1).min()) * 100, 2),
        "Sharpe": round(float(np.sqrt(252) * r.mean() / r.std()), 3) if r.std() > 0 else None,
    }


def yearly(curve):
    s = pd.Series({pd.Timestamp(d): v for d, v in curve}).sort_index()
    last = s.groupby(s.index.year).last()
    out, prev = {}, s.iloc[0]
    for y, v in last.items():
        out[str(y)] = round((v / prev - 1) * 100, 2)
        prev = v
    return out


def excess_t(strat, bench, sessions):
    """일별 초과수익 평균의 t 값 (Newey-West 아님 - 스모크 수준)."""
    if len(sessions) < 10:
        return None
    a = np.array([strat.get(d, 0.0) for d in sessions])
    b = np.array([bench.get(d, 0.0) for d in sessions])
    e = a - b
    return round(float(e.mean() / (e.std(ddof=1) / np.sqrt(len(e)))), 2) if e.std() > 0 else None


SPLITS = (("TRAIN", PERF_START, TRAIN_END), ("VALID", TRAIN_END, VALID_END), ("TEST", VALID_END, END))


def split_sessions(sessions, name, lo, hi):
    if name == "TRAIN":
        return [d for d in sessions if lo <= d <= hi]
    return [d for d in sessions if lo < d <= hi]


# --- 실행 --------------------------------------------------------------------
def load_data(n_tickers, seed):
    from engine.data.universeProvider import UniverseProvider
    from engine.data.a2aProvider import A2aProvider
    from engine.data.a2bProvider import A2bProvider
    from engine.data.mergedPriceProvider import MergedPriceProvider
    from engine.data.calendar import TradingCalendar

    uni = UniverseProvider(repo_root=REPO_ROOT, include_delisted=True)   # A1A_A1B_MERGED
    price = MergedPriceProvider(A2aProvider(repo_root=REPO_ROOT), A2bProvider(repo_root=REPO_ROOT))
    cal = TradingCalendar(repo_root=REPO_ROOT)

    tk = sorted(uni.tickers)
    if n_tickers and n_tickers < len(tk):
        rng = np.random.default_rng(seed)
        tk = sorted(rng.choice(tk, size=n_tickers, replace=False).tolist())
    bars = price.load(set(tk), RAW_START, END, universe_hash=uni.universe_hash)
    clean = {}
    for t, df in bars.items():
        if df is None or df.empty:
            continue
        if "is_suspended" in df.columns:
            df = df[~df["is_suspended"].astype(bool)]
        df = df[[c for c in ("open", "high", "low", "close") if c in df.columns]].dropna()
        df = df[(df > 0).all(axis=1)]          # A2a/A2b 에 0 가격 행이 있다 (분모)
        df.index = [str(x)[:10] for x in df.index]
        df = df[df.index <= END].sort_index()
        if len(df) > 60:
            clean[t] = df
    listed = {e.ticker: (e.listedAt or "")[:10] for e in uni.entries}
    sessions = [d for d in cal.days if PERF_START <= d <= END]
    return uni, clean, listed, sessions


def ew_benchmark(bars_by_ticker):
    """유니버스 동일가중, open->open, 매일 리밸런싱, 항상 완전투자."""
    acc = defaultdict(list)
    for df in bars_by_ticker.values():
        o = df["open"].values
        r = o[1:] / o[:-1] - 1.0
        for d, x in zip(df.index[:-1], r):
            if PERF_START <= d <= END:
                acc[d].append(x)
    return {d: float(np.mean(v)) for d, v in acc.items() if v}


def index_returns(name, sessions):
    p = HERE / "data" / "market-regime" / f"{name}.parquet"
    df = pd.read_parquet(p)
    col = "date" if "date" in df.columns else "usableFromDate"
    s = pd.Series(df["value"].values, index=[str(x)[:10] for x in df[col]]).dropna()
    s = s.reindex(sessions).ffill().dropna()
    return {d: float(x) for d, x in (s / s.shift(1) - 1).dropna().items()}


def placebo(variant_id, reps, n_tickers, seed):
    """난수 바닥선: 신호 배열을 심볼별로 원형이동(circular shift)한다.

    신호 개수·간격 분포는 그대로 두고 가격과의 시점관계만 깬다. combo-sweep
    (2026-09-02)에서 난수 팩터 4,845조합의 최고가 t=3.21 이었다 - 바닥선 없이
    t>=2.0 을 믿으면 안 된다.
    """
    t0 = time.time()
    uni, bars, listed, sessions = load_data(n_tickers, seed)
    v = next(x for x in build_variants() if x["id"] == variant_id)
    bench_ew = ew_benchmark(bars)
    sig = {sym: signal_frame(df, v) for sym, df in bars.items()}
    rng = np.random.default_rng(seed + 1)
    out = []
    for rep in range(reps):
        day, cnt = defaultdict(float), defaultdict(int)
        for sym, df in bars.items():
            en, ex = sig[sym]
            k = int(rng.integers(1, len(df)))
            for t in trades_for_symbol(sym, df, np.roll(en, k), np.roll(ex, k), listed.get(sym) or None):
                for d, r in daily_legs(t, df):
                    day[d] += r
                    cnt[d] += 1
        dd = {d: day[d] / cnt[d] for d in day if cnt[d]}
        m = metrics(curve_from_daily(dd, sessions))
        out.append({"rep": rep, "CAGR": m.get("CAGR"), "Sharpe": m.get("Sharpe"),
                    "tVsEW": excess_t(dd, bench_ew, sessions)})
        print(f"  placebo {rep+1}/{reps}: CAGR={m.get('CAGR')} tVsEW={out[-1]['tVsEW']} "
              f"({time.time()-t0:.0f}s)", flush=True)
    ts = sorted(x["tVsEW"] for x in out if x["tVsEW"] is not None)
    cs = sorted(x["CAGR"] for x in out if x["CAGR"] is not None)
    res = {"variantId": variant_id, "reps": reps, "method": "per-symbol circular shift of signal arrays",
           "tVsEW": {"max": ts[-1], "p95": ts[int(0.95 * (len(ts) - 1))], "median": ts[len(ts) // 2], "min": ts[0]},
           "CAGR": {"max": cs[-1], "p95": cs[int(0.95 * (len(cs) - 1))], "median": cs[len(cs) // 2], "min": cs[0]},
           "reps_detail": out, "elapsedSeconds": round(time.time() - t0, 1)}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"placebo_{variant_id}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("variantId", "tVsEW", "CAGR")}, ensure_ascii=False, indent=2))
    return res


def run(n_tickers, seed):
    t0 = time.time()
    uni, bars, listed, sessions = load_data(n_tickers, seed)
    print(f"universe={uni.mode} tickers_with_data={len(bars)} sessions={len(sessions)} "
          f"({time.time()-t0:.1f}s)", flush=True)

    variants = build_variants()
    per_variant = {v["id"]: {"day": defaultdict(float), "gday": defaultdict(float),
                             "cnt": defaultdict(int), "trades": [], "spec": v} for v in variants}

    for j, (sym, df) in enumerate(bars.items()):
        if j % 200 == 0:
            print(f"  [{j}/{len(bars)}] {sym} ({time.time()-t0:.1f}s)", flush=True)
        la = listed.get(sym) or None
        for v in variants:
            en, ex = signal_frame(df, v)
            trs = trades_for_symbol(sym, df, en, ex, la)
            if not trs:
                continue
            slot = per_variant[v["id"]]
            slot["trades"].extend(trs)
            for t in trs:
                for d, r in daily_legs(t, df, with_cost=True):
                    slot["day"][d] += r
                    slot["cnt"][d] += 1
                for d, r in daily_legs(t, df, with_cost=False):
                    slot["gday"][d] += r

    bench_ew = ew_benchmark(bars)
    bench_kospi = index_returns("krkospi_raw", sessions)

    results = []
    for v in variants:
        slot = per_variant[v["id"]]
        day = {d: slot["day"][d] / slot["cnt"][d] for d in slot["day"] if slot["cnt"][d]}
        gday = {d: slot["gday"][d] / slot["cnt"][d] for d in slot["gday"] if slot["cnt"][d]}
        trs = slot["trades"]
        curve = curve_from_daily(day, sessions)
        same_bar = sum(1 for t in trs
                       if t["entry_date"] <= t["signal_date"]
                       or (t.get("exit_signal_date") and t["exit_date"] <= t["exit_signal_date"]))
        row = {
            "id": v["id"], "group": v["group"],
            "spec": {k: v[k] for k in ("ma", "n", "stoch", "line", "entry", "exit")},
            "trades": len(trs),
            "forcedExits": sum(1 for t in trs if t.get("forced")),
            "avgHoldBars": round(float(np.mean([t["hold_bars"] for t in trs])), 1) if trs else None,
            "medHoldBars": int(np.median([t["hold_bars"] for t in trs])) if trs else None,
            "winRate": round(100 * float(np.mean([t["net_ret"] > 0 for t in trs])), 1) if trs else None,
            "avgTradeGrossPct": round(100 * float(np.mean([t["gross_ret"] for t in trs])), 3) if trs else None,
            "avgTradeNetPct": round(100 * float(np.mean([t["net_ret"] for t in trs])), 3) if trs else None,
            "exposure": round(float(np.mean([1.0 if d in day else 0.0 for d in sessions])), 3),
            "avgActivePositions": round(float(np.mean([slot["cnt"].get(d, 0) for d in sessions])), 1),
            "sameBarExecutions": same_bar,
            "gross": metrics(curve_from_daily(gday, sessions)),
            "net": metrics(curve),
            "yearly": yearly(curve),
            "tVsEW": excess_t(day, bench_ew, sessions),
            "tVsKOSPI": excess_t(day, bench_kospi, sessions),
        }
        for name, lo, hi in SPLITS:
            sub = split_sessions(sessions, name, lo, hi)
            row[name] = {**metrics(curve_from_daily(day, sub)),
                         "tVsEW": excess_t(day, bench_ew, sub),
                         "trades": sum(1 for t in trs if lo <= t["entry_date"] <= hi)}
        results.append(row)

    bench = {}
    for nm, dd in (("EW_universe", bench_ew), ("KOSPI", bench_kospi)):
        bench[nm] = {**metrics(curve_from_daily(dd, sessions)), "yearly": yearly(curve_from_daily(dd, sessions))}
        for name, lo, hi in SPLITS:
            bench[nm][name] = metrics(curve_from_daily(dd, split_sessions(sessions, name, lo, hi)))

    out = {
        "experiment": "DMA + Stochastic-50 (영상 유래) 일봉 proxy SMOKE",
        "sourceCaveat": "Claude 는 원본 영상을 보지 못했다. 사용자가 옮겨 적은 규칙만 입력이다.",
        "dataCaveat": "일봉이다. 영상의 단타(분봉) 체결구조는 재현하지 않는다.",
        "universeMode": uni.mode,
        "tickersWithData": len(bars),
        "tickersRequested": n_tickers,
        "seed": seed,
        "period": {"rawStart": RAW_START, "perfStart": PERF_START, "end": END,
                   "split": "TRAIN <= 2022-06-30 < VALID <= 2024-01-01 < TEST"},
        "costBps": {"entry": ENTRY_BPS, "exit": EXIT_BPS, "slippage": 0},
        "portfolio": "슬롯 상한 없는 동일가중 신호 포트폴리오 (활성 N개면 각 1/N, N=0 이면 현금). capacity 미검증.",
        "accounting": "일별 MTM (open->open 분해). 실현손익 누적 아님.",
        "benchmarks": bench,
        "variants": sorted(results, key=lambda r: -(r["net"].get("CAGR") or -99)),
        "elapsedSeconds": round(time.time() - t0, 1),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "smoke_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwritten: {OUT_DIR/'smoke_result.json'}  ({out['elapsedSeconds']}s)")
    return out


def selftest():
    idx = ["2020-01-%02d" % i for i in range(1, 21)]
    c = pd.Series([10, 10, 10, 10, 10, 10, 10, 10, 10, 10,
                   11, 12, 13, 14, 15, 14, 13, 12, 11, 10], index=idx, dtype=float)
    df = pd.DataFrame({"open": c, "high": c, "low": c, "close": c})

    k, _ = stochastic(df.high, df.low, df.close, 5, 3, 3)
    assert 0 <= k.dropna().min() and k.dropna().max() <= 100, "stoch out of range"

    up, dn = cross_flags(c, c.rolling(3).mean())
    assert up.iloc[10] and not up.iloc[9], "cross_flags: 상향돌파 bar 오식별"
    assert not (up & dn).any(), "cross_flags: 같은 bar 상하향 동시"

    # 체결이 신호 다음 bar 인지 (same-bar lookahead 0)
    en = np.zeros(20, bool)
    ex = np.zeros(20, bool)
    en[3] = True
    ex[8] = True
    tr = trades_for_symbol("T", df, en, ex, None)
    assert len(tr) == 1 and tr[0]["entry_date"] == idx[4] and tr[0]["exit_date"] == idx[9], tr
    assert tr[0]["entry_date"] > tr[0]["signal_date"] and tr[0]["exit_date"] > tr[0]["exit_signal_date"]

    # daily_legs 의 곱 == 트레이드 net 수익 (회계 항등)
    legs = daily_legs(tr[0], df)
    prod = float(np.prod([1 + r for _, r in legs])) - 1
    assert abs(prod - tr[0]["net_ret"]) < 1e-12, (prod, tr[0]["net_ret"])
    assert [dd for dd, _ in legs] == idx[4:9], legs

    # MTM: 100 -> 50 -> 100 의 MDD 는 -50% (실현손익 누적이면 0 이 나온다)
    m = metrics([("2020-01-31", 100.0), ("2020-02-29", 50.0), ("2020-03-31", 100.0)])
    assert m["MDD"] == -50.0 and m["totalReturn"] == 0.0, m
    assert period_of("2022-06-30") == "TRAIN" and period_of("2022-07-01") == "VALID"
    assert period_of("2024-01-01") == "VALID" and period_of("2024-01-02") == "TEST"
    print("selftest ok (11 assertions)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--placebo", default="", help="variant id (난수 바닥선)")
    ap.add_argument("--reps", type=int, default=20)
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.placebo:
        placebo(a.placebo, a.reps, a.tickers, a.seed)
    else:
        run(a.tickers, a.seed)
