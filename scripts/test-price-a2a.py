#!/usr/bin/env python3
"""A2a 품질 판별 회귀 테스트 — 합성 픽스처로 분기를 전부 밟는다.
  python scripts/test-price-a2a.py

네트워크도 수집 산출물도 필요 없다. 여기서 지키려는 것은 2026-08-05 첫 수집이
드러낸 세 가지 사실이며, 각각이 회귀하면 조용히 데이터가 오염된다.

  1. 거래량 0인 행의 종가는 체결가가 아니다 (거래정지 중 기준가 표기)
  2. 캘린더 간격 > 1인 쌍은 연속 변동이 아니다 (장기 정지 후 재개)
  3. KIND listedAt은 '현재 시장의 상장일'이라 이전상장 종목의 기대행을 과소 계산한다

픽스처 숫자는 실측에서 가져왔다 — 하이로닉 77,100 → 19,529(1/3.95배, 영구),
티이엠씨 26,500 → 51,600 → 25,100(일시), 아진엑스텍 거래량 0 전이.
"""
import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "a2a", os.path.join(ROOT, "scripts", "build-price-a2a.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

POL = json.load(open(os.path.join(ROOT, "config/policies/price.v1.json"), encoding="utf-8"))

DAYS = [f"2020-01-{d:02d}" for d in range(1, 21)]     # 20 '거래일'
CAL = {"tradingDays": DAYS}

passed = failed = 0


# 유니버스 규모 검사(minTickersWithData 2,400)는 합성 픽스처에서 항상 실패한다.
# 이 테스트의 대상이 아니므로 게이트 판정에서만 제외한다 — 검사 자체를 끄지는 않는다.
SCALE_CHECK = "데이터 확보 종목"


def case(name, rows, uni, expect_reasons, expect_fail_substr=None, expect_pass=True):
    """validate()를 돌리고 품질 제외 사유와 게이트 결과를 확인한다."""
    global passed, failed
    m.fails.clear()
    m.warns.clear()
    diag = {"actualDataFrom": min(r["date"] for r in rows)}
    with redirect_stdout(io.StringIO()):
        kept, excluded = m.validate(list(rows), uni, CAL, POL, diag)
    got = {e["ticker"]: e["reason"] for e in excluded}
    relevant = [f for f in m.fails if SCALE_CHECK not in f]
    ok = got == expect_reasons
    if ok and expect_fail_substr:
        ok = any(expect_fail_substr in f for f in relevant)
    if ok and expect_pass is not None:
        ok = (not relevant) == expect_pass
    if ok:
        passed += 1
        print(f"  OK    {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}\n        기대 제외 {expect_reasons} / 실제 {got}"
              f"\n        fails={relevant}")
    return diag, kept, excluded


# 깨끗한 종목이 함께 있어야 비율 기반 검사가 실제처럼 동작한다.
# 너무 적으면 (1) 위반 1종목만으로 제외율이 100%가 되고 (2) 거래정지 1종목이
# 전체 누락률을 지배한다 — 실제로는 2,579종목 중 하나다.
CLEAN_N = 60


def clean_fill():
    rows, tickers = [], []
    for n in range(CLEAN_N):
        tk = f"9{n:05d}"
        rows += flat(tk)
        tickers.append(tk)
    return rows, tickers


def row(tk, i, close, vol=1000):
    return {"ticker": tk, "date": DAYS[i], "open": close, "high": close,
            "low": close, "close": close, "volume": vol}


def flat(tk, n=20, close=1000, vol=1000):
    return [row(tk, i, close, vol) for i in range(n)]


def uni_of(*tickers, listed="2020-01-01"):
    return [{"ticker": t, "name": f"종목{t}", "market": "KOSDAQ",
             "listedAt": listed} for t in tickers]


print("[A2a 품질 판별]")
BASE, BASE_TK = clean_fill()

# 1. 정상 종목만 있으면 제외 0건, 게이트 통과
case("정상 시계열은 제외되지 않는다", BASE, uni_of(*BASE_TK), {})

# 2. 영구 계단 변화 = 수정주가 미적용 (실측 하이로닉 1/3.95배)
perm = flat("000002")
for i in range(10, 20):
    perm[i] = row("000002", i, 253)          # 1000 → 253 (-74.7%) 이후 유지
case("영구 계단 변화 → UNADJUSTED_CORPORATE_ACTION",
     BASE + perm, uni_of(*BASE_TK, "000002"),
     {"000002": "UNADJUSTED_CORPORATE_ACTION"})

# 3. 일시 스파이크 = 1일 오표기 (실측 티이엠씨 26,500 → 51,600 → 25,100)
spike = flat("000003")
spike[10] = row("000003", 10, 2000)          # 하루만 2배, 이후 복귀
case("1일 스파이크 → TRANSIENT_PRICE_SPIKE",
     BASE + spike, uni_of(*BASE_TK, "000003"),
     {"000003": "TRANSIENT_PRICE_SPIKE"})

# 4. 거래량 0 전이는 체결가 비교가 아니다 — 검사에서 제외된다
zero = flat("000004")
zero[10] = row("000004", 10, 9000, vol=0)    # 거래정지 중 기준가 표기
zero[11] = row("000004", 11, 1000)
d, _, _ = case("거래량 0 전이는 위반이 아니다", BASE + zero, uni_of(*BASE_TK, "000004"), {})
assert d["zeroVolumeTransitions"] >= 2, "거래량 0 전이가 진단에 기록되지 않았다"
print(f"        zeroVolumeTransitions={d['zeroVolumeTransitions']} (침묵하지 않고 기록됨)")

# 5. 캘린더 간격 > 1(장기 정지 후 재개)도 연속 변동이 아니다
gap = [row("000005", i, 1000) for i in range(0, 5)]
gap += [row("000005", i, 5000) for i in range(15, 20)]   # 10거래일 공백 후 5배
d, _, _ = case("장기 공백 전이는 위반이 아니다", BASE + gap, uni_of(*BASE_TK, "000005"), {})
assert d["suspendedGapTransitions"] >= 1, "장기 공백 전이가 진단에 기록되지 않았다"
print(f"        suspendedGapTransitions={d['suspendedGapTransitions']} (기록됨)")

# 6. 기대 모델 — listedAt이 데이터보다 뒤여도(이전상장) 누락률이 음수가 되지 않는다
uni6 = uni_of(*BASE_TK) + [{"ticker": "000006", "name": "이전상장", "market": "KOSPI",
                            "listedAt": "2020-01-15"}]
d, kept, _ = case("이전상장(listedAt > 실제 최초 거래일)에서 누락률이 음수가 아니다",
                  BASE + flat("000006"), uni6, {})
assert d["missingRate"] >= 0, f"누락률이 음수다: {d['missingRate']}"
assert d["rowsBeforeListedAt"] > 0, "상장일 이전 행이 관측되지 않았다"
print(f"        missingRate={d['missingRate']} · rowsBeforeListedAt={d['rowsBeforeListedAt']}")

# 7. 제외 후 남은 행에서 제외 종목이 실제로 빠졌는지
_, kept, _ = case("제외 종목의 행은 산출물에서 빠진다",
                  BASE + perm, uni_of(*BASE_TK, "000002"),
                  {"000002": "UNADJUSTED_CORPORATE_ACTION"})
assert "000002" not in {r["ticker"] for r in kept}, "제외 종목 행이 남아 있다"
print(f"        kept {len({r['ticker'] for r in kept})}종목 · 000002 제외됨")

# 8. 안전핀 — 제외율이 상한을 넘으면 게이트가 막는다
many = list(BASE)
for n in range(10):
    tk = f"0001{n:02d}"
    xs = flat(tk)
    for i in range(10, 20):
        xs[i] = row(tk, i, 253)
    many += xs
case("제외율 상한 초과는 FAIL (자동 제외가 게이트를 무력화하지 않는다)",
     many, uni_of(*BASE_TK, *[f"0001{n:02d}" for n in range(10)]),
     {f"0001{n:02d}": "UNADJUSTED_CORPORATE_ACTION" for n in range(10)},
     expect_fail_substr="품질 제외율", expect_pass=False)

# 9. 전이 관측치는 '전체' 기준이어야 한다.
#    find_violations는 잔여 위반 확인을 위해 제외 후 부분집합으로 한 번 더 호출된다.
#    그때 전체 기준 카운터가 덮이면, 제외 종목이 만난 거래정지 이력이 통째로 사라진다.
mix = list(BASE)
bad = flat("000300")
bad[5] = row("000300", 5, 1000, vol=0)       # 제외될 종목에 거래량 0 전이를 심는다
bad[6] = row("000300", 6, 1000, vol=0)
for i in range(10, 20):
    bad[i] = row("000300", i, 253)           # 영구 계단 → 제외 대상
mix += bad
d, _, _ = case("전이 관측치는 제외 후 부분집합에 덮이지 않는다",
               mix, uni_of(*BASE_TK, "000300"),
               {"000300": "UNADJUSTED_CORPORATE_ACTION"})
assert d["zeroVolumeTransitions"] > d["keptZeroVolumeTransitions"], (
    f"전체 {d['zeroVolumeTransitions']} vs 제외후 {d['keptZeroVolumeTransitions']} — "
    "제외 종목의 거래정지 전이가 관측치에서 사라졌다")
print(f"        전체 {d['zeroVolumeTransitions']} / 제외후 {d['keptZeroVolumeTransitions']} "
      "(둘 다 남는다)")

print(f"\n{'✅' if not failed else '❌'} A2a 품질 판별 {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
