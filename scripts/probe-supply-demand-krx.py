"""probe-supply-demand-krx.py — A4 계약 확정 전 3차(최종) 검증 라운드, Actions 전용.

1·2차 라운드(2026-08-17)에서 이미 확정한 것은 다시 안 한다: get_market_trading_value_by_date
/_volume_by_date가 정답 함수라는 것, 005930/2026-08-14 1건에서 KIS↔KRX 매핑이 정확히
일치한다는 것, 매수-매도=순매수 항등식이 성립한다는 것, 즉시 재조회는 동일하다는 것,
30콜(3종목×10일) 표본에서 실패 0건이라는 것 — 이 로그가 원본이다.

이번엔 세 가지만 잰다:
  A. 다른 종목·날짜 표본(3종목×3일=9건)에서 KIS↔KRX 매핑이 그대로 성립하는가.
     KIS 쪽 값은 scripts/probe-supply-demand.py 로 로컬에서 미리 받아 KIS_SAMPLES에 박아뒀다
     (이 스크립트는 KIS 키가 없는 Actions 환경에서 돌므로 KIS를 직접 호출하지 않는다).
  B. 즉시 재조회 재현성 표본을 넓힌다(종목·날짜 다양화). ★ 날짜를 걸친 재현성(오늘 값이
     며칠 뒤에도 같은가, T1급 검증)은 이번에도 하지 않는다 — TBD로 명시한다.
  C. 실제 백필 호출 설계에 필요한 두 가지: (1) 한 번의 호출로 몇 년치를 받아올 수 있는가
     (2016~현재 단일 호출, 내부적으로 쪼개지는지 소요시간으로 관찰) (2) 182종목 규모를
     가정한 소규모 표본(실제 유니버스에서 무작위 20종목)의 처리시간·실패율·차단 여부.

정찰 전용 — data/ · docs/data/ · config/policies/ 어디에도 쓰지 않는다. A4 정책·
production 코드는 무변경.
"""
import sys
import time
from datetime import datetime, timedelta

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

# scripts/probe-supply-demand.py(로컬, 2026-08-17)로 미리 받아둔 KIS 값.
# key=(ticker, YYYYMMDD) → 개인/외국인/기관 순매수 수량(qty).
KIS_SAMPLES = {
    ("005930", "20260703"): {"prsn": -3029168, "frgn": -1365575, "orgn": 4369649},
    ("005930", "20260806"): {"prsn": 4225347, "frgn": -3134136, "orgn": -1220335},
    ("005930", "20260814"): {"prsn": -3049225, "frgn": 4913433, "orgn": -1830920},
    ("000660", "20260703"): {"prsn": -344055, "frgn": -745377, "orgn": 1071876},
    ("000660", "20260806"): {"prsn": 1337421, "frgn": -1101883, "orgn": -275040},
    ("000660", "20260814"): {"prsn": -391964, "frgn": 747508, "orgn": -334859},
    ("035420", "20260703"): {"prsn": 153675, "frgn": -54729, "orgn": -98787},
    ("035420", "20260806"): {"prsn": -114468, "frgn": 47085, "orgn": 77134},
    ("035420", "20260814"): {"prsn": -77051, "frgn": 32305, "orgn": 43561},
}

INSTITUTION_COLS = ["금융투자", "보험", "투신", "사모", "은행", "기타금융", "연기금"]


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

    def vol_by_date(day, ticker):
        return stock.get_market_trading_volume_by_date(day, day, ticker, on="순매수", detail=True)

    hr("A. KIS↔KRX 매핑 재검증 — 3종목×3일=9건")
    match, mismatch, missing = 0, 0, 0
    for (ticker, day), kis in KIS_SAMPLES.items():
        df, _ = run(f"{ticker} {day}", lambda t=ticker, d=day: vol_by_date(d, t))
        if df is None:
            missing += 1
            continue
        row = df.iloc[0]
        krx_prsn = int(row["개인"])
        krx_frgn = int(row["외국인"]) + int(row["기타외국인"])
        krx_orgn = sum(int(row[c]) for c in INSTITUTION_COLS)
        ok_prsn = krx_prsn == kis["prsn"]
        ok_frgn = krx_frgn == kis["frgn"]
        ok_orgn = krx_orgn == kis["orgn"]
        if ok_prsn and ok_frgn and ok_orgn:
            match += 1
            print(f"    MATCH  개인 {krx_prsn:,} · 외국인 {krx_frgn:,} · 기관 {krx_orgn:,}")
        else:
            mismatch += 1
            print(f"    MISMATCH 개인 KIS={kis['prsn']:,} KRX={krx_prsn:,} ({'OK' if ok_prsn else 'DIFF'}) · "
                  f"외국인 KIS={kis['frgn']:,} KRX={krx_frgn:,} ({'OK' if ok_frgn else 'DIFF'}) · "
                  f"기관 KIS={kis['orgn']:,} KRX={krx_orgn:,} ({'OK' if ok_orgn else 'DIFF'})")
    print(f"\n9건 중 일치 {match} · 불일치 {mismatch} · 조회불가 {missing}")

    hr("B. 즉시 재조회 재현성 — 종목·날짜 다양화 (4건, 3초 간격 재조회)")
    print("★ TBD 명시: 이건 '지금 두 번 물으면 같은가'만 잰다. '오늘 값이 며칠 뒤에도")
    print("  같은가'(날짜를 걸친 재현성, T1급 검증)는 이번 라운드도 하지 않았다 — 여전히 TBD.\n")
    for ticker, day in [("005930", "20260814"), ("000660", "20260703"),
                        ("035420", "20260806"), ("005930", "20230102")]:
        df1, _ = run(f"1차 {ticker} {day}", lambda t=ticker, d=day: vol_by_date(d, t))
        time.sleep(3)
        df2, _ = run(f"2차 {ticker} {day} (3초 후)", lambda t=ticker, d=day: vol_by_date(d, t))
        if df1 is None or df2 is None:
            print(f"  {ticker} {day}: 데이터 부족")
            continue
        r1, r2 = df1.iloc[0], df2.iloc[0]
        diffs = [(c, int(r1[c]), int(r2[c])) for c in df1.columns if int(r1[c]) != int(r2[c])]
        print(f"  {ticker} {day}: " + ("완전 동일" if not diffs else f"차이 발견 {diffs}"))

    hr("C-1. 단일 호출로 몇 년치를 받는가 — 005930, 2016-01-04~오늘")
    today = datetime.now().strftime("%Y%m%d")
    df_long, elapsed_long = run(f"005930 20160104~{today} (단일 호출)",
                                lambda: stock.get_market_trading_value_by_date("20160104", today, "005930", on="순매수"))
    if df_long is not None:
        years = sorted({str(idx)[:4] for idx in df_long.index})
        print(f"  행 수: {len(df_long)} · 걸린 시간: {elapsed_long}s · 포함된 연도: {years}")
        print(f"  참고: 2016-01-04~{today[:4]}-{today[4:6]}-{today[6:]}의 영업일이 대략 몇 개인지와")
        print(f"        비교해 이 호출이 전체 구간을 한 번에 주는지, 어딘가서 잘리는지 판단한다.")
    else:
        print("  단일 호출 실패 — 긴 구간은 별도 청크 분할이 필요하다는 뜻일 수 있음")

    hr("C-2. 182종목 규모 가정 — 실제 유니버스 무작위 20종목×1년 구간, 1콜씩")
    # data/backfill/universe/a1a/current.jsonl 에서 random.seed(20260817)로 뽑은 20종목
    # (재현 가능하도록 시드 고정, 이 정찰 세션에서 미리 뽑아 하드코딩)
    sample20 = ["002700", "003830", "005500", "007530", "018500", "020150", "024800",
                "024890", "031820", "038870", "072950", "097230", "219750", "246250",
                "263770", "274400", "304100", "317400", "359090", "383310"]
    one_year_from = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
    one_year_to = datetime.now().strftime("%Y%m%d")
    elapsed_list, fail_count, row_counts = [], 0, []
    for tk in sample20:
        df, elapsed = run(f"{tk} {one_year_from}~{one_year_to}",
                          lambda t=tk: stock.get_market_trading_value_by_date(one_year_from, one_year_to, t, on="순매수"))
        elapsed_list.append(elapsed)
        if df is None:
            fail_count += 1
        else:
            row_counts.append(len(df))
    total = len(elapsed_list)
    print(f"\n총 {total}종목(1년 구간, 1콜/종목) · 실패 {fail_count}건 ({fail_count/total*100:.1f}%) · "
          f"평균 {sum(elapsed_list)/total:.2f}s · 최소 {min(elapsed_list):.2f}s · 최대 {max(elapsed_list):.2f}s")
    if row_counts:
        print(f"반환 행수: 평균 {sum(row_counts)/len(row_counts):.0f} · "
              f"최소 {min(row_counts)} · 최대 {max(row_counts)} (1년 영업일수와 비교)")

    hr("완료")
    print(f"probedAt(UTC) = {datetime.utcnow().isoformat()}Z")


if __name__ == "__main__":
    main()
