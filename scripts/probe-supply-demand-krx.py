"""probe-supply-demand-krx.py — KRX(pykrx) 종목별 투자자매매 검증, Actions 전용.

A4 계약 확정 전 마지막 검증 라운드. 1차 프로브(2026-08-17)에서 이미 확정한 것은
다시 안 한다 — get_market_trading_value_by_date/_volume_by_date가 정답 함수라는 것,
KIS와 순매수 값이 카테고리 매핑 후 정확히 일치한다는 것, 2016~2023 anchor가 열린다는
것은 그 실행 로그가 원본이다. 이번 라운드는 네 가지만 잰다:

  A. 매수/매도(on="매수"/"매도") 필드가 실제 값을 반환하는가 — 순매수만 확인했었다.
  B. 순매수 = 매수 - 매도 가 실제 값에서 성립하는가(정수 연산이라 오차 0이어야 정상).
  C. 같은 날짜를 그 자리에서 재조회하면 값이 같은가(즉시 재현성) — 최근일 1개·
     오래된 확정일 1개를 각각 2회 조회해 대조한다. 이건 "지금 이 순간의 재현성"이지
     T1처럼 날짜를 걸친 재현성이 아니다 — 그 차이를 결과에 남긴다.
  D. 소규모 표본(3종목×10일=30콜)의 실패율·호출 간격 — 전체 백필 부하가 아니다.

정찰 전용 — data/ · docs/data/ · config/policies/ 어디에도 쓰지 않는다.
전부 로그 출력(Actions 로그에서 사람이 읽는다). A4 정책·production 코드는 무변경.
"""
import sys
import time
from datetime import datetime

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

TICKER_A = "005930"  # 삼성전자
TICKER_B = "000660"  # SK하이닉스
TICKER_C = "035420"  # NAVER — 표본 다양화용

RECENT_DAY = "20260814"    # 1차 프로브에서 KIS와 이미 교차검증된 날짜
OLD_DAY = "20230102"       # 오래돼 정정 가능성이 낮다고 볼 수 있는 날짜(가설)

DETAIL_COLS = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금",
               "기타법인", "개인", "외국인", "기타외국인", "전체"]


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
        print(f"[OK] {label} ({elapsed}s) — {len(df)}행")
        return df, elapsed
    except Exception as e:  # noqa: BLE001
        elapsed = round(time.time() - t0, 2)
        print(f"[FAIL] {label} ({elapsed}s) — {type(e).__name__}: {e}")
        return None, elapsed


def main():
    from pykrx import stock

    def by_date_value(day, on, ticker=TICKER_A):
        return stock.get_market_trading_value_by_date(day, day, ticker, on=on, detail=True)

    def by_date_volume(day, on, ticker=TICKER_A):
        return stock.get_market_trading_volume_by_date(day, day, ticker, on=on, detail=True)

    hr("A. 매수/매도 필드 확인 — 005930, " + RECENT_DAY)
    v_buy, _ = run("value on=매수", lambda: by_date_value(RECENT_DAY, "매수"))
    v_sell, _ = run("value on=매도", lambda: by_date_value(RECENT_DAY, "매도"))
    v_net, _ = run("value on=순매수", lambda: by_date_value(RECENT_DAY, "순매수"))
    vol_buy, _ = run("volume on=매수", lambda: by_date_volume(RECENT_DAY, "매수"))
    vol_sell, _ = run("volume on=매도", lambda: by_date_volume(RECENT_DAY, "매도"))
    vol_net, _ = run("volume on=순매수", lambda: by_date_volume(RECENT_DAY, "순매수"))

    for label, df in [("value(금액) 매수", v_buy), ("value(금액) 매도", v_sell),
                       ("value(금액) 순매수", v_net), ("volume(수량) 매수", vol_buy),
                       ("volume(수량) 매도", vol_sell), ("volume(수량) 순매수", vol_net)]:
        if df is not None:
            print(f"\n{label}:")
            print(df.to_string())

    hr("B. 순매수 = 매수 - 매도 검증")

    def check_identity(buy, sell, net, label):
        if buy is None or sell is None or net is None:
            print(f"{label}: 데이터 부족으로 검증 불가")
            return
        row_b, row_s, row_n = buy.iloc[0], sell.iloc[0], net.iloc[0]
        mismatches = []
        for col in buy.columns:
            if col not in sell.columns or col not in net.columns:
                continue
            expected = int(row_b[col]) - int(row_s[col])
            actual = int(row_n[col])
            if expected != actual:
                mismatches.append((col, expected, actual, expected - actual))
        if mismatches:
            print(f"{label}: 불일치 {len(mismatches)}건")
            for col, exp, act, diff in mismatches:
                print(f"    {col}: 매수-매도={exp:,} vs 순매수={act:,} (차이 {diff:,})")
        else:
            print(f"{label}: 전 카테고리({len(buy.columns)}개) 매수-매도=순매수 정확히 일치")

    check_identity(v_buy, v_sell, v_net, "금액(원)")
    check_identity(vol_buy, vol_sell, vol_net, "수량(주)")

    hr("C. 즉시 재조회 재현성 — 최근일·오래된 확정일 각 2회")

    def reproducibility_check(day, label):
        df1, e1 = run(f"{label} 1차조회 {day}", lambda: by_date_value(day, "순매수"))
        time.sleep(3)
        df2, e2 = run(f"{label} 2차조회 {day} (3초 후)", lambda: by_date_value(day, "순매수"))
        if df1 is None or df2 is None:
            print(f"{label}: 데이터 부족으로 재현성 비교 불가")
            return
        row1, row2 = df1.iloc[0], df2.iloc[0]
        diffs = [(c, int(row1[c]), int(row2[c])) for c in df1.columns
                 if c in df2.columns and int(row1[c]) != int(row2[c])]
        if diffs:
            print(f"{label}: 값이 바뀜 — {diffs}")
        else:
            print(f"{label}: 1차·2차 완전 동일 ({len(df1.columns)}개 컬럼)")

    reproducibility_check(RECENT_DAY, "최근일(" + RECENT_DAY + ")")
    reproducibility_check(OLD_DAY, "오래된 확정일(" + OLD_DAY + ")")

    hr("D. 소규모 표본 — 3종목×10일=30콜, 실패율·호출 간격")
    days = ["20260803", "20260804", "20260805", "20260806", "20260807",
            "20260810", "20260811", "20260812", "20260813", "20260814"]
    tickers = [TICKER_A, TICKER_B, TICKER_C]
    elapsed_list, fail_count = [], 0
    for tk in tickers:
        for d in days:
            df, elapsed = run(f"{tk} {d}", lambda t=tk, dd=d: by_date_value(dd, "순매수", ticker=t))
            elapsed_list.append(elapsed)
            if df is None:
                fail_count += 1
    total = len(elapsed_list)
    print(f"\n총 호출 {total}건 · 실패 {fail_count}건 ({fail_count/total*100:.1f}%) · "
          f"평균 {sum(elapsed_list)/total:.2f}s · 최소 {min(elapsed_list):.2f}s · "
          f"최대 {max(elapsed_list):.2f}s")

    hr("완료")
    print(f"probedAt(UTC) = {datetime.utcnow().isoformat()}Z")


if __name__ == "__main__":
    main()
