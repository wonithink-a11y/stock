#!/usr/bin/env python3
"""공매도 데이터 정찰(scouting) — data-source-availability.md가 "차단"으로 남겨둔
공매도가 A4(수급)를 뚫은 것과 같은 KRX_ID/KRX_PW 로그인 세션으로도 여전히
막혀 있는지 재확인한다(교훈52: 전제가 바뀌면 다시 잰다). A4의 probeTickers
(005930, 000660, config/policies/supplyDemand.v1.json)와 동일 종목·같은
2회 정찰 패턴을 그대로 따른다.

data/backfill/에 아무것도 쓰지 않는다. manifest 없음. commit 없음. 순수 진단
출력(stdout + 로컬 JSON 하나)뿐이다 — 실제 백필 설계는 이 결과를 본 뒤 별도로
한다.

  KRX_ID=... KRX_PW=... python scripts/probe-shorting-krx.py
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta

PROBE_TICKERS = ["005930", "000660"]  # A4와 동일(config/policies/supplyDemand.v1.json)


def _import_pykrx_stock():
    """pykrx는 import 시점에 KRX_ID/KRX_PW로 로그인을 시도한다(A4의
    _import_pykrx_stock()과 동일한 재시도 패턴 - 짧은 백오프 4회)."""
    last_err = None
    for attempt in range(4):
        try:
            from pykrx import stock
            return stock
        except Exception as e:  # noqa: BLE001
            last_err = e
            wait = 15 * (attempt + 1)
            print(f"  pykrx import/KRX 로그인 실패(시도 {attempt + 1}/4, {wait}초 대기): "
                  f"{type(e).__name__}: {e}")
            time.sleep(wait)
    raise last_err


def main():
    result = {
        "generatedAt": datetime.now().isoformat(),
        "hasKrxCredentials": bool(os.environ.get("KRX_ID")) and bool(os.environ.get("KRX_PW")),
        "probeTickers": PROBE_TICKERS,
    }
    if not result["hasKrxCredentials"]:
        print("KRX_ID/KRX_PW 미설정 - 로그인 세션 없이는 이 정찰이 의미 없다(교훈: "
              "무자격 재실측은 이미 '차단'으로 확정돼 있음, data-source-availability.md).")
        result["aborted"] = "no_krx_credentials"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(1)

    stock = _import_pykrx_stock()
    result["importOk"] = True

    shorting_related = sorted(n for n in dir(stock) if "short" in n.lower())
    result["shortingFunctionsFound"] = shorting_related
    print("공매도 관련 함수(pykrx 설치 버전 실측):", shorting_related)

    to_date = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    from_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")

    attempts = []
    for fn_name in shorting_related:
        fn = getattr(stock, fn_name)
        for ticker in PROBE_TICKERS:
            entry = {"function": fn_name, "ticker": ticker}
            try:
                df = fn(from_date, to_date, ticker)
                entry["ok"] = True
                entry["rows"] = len(df)
                entry["columns"] = list(df.columns.astype(str))
                entry["sampleTail"] = df.tail(2).to_dict(orient="records") if len(df) else []
                print(f"  OK  {fn_name}({from_date}~{to_date}, {ticker}) -> "
                      f"{len(df)}행, 컬럼={entry['columns']}")
            except Exception as e:  # noqa: BLE001
                entry["ok"] = False
                entry["error"] = f"{type(e).__name__}: {e}"
                print(f"  FAIL {fn_name}({from_date}~{to_date}, {ticker}) -> {entry['error']}")
            attempts.append(entry)

    result["attempts"] = attempts
    result["anySucceeded"] = any(a["ok"] for a in attempts)

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                             "probe-shorting-krx-result.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print("\nsaved:", out_path)
    print("\n결론:", "일부 경로 성공 - 공매도 데이터 접근 가능성 있음" if result["anySucceeded"]
          else "전부 실패 - 공매도는 이 로그인 방식으로도 여전히 막혀 있음")


if __name__ == "__main__":
    main()
