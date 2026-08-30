#!/usr/bin/env python
"""Step 20 — Premium Volatility(p_vol) 안정성·집중도 검증.

Step 19에서 발견된 p_vol(당일 1h premium std)의 강한 단독 예측력(t≈-13)이
독립 정보인지, 특정 코인·연도·구간 착시인지 검증한다.

- 데이터/정렬/forward return: Step 19와 100% 동일 (load_joint 재사용).
- p_vol 정의: KST day d 내 1h premium(mark_close/index_close-1)의 표본 std.
  포함 bucket 시작 = 16Z(d-1)..14Z(d) → 전부 마감 ≤ 24:00 KST d (미래 데이터 없음).
  minobs 12 이상. 금지: 백테스트/최적화/S2·데이터 수정.
- 데시일: 자산 내 D1(저변동)≠D10(고변동), Welch t (기존과 동일).
- 날짜별 cross-sectional: 각 날짜 내 p_vol 상/하위 30% 수익률 스프레드의
  시계열 t(mean/(std/sqrt(n_dates))) — 단순 pooled t 외 보조 판정 지표.
- 다중검정 보정 없음(요구대로). 28 LOO + 4년 + 7반기 + 데시일 = 다수 구간 탐색임을 명시.
출력: findings/premium-vol-stability-2026-08.json + MD.
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore", category=DeprecationWarning)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from funding_premium_info_check import (  # noqa: E402
    ALL, load_joint, spread, corr2,
)

OUT_JSON = HERE / "findings" / "premium-vol-stability-2026-08.json"
OUT_MD = HERE / "findings" / "premium-vol-stability-2026-08.md"
HORIZONS = {"r_1": 1, "r_3": 3, "r_7": 7}
MINASSETS = 5


def date_cs_spread(sub, feat, h, q=0.3):
    """날짜별 cross-sectional 상/하위 q 수익률 스프레드 시계열 t."""
    spreads = []
    for d, g in sub.groupby("date"):
        g = g.dropna(subset=[feat, h])
        if len(g) < MINASSETS:
            continue
        r = g[feat].rank(pct=True)
        hi = g.loc[r >= 1 - q, h].to_numpy(float)
        lo = g.loc[r <= q, h].to_numpy(float)
        if len(hi) == 0 or len(lo) == 0:
            continue
        spreads.append(float(hi.mean() - lo.mean()))
    spreads = np.asarray(spreads, float)
    if len(spreads) < 30:
        return {"n_dates": int(len(spreads)), "spread": None, "t": None}
    t = spreads.mean() / (spreads.std(ddof=1) / np.sqrt(len(spreads)))
    return {"n_dates": int(len(spreads)), "spread": round(float(spreads.mean()), 6),
            "t": round(float(t), 3)}


def decile_means(sub, feat, h):
    s = sub.dropna(subset=[feat, h, "symbol"]).copy()
    s["_dec"] = np.nan
    for b in s["symbol"].unique():
        m = s["symbol"] == b
        v = s.loc[m, feat]
        s.loc[m, "_dec"] = (v.rank(pct=True) * 10).clip(0, 9).astype(int) + 1
    out = {}
    for k in range(1, 11):
        d = s.loc[s["_dec"] == k, h]
        out[int(k)] = {"mean": round(float(d.mean()), 6) if len(d) else None,
                       "n": int(len(d))}
    return out


def date_cs_spearman(sub, feat, h):
    """날짜별 spearman(feat, r) 평균과 그 시계열 t."""
    rs = []
    for d, g in sub.groupby("date"):
        g = g.dropna(subset=[feat, h])
        if len(g) < MINASSETS:
            continue
        x = g[feat].rank().to_numpy(float)
        y = g[h].rank().to_numpy(float)
        rs.append(float(np.corrcoef(x, y)[0, 1]))
    rs = np.asarray(rs, float)
    if len(rs) < 30:
        return {"n_dates": int(len(rs)), "mean": None, "t": None}
    t = rs.mean() / (rs.std(ddof=1) / np.sqrt(len(rs)))
    return {"n_dates": int(len(rs)), "mean": round(float(rs.mean()), 4),
            "t": round(float(t), 2)}


def main():
    frames = {b: load_joint(b) for b in ALL}
    full = pd.concat(frames.values()).reset_index().rename(columns={"index": "date"})
    full["year"] = full["date"].dt.year
    full["half"] = full["date"].dt.year.astype(str) + "-" + np.where(
        full["date"].dt.month <= 6, "H1", "H2")

    out = {"design": {
        "p_vol": "KST day d 내 1h premium(mark_close/index_close-1) 표본 std "
                 "(16Z(d-1)..14Z(d) 시작 bucket, 마감 ≤ 24:00 KST d, minobs=12) — "
                 "미래 데이터 미사용. Step 19와 동일 정의.",
        "forward_return": "r_H(d)=close(d+H)/close(d)-1 (KST, USDT mark close 24:00 마감)",
        "alignment": "funding/premium 8h → UTC+9h → KST 날짜 d (Step 14/19 동일)",
        "decile": "자산 내 데시일 D1(저변동)-D10(고변동), Welch t",
        "date_cs": "각 날짜 내 p_vol 상/하위 30% 수익률 스프레드 시계열 t "
                   "(날짜당 ≥5종목). r7은 7일 겹침 표본이라 naive t는 과대 가능 — 보조 지표.",
        "multi_testing": "다중검정 보정 안 함. 탐색 구간 수: LOO 28 + 연도 4 + 반기 7 + 데시일 — 명시.",
        "forbidden": "백테스트/최적화/S2·데이터 수정 없음",
    }}

    # 무미래 확인 지표: p_vol과 그 계산에 쓰인 마지막 bucket의 관계(설계 문서화)
    out["sanity"] = {
        "p_vol_no_future_data": (
            "p_vol(d)는 day d의 15:00Z(=24:00 KST) 이전에 마감되는 시간대 프리미엄으로만 계산. "
            "16Z(d-1) bucket close=01:00 KST d .. 14Z(d) bucket close=15:00Z=24:00 KST d까지 전부 "
            "close(d) 시점 이전 관측 가능 → lookahead 없음."),
        "p_vol_spearman_vs_mom30": corr2(full["p_vol"].to_numpy(float),
                                         full["mom30"].to_numpy(float))[1],
    }

    # ---------- 1) LOO ----------
    loo = {}
    base_t = {}
    for h in HORIZONS:
        base_t[h] = spread(full, "p_vol", h)
    loo["all"] = base_t
    loo["drop_each"] = {}
    for b in ALL:
        rest = full[full["symbol"] != b]
        loo["drop_each"][b] = {h: spread(rest, "p_vol", h) for h in HORIZONS}
    loo["summary"] = {}
    for h in HORIZONS:
        ts = {b: loo["drop_each"][b][h]["t"] for b in ALL}
        ts = {k: v for k, v in ts.items() if v is not None}
        t_all = base_t[h]["t"]
        loo["summary"][h] = {
            "t_all": t_all,
            "t_min": min(ts.values()), "t_min_asset": min(ts, key=ts.get),
            "t_max": max(ts.values()), "t_max_asset": max(ts, key=ts.get),
            "ngt2": int(sum(1 for v in ts.values() if abs(v) > 2)),
        }
    out["loo"] = loo

    # ---------- 2) 연도별 (2023~2026 핵심, 그 외 보너스) ----------
    years = {}
    for y in sorted(full["year"].unique()):
        ys = full[full["year"] == y]
        if len(ys) < 200:
            continue
        years[int(y)] = {h: spread(ys, "p_vol", h) for h in HORIZONS}
        years[int(y)]["cs_r7"] = date_cs_spread(ys, "p_vol", "r_7")
        years[int(y)]["cs_spearman_r7"] = date_cs_spearman(ys, "p_vol", "r_7")
        years[int(y)]["n"] = int(len(ys))
    out["by_year"] = years

    # ---------- 3) 반기별 ----------
    halves = {}
    for hh in ["2023-H2", "2024-H1", "2024-H2", "2025-H1", "2025-H2", "2026-H1", "2026-H2"]:
        y, hhx = hh.split("-")
        ys = full[(full["year"] == int(y)) & (full["half"] == hh)]
        if len(ys) < 100:
            continue
        halves[hh] = {h: spread(ys, "p_vol", h) for h in HORIZONS}
        halves[hh]["cs_r7"] = date_cs_spread(ys, "p_vol", "r_7")
        halves[hh]["cs_spearman_r7"] = date_cs_spearman(ys, "p_vol", "r_7")
        halves[hh]["n"] = int(len(ys))
        halves[hh]["first"] = str(ys["date"].min().date())
        halves[hh]["last"] = str(ys["date"].max().date())
    out["by_half"] = halves

    # ---------- 4) Monotonicity ----------
    mono = {}
    for h in HORIZONS:
        m = decile_means(full, "p_vol", h)
        mono[h] = {
            "decile_means": {k: v["mean"] for k, v in m.items()},
            "n": {k: v["n"] for k, v in m.items()},
            "pooled_spearman": corr2(full["p_vol"].to_numpy(float),
                                     full[h].to_numpy(float))[1],
            "cs_spearman": date_cs_spearman(full, "p_vol", h),
        }
        # monotonicity 지표: decile 단조성(8/10 단계에서 음이면 음monotonic)
        means = [m[k]["mean"] for k in range(1, 11)]
        news = [(m[k]["mean"] or np.nan) for k in range(1, 11)]
        run = 0
        for i in range(9):
            a, b = news[i], news[i + 1]
            if np.isnan(a) or np.isnan(b):
                continue
            run += int(np.sign(a - b))   # 음이면 다음 decile로 갈수록 낮아짐
        mono[h]["step_streak"] = run
    out["monotonicity"] = mono

    # ---------- 5) 날짜 cross-sectional (전체) t ----------
    cs_total = {}
    for h in HORIZONS:
        cs_total[h] = {"tercile": date_cs_spread(full, "p_vol", h, q=0.3),
                       "quintile": date_cs_spread(full, "p_vol", h, q=0.2),
                       "spearman": date_cs_spearman(full, "p_vol", h)}
    out["date_cs_total"] = cs_total

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---------- 콘솔 ----------
    print("=== Step 20 premium-vol stability ===")
    print("[1] LOO (r7): all t=%s" % base_t["r_7"]["t"])
    s = loo["summary"]
    for h in HORIZONS:
        m = s[h]
        print(f"  {h}: t_all={m['t_all']} t_min={m['t_min']}({m['t_min_asset']}) "
              f"t_max={m['t_max']}({m['t_max_asset']}) |t|>2: {m['ngt2']}/28")
    print("[2] 연도별 r7 (D1-D10 Δ, t, cs_r7 t)")
    for y, v in years.items():
        d = v["r_7"]
        print(f"  {y}: Δ={d['D1_minus_D10']:+.5f}(t{d['t']}) nD1={d['n_D1']} "
              f"cs_r7_t={v['cs_r7']['t']} cs_spear_t={v['cs_spearman_r7']['t']}")
    print("[3] 반기별 r7")
    for hh, v in halves.items():
        d = v["r_7"]
        print(f"  {hh}: Δ={d['D1_minus_D10']:+.5f}(t{d['t']}) nD1={d['n_D1']} "
              f"cs_r7_t={v['cs_r7']['t']} ({v['first']}~{v['last']})")
    print("[4] monotonic r7 decile means")
    for k, v in mono["r_7"]["decile_means"].items():
        print(f"    D{k}: {v:+.5f}", end="")
        if k % 5 == 0:
            print()
    print(f"  pooled_spear r7={mono['r_7']['pooled_spearman']:+.4f} "
          f"step_streak={mono['r_7']['step_streak']} (-9=완전 단조음)")
    print("[5] date-CS 전체")
    for h, v in cs_total.items():
        print(f"  {h}: tercile t={v['tercile']['t']}({v['tercile']['n_dates']}d) "
              f"quintile t={v['quintile']['t']} spearman_t={v['spearman']['t']}")
    print("\nJSON:", OUT_JSON)


if __name__ == "__main__":
    main()