"""probe-supply-demand-krx.py — KRX(pykrx) 종목별 투자자매매 프로브, Actions 전용.

배경: scripts/probe-supply-demand.py 로컬 실행에서 KIS는 성공했지만 KRX(pykrx)는
로컬 발신 IP가 data.krx.co.kr에 "LOGOUT"(HTTP 400)으로 막혀 검증 불가였다.
기존 market-flows.yml(시장 전체 집계)은 Actions에서 이미 성공 중이므로,
같은 실행 환경에서 종목별(개별 티커) 함수만 별도로 확인한다.

이 스크립트는 정찰 전용이다 — data/ · docs/data/ 어디에도 쓰지 않는다.
전부 로그 출력(Actions 로그에서 사람이 읽는다).

확인 항목:
  1. 종목별 투자자매매(get_market_trading_value_by_investor / _volume_)가
     실제 값을 반환하는가 — KIS 프로브(2026-08-14, 005930)와 같은 날짜·종목으로
     교차검증 가능한 값을 남긴다.
  2. 2016년 근방까지 과거 조회가 실제로 되는가(anchor 4개, 각 소구간).
  3. 연속 호출 시 체감 지연·에러 패턴(엄밀한 한도 측정 아님, 감만 잡는다).
"""
import sys
import time
from datetime import datetime

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

TICKER_A = "005930"  # 삼성전자 — KIS 프로브와 동일 종목으로 교차검증
TICKER_B = "000660"  # SK하이닉스

# KIS 프로브(scripts/probe-supply-demand.py, 2026-08-17 실행)가 확보한 값과
# 직접 비교하려고 같은 날짜 구간을 쓴다.
OVERLAP_FROM, OVERLAP_TO = "20260810", "20260814"
KIS_REFERENCE = {
    "005930": {"date": "20260814", "frgn_ntby_qty": 4913433,
               "orgn_ntby_qty": -1830920, "prsn_ntby_qty": -3049225},
}

ANCHORS = ["20160104", "20180102", "20200102", "20230102"]


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
            print(f"[EMPTY] {label} ({elapsed}s) — 응답은 왔지만 행이 없음")
            return None
        print(f"[OK] {label} ({elapsed}s) — {len(df)}행, 컬럼: {list(df.columns)}")
        return df
    except Exception as e:  # noqa: BLE001
        elapsed = round(time.time() - t0, 2)
        print(f"[FAIL] {label} ({elapsed}s) — {type(e).__name__}: {e}")
        return None


def main():
    from pykrx import stock

    hr("1. 최근 구간 — KIS 프로브와 동일 종목·날짜로 교차검증용")
    df_a = run(f"value_by_investor {TICKER_A} {OVERLAP_FROM}~{OVERLAP_TO}",
               lambda: stock.get_market_trading_value_by_investor(OVERLAP_FROM, OVERLAP_TO, TICKER_A))
    if df_a is not None:
        print("\n원본 DataFrame (금액, 원):")
        print(df_a.to_string())

    df_a_vol = run(f"volume_by_investor {TICKER_A} {OVERLAP_FROM}~{OVERLAP_TO}",
                   lambda: stock.get_market_trading_volume_by_investor(OVERLAP_FROM, OVERLAP_TO, TICKER_A))
    if df_a_vol is not None:
        print("\n원본 DataFrame (수량, 주):")
        print(df_a_vol.to_string())
        ref = KIS_REFERENCE["005930"]
        print(f"\nKIS 참고값(2026-08-14 005930): 외국인순매수 {ref['frgn_ntby_qty']:,}주 · "
              f"기관 {ref['orgn_ntby_qty']:,}주 · 개인 {ref['prsn_ntby_qty']:,}주")
        print("위 KRX volume DataFrame에서 같은 날짜 행과 부호·크기가 맞는지 사람이 대조한다"
              "(투자자구분 라벨 체계가 달라 자동 매칭은 안 함).")

    run(f"value_by_investor {TICKER_B} {OVERLAP_FROM}~{OVERLAP_TO}",
        lambda: stock.get_market_trading_value_by_investor(OVERLAP_FROM, OVERLAP_TO, TICKER_B))

    hr("2. 과거 구간 — 2016~2023 anchor 4개 (005930)")
    for anchor in ANCHORS:
        end = anchor[:4] + anchor[4:6] + f"{int(anchor[6:8]) + 5:02d}"
        df = run(f"anchor {anchor}~{end}",
                 lambda a=anchor, e=end: stock.get_market_trading_value_by_investor(a, e, TICKER_A))
        if df is not None:
            print(df.to_string())

    hr("3. 연속 호출 체감 — 단일일 조회 10회 (005930)")
    days = ["20260803", "20260804", "20260805", "20260806", "20260807",
            "20260810", "20260811", "20260812", "20260813", "20260814"]
    fail_count = 0
    for d in days:
        df = run(f"single-day {d}", lambda dd=d: stock.get_market_trading_value_by_investor(dd, dd, TICKER_A))
        if df is None:
            fail_count += 1
    print(f"\n10회 중 실패 {fail_count}건")

    hr("완료")
    print(f"probedAt(UTC) = {datetime.utcnow().isoformat()}Z")


if __name__ == "__main__":
    main()
