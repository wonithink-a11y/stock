#!/usr/bin/env python3
"""PBR combined 슬리브 체결 시각 효과 — short-horizon-phase3 P3-X(SUPPORTED)의 적용 측정.

현재 정책: 진입 = 리밸런싱일 다음 세션 **시가**, 시간청산 = N번째 세션 **종가**.
대안(같은 세션 안에서만 시각 이동): 진입 = 같은 진입일 **종가**, 청산 = 같은 청산일 **시가**.
개선(bp) = −intraday(진입일) − intraday(청산일). 선견 없음(같은 날 더 늦게 사고, 더 일찍 판다).

  python research/strategy-lab/futures/pbr_execution_timing.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LAB = HERE.parent
sel = json.loads((LAB / "strategies" / "pbr_value_v1_combined" / "selection.json").read_text(encoding="utf-8"))["selection"]
a2a = pd.concat([pd.read_parquet(p) for p in sorted((LAB / ".cache" / "a2a_parquet").glob("*.parquet"))])
a2a = a2a[(a2a["open"] > 0) & (a2a["close"] > 0)]
a2a["date"] = pd.to_datetime(a2a["date"])
intra = (a2a.set_index(["ticker", "date"])["close"] / a2a.set_index(["ticker", "date"])["open"] - 1) * 1e4
cal = pd.DatetimeIndex(sorted(a2a["date"].unique()))

rows = []
for tk, lst in sel.items():
    starts = []
    for e in lst:
        t = pd.Timestamp(e["date"])
        k = cal.searchsorted(t, side="right")          # 다음 세션
        if k + e["holdSessions"] - 1 >= len(cal):
            continue
        ent, ext = cal[k], cal[k + e["holdSessions"] - 1]
        starts.append((ent, ext))
    for i, (ent, ext) in enumerate(starts):
        cont_in = i > 0 and cal.searchsorted(starts[i - 1][1]) + 1 == cal.searchsorted(ent)
        cont_out = i + 1 < len(starts) and cal.searchsorted(ext) + 1 == cal.searchsorted(starts[i + 1][0])
        rows.append({"ticker": tk, "entry": ent, "exit": ext,
                     "intra_entry": intra.get((tk, ent), np.nan), "intra_exit": intra.get((tk, ext), np.nan),
                     "cont_in": cont_in, "cont_out": cont_out})
df = pd.DataFrame(rows).dropna(subset=["intra_entry", "intra_exit"])
df["gain_all"] = -df["intra_entry"] - df["intra_exit"]
# 연속 보유(전달 청산일 다음 세션에 재진입)는 실제로는 안 판다고 보면 그 다리의 개선은 0
df["gain_netted"] = np.where(df["cont_in"], 0, -df["intra_entry"]) + np.where(df["cont_out"], 0, -df["intra_exit"])
df["year"] = df["entry"].dt.year


def t(x):
    x = x.dropna()
    return round(float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))), 2)


# 월 단위(리밸런싱 코호트)로 묶어 t — 같은 날 종목들은 상관
m = df.groupby(df["entry"].dt.to_period("M"))[["intra_entry", "intra_exit", "gain_all", "gain_netted"]].mean()
out = {"trades": len(df), "months": len(m),
       "intra_entry_bp": round(float(df["intra_entry"].mean()), 2), "intra_exit_bp": round(float(df["intra_exit"].mean()), 2),
       "gain_per_trade_all_bp": round(float(df["gain_all"].mean()), 2), "t_month_all": t(m["gain_all"]),
       "gain_per_trade_netted_bp": round(float(df["gain_netted"].mean()), 2), "t_month_netted": t(m["gain_netted"]),
       "annual_pct_all": round(float(m["gain_all"].mean()) * 12 / 100, 2),
       "annual_pct_netted": round(float(m["gain_netted"].mean()) * 12 / 100, 2),
       "share_cont_in": round(float(df["cont_in"].mean()), 3),
       "months_positive_all": round(float((m["gain_all"] > 0).mean()), 3),
       "yearly_gain_all_bp": {int(y): round(float(v), 1) for y, v in df.groupby("year")["gain_all"].mean().items()}}
(HERE / "pbr-execution-timing.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=1))
