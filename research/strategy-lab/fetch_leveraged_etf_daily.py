#!/usr/bin/env python3
"""3배 레버리지 ETF 일봉 수집 (무한매수법 백테스트 입력).

    python research/strategy-lab/fetch_leveraged_etf_daily.py
    python research/strategy-lab/fetch_leveraged_etf_daily.py --tickers TQQQ SOXL
    python research/strategy-lab/fetch_leveraged_etf_daily.py --selftest   # 네트워크 없음

출처는 yfinance(무료·키 불필요). 산출물은
research/strategy-lab/data/leveraged-etf/{TICKER}.parquet 와 _manifest.json.

★ 분할 조정만 하고 배당 조정은 하지 않는다(auto_adjust=False, 'Close' 사용).
  무한매수법은 실제 체결 가격 수준으로 LOC 문턱을 잡으므로 배당 재투자 가격열을 쓰면
  평단·별지점이 실제와 어긋난다. 레버리지 ETF 는 역분할이 잦아 분할 조정은 필수다.
  배당은 별도 열로 같이 저장해 필요하면 하류가 더한다(교훈75 — 원시 사실을 남긴다).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parents[0] / "data" / "leveraged-etf"
DEFAULT = ["TQQQ", "SOXL", "KORU"]
COLS = ["date", "open", "high", "low", "close", "volume", "dividends", "splits"]


def fetch(ticker: str):
    import pandas as pd
    import yfinance as yf

    df = yf.Ticker(ticker).history(period="max", auto_adjust=False, actions=True)
    if df is None or df.empty:
        raise SystemExit(f"{ticker}: 빈 응답 — 티커를 확인한다")
    df = df.reset_index().rename(columns=str.lower)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
    df = df.rename(columns={"stock splits": "splits"})
    for c in ("dividends", "splits"):
        if c not in df:
            df[c] = 0.0
    return df[COLS].sort_values("date").reset_index(drop=True)


def check(ticker: str, df) -> list[str]:
    """조용히 틀릴 수 있는 것만 본다. 통과는 정보를 거의 안 준다(교훈61)."""
    bad = []
    if df["date"].duplicated().any():
        bad.append("중복 거래일")
    if not df["date"].is_monotonic_increasing:
        bad.append("날짜 역행")
    ohlc = df[["open", "high", "low", "close"]]
    if (ohlc <= 0).any().any() or ohlc.isna().any().any():
        bad.append("0 이하 또는 결측 OHLC")
    if (df["high"] < df["low"]).any():
        bad.append("high < low")
    if ((df["close"] > df["high"]) | (df["close"] < df["low"])).any():
        bad.append("close 가 high/low 밖")
    if len(df) < 250:
        bad.append(f"행 수 부족 {len(df)}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+", default=DEFAULT)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "axis": "leveraged-etf/daily",
        "generatedAtUTC": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance history(period=max, auto_adjust=False, actions=True)",
        "note": "분할 조정만. 배당 미조정 — dividends 열을 따로 저장한다",
        "tickers": {},
    }
    for t in a.tickers:
        df = fetch(t)
        bad = check(t, df)
        if bad:
            print(f"FAIL {t}: {', '.join(bad)}", file=sys.stderr)
            return 1
        p = OUT / f"{t}.parquet"
        df.to_parquet(p, index=False)
        manifest["tickers"][t] = {
            "rows": len(df),
            "from": str(df["date"].iloc[0].date()),
            "to": str(df["date"].iloc[-1].date()),
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
            "reverseSplits": int((df["splits"] > 0).sum()),
        }
        m = manifest["tickers"][t]
        print(f"{t:6} {m['rows']:>5}행  {m['from']} ~ {m['to']}  분할 {m['reverseSplits']}건")

    (OUT / "_manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(f"-> {OUT}")
    return 0


def selftest() -> int:
    import pandas as pd

    ok = pd.DataFrame({
        "date": pd.to_datetime(["2020-01-02", "2020-01-03"]),
        "open": [1.0, 1.1], "high": [1.2, 1.3], "low": [0.9, 1.0],
        "close": [1.1, 1.2], "volume": [10, 20],
        "dividends": [0.0, 0.0], "splits": [0.0, 0.0],
    })
    cases = [
        ("정상(행 수만 걸림)", ok, ["행 수 부족 2"]),
        ("중복일", pd.concat([ok, ok.iloc[[0]]]).sort_values("date"), "중복 거래일"),
        ("close 가 범위 밖", ok.assign(close=[9.9, 1.2]), "close 가 high/low 밖"),
        ("high < low", ok.assign(high=[0.1, 1.3]), "high < low"),
    ]
    fails = 0
    for name, df, want in cases:
        got = check("X", df.reset_index(drop=True))
        want_list = want if isinstance(want, list) else [want]
        if not all(w in got for w in want_list):
            print(f"FAIL {name}: {got}")
            fails += 1
        else:
            print(f"ok   {name}")
    print(f"selftest {4 - fails}/4")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
