#!/usr/bin/env python3
"""바이낸스 신규 상장 7일 숏 무기한 — 진입 시각 점검. 사전등록 findings/binance-listing-perp-entry-time-preregistration-2026-11.md (c4cc89f0).

원 실험(binance_listing_perp.py, 8512abb)의 진입가는 무기한 일봉 시가다. 무기한이 t0 당일 장중에 열린 건(D)에서는 그 값이 첫 체결가라 실행 불가능하다.
D 건만 1시간봉 기준 실행 가능 진입가(첫 봉 + 1시간 시가, 168시간 보유)로 바꿔 원 판정 규칙을 다시 적용한다. 기록 전용 — 운용 불변.

    python research/strategy-lab/futures/binance_listing_perp_entry.py --collect   # 일봉·펀딩(없으면)·D 건 1시간봉·BTC 1시간봉 → data/crypto/listing_perp/
    python research/strategy-lab/futures/binance_listing_perp_entry.py             # 판정 → futures/binance-listing-perp-entry.json
    python research/strategy-lab/futures/binance_listing_perp_entry.py --selftest
"""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binance_listing as bl  # noqa: E402
import binance_listing_perp as bp  # noqa: E402  원 실험(8512abb)
import coinbase_premium as cp  # noqa: E402
import coinbase_premium_robustness as rb  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

DATA, D, H, COST, STRESS, END = bp.DATA, bp.D, bp.H, bp.COST, bp.STRESS, bp.END
HR = pd.Timedelta(hours=1)
DELAY, DELAY_STRESS = 1, 4          # 사전등록: 주 1시간, 기록 4시간


def hourly(sym: str, months: list[str]) -> pd.Series:
    fr = []
    for m in months:
        d = bp._csv(f"{bp.UM}/klines/{sym}/1h/{sym}-1h-{m}.zip")
        if len(d):
            s = pd.Series(d[1].astype(float).to_numpy(), index=bp._ms(d[0]))
            fr.append(s[s.index.tz_convert(None).to_period("M") == pd.Period(m, "M")])
    return pd.concat(fr).sort_index() if fr else pd.Series(dtype=float)


def classify(first_day: pd.Timestamp, t0: pd.Timestamp) -> str:
    return "C" if first_day < t0 else ("D" if first_day == t0 else "X")


def observe_hourly(px: pd.Series, fu: pd.DataFrame, btc: pd.Series, delay: int) -> dict:
    """px·btc: 1시간봉 시가(UTC). 첫 봉 F → 진입 E = F + delay 시간, 청산 E + 168시간."""
    if not len(px):
        return {"ok": False}
    F = px.index[0]
    E = F + delay * HR
    X = E + 24 * H * HR
    p0, p1, b0, b1 = px.get(E, np.nan), px.get(X, np.nan), btc.get(E, np.nan), btc.get(X, np.nan)
    if not all(np.isfinite([p0, p1, b0, b1])) or X > END:
        return {"ok": False}
    f = fu[(fu.index > E) & (fu.index <= X)] if len(fu) else fu
    Fs = float(f["rate"].sum()) if len(f) else 0.0
    r, b = p1 / p0 - 1, b1 / b0 - 1
    first_gap = (px.iloc[0] / p0 - 1) * 1e4 if px.iloc[0] != p0 else 0.0    # 첫 체결가가 진입가보다 얼마 높았나
    return {"ok": True, "obs": (-(r - b) + Fs) * 1e4, "price_only": -(r - b) * 1e4, "funding": Fs * 1e4, "first_gap": first_gap}


def collect():
    if not (DATA / "match.json").exists():
        bp.collect()                      # 일봉·펀딩·BTC 일봉 (원 수집 그대로)
    m = json.loads((DATA / "match.json").read_text(encoding="utf-8"))
    ev = bl.events_table(json.loads((bl.DATA / "months.json").read_text(encoding="utf-8")))

    def one(e):
        sym = m.get(e["sym"])
        pf = DATA / f"{e['sym']}_perp.parquet"
        if sym is None or not pf.exists():
            return 0
        px = rb._read(pf)["open"]
        spot = rb._read(bl.DATA / f"{e['sym']}.parquet")["open"]
        if not len(px) or not len(spot) or classify(px.index[0], spot.index[0] + D) != "D":
            return 0
        p = pd.Period(e["first"], "M")
        s = hourly(sym, [str(p + k) for k in range(3)])
        s.rename("open").to_frame().to_parquet(DATA / f"{e['sym']}_perp1h.parquet")
        return 1
    with ThreadPoolExecutor(8) as ex:
        n = sum(ex.map(one, ev))
    hourly("BTCUSDT", [str(p) for p in pd.period_range("2019-09", "2026-09", freq="M")]).rename("open").to_frame().to_parquet(DATA / "BTCUSDT_perp1h.parquet")
    print("D 건 1시간봉", n)


def evaluate(df: pd.DataFrame, col: str) -> dict:
    """원 binance_listing_perp.main 의 집계·판정 규칙(8512abb)을 col 열 기준으로 그대로 적용."""
    df = df[df["L"] + D + H * D <= END]
    ok = df[df[col].notna()].copy()
    day = ok.groupby("L")[[col]].mean().rename(columns={col: "obs"})
    day["split"] = day.index.map(cp.split)
    oos, te = day[day["split"] != "TRAIN"], day[day["split"] == "TEST"]
    x = oos["obs"].to_numpy()
    n1, n3 = x - COST, x - STRESS
    if len(oos) < 30 or n1.mean() <= 0:
        v = "NOT EXECUTABLE"
    elif tstat(n1) >= 2 and n3.mean() > 0 and te["obs"].mean() - COST > 0:
        v = "EXECUTABLE"
    else:
        v = "PARTIAL"
    per = {g: {"days": int(len(x_)), "obs": round(float(x_["obs"].mean()), 1), "t": round(tstat(x_["obs"].to_numpy()), 2)}
           for g, x_ in day.groupby(day.index.map(cp.period))}
    return {"verdict": v, "oosDays": int(len(oos)), "net10": round(float(n1.mean()), 1), "t_net10": round(tstat(n1), 2), "net30": round(float(n3.mean()), 1),
            "test_net10": round(float(te["obs"].mean() - COST), 1) if len(te) else None, "periods": per,
            "bySplit": {k: {"days": int(len(x_)), "obs": round(float(x_["obs"].mean()), 1), "t": round(tstat(x_["obs"].to_numpy()), 2)} for k, x_ in day.groupby("split")}}


def label(orig: dict, corr: dict) -> str:
    drop = orig["net10"] - corr["net10"]
    if corr["verdict"] != "EXECUTABLE":
        return "진입가 문제로 약화"
    return "진입가 문제 없음" if drop <= 100 else "진입가 문제 있음(규모 한정)"


def main():
    m = json.loads((DATA / "match.json").read_text(encoding="utf-8"))
    btc_d = rb._read(DATA / "BTCUSDT_perp.parquet")["open"]
    btc_h = rb._read(DATA / "BTCUSDT_perp1h.parquet")["open"]
    ev = bl.events_table(json.loads((bl.DATA / "months.json").read_text(encoding="utf-8")))
    rows = []
    for e in ev:
        spot = rb._read(bl.DATA / f"{e['sym']}.parquet")["open"]
        if not len(spot):
            continue
        L = spot.index[0]
        row = {"sym": e["sym"], "L": L, "grp": None, "orig": np.nan, "corr": np.nan, "corr4": np.nan, "origD": np.nan, "gap": np.nan, "firstGap": np.nan}
        pf = DATA / f"{e['sym']}_perp.parquet"
        if m.get(e["sym"]) is not None and pf.exists():
            px = rb._read(pf)["open"]
            if len(px):
                fu = rb._read(DATA / f"{e['sym']}_funding.parquet") if (DATA / f"{e['sym']}_funding.parquet").exists() else pd.DataFrame(columns=["rate", "ivl"])
                row["grp"] = classify(px.index[0], L + D)
                o = bp.observe(L, px, fu, btc_d, spot.get(L + D, np.nan))
                if o["ok"]:
                    row["orig"] = o["obs"]
                    if row["grp"] == "C":
                        row["corr"] = row["corr4"] = o["obs"]
                    elif row["grp"] == "D":
                        row["origD"] = o["obs"]
                        hf = DATA / f"{e['sym']}_perp1h.parquet"
                        if hf.exists():
                            ph = rb._read(hf)["open"]
                            for col, dl in (("corr", DELAY), ("corr4", DELAY_STRESS)):
                                c = observe_hourly(ph, fu, btc_h, dl)
                                row[col] = c["obs"] if c["ok"] else np.nan
                                if col == "corr" and c["ok"]:
                                    row["firstGap"] = c["first_gap"]
                                    row["gap"] = (px.get(L + D, np.nan) / ph.get(ph.index[0] + dl * HR, np.nan) - 1) * 1e4
        rows.append(row)
    df = pd.DataFrame(rows)
    df = df[df["L"] + D + H * D <= END].copy()
    df["split"] = df["L"].map(cp.split)
    cov = {k: {g: int((x_["grp"] == g).sum()) for g in ("C", "D", "X")} for k, x_ in df.groupby("split")}
    d_ev = df[df["grp"] == "D"]
    df["cleanOnly"] = np.where(df["grp"] == "C", df["orig"], np.nan)
    orig, corr = evaluate(df, "orig"), evaluate(df, "corr")
    out = {"verdict": corr["verdict"], "label": label(orig, corr), "original": orig, "corrected": corr, "stress4h": evaluate(df, "corr4"), "cleanOnly": evaluate(df, "cleanOnly"),
           "coverage": cov,
           "dEvents": {"n": int(len(d_ev)), "withOrig": int(d_ev["orig"].notna().sum()), "withCorr": int(d_ev["corr"].notna().sum()),
                       "origMean": round(float(d_ev["origD"].mean()), 1), "corrMean": round(float(d_ev["corr"].mean()), 1),
                       "origVsEntryGap_bp_median": round(float(d_ev["gap"].median()), 1), "firstPrintVsEntry_bp_median": round(float(d_ev["firstGap"].median()), 1)}}
    (HERE / "binance-listing-perp-entry.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def selftest():
    t0 = pd.Timestamp("2024-03-02", tz="UTC")
    assert classify(t0 - D, t0) == "C" and classify(t0, t0) == "D" and classify(t0 + D, t0) == "X"
    idx = pd.date_range(t0 + 11 * HR, periods=24 * 12, freq="h")         # 11:00 에 개설
    px = pd.Series(100.0, index=idx); px.iloc[0] = 150.0                  # 첫 체결가만 높다
    E = idx[0] + HR
    px[E + 168 * HR] = 80.0                                               # 7일 뒤 −20%
    btc = pd.Series(50.0, index=pd.date_range(t0, periods=24 * 12, freq="h")); btc[E + 168 * HR] = 55.0
    fu = pd.DataFrame({"rate": [-0.001] * 3, "ivl": [8.0] * 3}, index=[E, E + 8 * HR, E + 169 * HR])   # E 정산 제외, 창 안 1건, 밖 1건
    o = observe_hourly(px, fu, btc, 1)
    assert o["ok"] and abs(o["price_only"] - 3000.0) < 1e-6 and abs(o["funding"] + 10.0) < 1e-9, o      # 진입 100(첫 체결가 150 아님): −(−0.2−0.1)=30%
    assert abs(o["first_gap"] - 5000.0) < 1e-6, o
    assert not observe_hourly(px, fu, btc, 400)["ok"]
    print("selftest 3/3 OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        main()
