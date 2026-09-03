#!/usr/bin/env python
"""손익비(TP/SL) 시뮬레이터 — Tier 1.5.

Tier 1(월별 패널 스윕)은 "무엇을 살까"만 답한다. 월별 종가만 보기 때문에
"손절을 먼저 맞았는지 목표가를 먼저 맞았는지"를 알 수 없어 손익비 개념 자체가
성립하지 않는다. 이 스크립트는 A2a 일별 OHLC(2014~2026)로 그 경로를 재현해
"언제 팔까"를 격자로 훑는다.

  Tier 1    월별 패널 스윕     무엇을 살까      15ms/조합
  Tier 1.5  여기               언제 팔까        손익비 격자
  Tier 2    실제 엔진          슬롯·현금·비용    최종 확인

청산 규칙은 새로 정하지 않았다 - engine/execution/executor.py 를 읽어 그대로
옮겼다. 안 그러면 여기서 고른 후보가 실제 엔진에서 무의미해진다:

  1 진입 = 신호일 다음 세션의 **시가**            build_order + bars["open"]
  2 손절가 = 진입가 - stop_distance (절대거리)
  3 목표가 = 진입가 + reward_risk * stop_distance  <- 여기가 손익비
  4 같은 봉에 둘 다 닿으면 **무조건 손절**         if hit_stop: ... elif hit_target:
  5 시가가 이미 손절가 아래면 그 시가에 체결       _fill_stop gapped_through
  6 **진입 당일도 판정 대상**                      next_n_sessions 가 시작일 포함
  7 미체결 시 마지막 세션 종가 청산                TIME_EXIT
  + 거래정지(바 없음)는 건너뛴다. 보유 중 데이터가 끊기면 거래를 지어내지 않고 버린다.
  + 비용도 엔진과 동일: 매수가 x(1+15bp), 매도대금 x(1-15bp).

종목선택은 sweep_combos.build_matrices 를 그대로 재사용한다 - 랭킹 규약이
어긋나면 Tier 1 과 다른 전략을 재는 셈이 되기 때문이다.

주의 - 이 계층은 포트폴리오가 아니다. 손익비를 넣으면 보유기간이 제각각이라
포지션이 겹치는데, 슬롯 30개·현금 제약까지 넣으면 그게 곧 Tier 2 다. 여기서는
**거래 단위 통계**만 낸다(기대값·승률·실현손익비·평균보유일). 슬롯 경쟁이
결론을 뒤집은 사례가 이미 있다(VIX 정제필터 기각) - 그 판단은 Tier 2 몫이다.

사용법
------
  python simulate_exits.py --selftest
  python simulate_exits.py --calibrate --factors pbr,roe    # Tier 1 과 일치하는지
  python simulate_exits.py --factors pbr,growth_accel       # 격자 스윕
"""
import argparse
import bisect
import glob
import gzip
import json
import math
import os
import sys
import time

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(LAB))
A2A_DIR = os.path.join(REPO, "data", "backfill", "price", "a2a")
OHLC_CACHE = os.path.join(LAB, "data", "factor-panel", "a2a-ohlc.parquet")
PANEL_PATH = os.path.join(LAB, "data", "factor-panel", "kr-monthly-v1.parquet")
MANIFEST_PATH = os.path.join(LAB, "data", "factor-panel", "_manifest_kr_monthly.json")

ENTRY_BPS, EXIT_BPS = 15.0, 15.0     # 엔진 Primary 기본값
ATR_WINDOW = 20
TOP_QUANTILE = 0.9
MIN_NAMES = 30

# 격자 - 손절폭 x 손익비 x 최대보유
ATR_MULTS = [1.0, 1.5, 2.0, 3.0]
PCT_STOPS = [0.05, 0.08, 0.12]
REWARD_RISKS = [1.0, 1.5, 2.0, 3.0, 5.0]
MAX_HOLDS = [21, 42, 63]


# ---------------------------------------------------------------------------
# A2a 일별 OHLC
# ---------------------------------------------------------------------------
def build_ohlc_cache(verbose=True):
    rows = []
    for fp in sorted(glob.glob(os.path.join(A2A_DIR, "[12]*.jsonl.gz"))):
        with gzip.open(fp, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if "open" not in r:          # 품질제외 로그 등 다른 스키마는 건너뛴다
                    break
                rows.append((r["ticker"], r["date"], r["open"], r["high"],
                             r["low"], r["close"]))
        if verbose:
            print(f"  {os.path.basename(fp)}: 누적 {len(rows):,}행", flush=True)
    df = pd.DataFrame(rows, columns=["ticker", "date", "open", "high", "low", "close"])
    df = df.drop_duplicates(subset=["ticker", "date"], keep="last")
    os.makedirs(os.path.dirname(OHLC_CACHE), exist_ok=True)
    df.to_parquet(OHLC_CACHE, index=False)
    return df


def load_ohlc(verbose=True):
    """(dates, tickers, O, H, L, C, ATR) - 전부 (날짜 x 종목) 행렬."""
    if not os.path.exists(OHLC_CACHE):
        if verbose:
            print("A2a OHLC 캐시가 없다 - 최초 1회 생성 ...", flush=True)
        df = build_ohlc_cache(verbose)
    else:
        df = pd.read_parquet(OHLC_CACHE)
    df["date"] = df["date"].astype(str)
    wide = {c: df.pivot_table(index="date", columns="ticker", values=c, aggfunc="last")
            for c in ("open", "high", "low", "close")}
    dates = list(wide["close"].index)
    tickers = list(wide["close"].columns)
    O, H, L, C = (wide[c].to_numpy(dtype=np.float32) for c in ("open", "high", "low", "close"))
    # 거래정지 아티팩트: A2a 는 open=high=low=0 을 남길 수 있다(랩에서 이미 확인된 사례)
    bad = (O <= 0) | (H <= 0) | (L <= 0) | (C <= 0)
    O[bad] = H[bad] = L[bad] = C[bad] = np.nan
    # ATR: true range 의 단순이동평균
    prev_c = np.vstack([np.full((1, C.shape[1]), np.nan, np.float32), C[:-1]])
    tr = np.fmax(H - L, np.fmax(np.abs(H - prev_c), np.abs(L - prev_c)))
    atr = pd.DataFrame(tr).rolling(ATR_WINDOW, min_periods=ATR_WINDOW).mean().to_numpy(np.float32)
    return dates, tickers, O, H, L, C, atr


# ---------------------------------------------------------------------------
# 경로 시뮬레이션 (코호트 단위 벡터화)
# ---------------------------------------------------------------------------
def simulate_cohort(entry_i, cols, O, H, L, C, stop_dist, rr, max_hold, slip_bps=0.0):
    """한 코호트(같은 날 진입하는 종목들)를 한 번에 시뮬레이션한다.

    slip_bps 는 엔진 `_apply_slippage` 와 같은 방식이다 - 매수는 시가를 올려서 체결하고,
    손절/목표/시간청산가는 내려서 체결한다. 손절가·목표가는 **슬리피지가 반영된
    진입가**에서 계산된다(엔진과 동일). 저유동성 종목을 사는 전략의 생사가 여기 달렸다.

    반환: (ret, hold_days, kind) - 유효한 거래만. kind 0=STOP 1=TARGET 2=TIME.
    """
    n_days = O.shape[0]
    end = min(entry_i + max_hold, n_days)
    if end <= entry_i:
        return None
    entry = O[entry_i, cols] * (1 + slip_bps / 1e4)          # 매수 슬리피지
    ok = np.isfinite(entry) & np.isfinite(stop_dist) & (stop_dist > 0)
    if not ok.any():
        return None
    cols, entry, stop_dist = cols[ok], entry[ok], stop_dist[ok]

    stop = entry - stop_dist
    target = entry + rr * stop_dist
    lo, hi, op, cl = (X[entry_i:end][:, cols] for X in (L, H, O, C))   # (H, n)

    with np.errstate(invalid="ignore"):
        hit_s = lo <= stop            # NaN 비교는 False -> 거래정지일 자동 스킵
        hit_t = hi >= target
    event = hit_s | hit_t
    any_ev = event.any(axis=0)
    first = np.argmax(event, axis=0)                       # 최초 발생일

    idx = np.arange(len(cols))
    is_stop = np.zeros(len(cols), bool)
    is_stop[any_ev] = hit_s[first[any_ev], idx[any_ev]]    # 규칙 4: 같은 봉이면 손절

    # 마지막 유효 종가 (규칙 7). 마지막 세션에 바가 없으면 거래를 버린다.
    last_close = cl[-1]
    exit_p = np.full(len(cols), np.nan, np.float32)
    hold = np.full(len(cols), end - entry_i, np.int32)

    # STOP: 시가가 이미 손절가 아래면 그 시가 (규칙 5)
    s_idx = idx[any_ev & is_stop]
    if len(s_idx):
        f = first[s_idx]
        o_at = op[f, s_idx]
        gapped = np.isfinite(o_at) & (o_at <= stop[s_idx])
        exit_p[s_idx] = np.where(gapped, o_at, stop[s_idx])
        hold[s_idx] = f + 1
    # TARGET
    t_idx = idx[any_ev & ~is_stop]
    if len(t_idx):
        exit_p[t_idx] = target[t_idx]
        hold[t_idx] = first[t_idx] + 1
    # TIME EXIT
    n_idx = idx[~any_ev]
    if len(n_idx):
        exit_p[n_idx] = last_close[n_idx]

    kind = np.where(any_ev, np.where(is_stop, 0, 1), 2).astype(np.int8)
    valid = np.isfinite(exit_p)
    if not valid.any():
        return None
    buy = entry[valid] * (1 + ENTRY_BPS / 1e4)
    sell = exit_p[valid] * (1 - slip_bps / 1e4) * (1 - EXIT_BPS / 1e4)   # 매도 슬리피지
    return sell / buy - 1.0, hold[valid], kind[valid]


def run_grid(sel_by_month, dates, tickers, O, H, L, C, ATR,
             stop_mode, stop_param, rr, max_hold, slip_bps=0.0):
    """모든 코호트를 한 격자점으로 시뮬레이션하고 거래 단위 통계를 낸다."""
    tix = {t: i for i, t in enumerate(tickers)}
    rets, holds, kinds, monthly = [], [], [], []
    for sig_date, names in sel_by_month:
        ei = bisect.bisect_right(dates, sig_date)          # 신호일 '다음' 세션 (규칙 1)
        if ei >= len(dates):
            continue
        cols = np.array([tix[t] for t in names if t in tix], dtype=np.int64)
        if len(cols) == 0:
            continue
        if stop_mode == "atr":
            dist = ATR[ei, cols] * stop_param
        else:
            dist = O[ei, cols] * stop_param
        out = simulate_cohort(ei, cols, O, H, L, C, dist, rr, max_hold, slip_bps)
        if out is None:
            continue
        r, h, k = out
        rets.append(r); holds.append(h); kinds.append(k)
        monthly.append(float(np.mean(r)))
    if not rets:
        return None
    r = np.concatenate(rets); h = np.concatenate(holds); k = np.concatenate(kinds)
    m = np.array(monthly, dtype=float)
    wins, losses = r[r > 0], r[r < 0]
    avg_w = float(wins.mean()) if len(wins) else 0.0
    avg_l = float(losses.mean()) if len(losses) else 0.0
    sd = float(m.std(ddof=1)) if len(m) > 1 else 0.0
    # t 는 월별 코호트 평균으로 낸다(거래끼리 같은 달을 공유하므로 클러스터 보정 효과)
    t = float(m.mean() / (sd / math.sqrt(len(m)))) if sd > 0 else 0.0
    avg_hold = float(h.mean())
    return {
        "stopMode": stop_mode, "stopParam": stop_param, "rr": rr, "maxHold": max_hold,
        "slipBps": slip_bps,
        "nTrades": int(len(r)), "nCohorts": len(m),
        "winRate": round(float((r > 0).mean()), 4),
        "expectancy": round(float(r.mean()), 6),          # 기대값 = 최적화 대상
        "medianTrade": round(float(np.median(r)), 6),
        "avgWin": round(avg_w, 6), "avgLoss": round(avg_l, 6),
        "realizedRR": round(avg_w / abs(avg_l), 3) if avg_l < 0 else None,
        "avgHoldDays": round(avg_hold, 1),
        "exitStopPct": round(float((k == 0).mean()), 4),
        "exitTargetPct": round(float((k == 1).mean()), 4),
        "exitTimePct": round(float((k == 2).mean()), 4),
        "monthlyMean": round(float(m.mean()), 6), "t": round(t, 3),
        # 회전을 가정한 연환산 근사. 자본제약·유휴현금 미반영 - Tier 2 가 진짜를 잰다.
        "annualizedApprox": round((1 + float(r.mean())) ** (252.0 / max(avg_hold, 1)) - 1, 4),
    }


# ---------------------------------------------------------------------------
def selections_for(factors, period="TRAIN"):
    """sweep_combos 와 **동일한** 랭킹으로 월별 상위 decile 종목을 뽑는다."""
    import sweep_combos as sw
    catalog = json.load(open(MANIFEST_PATH, encoding="utf-8"))["factors"]
    panel = pd.read_parquet(PANEL_PATH)
    R, FWD, TICK, months, M, width, names = sw.build_matrices(panel, catalog, factors, period)
    idx = list(range(len(factors)))
    comp = R[idx].sum(axis=0) if len(idx) > 1 else R[idx[0]]
    out = []
    for mi in range(M):
        row = comp[mi]
        v = ~np.isnan(row)
        if v.sum() < MIN_NAMES:
            continue
        thr = np.nanquantile(row[v], TOP_QUANTILE)
        pick = v & (row >= thr)
        out.append((months[mi], [names[c] for c in TICK[mi][pick] if c >= 0]))
    return out


def random_selections_for(n, period="TRAIN", seed=0):
    """종목선택 능력이 0인 대조군. 청산규칙이 '종목을 잘 골라서'가 아니라
    규칙 자체로 이득을 주는지 보려면 이 바닥선이 필요하다(2026-09-02 난수 절차와 같은 취지).
    유니버스는 팩터 유효성이 아니라 fwd1m 유효성(다음달 거래가능)으로만 잡는다 - 팩터 편향 없음."""
    import sweep_combos as sw
    catalog = json.load(open(MANIFEST_PATH, encoding="utf-8"))["factors"]
    panel = pd.read_parquet(PANEL_PATH)
    anchor = next(iter(catalog))
    _, FWD, TICK, months, M, _, names = sw.build_matrices(panel, catalog, [anchor], period)
    rng = np.random.default_rng(seed)
    out = []
    for mi in range(M):
        v = np.where(~np.isnan(FWD[mi]))[0]
        if len(v) < n:
            continue
        pick = rng.choice(v, size=n, replace=False)
        out.append((months[mi], [names[c] for c in TICK[mi][pick] if c >= 0]))
    return out


def print_table(res, title):
    print(f"\n{title}")
    print(f"{'손절':>10} {'RR':>4} {'보유':>4} {'거래':>7} {'승률':>6} {'기대값':>8} "
          f"{'실현RR':>7} {'평균보유':>7} {'손절%':>6} {'목표%':>6} {'시간%':>6} "
          f"{'연환산≈':>8} {'t':>6}")
    print("-" * 108)
    for r in res:
        sp = (f"ATR×{r['stopParam']:.1f}" if r["stopMode"] == "atr"
              else f"{r['stopParam'] * 100:.0f}%")
        rr = f"{r['realizedRR']:.2f}" if r["realizedRR"] is not None else "—"
        print(f"{sp:>10} {r['rr']:>4.1f} {r['maxHold']:>4} {r['nTrades']:>7,} "
              f"{r['winRate'] * 100:>5.1f}% {r['expectancy'] * 100:>7.3f}% {rr:>7} "
              f"{r['avgHoldDays']:>7.1f} {r['exitStopPct'] * 100:>5.1f}% "
              f"{r['exitTargetPct'] * 100:>5.1f}% {r['exitTimePct'] * 100:>5.1f}% "
              f"{r['annualizedApprox'] * 100:>7.2f}% {r['t']:>6.2f}")


def selftest():
    """엔진 규칙 7개가 실제로 그렇게 동작하는지 손으로 만든 봉으로 확인한다."""
    def bars(rows):
        a = np.array(rows, dtype=np.float32).T          # (4, days) -> O,H,L,C
        return [x.reshape(-1, 1) for x in a]

    # 진입 100. 손절거리 10 -> 손절 90, RR 2 -> 목표 120
    # day0(진입일): 96~105 로 아무것도 안 닿음 / day1: 저가 89 -> 손절
    O, H, L, C = bars([[100, 105, 96, 104], [104, 110, 89, 95]])
    r, h, k = simulate_cohort(0, np.array([0]), O, H, L, C, np.array([10.0], np.float32), 2.0, 5)
    assert k[0] == 0 and h[0] == 2, (k, h)                      # 규칙 4/7
    assert abs(r[0] - ((90 * (1 - 15e-4)) / (100 * (1 + 15e-4)) - 1)) < 1e-6

    # 규칙 5: 시가가 이미 손절가 아래 -> 그 시가에 체결(90 이 아니라 85)
    O, H, L, C = bars([[100, 105, 96, 104], [85, 88, 80, 82]])
    r, h, k = simulate_cohort(0, np.array([0]), O, H, L, C, np.array([10.0], np.float32), 2.0, 5)
    assert k[0] == 0 and abs(r[0] - ((85 * (1 - 15e-4)) / (100 * (1 + 15e-4)) - 1)) < 1e-6

    # 규칙 4: 같은 봉에 손절·목표 둘 다 -> 손절 우선
    O, H, L, C = bars([[100, 125, 85, 120]])
    r, h, k = simulate_cohort(0, np.array([0]), O, H, L, C, np.array([10.0], np.float32), 2.0, 5)
    assert k[0] == 0, "같은 봉에서 목표를 먼저 잡았다"

    # 규칙 6: 진입 당일에도 목표 도달이 잡힌다
    O, H, L, C = bars([[100, 121, 99, 120]])
    r, h, k = simulate_cohort(0, np.array([0]), O, H, L, C, np.array([10.0], np.float32), 2.0, 5)
    assert k[0] == 1 and h[0] == 1, (k, h)

    # 규칙 7: 아무것도 안 닿으면 마지막 세션 종가
    O, H, L, C = bars([[100, 105, 96, 104], [104, 108, 99, 107]])
    r, h, k = simulate_cohort(0, np.array([0]), O, H, L, C, np.array([10.0], np.float32), 2.0, 2)
    assert k[0] == 2 and abs(r[0] - ((107 * (1 - 15e-4)) / (100 * (1 + 15e-4)) - 1)) < 1e-6

    # 거래정지(NaN)는 건너뛰고, 마지막 봉이 없으면 거래를 버린다
    O, H, L, C = bars([[100, 105, 96, 104], [np.nan] * 4])
    out = simulate_cohort(0, np.array([0]), O, H, L, C, np.array([10.0], np.float32), 2.0, 2)
    assert out is None, "마지막 봉이 없는데 거래를 지어냈다"

    # 슬리피지: 매수는 비싸게, 매도는 싸게. 손절가·목표가도 슬리피지 반영 진입가 기준.
    O, H, L, C = bars([[100, 105, 96, 104], [104, 108, 99, 107]])
    r0, _, _ = simulate_cohort(0, np.array([0]), O, H, L, C,
                               np.array([10.0], np.float32), 2.0, 2, slip_bps=0.0)
    r1, _, _ = simulate_cohort(0, np.array([0]), O, H, L, C,
                               np.array([10.0], np.float32), 2.0, 2, slip_bps=50.0)
    assert r1[0] < r0[0], "슬리피지를 넣었는데 수익이 안 줄었다"
    exp = (107 * (1 - 50e-4) * (1 - 15e-4)) / (100 * (1 + 50e-4) * (1 + 15e-4)) - 1
    assert abs(r1[0] - exp) < 1e-6, (r1[0], exp)

    # 손익비를 올리면 승률은 내려간다(산수) - 착시 방지용 회귀
    rng = np.random.default_rng(3)
    n = 400
    path = 100 * np.cumprod(1 + rng.standard_normal((30, n)) * 0.02, axis=0).astype(np.float32)
    Ox = np.vstack([np.full((1, n), 100, np.float32), path[:-1]])
    Hx, Lx, Cx = path * 1.01, path * 0.99, path
    dist = np.full(n, 5.0, np.float32)
    wr = []
    for rr in (1.0, 3.0):
        r, h, k = simulate_cohort(0, np.arange(n), Ox, Hx, Lx, Cx, dist, rr, 30)
        wr.append((r > 0).mean())
    assert wr[0] > wr[1], f"RR 을 올렸는데 승률이 안 내려갔다 {wr}"

    print("selftest OK (엔진규칙 7건 + 손익비-승률 반비례 1건)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--factors", default=None, help="쉼표구분 팩터 조합")
    ap.add_argument("--period", default="TRAIN")
    ap.add_argument("--stop-mode", default="atr", choices=["atr", "pct", "both"])
    ap.add_argument("--calibrate", action="store_true",
                    help="손절 없이 21세션 시간청산 - Tier 1 과 같은 세계를 보는지 확인")
    ap.add_argument("--build-cache", action="store_true")
    ap.add_argument("--out", default=None)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--random-entries", type=int, default=None,
                    help="종목선택 대조군: 매달 무작위 N종목 (팩터 대신)")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    if a.selftest:
        selftest()
        return 0
    selftest()
    if a.build_cache:
        build_ohlc_cache()
        print(f"저장: {OHLC_CACHE}")
        return 0
    if not a.factors and a.random_entries is None:
        raise SystemExit("--factors 또는 --random-entries 가 필요하다")

    factors = a.factors.split(",") if a.factors else []
    t0 = time.time()
    print(f"A2a 일별 OHLC 적재 ...", flush=True)
    dates, tickers, O, H, L, C, ATR = load_ohlc()
    print(f"  {len(dates):,}일 x {len(tickers):,}종목  ({time.time() - t0:.0f}s)")

    if a.random_entries is not None:
        sel = random_selections_for(a.random_entries, a.period, a.seed)
        label = f"무작위 {a.random_entries}종목 seed={a.seed}"
    else:
        sel = selections_for(factors, a.period)
        label = "+".join(factors)
    n_names = np.mean([len(s[1]) for s in sel]) if sel else 0
    print(f"종목선택({label}, {a.period}): {len(sel)}개 코호트, "
          f"평균 {n_names:.0f}종목/월")

    if a.calibrate:
        # 손절거리를 진입가의 100배로 -> 닿을 수 없다 = 순수 시간청산
        res = [run_grid(sel, dates, tickers, O, H, L, C, ATR, "pct", 100.0, 1.0, 21)]
        print_table([r for r in res if r], "교정 — 손절 없이 21세션 시간청산")
        print("\n  Tier 1 의 같은 조합 월평균 초과수익과 비교할 것. 완전히 같지는 않다 —")
        print("  Tier 1 은 다음날 '종가' 진입, 여기는 엔진과 같은 다음날 '시가' 진입이다.")
        return 0

    grid = []
    if a.stop_mode in ("atr", "both"):
        grid += [("atr", m) for m in ATR_MULTS]
    if a.stop_mode in ("pct", "both"):
        grid += [("pct", p) for p in PCT_STOPS]

    res = []
    for mode, param in grid:
        for rr in REWARD_RISKS:
            for mh in MAX_HOLDS:
                r = run_grid(sel, dates, tickers, O, H, L, C, ATR, mode, param, rr, mh)
                if r:
                    res.append(r)
    print(f"\n격자 {len(res)}점 완료 ({time.time() - t0:.0f}s)")

    res.sort(key=lambda r: r["expectancy"], reverse=True)
    print_table(res[:20], "기대값 상위 20 — ★ 승률이 아니라 기대값으로 고른다")
    print("\n  손익비를 올리면 승률은 기계적으로 내려간다(알파가 아니라 산수다).")
    print("  최적화 대상은 승률도 실현RR 도 아닌 **기대값**이다.")

    # 표면의 매끄러움 - 한 칸만 뾰족하면 노이즈, 완만한 언덕이면 진짜
    print(f"\n=== RR 별 기대값 표면 (최대보유 42세션 고정) ===")
    print(f"{'손절':>10} " + "".join(f"{f'RR {r:g}':>10}" for r in REWARD_RISKS))
    for mode, param in grid:
        sp = f"ATR×{param:.1f}" if mode == "atr" else f"{param * 100:.0f}%"
        cells = []
        for rr in REWARD_RISKS:
            m = next((x for x in res if x["stopMode"] == mode and x["stopParam"] == param
                      and x["rr"] == rr and x["maxHold"] == 42), None)
            cells.append(f"{m['expectancy'] * 100:>9.3f}%" if m else f"{'—':>10}")
        print(f"{sp:>10} " + "".join(cells))

    out_dir = a.out or os.path.join(LAB, "reports", f"{time.strftime('%Y-%m-%d')}-exit-grid")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"exit-grid-{'_'.join(factors)}-{a.period.lower()}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "experiment": "EXIT-GRID-KR", "factors": factors, "period": a.period,
            "engineRules": "engine/execution/executor.py 그대로 (진입=다음세션 시가, "
                           "같은봉 STOP_FIRST, 갭시 시가체결, 진입당일 판정, 시간청산=종가)",
            "costBps": {"entry": ENTRY_BPS, "exit": EXIT_BPS},
            "nCohorts": len(sel), "avgNamesPerCohort": round(float(n_names), 1),
            "gridPoints": len(res),
            "warning": "거래 단위 통계다. 슬롯 경쟁·현금 제약·주식 수 반올림은 반영돼 있지 "
                       "않다 - 그건 Tier 2(실제 엔진) 몫이다. annualizedApprox 는 회전을 "
                       "가정한 근사이지 CAGR 이 아니다. 격자 최댓값 하나를 고르지 말고 "
                       "RR 표면이 완만한 언덕인지부터 볼 것.",
            "results": res,
        }, f, ensure_ascii=False, indent=1)
    print(f"\n저장: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
