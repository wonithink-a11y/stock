"""KRX Open API 일별 전종목(2010-01 ~, 우선주·폐지 포함) → 행렬. 우선주 스위칭·보호예수 연구가 같이 쓴다.

자료: data/krx-pbr-history/daily/(2010-01 ~ 2016-01) + data/krx-daily-ext/(2016-02 ~). 캐시: .cache/krx_daily_panel.npz(+ 메타 json).
수익은 FLUC_RT(기업행사 반영)만 쓴다 — 종가 원값은 분할 때 끊긴다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
SRC = [HERE / "data" / "krx-pbr-history" / "daily", HERE / "data" / "krx-daily-ext"]
CACHE = HERE / ".cache" / "krx_daily_panel.npz"
META = HERE / ".cache" / "krx_daily_panel.json"
COLS = ["BAS_DD", "ISU_CD", "ISU_NM", "FLUC_RT", "ACC_TRDVAL", "MKTCAP", "market"]


def build(rebuild=False):
    files = [f for d in SRC for f in sorted(d.glob("*.parquet"))]
    sig = [f"{f.name}:{f.stat().st_size}" for f in files]
    if not rebuild and CACHE.exists() and META.exists() and json.loads(META.read_text(encoding="utf-8")).get("sig") == sig:
        z = np.load(CACHE, allow_pickle=True)
        m = json.loads(META.read_text(encoding="utf-8"))
        return pd.DatetimeIndex(z["dates"]), list(z["tick"]), {k: z[k] for k in ("R", "VAL", "MCAP")}, m["names"], m["market"]
    d = pd.concat([pd.read_parquet(f, columns=COLS) for f in files], ignore_index=True).drop_duplicates(["BAS_DD", "ISU_CD"])
    d["date"] = pd.to_datetime(d["BAS_DD"])
    dates = pd.DatetimeIndex(np.sort(d["date"].unique()))
    tick = sorted(d["ISU_CD"].astype(str).unique())
    di, ti = np.searchsorted(dates, d["date"].to_numpy()), np.searchsorted(tick, d["ISU_CD"].astype(str).to_numpy())
    M = {}
    for k, c in (("R", "FLUC_RT"), ("VAL", "ACC_TRDVAL"), ("MCAP", "MKTCAP")):
        A = np.full((len(dates), len(tick)), np.nan, np.float32)
        A[di, ti] = pd.to_numeric(d[c], errors="coerce").to_numpy(np.float32) / (100 if k == "R" else 1)
        M[k] = A
    last = d.sort_values("date").groupby("ISU_CD").last()
    names, market = last["ISU_NM"].astype(str).to_dict(), last["market"].astype(str).to_dict()
    CACHE.parent.mkdir(exist_ok=True)
    np.savez(CACHE, dates=dates.to_numpy(), tick=np.array(tick, dtype=object), **M)
    META.write_text(json.dumps({"sig": sig, "names": names, "market": market}, ensure_ascii=False), encoding="utf-8")
    return dates, tick, M, names, market


def clean_returns(R):
    """FLUC_RT 자료 이상 처리: 하루 +100% 초과(그 종목 첫 거래일 제외) → 0. 하락 쪽(정리매매 등)은 실제 가격이라 그대로(1월 효과 개정 1과 같은 규칙)."""
    R = R.astype(float)
    tr = ~np.isnan(R)
    fr = np.where(tr.any(0), tr.argmax(0), -1)
    first = np.zeros_like(tr)
    first[fr[fr >= 0], np.flatnonzero(fr >= 0)] = True
    return np.where((R > 1.0) & ~first, 0.0, R)
