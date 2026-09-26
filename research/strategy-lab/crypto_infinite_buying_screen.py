#!/usr/bin/env python3
"""무한매수법(V4.0 엔진) 크립토 스크리닝 — 격자·판정 기준은 이 파일이 결과 전 커밋으로 고정한다.

09-12 연구(infinite-buying-splits-2x3x-crypto-extension §7)는 BTC·ETH 일봉 40분할에서 '4년 주기와 설계 시간축
(약 2개월) 불일치'로 기각했다. 이번에 묻는 것: (1) 분할 수를 늘리거나 주봉으로 바꿔 시간축을 맞추면 달라지나,
(2) 알트코인(상장폐지 LUNA·FTT 포함)에서는, (3) CAGR 이 아니라 위험 대비(Sharpe·MDD)로 보유를 이기나.

    python research/strategy-lab/crypto_infinite_buying_screen.py            # 수집(캐시) + 실행
    python research/strategy-lab/crypto_infinite_buying_screen.py --selftest

판정(스크리닝, 결과 전 고정): 변형이 한 자산에서 '이김' = Sharpe > 보유 Sharpe AND MDD < 보유 MDD.
후보 = BTC·ETH 둘 다 이기고 알트(폐지 포함) 3분의 2 이상에서 이김. 후보도 채택이 아니다 — 새 사전등록·OOS 가 필요하다.
Sharpe 는 현금 이자 0 가정이라 보유 비중을 낮춘 보유(노출 맞춤)의 Sharpe 는 보유와 같다 — 그래서 비교 기준을 보유 하나로 둔다.
"""
from __future__ import annotations

import io
import json
import sys
import time
import zipfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import infinite_buying_engine as E  # noqa: E402

RULES = HERE / "data" / "leveraged-etf" / "_rules.local.json"
CACHE = HERE / "data" / "crypto" / "daily-binance"
OUT = HERE / "findings" / "crypto-infinite-buying-screen-2026-09.json"
VISION = "https://data.binance.vision/data/spot/monthly/klines/{s}/1d/{s}-1d-{m}.zip"
COMMISSION = 0.0005          # 업비트·바이낸스 현물 편도 0.05%. 세금은 넣지 않는다(국내 가상자산 과세 유예)
SEED = 1e8
START_PX = 1000.0            # 정수 수량 엔진이라 가격을 첫 종가 1000 으로 정규화(수익률 불변)
END = "2026-08-31"

VARIANTS = ([("D", n, b) for n in (40, 80, 160, 320) for b in (10.0, 20.0, 30.0)]
            + [("W", n, b) for n in (20, 40) for b in (10.0, 20.0, 30.0)])      # (봉, 분할, base%)
ALTS = ["AAVE", "ADA", "APT", "ARB", "ATOM", "AVAX", "BCH", "BNB", "DOGE", "DOT", "FIL", "INJ", "LINK", "LTC",
        "NEAR", "OP", "PEPE", "SHIB", "SOL", "SUI", "TRX", "UNI", "WLD", "XMR", "XRP", "ZEC",
        "LUNA", "FTT"]      # 마지막 둘 = 붕괴·사실상 폐지(생존편향 대조). XMR 은 2024-02 바이낸스 상장폐지


def fetch(sym: str) -> pd.DataFrame:
    f = CACHE / f"{sym}USDT.parquet"
    if f.exists():
        return pd.read_parquet(f)
    CACHE.mkdir(parents=True, exist_ok=True)
    rows, ses = [], requests.Session()
    for m in pd.period_range("2017-08", END[:7], freq="M"):
        r = None
        for i in range(3):
            try:
                r = ses.get(VISION.format(s=f"{sym}USDT", m=str(m)), timeout=30)
                break
            except requests.RequestException:
                time.sleep(2 ** i)
        if r is None or r.status_code != 200:
            continue
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            d = pd.read_csv(z.open(z.namelist()[0]), header=None, usecols=range(5))
        rows.append(d)
    d = pd.concat(rows, ignore_index=True)
    d.columns = ["t", "open", "high", "low", "close"]
    unit = "us" if d["t"].max() > 1e14 else "ms"     # 2025 이후 바이낸스 자료실은 마이크로초
    d["date"] = pd.to_datetime(d["t"], unit=unit).dt.normalize()
    d = d.drop(columns="t").drop_duplicates("date").sort_values("date").reset_index(drop=True)
    d.to_parquet(f)
    return d


def first_run(d: pd.DataFrame) -> pd.DataFrame:
    """첫 3일 초과 공백에서 자른다 — 거래 중단(LUNA 2022-05) 뒤 다른 자산으로 재상장된 구간을 잇지 않는다."""
    gap = d["date"].diff().dt.days.fillna(1)
    cut = np.flatnonzero(gap.to_numpy() > 3)
    return d.iloc[: cut[0]] if len(cut) else d


def load_all() -> dict[str, pd.DataFrame]:
    out = {}
    for t in ("BTC", "ETH"):
        d = pd.read_parquet(HERE / "data" / "leveraged-etf" / f"{t}-USD.parquet")
        d["date"] = pd.to_datetime(d["date"]).dt.tz_localize(None).dt.normalize()
        out[t] = d[["date", "open", "high", "low", "close"]]
    for a in ALTS:
        out[a] = first_run(fetch(a))
    return {k: v[v["date"] <= END].reset_index(drop=True) for k, v in out.items()}


def bars(d: pd.DataFrame, kind: str) -> pd.DataFrame:
    if kind == "W":
        d = (d.set_index("date").resample("W-SUN")
             .agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index())
    k = START_PX / d["close"].iloc[0]
    d = d.copy()
    d[["open", "high", "low", "close"]] *= k
    return d


def metrics(eq: np.ndarray, per_year: float, dates: pd.Series) -> dict:
    r = np.diff(eq) / eq[:-1]
    yrs = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    peak = np.maximum.accumulate(eq)
    return {"cagr": float((eq[-1] / eq[0]) ** (1 / yrs) - 1) * 100 if yrs > 0 and eq[-1] > 0 else -100.0,
            "mdd": float(((peak - eq) / peak).max() * 100),
            "sharpe": float(r.mean() / r.std() * np.sqrt(per_year)) if r.std() > 0 else 0.0}


def run_variant(d: pd.DataFrame, kind: str, n: int, base: float, rules0: E.Rules) -> dict:
    b = bars(d, kind)
    candles = [{"date": x.strftime("%Y-%m-%d"), "open": o, "high": h, "low": lo, "close": c}
               for x, o, h, lo, c in b[["date", "open", "high", "low", "close"]].itertuples(index=False)]
    r = replace(rules0, splits=n, base_pct=base, tick=1e-6, seed=SEED, commission=COMMISSION)
    tr: list = []
    res = E.backtest(candles, r, trace=tr)
    eq = np.array([SEED] + [x["equity"] for x in tr])
    expo = np.array([x["qty"] * x["close"] / x["equity"] for x in tr if x["equity"] > 0])
    py = 365.0 if kind == "D" else 52.0
    m = metrics(eq, py, pd.concat([b["date"].iloc[:1] - pd.Timedelta(days=1 if kind == "D" else 7), b["date"]]))
    worst = min((c["profit"] for c in res.cycles), default=0.0)
    m.update({"exposure": float(expo.mean()), "cycles": len(res.cycles), "worst_cycle_pct": worst / SEED * 100,
              "reverse_share": res.reverse_days / len(candles), "open_at_end": bool(res.state.qty > 0)})
    return m


def hold(d: pd.DataFrame, kind: str) -> dict:
    b = bars(d, kind)
    eq = b["close"].to_numpy(float)
    return metrics(eq, 365.0 if kind == "D" else 52.0, b["date"])


def main():
    rules0 = E.Rules.load(RULES, "TQQQ", 40)
    data = load_all()
    res = {"variants": [list(v) for v in VARIANTS], "assets": {}}
    for a, d in data.items():
        row = {"from": str(d["date"].iloc[0].date()), "to": str(d["date"].iloc[-1].date()),
               "hold": {k: hold(d, k) for k in ("D", "W")}, "ib": {}}
        for kind, n, base in VARIANTS:
            row["ib"][f"{kind}{n}b{base:g}"] = run_variant(d, kind, n, base, rules0)
        res["assets"][a] = row
        print(a, row["from"], row["to"], "보유", {k: round(v["sharpe"], 2) for k, v in row["hold"].items()})
    summary = {}
    alts = [a for a in data if a not in ("BTC", "ETH")]
    for kind, n, base in VARIANTS:
        key = f"{kind}{n}b{base:g}"
        win = {a: bool(r["ib"][key]["sharpe"] > r["hold"][kind]["sharpe"] and r["ib"][key]["mdd"] < r["hold"][kind]["mdd"])
               for a, r in res["assets"].items()}
        alt_rate = float(np.mean([win[a] for a in alts]))
        summary[key] = {"btc": win["BTC"], "eth": win["ETH"], "alt_win_rate": alt_rate,
                        "candidate": bool(win["BTC"] and win["ETH"] and alt_rate >= 2 / 3),
                        "median_sharpe_diff": float(np.median([r["ib"][key]["sharpe"] - r["hold"][kind]["sharpe"]
                                                               for r in res["assets"].values()]))}
    res["summary"] = summary
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in summary.items():
        print(k, v)


def selftest():
    ok = 0
    d = pd.DataFrame({"date": pd.to_datetime(["2022-05-10", "2022-05-11", "2022-05-12", "2022-05-31", "2022-06-01"]),
                      "open": 1.0, "high": 1.0, "low": 1.0, "close": [1.0, .5, .01, 5.0, 6.0]})
    assert len(first_run(d)) == 3; ok += 1
    w = bars(pd.DataFrame({"date": pd.date_range("2024-01-01", periods=14), "open": range(1, 15), "high": range(1, 15),
                           "low": range(1, 15), "close": range(1, 15)}).astype({"open": float, "high": float, "low": float, "close": float}), "W")
    assert len(w) == 2 and abs(w["close"].iloc[0] - 1000) < 1e-9 and abs(w["close"].iloc[1] - 2000) < 1e-9, w; ok += 1
    m = metrics(np.array([100.0, 50.0, 100.0]), 365, pd.Series(pd.to_datetime(["2020-01-01", "2020-07-01", "2021-01-01"])))
    assert abs(m["mdd"] - 50) < 1e-9 and abs(m["cagr"]) < 1e-9; ok += 1
    print(f"selftest {ok}/3 OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
