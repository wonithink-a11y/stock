#!/usr/bin/env python3
"""워뇨띠 운용 구조(급락 분할 매수 + 되돌림 청산) — 사전등록 findings/wonyotti-ladder-structure-preregistration-2026-09.md

    python research/strategy-lab/wonyotti/ladder_structure.py            # 실행(8프로세스, 수 분)
    python research/strategy-lab/wonyotti/ladder_structure.py --selftest
"""
from __future__ import annotations

import glob
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
DATA = LAB / "data" / "crypto"
OUT = LAB / "findings" / "wonyotti-ladder-structure-results-2026-09.json"
SIDE_BP = 5.0          # 한 방향 비용(테이커 0.05%) — 왕복 10bp
STRESS_SIDE_BP = 10.0  # 스트레스 왕복 20bp
ACT = 0.5              # 되돌림 청산 활성화: 마지막 체결 뒤 고점 ≥ 평단 × (1 + 0.5·σ24)
STOP_SD = 4.0          # 손절(선택): 첫 진입가 × (1 − 4·σ24)
N_NULL = 200
SEED = 20260926
TRAIN = ("2018-01-01", "2021-12-31 23:00")
OOS_START = "2022-01-01"

TRIGGERS = [(4, 2.0), (4, 3.0), (24, 2.0), (24, 3.0)]                  # (L 시간, k σ)
ADDS = [(0, 0.0, 1)] + [(m, g, a) for m in (2, 5) for g in (0.5, 1.0) for a in (1, 2)]  # (최대 추가, 간격 σ24, 크기 배수)
EXITS = [(q, h, s) for q in (0.3, 0.5) for h in (24, 72, 168) for s in (False, True)]   # (되돌림 비율, 최대 보유, 손절)
COMBOS = [(t, a, e) for t in range(len(TRIGGERS)) for a in ADDS for e in EXITS]


def hourly_btc() -> pd.Series:
    b = pd.read_parquet(DATA / "1m" / "BTCUSDT_1m.parquet", columns=["open_time_utc", "open"])
    p = b.set_index("open_time_utc")["open"].resample("1h").first()
    return p.ffill(limit=3)


def hourly_coins() -> dict[str, pd.Series]:
    out = {}
    for f in sorted(glob.glob(str(DATA / "basis" / "1h" / "*_1h.parquet"))):
        sym = Path(f).name.replace("_1h.parquet", "")
        if sym == "BTCUSDT":
            continue
        d = pd.read_parquet(f, columns=["time", "mark_open"]).set_index("time").sort_index()
        d = d[~d.index.duplicated()].asfreq("1h")["mark_open"].ffill(limit=3)
        d.index = d.index.tz_localize(None) if d.index.tz is not None else d.index
        out[sym] = d
    return out


def prep(p: pd.Series) -> dict:
    lp = np.log(p)
    s1 = lp.diff().shift(1).rolling(720, min_periods=360).std()
    trig = []
    for L, k in TRIGGERS:
        trig.append(((lp - lp.shift(L)) <= -k * s1 * np.sqrt(L)).to_numpy())
    return {"idx": p.index, "p": p.to_numpy(float), "s24": (s1 * np.sqrt(24)).to_numpy(float), "trig": trig}


def run(p, s24, starts, add, ext, end=None):
    """starts: 정렬된 후보 진입 인덱스. 반환: [(진입 i, 청산 t, gross bp, 비용 단위)] — 비용 단위 × 한 방향 bp = 비용."""
    m, g, a = add
    q, H, stop = ext
    n = len(p) if end is None else end
    units = [a ** j for j in range(m + 1)]
    C = float(sum(units))
    out, last = [], -1
    for i in starts:
        if i <= last:
            continue
        if i + H >= n:
            break
        P0, sd = p[i], s24[i]
        if not (np.isfinite(P0) and np.isfinite(sd) and sd > 0):
            continue
        levels = [P0 * (1 - j * g * sd) for j in range(1, m + 1)]
        fu, fx = [1.0], [P0]
        nxt, peak = 0, P0
        stop_p = P0 * (1 - STOP_SD * sd) if stop else -1.0
        t = i
        for t in range(i + 1, i + H + 1):
            pt = p[t]
            if not np.isfinite(pt):
                continue
            filled_now = False
            while nxt < m and pt <= levels[nxt]:
                fu.append(float(units[nxt + 1]))
                fx.append(pt)
                nxt += 1
                filled_now = True
            if filled_now:
                peak = pt
                continue
            if pt <= stop_p:
                break
            peak = max(peak, pt)
            avg = sum(u * x for u, x in zip(fu, fx)) / sum(fu)
            if q > 0 and peak >= avg * (1 + ACT * sd) and pt <= peak - q * (peak - avg):
                break
        pe = p[t]
        gross = sum(u * (pe / x - 1) for u, x in zip(fu, fx)) / C * 1e4
        out.append((i, t, gross, 2 * sum(fu) / C))
        last = t
    return out


def tstat(x) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else 0.0


def net(res, side=SIDE_BP):
    return np.array([g - c * side for _, _, g, c in res])


def starts_in(mask, idx, lo, hi):
    ok = np.asarray(mask, bool) & (idx >= pd.Timestamp(lo)) & (idx <= pd.Timestamp(hi))
    return np.flatnonzero(ok)


def roll_mask(mask, lo_i, hi_i, rng):
    """[lo_i, hi_i] 구간 안에서 신호 마스크를 원형 이동 — 신호의 군집 구조·개수는 보존, 가격과의 정렬만 끊는다."""
    seg = mask[lo_i:hi_i + 1]
    span = len(seg)
    off = int(rng.integers(720, span - 720))
    out = mask.copy()
    out[lo_i:hi_i + 1] = np.roll(seg, off)
    return out


def train_all(P, masks, lo, hi, end):
    ts = []
    for ti, add, ext in COMBOS:
        st = starts_in(masks[ti], P["idx"], lo, hi)
        ts.append(tstat(net(run(P["p"], P["s24"], st, add, ext, end))))
    return ts


def _null_worker(args):
    P, lo, hi, end, seed = args
    rng = np.random.default_rng(seed)
    lo_i = int(np.searchsorted(P["idx"], pd.Timestamp(lo)))
    hi_i = int(np.searchsorted(P["idx"], pd.Timestamp(hi), side="right")) - 1
    masks = [roll_mask(m, lo_i, hi_i, rng) for m in P["trig"]]
    return max(train_all(P, masks, lo, hi, end))


def summarize(res, label):
    g = np.array([r[2] for r in res])
    cu = np.array([r[3] for r in res])
    n10, n20 = net(res), net(res, STRESS_SIDE_BP)
    rng = np.random.default_rng(SEED)
    boot = [rng.choice(g, len(g)).mean() for _ in range(2000)] if len(g) > 2 else [np.nan]
    return {"label": label, "n": len(res), "gross_bp": float(g.mean()) if len(g) else None,
            "gross_ci95": [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
            "net10_bp": float(n10.mean()) if len(g) else None, "net10_t": tstat(n10),
            "net20_bp": float(n20.mean()) if len(g) else None,
            "breakeven_roundtrip_bp": float(g.mean() / cu.mean() * 2) if len(g) and cu.mean() > 0 else None,
            "win_rate": float((n10 > 0).mean()) if len(g) else None,
            "skew": float(pd.Series(n10).skew()) if len(g) > 2 else None}


def monthly_t(res_by_coin, idx_by_coin):
    rows = [(idx_by_coin[c][i].to_period("M"), g - cu * SIDE_BP) for c, res in res_by_coin.items() for i, _, g, cu in res]
    if not rows:
        return 0.0, 0
    s = pd.DataFrame(rows, columns=["m", "r"]).groupby("m").r.mean()
    return tstat(s.to_numpy()), len(s)


def main():
    btc = prep(hourly_btc())
    idx = btc["idx"]
    end_tr = int(np.searchsorted(idx, pd.Timestamp(TRAIN[1]), side="right"))
    # 1) TRAIN 전 조합
    t_real = train_all(btc, btc["trig"], TRAIN[0], TRAIN[1], end_tr)
    order = np.argsort(t_real)[::-1]
    # 2) 바닥선: 신호 원형 이동 N_NULL 회, 회마다 전 조합 최대 t
    with Pool(8) as pool:
        mx = pool.map(_null_worker, [(btc, TRAIN[0], TRAIN[1], end_tr, SEED + k) for k in range(N_NULL)])
    floor = float(np.quantile(mx, 0.95))
    best = order[0]
    ti, add, ext = COMBOS[best]
    passed = t_real[best] >= floor
    # 3) OOS 1회: BTC 2022~ · 코인 27종 전 구간
    st_oos = starts_in(btc["trig"][ti], idx, OOS_START, idx[-1])
    r_btc = run(btc["p"], btc["s24"], st_oos, add, ext)
    rng = np.random.default_rng(SEED + 999)
    lo_i = int(np.searchsorted(idx, pd.Timestamp(OOS_START)))
    null_btc = []
    for _ in range(N_NULL):
        m = roll_mask(btc["trig"][ti], lo_i, len(idx) - 1, rng)
        null_btc.append(net(run(btc["p"], btc["s24"], starts_in(m, idx, OOS_START, idx[-1]), add, ext)).mean())
    coins = {s: prep(p) for s, p in hourly_coins().items()}
    rc, null_c = {}, []
    for s, P in coins.items():
        rc[s] = run(P["p"], P["s24"], np.flatnonzero(P["trig"][ti]), add, ext)
    for _ in range(N_NULL):
        allr = []
        for s, P in coins.items():
            m = roll_mask(P["trig"][ti], 0, len(P["p"]) - 1, rng)
            allr += list(net(run(P["p"], P["s24"], np.flatnonzero(m), add, ext)))
        null_c.append(float(np.mean(allr)))
    pooled = [r for v in rc.values() for r in v]
    mt, nm = monthly_t(rc, {s: P["idx"] for s, P in coins.items()})
    # 기록 전용: 같은 신호·같은 최대 보유의 고정 보유(추가·되돌림 없음)
    base_ext = (0.0, ext[1], False)
    r_btc_base = run(btc["p"], btc["s24"], st_oos, (0, 0.0, 1), base_ext)
    pooled_base = [r for s, P in coins.items() for r in run(P["p"], P["s24"], np.flatnonzero(P["trig"][ti]), (0, 0.0, 1), base_ext)]
    r_tr_best = run(btc["p"], btc["s24"], starts_in(btc["trig"][ti], idx, *TRAIN), add, ext, end_tr)
    sb, sc = summarize(r_btc, "BTC OOS"), summarize(pooled, "27종 전 구간")
    ex_btc = sb["net10_bp"] - float(np.mean(null_btc)) if sb["n"] else None
    ex_c = sc["net10_bp"] - float(np.mean(null_c)) if sc["n"] else None
    info = bool(passed and ex_btc is not None and ex_btc > 0 and ex_c is not None and ex_c > 0)
    econ = bool(info and sb["net10_bp"] > 0 and sb["net20_bp"] > 0 and sc["net10_bp"] > 0)
    robust = bool(econ and sb["net10_t"] >= 2 and mt >= 2)
    verdict = "ROBUST" if robust else ("ECONOMIC" if econ else ("INFORMATION" if info else "REJECT"))
    res = {
        "floor_t": floor, "null_max_t_median": float(np.median(mx)),
        "top10_train": [{"combo": {"trigger": TRIGGERS[COMBOS[i][0]], "add": COMBOS[i][1], "exit": COMBOS[i][2]},
                         "t": t_real[i]} for i in order[:10]],
        "n_combos": len(COMBOS), "selected": {"trigger": TRIGGERS[ti], "add": add, "exit": ext}, "train_t": t_real[best],
        "train_pass_floor": bool(passed), "train": summarize(r_tr_best, "BTC TRAIN"),
        "oos_btc": sb, "oos_btc_null_mean_net10": float(np.mean(null_btc)), "oos_btc_null_p95": float(np.quantile(null_btc, .95)),
        "oos_btc_excess_vs_null": ex_btc,
        "coins": sc, "coins_null_mean_net10": float(np.mean(null_c)), "coins_null_p95": float(np.quantile(null_c, .95)),
        "coins_excess_vs_null": ex_c, "coins_monthly_t": mt, "coins_months": nm,
        "coins_by_symbol": {s: {"n": len(v), "net10_bp": float(net(v).mean()) if v else None} for s, v in rc.items()},
        "record_fixed_hold": {"btc_oos": summarize(r_btc_base, "BTC OOS 고정보유"), "coins": summarize(pooled_base, "27종 고정보유")},
        "verdict": verdict,
    }
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("floor_t", "selected", "train_t", "train_pass_floor", "verdict")}, ensure_ascii=False, default=float))
    print("TRAIN", res["train"]); print("BTC OOS", sb, "null", res["oos_btc_null_mean_net10"])
    print("COINS", sc, "null", res["coins_null_mean_net10"], "monthly t", mt)
    print("고정보유(기록)", res["record_fixed_hold"])


def selftest():
    ok = 0
    # 1) V자: 100 → 급락 → 추가 두 번 → 반등 → 되돌림 청산
    p = np.array([100, 100, 90, 85, 80, 90, 100, 110, 104, 104, 104], float)
    s24 = np.full(len(p), 0.1)
    r = run(p, s24, [1], (2, 0.5, 1), (0.5, 9, False))
    i, t, g, cu = r[0]
    # 체결: 100(1) · 90 이 95·90 두 단계를 한 번에 통과 → 90 에 1+1. 평단 93.33, 110 고점, 되돌림 기준 101.67 → 104 미해당 → 9봉 만기 청산 104
    exp = ((104 / 100 - 1) + 2 * (104 / 90 - 1)) / 3 * 1e4
    assert (i, t) == (1, 10) and abs(g - exp) < 1e-9 and abs(cu - 2.0) < 1e-12, r; ok += 1
    # 2) 되돌림 청산 발동
    p2 = np.array([100, 100, 110, 120, 105, 105], float)
    r2 = run(p2, np.full(6, 0.1), [1], (0, 0.0, 1), (0.5, 4, False))
    assert r2[0][1] == 4 and abs(r2[0][2] - 500) < 1e-9, r2; ok += 1
    # 3) 손절(첫 진입가 × (1 − 4·0.1) = 60) 과 비중첩
    p3 = np.array([100, 100, 70, 55, 60, 100, 100, 100], float)
    r3 = run(p3, np.full(8, 0.1), [1, 2, 5], (0, 0.0, 1), (0.5, 2, True))
    assert r3[0][:2] == (1, 3) and r3[1][0] == 5, r3; ok += 1
    # 4) 비용 단위: 추가 크기 배수 2, 한 번만 체결 → (1+2)/(1+2+4) × 2
    r4 = run(np.array([100, 100, 94, 94, 94], float), np.full(5, 0.1), [1], (2, 0.5, 2), (0.5, 3, False))
    assert abs(r4[0][3] - 2 * 3 / 7) < 1e-12, r4; ok += 1
    # 5) 원형 이동은 개수 보존·구간 밖 불변
    m = np.zeros(5000, bool); m[[10, 2000, 2001, 4990]] = True
    rm = roll_mask(m, 100, 4000, np.random.default_rng(1))
    assert rm.sum() == 4 and rm[10] and rm[4990], rm.sum(); ok += 1
    print(f"selftest {ok}/5 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
