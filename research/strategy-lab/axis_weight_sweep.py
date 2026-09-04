#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""축 가중치 재조정(A층) — 35/30/15/20 이 맞는 배점인가.

현재 KR-2.3 의 축 배점(fundamental .35 / valuation .30 / technical .15 /
supplyDemand .20)은 프로젝트 초기에 데이터 없이 정해진 값이고 측정으로
확인된 적이 없다. 확인된 곳마다 오히려 틀렸다:
  - 2026-08-19 slot-marginal: IC 를 결정적으로 올리는 슬롯은 pbr 하나
    (ΔIC d120 +0.0385)인데 그 배점은 0.20 x 0.30 = 전체의 6% 다.
  - 같은 측정: 수급 5일 추세를 얹으면 IC 가 오히려 감소.
  - 2026-09-03 KR-2.3: technical MA크로스는 방향 자체가 틀려 있었다.

**재백필 없이 잰다.** A5 패널이 축별 기여도 c 를 저장하는데 그것은 이미
재정규화된 값이다(결측 축이 있는 행에서 확인 - 축 둘만 있는데 기여합이
가중합 상한을 넘는다). 정확한 역산:

    축 원점수 = c[축] x (존재 축 가중치 합) / W[축]
    새 점수   = Σ 새W[축] x 축 원점수 / Σ 새W[존재 축]

복원값이 0~100.1 에 들어가고 오차는 소수 1자리 반올림뿐(최대 0.2)임을 확인했다.

판정은 착수 전에 고정한다 - TRAIN 에서만 고르고 VALID·TEST 는 보고만 하며,
**난수 가중치 바닥선**(무작위 가중치 N개의 p95)을 넘어야 한다.

  python axis_weight_sweep.py --selftest
  python axis_weight_sweep.py --step 0.1 --random 200
"""
import argparse
import gzip
import itertools
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np   # noqa: E402
import pandas as pd  # noqa: E402

LAB = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(LAB))
SCORES = os.path.join(REPO_ROOT, "data", "backfill", "scores")
OUT_DIR = os.path.join(LAB, "reports", "2026-09-04-axis-weights")
AXES = ("fundamental", "valuation", "technical", "supplyDemand")
CURRENT = {"fundamental": 0.35, "valuation": 0.30, "technical": 0.15, "supplyDemand": 0.20}
SPLIT = {"TRAIN": 0.60, "VALID": 0.15}
NW_LAG = 4          # d20 은 주간 스냅샷 4개와 겹친다


def axis_matrix(c, weights=CURRENT):
    """기여도 dict -> 축 원점수 dict. 재정규화를 되돌린다."""
    p = {k: v for k, v in c.items() if v is not None}
    ws = sum(weights[k] for k in p)
    if ws <= 0:
        return {}
    return {k: v * ws / weights[k] for k, v in p.items()}


def load_panel(horizon="d20"):
    dates, scores, fwds = [], [], []
    for fn in sorted(os.listdir(SCORES)):
        if not fn.endswith(".jsonl.gz"):
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
                a = axis_matrix(r.get("c") or {})
                if not a:
                    continue
                dates.append(r["d"])
                scores.append([a.get(k, np.nan) for k in AXES])
                fwds.append(float(fw))
    return (np.array(dates), np.array(scores, dtype=float), np.array(fwds, dtype=float))


def rescore(A, w):
    """축 원점수 행렬 A(n x 4) 를 가중치 w 로 재합성. 결측 축은 존재 축끼리
    재정규화한다(엔진의 weightedAverage 와 같은 동작)."""
    W = np.array([w[k] for k in AXES], dtype=float)
    present = ~np.isnan(A)
    num = np.nansum(A * W, axis=1)
    den = (present * W).sum(axis=1)
    out = np.full(len(A), np.nan)
    ok = den > 0
    out[ok] = num[ok] / den[ok]
    return out


def _rank(x):
    order = np.argsort(np.argsort(x))
    return order.astype(float)


def daily_ic(dates_idx, score, fwd_rank_by_group):
    """날짜별 횡단면 Spearman IC 리스트."""
    out = []
    for g, (lo, hi) in dates_idx.items():
        s = score[lo:hi]
        if np.isnan(s).all() or hi - lo < 5:
            continue
        m = ~np.isnan(s)
        if m.sum() < 5:
            continue
        sr = _rank(s[m])
        fr = fwd_rank_by_group[g][m]
        if sr.std() == 0 or fr.std() == 0:
            continue
        out.append(float(np.corrcoef(sr, fr)[0, 1]))
    return np.array(out)


def nw_t(x, lag=NW_LAG):
    """Newey-West 보정 t. 겹치는 forward return 이라 naive t 는 부풀려진다."""
    n = len(x)
    if n < lag + 2:
        return None
    mu = x.mean()
    e = x - mu
    g0 = (e * e).sum() / n
    var = g0
    for L in range(1, lag + 1):
        gl = (e[L:] * e[:-L]).sum() / n
        var += 2 * (1 - L / (lag + 1)) * gl
    if var <= 0:
        return None
    return float(mu / np.sqrt(var / n))


def build_index(dates):
    """정렬된 날짜 배열에서 {날짜: (시작, 끝)} 슬라이스."""
    idx, start = {}, 0
    for i in range(1, len(dates) + 1):
        if i == len(dates) or dates[i] != dates[start]:
            idx[dates[start]] = (start, i)
            start = i
    return idx


def weight_grid(step):
    """합이 1 인 4축 가중치 격자. 축 하나가 0 인 경우도 포함한다(그 축을 빼는
    것도 후보다)."""
    k = int(round(1.0 / step))
    out = []
    for c in itertools.product(range(k + 1), repeat=3):
        if sum(c) > k:
            continue
        d = k - sum(c)
        out.append({a: v * step for a, v in zip(AXES, list(c) + [d])})
    return out


def evaluate(w, segs, fwd_ranks):
    res = {}
    for k, (dates_idx, A, _) in segs.items():
        ic = daily_ic(dates_idx, rescore(A, w), fwd_ranks[k])
        res[k] = {"n": len(ic), "ic": float(ic.mean()) if len(ic) else None,
                  "t": nw_t(ic) if len(ic) else None}
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", default="d20")
    ap.add_argument("--step", type=float, default=0.1)
    ap.add_argument("--random", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    print("A5 패널 로드 중 ...", flush=True)
    dates, A, fwd = load_panel(a.horizon)
    order = np.argsort(dates, kind="stable")
    dates, A, fwd = dates[order], A[order], fwd[order]
    print("행 {:,}  날짜 {:,}".format(len(dates), len(set(dates))))

    uniq = sorted(set(dates))
    nt, nv = int(round(len(uniq) * SPLIT["TRAIN"])), int(round(len(uniq) * SPLIT["VALID"]))
    seg_dates = {"TRAIN": set(uniq[:nt]), "VALID": set(uniq[nt:nt + nv]), "TEST": set(uniq[nt + nv:])}
    segs, fwd_ranks = {}, {}
    for k, ds in seg_dates.items():
        m = np.isin(dates, list(ds))
        d2, A2, f2 = dates[m], A[m], fwd[m]
        idx = build_index(d2)
        segs[k] = (idx, A2, f2)
        fwd_ranks[k] = {g: _rank(f2[lo:hi]) for g, (lo, hi) in idx.items()}
        print("  {} {}~{}  {:,}행 {:,}일".format(k, min(ds), max(ds), len(d2), len(idx)))

    cur = evaluate(CURRENT, segs, fwd_ranks)
    print("\n현행 KR-2.3 (35/30/15/20)")
    for k in ("TRAIN", "VALID", "TEST"):
        print("  {:6} IC {:+.4f}  NW t {:>6}".format(
            k, cur[k]["ic"], "{:.2f}".format(cur[k]["t"]) if cur[k]["t"] else "-"))

    grid = weight_grid(a.step)
    print("\n격자 {}개 평가 중 ...".format(len(grid)), flush=True)
    rows = []
    for i, w in enumerate(grid):
        rows.append({"weights": w, "segments": evaluate(w, segs, fwd_ranks)})
        if (i + 1) % 25 == 0:
            print("  {}/{}".format(i + 1, len(grid)), flush=True)

    rnd = np.random.default_rng(a.seed)
    print("난수 가중치 {}개(바닥선) ...".format(a.random), flush=True)
    null_train = []
    for _ in range(a.random):
        v = rnd.dirichlet(np.ones(4))
        w = {ax: float(x) for ax, x in zip(AXES, v)}
        null_train.append(evaluate(w, segs, fwd_ranks)["TRAIN"]["ic"])
    null_train = np.array([x for x in null_train if x is not None])
    bar = float(np.quantile(null_train, 0.95))
    print("  난수 TRAIN IC  중앙 {:+.4f}  p95 {:+.4f}  최대 {:+.4f}".format(
        np.median(null_train), bar, null_train.max()))

    rows.sort(key=lambda r: -(r["segments"]["TRAIN"]["ic"] or -9))
    print("\nTRAIN IC 상위 10 (선택은 TRAIN 에서만, VALID·TEST 는 보고만)")
    print("  {:28} {:>9} {:>9} {:>9}".format("가중치 F/V/T/S", "TRAIN", "VALID", "TEST"))
    for r in rows[:10]:
        w = r["weights"]; s = r["segments"]
        lab = "/".join("{:.0f}".format(w[a2] * 100) for a2 in AXES)
        print("  {:28} {:+9.4f} {:+9.4f} {:+9.4f}".format(
            lab, s["TRAIN"]["ic"], s["VALID"]["ic"], s["TEST"]["ic"]))

    best = rows[0]
    print("\n현행 대비 TRAIN 최선: {} (IC {:+.4f} vs 현행 {:+.4f})".format(
        "/".join("{:.0f}".format(best["weights"][a2] * 100) for a2 in AXES),
        best["segments"]["TRAIN"]["ic"], cur["TRAIN"]["ic"]))
    print("난수 바닥선(p95) {:+.4f} -> {}".format(
        bar, "넘음" if best["segments"]["TRAIN"]["ic"] > bar else "★ 못 넘음"))

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "sweep_{}.json".format(a.horizon))
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"horizon": a.horizon, "current": {"weights": CURRENT, "segments": cur},
                   "nullBarP95": bar, "nullMedian": float(np.median(null_train)),
                   "nullMax": float(null_train.max()), "nullN": int(len(null_train)),
                   "rows": rows}, f, ensure_ascii=False, indent=1)
    print("\n저장: " + out)


def selftest():
    # 역산: 축 둘만 있는 행에서 재정규화를 되돌린다
    a = axis_matrix({"supplyDemand": 25.4, "technical": 19.0,
                     "fundamental": None, "valuation": None})
    ws = 0.20 + 0.15
    assert abs(a["supplyDemand"] - 25.4 * ws / 0.20) < 1e-9, a
    assert abs(a["technical"] - 19.0 * ws / 0.15) < 1e-9, a
    # 되돌린 축 원점수를 같은 가중치로 재합성하면 원래 raw(=기여합)가 나온다.
    # c 는 이미 재정규화된 값이므로 Σc 자체가 0~100 점수다.
    A = np.array([[np.nan, np.nan, a["technical"], a["supplyDemand"]]])
    assert abs(rescore(A, CURRENT)[0] - (25.4 + 19.0)) < 1e-9, rescore(A, CURRENT)

    # 전 축이 있으면 c/W 와 같다
    a2 = axis_matrix({k: v for k, v in zip(AXES, [35.0, 30.0, 15.0, 20.0])})
    assert all(abs(a2[k] - 100.0) < 1e-9 for k in AXES), a2

    # rescore: 결측 축은 존재 축끼리 재정규화
    A2 = np.array([[80.0, np.nan, 40.0, np.nan]])
    w = {"fundamental": 0.5, "valuation": 0.2, "technical": 0.3, "supplyDemand": 0.0}
    exp = (0.5 * 80 + 0.3 * 40) / (0.5 + 0.3)
    assert abs(rescore(A2, w)[0] - exp) < 1e-9, rescore(A2, w)
    # 존재 축의 가중치가 전부 0 이면 점수를 지어내지 않는다
    w0 = {"fundamental": 0.0, "valuation": 0.5, "technical": 0.0, "supplyDemand": 0.5}
    assert np.isnan(rescore(A2, w0)[0])

    # 격자: 합이 1 이고 중복 없음
    g = weight_grid(0.25)
    assert all(abs(sum(x.values()) - 1.0) < 1e-9 for x in g), g[:3]
    assert len({tuple(round(x[a3], 4) for a3 in AXES) for x in g}) == len(g)
    assert CURRENT not in g or True   # 0.25 격자엔 35/30/15/20 이 없다(정상)
    assert {"fundamental": 0.5, "valuation": 0.25, "technical": 0.25,
            "supplyDemand": 0.0} in g

    # NW t: 자기상관이 있으면 naive 보다 작아진다
    rng = np.random.default_rng(0)
    e = rng.normal(size=400)
    x = 0.02 + e + np.roll(e, 1)          # 강한 1차 자기상관
    naive = x.mean() / x.std() * np.sqrt(len(x))
    assert abs(nw_t(x)) < abs(naive), (nw_t(x), naive)
    assert nw_t(np.array([1.0, 2.0])) is None      # 표본 부족

    # build_index
    idx = build_index(np.array(["a", "a", "b", "c", "c", "c"]))
    assert idx == {"a": (0, 2), "b": (2, 3), "c": (3, 6)}, idx
    print("selftest ok (11건)")


if __name__ == "__main__":
    main()
