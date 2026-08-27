#!/usr/bin/env python3
"""KOSPI200 선물 데이터 정찰 (수집 아님, 가용성 판정만).

로컬 샌드박스에서 pykrx.stock.get_future_ohlcv_by_ticker()가 빈 응답으로
실패했다 - IP 차단인지 진짜 엔드포인트 문제인지 이 환경에서 확정할 수 없어
GH Actions 실 러너에서 재확인한다(probe-krx.py와 같은 방법론, 교훈32:
전체 파이프라인을 다시 짜기 전에 경로부터 1회씩 확인).

출력: data/backfill/_probe-future-krx.json
"""
import json
import os
import sys
import time
import traceback

OUT = "data/backfill/_probe-future-krx.json"
PROD = "KRDRVFUK2I"  # pykrx 확인: "KOSPI 200 Futures"

results = {}


def rec(name, **kw):
    results[name] = kw
    verdict = kw.get("verdict", "?")
    print(f"[{name}] {verdict}  " + "  ".join(
        f"{k}={v}" for k, v in kw.items() if k in ("rows", "error", "count")))


def probe(name, fn):
    t0 = time.time()
    try:
        fn(name)
    except Exception as e:  # noqa: BLE001
        rec(name, verdict="EXC", error=f"{type(e).__name__}: {e}",
            trace=traceback.format_exc()[-600:])
    print(f"    ({time.time() - t0:.1f}s)")


def biz_days_back(n):
    """최근 n영업일(주말만 제외, 공휴일은 응답 자체로 판단) YYYYMMDD 리스트."""
    import datetime
    out, d = [], datetime.date.today()
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d -= datetime.timedelta(days=1)
    return out


# ── A. 로그인 자격 확인 (probe-krx.py와 동일 패턴) ─────────────────
def p_login(name):
    has = bool(os.environ.get("KRX_ID")) and bool(os.environ.get("KRX_PW"))
    import pykrx
    rec(name, verdict="CRED_OK" if has else "CRED_MISSING",
        pykrxVersion=getattr(pykrx, "__version__", "unknown"))


# ── B. 선물 상품 티커 목록/이름 (메타데이터, 로그인 무관 예상) ──────
def p_ticker_meta(name):
    from pykrx import stock
    tickers = stock.get_future_ticker_list()
    nm = stock.get_future_ticker_name(PROD)
    rec(name, verdict="OK" if tickers and PROD in tickers else "MISSING",
        count=len(tickers) if tickers else 0, prodName=str(nm)[:100])


# ── C. 선물 일별 OHLCV (실제 시세 - 로컬에서 실패했던 지점) ────────
def p_ohlcv_by_ticker(name):
    from pykrx import stock
    ok_days = []
    for d in biz_days_back(5):
        try:
            df = stock.get_future_ohlcv_by_ticker(d, PROD)
            rows = 0 if df is None else len(df)
            if rows:
                ok_days.append(d)
        except Exception as e:  # noqa: BLE001
            rec(f"{name}_{d}_error", verdict="EXC", error=str(e)[:200])
            continue
    rec(name, verdict="OK" if ok_days else "EMPTY_ALL",
        okDays=ok_days, triedDays=5)


# ── D. alternative=True 변형(다른 내부 소스 경로) ──────────────────
def p_ohlcv_alternative(name):
    from pykrx import stock
    d = biz_days_back(3)[-1]
    df = stock.get_future_ohlcv_by_ticker(d, PROD, alternative=True)
    rows = 0 if df is None else len(df)
    rec(name, verdict="OK" if rows else "EMPTY", rows=rows, date=d)


# ── E. 대조군: 지수(현물) OHLCV — pykrx 기본 경로가 이 환경에서
# 살아있는지 확인해 "선물만 막힘"과 "pykrx 전체가 막힘"을 가른다 ──────
def p_index_control(name):
    from pykrx import stock
    d = biz_days_back(3)[-1]
    df = stock.get_index_ohlcv_by_date(d, d, "1028")  # 1028 = KOSPI200
    rows = 0 if df is None else len(df)
    rec(name, verdict="OK" if rows else "EMPTY", rows=rows, date=d)


def main():
    print("KOSPI200 선물 데이터 정찰 (pykrx)\n")
    probe("A_login_state", p_login)
    probe("B_ticker_meta", p_ticker_meta)
    probe("C_ohlcv_by_ticker", p_ohlcv_by_ticker)
    probe("D_ohlcv_alternative", p_ohlcv_alternative)
    probe("E_index_control", p_index_control)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"probedAt": time.strftime("%Y-%m-%dT%H:%M:%S+0900"),
                   "product": PROD, "results": results},
                  f, ensure_ascii=False, indent=2)

    v = {k: r.get("verdict") for k, r in results.items()}
    print("\n── 판정 ──")
    for k, s in v.items():
        print(f"  {k:26s} {s}")

    futures_ok = v.get("C_ohlcv_by_ticker") == "OK" or v.get("D_ohlcv_alternative") == "OK"
    control_ok = v.get("E_index_control") == "OK"

    print("\n── 결론 ──")
    if futures_ok:
        print("  선물 OHLCV 확보 가능 - fetch_macro.py에 pykrx 경로 추가를 고려한다.")
    elif control_ok:
        print("  지수(현물)는 되는데 선물만 막힘 - 선물 전용 제약(권한·엔드포인트) 의심.")
    else:
        print("  pykrx 경로 자체가 이 러너에서 막힘 - 선물 문제가 아니라 환경 문제.")
    # 정찰은 판정이 산출물이다. 어떤 결과든 exit 0으로 끝내 산출물을 커밋시킨다.
    return 0


if __name__ == "__main__":
    sys.exit(main())
