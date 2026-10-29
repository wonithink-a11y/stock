#!/usr/bin/env python3
"""스테이블코인 발행량 → BTC — 2023~ 세밀 탐색(사후 기술, 판정 없음).

배경: 백테스트(stablecoin-supply-btc, S1 REJECT·S7 판정불가)의 확인 구간 2023~ 가 양이었다. 사용자 요청(2026-10-30)으로 그 기간을 자세히 본다.
**이미 결과를 본 기간이다 — 여기 숫자로 규칙을 고르거나 판정하지 않는다.** 나온 가설은 forward(#24, 이미 고정된 규칙) 또는 새 사전등록으로만.

    python research/strategy-lab/futures/stablecoin_supply_explore_2023.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
import stablecoin_supply_btc as sb  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

D = pd.Timedelta(days=1)
A, B = pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")


def stat(x) -> dict:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if not len(x):
        return {"n": 0}
    return {"n": int(len(x)), "bp": round(float(x.mean()), 1), "t": round(tstat(x), 2), "win%": round(float((x > 0).mean() * 100), 1),
            "median": round(float(np.median(x)), 1)}


def main():
    bn = rb._read(cp.DATA / "bn_btc.parquet")["open"]
    od = bn[bn.index.hour == 0]
    S = sb.load_supply("all")
    z = sb.zscore(S)
    ret1 = (od.shift(-1) / od - 1) * 1e4                      # od[t] → od[t+1]
    out = {}
    # 0) 백테스트와 같은 사건(S1·S7, 차단 사슬은 전체 이력)
    e1, e7 = sb.events(z, od, 1), sb.events(z, od, 7)
    e1, e7 = e1[(e1.index >= A) & (e1.index < B)], e7[(e7.index >= A) & (e7.index < B)]
    sg1 = np.sign(z.reindex(e1.index))
    out["S1_all"] = stat(e1)
    out["S1_growth"] = stat(e1[(sg1 > 0).to_numpy()])
    out["S1_contraction"] = stat(e1[(sg1 < 0).to_numpy()])
    out["S7_all"] = stat(e7)
    # 1) 분기별
    q = e1.groupby(e1.index.tz_convert(None).to_period("Q"))
    out["S1_by_quarter"] = {str(k): stat(v) for k, v in q}
    # 2) 사건 뒤 0~10일 누적 경로(방향 곱), 갈래별 + 같은 기간 무조건 평균
    def path(idx, sign):
        rows = []
        for d, s in zip(idx, sign):
            t0 = d + D
            p0 = od.get(t0, np.nan)
            rows.append([s * (od.get(t0 + k * D, np.nan) / p0 - 1) * 1e4 for k in range(1, 11)])
        a = np.array(rows, float)
        return [round(float(np.nanmean(a[:, k])), 1) for k in range(10)] if len(a) else []
    allz = z[(z.index >= A) & (z.index < B)]
    g_idx, c_idx = e1.index[(sg1 > 0).to_numpy()], e1.index[(sg1 < 0).to_numpy()]
    out["path_growth_long_day1to10"] = path(g_idx, [1] * len(g_idx))
    out["path_contraction_short_day1to10"] = path(c_idx, [-1] * len(c_idx))
    base_days = od[(od.index >= A) & (od.index < B)].index
    out["path_unconditional_long_day1to10"] = path(base_days - D, [1] * len(base_days))
    # 3) z 크기별(겹침 허용 — 모든 날, 다음 1일)
    nxt = pd.Series([ret1.get(d + D, np.nan) for d in allz.index], index=allz.index)
    bins = [(-99, -2.5), (-2.5, -2), (-2, -1), (-1, 1), (1, 2), (2, 2.5), (2.5, 3), (3, 99)]
    out["all_days_next1d_by_z"] = {f"[{lo},{hi})": stat(nxt[(allz >= lo) & (allz < hi)]) for lo, hi in bins}
    # 4) BTC 200일선 위/아래(사건일 기준)
    ma = od.rolling(200, min_periods=200).mean()
    up = pd.Series([od.get(d + D, np.nan) > ma.get(d, np.nan) for d in e1.index], index=e1.index)
    out["S1_regime"] = {"above200": stat(e1[up.to_numpy()]), "below200": stat(e1[(~up).to_numpy()])}
    out["S1_growth_regime"] = {"above200": stat(e1[(up & (sg1 > 0)).to_numpy()]), "below200": stat(e1[((~up) & (sg1 > 0)).to_numpy()])}
    # 5) 드리프트 대비: 무조건 다음 1일 평균(2023~)
    unc = ret1[(ret1.index >= A + D) & (ret1.index < B)]
    out["unconditional_next1d"] = stat(unc)
    # 6) 집중도: 상위 3건 빼면
    srt = e1.sort_values(ascending=False)
    out["S1_without_top3"] = stat(srt.iloc[3:])
    out["S1_top3"] = {str(k.date()): round(float(v), 1) for k, v in srt.iloc[:3].items()}
    # 7) USDT·USDC 2023~
    for kind in ("usdt", "usdc"):
        zk = sb.zscore(sb.load_supply(kind))
        ek = sb.events(zk, od, 1)
        out[f"{kind}_S1_2023on"] = stat(ek[(ek.index >= A) & (ek.index < B)])
    # 8) 문턱 민감도(겹침 허용, 다음 1일, 방향 곱) — 탐색 전용
    sgn_next = nxt * np.sign(allz)
    out["threshold_all_days_dir_next1d"] = {f"|z|>={th}": stat(sgn_next[allz.abs() >= th]) for th in (1.0, 1.5, 2.0, 2.5, 3.0)}
    # 9) 코인베이스 프리미엄 ＋ 사건과 같은 7일 안에 겹치는 비율
    cb, bnh = (rb._read(cp.DATA / f"{n}.parquet") for n in ("cb_btc", "bn_btc"))
    ec = cp.events(cp.zscore(cp.premium(cb, bnh)), bnh["open"], 24)
    near = [((ec.index >= d - 7 * D) & (ec.index <= d + 7 * D)).any() for d in e1.index]
    out["S1_with_coinbase_event_within_7d_pct"] = round(float(np.mean(near) * 100), 1)
    out["S1_with_vs_without_cb"] = {"with": stat(e1[np.array(near)]), "without": stat(e1[~np.array(near)])}
    # 10) 사건 목록(2023~)
    out["S1_events"] = [{"d": str(d.date()), "z": round(float(z[d]), 2), "netBp": round(float(v) - 10, 1)} for d, v in e1.items()]
    (HERE / "stablecoin-supply-explore-2023.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "S1_events"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
