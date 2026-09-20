#!/usr/bin/env python3
"""종가→익일 시가 계열 5차 — 사전등록 `findings/close-open-preregistration-2026-09.md`.

    python research/strategy-lab/futures/close_open_phase5.py            # 실행
    python research/strategy-lab/futures/close_open_phase5.py --selftest

A2a 일봉(2016~2026, 유동 종목)으로 "종가 정보가 다음날 시가를 예측하는가"를 본다. 거래는 종가·시가 **단일가**에서 체결된다고 본다
(스프레드를 건너지 않는다 — 다만 단일가 체결 충격은 스트레스 셀이 다룬다). 셀·비용·판정은 사전등록에 고정.
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from short_horizon_study import tstat  # noqa: E402
from structure_phase4 import family, tick_bp  # noqa: E402

warnings.filterwarnings("ignore", category=RuntimeWarning)
CACHE = HERE.parent / ".cache"
SEED = 20260925

# ---- 비용: 성분을 분리해 기록한다 (2026-09-20 KIS 이벤트 페이지 확인) -----------------------
TAX_BP = 20.0                    # 매도 거래세(+농특세) 0.20% — 왕복 1회(매도 때만)
FEE_SIDE_BP = 1.40527            # 정상 온라인 수수료 0.0140527% 편도
KIKWAN_SIDE_BP = 0.3640          # 유관기관제비용 0.003640% 편도
FIXED_BP = TAX_BP + 2 * FEE_SIDE_BP + 2 * KIKWAN_SIDE_BP     # 23.54 (지속 가능한 기준)
EVENT_BP = TAX_BP                # 코인원 WTS 이벤트(2026-09 한정): 수수료·유관 0, 세금은 유지
LIQ_MIN = 2e9
LIMIT_UP = 0.28                  # 종가 상한가 근처는 종가 단일가로 못 산다 — 제외


def split(d):
    d = pd.Timestamp(d)
    return "TRAIN" if d.year <= 2020 else ("VALID" if d.year <= 2022 else "TEST")


def load() -> pd.DataFrame:
    a = pd.concat([pd.read_parquet(p) for p in sorted((CACHE / "a2a_parquet").glob("*.parquet"))])
    a = a[(a.open > 0) & (a.close > 0) & (a.high > 0) & (a.low > 0)].copy()
    a["date"] = pd.to_datetime(a["date"])
    a = a.sort_values(["ticker", "date"]).reset_index(drop=True)
    return features(a)


def features(a: pd.DataFrame) -> pd.DataFrame:
    cal = np.sort(a.date.unique())
    a["k"] = a.date.map(pd.Series(np.arange(len(cal)), index=cal))
    g = a.groupby("ticker")
    prev_ok = g.k.shift(1) == a.k - 1
    next_ok = g.k.shift(-1) == a.k + 1
    a["ret"] = np.where(prev_ok, a.close / g.close.shift(1) - 1, np.nan)
    a["gap"] = np.where(prev_ok, a.open / g.close.shift(1) - 1, np.nan)
    a["pdh"] = np.where(prev_ok, g.high.shift(1), np.nan)
    rng = a.high - a.low
    a["clv"] = np.where(rng > 0, (a.close - a.low) / rng, np.nan)
    a["amt"] = a.close * a.volume
    a["liq"] = g.amt.transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
    a["volr"] = a.volume / g.volume.transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean())
    a["on"] = np.where(next_ok, g.open.shift(-1) / a.close - 1, np.nan) * 1e4     # 종가 -> 익일 시가
    a["oc"] = (a.close / a.open - 1) * 1e4                                        # 시가 -> 종가
    for c in ("on", "oc"):
        a.loc[a[c].abs() > 3000, c] = np.nan
    a["ocn"] = np.where(next_ok, a.groupby("ticker").oc.shift(-1), np.nan)      # 익일 시가 -> 익일 종가 (룩어헤드 없음)
    return a


# id -> (조건, 구간, 방향, 플래그)
LONG, INFO = {"long_only": True}, {"info_only": True}
CELLS = {
    "O0": (lambda u: u.ret.notna(), "on", 1, LONG),                                   # 기준선(전 유동 종목 밤사이)
    "O1": (lambda u: (u.clv >= 0.8) & (u.ret > 0) & (u.volr >= 1.5), "on", 1, LONG),  # 종가 강도
    "O1s": (lambda u: (u.clv <= 0.2) & (u.ret < 0) & (u.volr >= 1.5), "on", -1, INFO),
    "O2": (lambda u: (u.close > u.pdh) & (u.clv >= 0.8), "on", 1, LONG),              # 종가 > 전일 고가 + 종가 강도
    "O2b": (lambda u: (u.close > u.pdh) & (u.volr >= 1.5), "on", 1, LONG),            # 종가 > 전일 고가 + 거래량
    "O3d": (lambda u: u.ret <= -0.04, "on", 1, LONG),                                 # EOD 평균회귀(급락)
    "O3u": (lambda u: u.ret >= 0.05, "on", 1, LONG),                                  # 급등 후 밤사이(부호는 TRAIN)
    # 룩어헤드 없는 짝: 신호는 T 종가, 진입은 T+1 시가, 청산은 T+1 종가 (종가 동시 체결 가정이 없다)
    "O0n": (lambda u: u.ret.notna(), "ocn", 1, LONG),
    "O1n": (lambda u: (u.clv >= 0.8) & (u.ret > 0) & (u.volr >= 1.5), "ocn", 1, LONG),
    "O2n": (lambda u: (u.close > u.pdh) & (u.clv >= 0.8), "ocn", 1, LONG),
    "O3dn": (lambda u: u.ret <= -0.04, "ocn", 1, LONG),
    "O3un": (lambda u: u.ret >= 0.05, "ocn", 1, LONG),
    "O4d": (lambda u: u.gap <= -0.02, "oc", 1, LONG),                                 # 갭하락 -> 시가 매수·종가 매도
    "O4u": (lambda u: u.gap >= 0.02, "oc", 1, LONG),                                  # 갭상승 continuation
}


def cell_events(u: pd.DataFrame, cid: str):
    cond, win, d, _ = CELLS[cid]
    ev = u[cond(u)].dropna(subset=[win])
    if cid != "O4d" and cid != "O4u":
        ev = ev[ev.ret < LIMIT_UP]                # 종가 상한가 근처는 매수 불가
    mkt = u.groupby("date")[win].mean()
    gross = d * ev[win]
    info = gross - d * ev["date"].map(mkt)
    tk = tick_bp(ev["close"] if win == "on" else ev["open"])      # ocn/oc 는 시가 진입
    df = pd.DataFrame({"date": ev["date"], "i": info, "g": gross, "tk": tk})
    df = df.groupby("date").mean()
    return [(dt, r.i, r.g, FIXED_BP, FIXED_BP + r.tk) for dt, r in df.iterrows()], int(len(ev))


def main():
    a = load()
    u = a[(a.liq >= LIQ_MIN)].copy()
    cells, counts = {}, {}
    for cid in CELLS:
        cells[cid], counts[cid] = cell_events(u, cid)
    rng = np.random.default_rng(SEED)
    res = family(cells, split, rng, {c: CELLS[c][3] for c in CELLS})
    res["event_counts"] = counts
    res["cost_bp"] = {"tax": TAX_BP, "fee": round(2 * FEE_SIDE_BP, 2), "kikwan": round(2 * KIKWAN_SIDE_BP, 2),
                      "spread_base": 0.0, "fixed_total": round(FIXED_BP, 2), "event_total": EVENT_BP,
                      "spread_stress": "진입가 한 호가(bp)"}
    for cid, r in res["cells"].items():
        if "TRAIN" not in r:
            continue
        ev = cells[cid]
        s = r["train_sign"]
        dts = np.array([e[0] for e in ev])
        g = np.array([e[2] for e in ev])
        oos = np.array([split(x) != "TRAIN" for x in dts])
        r["net_event_oos_bp"] = round(float((s * g[oos] - EVENT_BP).mean()), 2) if oos.any() else None
        yrs = pd.Series(s * g - FIXED_BP, index=pd.to_datetime(dts)).groupby(lambda x: x.year).mean()
        r["yearly_net_bp"] = {int(y): round(float(v), 1) for y, v in yrs.items()}
        r["names_per_day"] = round(counts[cid] / max(1, len(ev)), 1)
    (HERE / "close-open-phase5.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"bar |t|={res['bar']}  cost fixed {FIXED_BP:.2f}bp (event {EVENT_BP})  events {counts}")
    for cid, r in res["cells"].items():
        if "TRAIN" not in r:
            print(cid, r["verdict"]); continue
        print(f"{cid:4s} {r['verdict']:11s} s{r['train_sign']:+d} tTR {r['t_train']:6.2f} n {r['TRAIN']['n']}/{r['VALID']['n']}/{r['TEST']['n']} "
              f"info {r['TRAIN']['info_bp']}/{r['VALID']['info_bp']}/{r['TEST']['info_bp']} gross {r['TRAIN']['gross_bp']}/{r['VALID']['gross_bp']}/{r['TEST']['gross_bp']} "
              f"net {r['net1_oos_bp']} / stress {r['net2_oos_bp']} / event {r['net_event_oos_bp']}  names/d {r['names_per_day']}")
        print("     yearly net", r["yearly_net_bp"])


def selftest():
    assert abs(FIXED_BP - 23.53854) < 1e-4, FIXED_BP           # 20 + 2*1.40527 + 2*0.364
    rows = []
    for t, base in (("A", 100.0), ("B", 200.0)):
        for i, d in enumerate(pd.bdate_range("2026-01-05", periods=25)):
            o = base * (1 + 0.001 * i)
            rows.append({"ticker": t, "date": d, "open": o, "high": o * 1.02, "low": o * 0.98, "close": o * 1.01, "volume": 1000.0 + i})
    f = features(pd.DataFrame(rows))
    a = f[f.ticker == "A"].reset_index(drop=True)
    assert abs(a.loc[5, "clv"] - 0.75) < 1e-9                                  # (1.01-0.98)/(1.02-0.98)
    assert abs(a.loc[5, "on"] - ((a.loc[6, "open"] / a.loc[5, "close"] - 1) * 1e4)) < 1e-9   # 종가 -> 익일 시가
    assert np.isnan(a.loc[24, "on"])                                           # 마지막 날엔 익일이 없다
    assert abs(a.loc[5, "ocn"] - a.loc[6, "oc"]) < 1e-9                        # 익일 시가→종가
    assert abs(a.loc[5, "pdh"] - a.loc[4, "high"]) < 1e-9
    assert abs(a.loc[5, "gap"] - (a.loc[5, "open"] / a.loc[4, "close"] - 1)) < 1e-9
    # 거래일 연속이 끊긴 종목은 밤사이·전일 값이 NaN (결측일 건너뛰기 금지)
    b = pd.DataFrame(rows)
    b = b[~((b.ticker == "A") & (b.date == pd.Timestamp("2026-01-12")))]
    fb = features(b)
    ab = fb[fb.ticker == "A"].reset_index(drop=True)
    i = ab.index[ab.date == pd.Timestamp("2026-01-09")][0]
    assert np.isnan(ab.loc[i, "on"]), ab.loc[i, "on"]
    print("selftest ok (8건)")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
