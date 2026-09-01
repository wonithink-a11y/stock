"""probe-etf-etn-supply-demand-krx.py — ETF/ETN 매매동향(수급) KRX 로그인 정찰.

로컬에서 KRX_ID/KRX_PW 없이 pykrx.get_etf_trading_volume_and_value()를
불렀더니 티커목록 조회 단계(EtxTicker._get_tickers, MDCSTAT04601/06701)에서
raw HTTP로 "LOGOUT"을 직접 재현했다(2026-09-01). probe-supply-demand-krx.py
(2026-08-17)가 이미 "KRX_ID/KRX_PW + Actions 환경이면 일반 종목 수급은
된다"는 걸 확인했지만, 그건 다른 엔드포인트(개별종목 investor trend)였다 -
ETF/ETN 티커목록·매매동향 엔드포인트가 같은 결론인지는 아직 안 쟀다.

정찰 전용 — data/ · docs/data/ · config/policies/ 어디에도 쓰지 않는다.
"""
import sys
import time
from datetime import datetime, timedelta

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass


def hr(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def run(label, fn):
    t0 = time.time()
    try:
        df = fn()
        elapsed = round(time.time() - t0, 2)
        if df is None or df.empty:
            print(f"[EMPTY] {label} ({elapsed}s)")
            return None, elapsed
        print(f"[OK] {label} ({elapsed}s) - {len(df)}행")
        print(df)
        return df, elapsed
    except Exception as e:  # noqa: BLE001
        elapsed = round(time.time() - t0, 2)
        print(f"[FAIL] {label} ({elapsed}s) - {type(e).__name__}: {e}")
        return None, elapsed


def main():
    from pykrx import stock

    to = datetime.now().strftime("%Y%m%d")
    frm = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")

    hr("A. ETF/ETN 티커목록 조회 (로컬에서 LOGOUT으로 막혔던 지점)")
    run("get_etx_ticker_list(오늘, ALL)",
        lambda: __import__("pandas").DataFrame(
            {"ticker": stock.get_etx_ticker_list(to, "ALL")}))

    hr("B. ETF 매매동향 - 069500 KODEX 200")
    run(f"get_etf_trading_volume_and_value({frm}~{to}, 069500)",
        lambda: stock.get_etf_trading_volume_and_value(frm, to, "069500"))

    hr("C. ETN 매매동향 - 580011")
    run(f"get_etf_trading_volume_and_value({frm}~{to}, 580011)",
        lambda: stock.get_etf_trading_volume_and_value(frm, to, "580011"))

    hr("D. ETN 매매동향 - 우리 관심대상 중 하나(500095, 신한 VIX ETN)")
    run(f"get_etf_trading_volume_and_value({frm}~{to}, 500095)",
        lambda: stock.get_etf_trading_volume_and_value(frm, to, "500095"))

    hr("완료")
    print(f"probedAt(UTC) = {datetime.utcnow().isoformat()}Z")


if __name__ == "__main__":
    main()
