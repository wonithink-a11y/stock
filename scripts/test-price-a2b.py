#!/usr/bin/env python3
"""A2b 회귀 테스트 — 합성 픽스처로 A2b 고유 분기를 밟는다.
  python scripts/test-price-a2b.py

네트워크도 수집 산출물도 필요 없다. 여기서 지키는 것은 'A2a를 그대로 복사하면
안 되는 곳' 넷이며, 각각이 회귀하면 조용히 틀린 데이터가 통과한다.

  1. 기대 거래일을 상장기간으로 한정 — 회귀하면 누락률이 90%대로 튄다(FAIL로 드러남)
  2. 빈 응답은 서킷을 걸지 않는다 — 회귀하면 정상 데이터 수집이 중간에 멈춘다
  3. exitAt은 마지막 거래일에서만 온다 — 회귀하면 폐지일이 DART 수정일로 바뀌고,
     그것은 조용히 무너진다: 값이 있고 형식도 맞아서 하류가 그대로 쓴다
  4. 커버리지 분모는 분석 구간 — 회귀하면 51.6%가 커버리지로 굳는다

3번이 이 파일의 핵심이다. A5의 EP가 '구간 밖'을 판정할 때 쓰는 값이라 틀려도
점수는 정상으로 보인다(A3의 PIT와 같은 성질이다, 교훈49).
"""
import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stdout

# 진단 메시지에 em-dash가 섞여 있어 Windows 콘솔(cp949)에서 죽는다. CI(ubuntu)는
# utf-8이라 무관하지만, 로컬에서 수집 전에 돌리는 것이 이 테스트의 용도다(교훈49).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "a2b", os.path.join(ROOT, "scripts", "build-price-a2b.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

POL = json.load(open(os.path.join(ROOT, "config/policies/price.v1.json"), encoding="utf-8"))

# 40 '거래일'. analysisFrom을 중간에 둬 구간 안/밖을 둘 다 만든다.
DAYS = ([f"2020-01-{d:02d}" for d in range(1, 32)]
        + [f"2020-02-{d:02d}" for d in range(1, 10)])
ANALYSIS_FROM = DAYS[20]
CAL = {"tradingDays": DAYS, "analysisFrom": ANALYSIS_FROM}

# 규모 게이트(minTickersWithData 600 · minTickersInAnalysisWindow 550)가 실제
# 임계로 동작하도록 픽스처를 그 위에 둔다. 임계 아래로 두면 모든 케이스가
# 규모 FAIL을 달고 나와 다른 검사의 판정을 읽을 수 없다.
CLEAN_N = 620

passed = failed = 0


def row(tk, i, close=1000, vol=1000):
    return {"ticker": tk, "date": DAYS[i], "open": close, "high": close,
            "low": close, "close": close, "volume": vol}


def series(tk, lo, hi, close=1000, vol=1000):
    """DAYS[lo:hi] 구간만 거래한 종목."""
    return [row(tk, i, close, vol) for i in range(lo, hi)]


def cand_of(*tickers, dart="20240115"):
    return [{"corp": f"{i:08d}", "ticker": t, "corpName": f"폐지법인{t}",
             "exitReason": "PENDING", "exitAt": None,
             "dartModifyDate": dart, "source": "A0.7-A1a-diff"}
            for i, t in enumerate(tickers, 1)]


def clean_fill():
    """DAYS[0:30]을 거래하고 폐지된 종목 620개. 마지막 거래일이 analysisFrom 이후라
    분석 구간 안이다."""
    rows, tickers = [], []
    for n in range(CLEAN_N):
        tk = f"9{n:05d}"
        rows += series(tk, 0, 30)
        tickers.append(tk)
    return rows, tickers


def run(rows, cand, pol=None, empty_count=0):
    """validate()를 돌리고 (diag, kept, excluded, exits, fails, warns)를 돌려준다."""
    m.fails.clear()
    m.warns.clear()
    diag = {"emptyCount": empty_count}
    with redirect_stdout(io.StringIO()):
        kept, excluded, exits = m.validate(list(rows), cand, CAL, pol or POL, diag)
    return diag, kept, excluded, exits, list(m.fails), list(m.warns)


def case(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  OK    {name}" + (f"  ({detail})" if detail else ""))
    else:
        failed += 1
        print(f"  FAIL  {name}\n        {detail}")


print("[A2b — A2a와 다른 넷]")
BASE, BASE_TK = clean_fill()
BASE_CAND = cand_of(*BASE_TK)

# ── 차이 1. 기대 거래일을 상장기간으로 한정한다 ────────────────────
diag, kept, exc, exits, fails, warns = run(BASE, BASE_CAND)
case("정상 폐지 종목은 게이트를 통과한다", not fails, f"fails={fails}")
case("누락률이 상장기간 기준으로 0이다",
     diag["missingRate"] == 0,
     f"missingRate={diag['missingRate']} (폐지 후 구간을 기대에 넣으면 0.25가 된다)")
case("기대 거래일이 폐지 이후를 포함하지 않는다",
     diag["expectedRows"] == CLEAN_N * 30,
     f"expected={diag['expectedRows']} / 캘린더 끝 기준이면 {CLEAN_N * 40}")
case("기대 모델 근거가 진단에 남는다",
     diag["expectedRowsBasis"] == "listingPeriod", diag.get("expectedRowsBasis"))

# 회귀 확인 — A2a 기준(캘린더 끝까지)으로 재면 누락률이 25%다.
a2a_style = sum(1 for d in DAYS if d >= DAYS[0]) * CLEAN_N
case("A2a 기준으로 재면 누락률이 실제로 튄다(한정이 필요한 이유)",
     abs(1 - (CLEAN_N * 30) / a2a_style - 0.25) < 1e-9,
     f"A2a 기준 누락률 {1 - (CLEAN_N * 30) / a2a_style:.2f}")

# ── 차이 3. exitAt은 마지막 거래일에서만 온다 ──────────────────────
case("exitAt이 마지막 거래일이다",
     all(e["exitAtConfirmed"] == DAYS[29] for e in exits),
     f"sample={exits[0]['exitAtConfirmed']}")
case("exitAt이 dartModifyDate가 아니다",
     all(e["exitAtConfirmed"] != "2024-01-15" for e in exits),
     "dartModifyDate=20240115")
case("exitAt 출처가 산출물에 명시된다",
     all(e["exitAtSource"] == "lastTradedDate" for e in exits))
case("exitAt 레코드 수 = 확보 종목 수",
     len(exits) == len({x["ticker"] for x in kept}),
     f"{len(exits)} vs {len({x['ticker'] for x in kept})}")
case("dartModifyDate 비교 분포가 진단에 남는다",
     diag["exitAtVsDartModifyDate"]["comparable"] == len(exits)
     and diag["exitAtVsDartModifyDate"]["same"] == 0,
     str({k: v for k, v in diag["exitAtVsDartModifyDate"].items() if k != "note"}))
case("폐지일이 아니라 마지막 거래일이라는 스탬프가 있다",
     diag["exitAtIsLastTradedNotEffectiveDate"] is True)

# 핵심 회귀 — 소스를 dartModifyDate로 바꾸면 게이트가 막아야 한다.
# 이 경로가 막히지 않으면 A5의 EP가 '폐지 5년 뒤 수정일'을 폐지일로 읽는다.
wrong = json.loads(json.dumps(POL))
wrong["a2b"]["exitAt"]["source"] = "dartModifyDate"
_, _, _, wexits, wfails, _ = run(BASE, BASE_CAND, pol=wrong)
case("exitAt 소스를 dartModifyDate로 바꾸면 FAIL이다",
     any("exitAt 소스" in f for f in wfails)
     and any("거래일이 아닌" in f for f in wfails),
     f"fails={wfails}")

# 소스가 아예 모르는 값이면 값이 비고, 누락 검사가 잡는다.
unknown = json.loads(json.dumps(POL))
unknown["a2b"]["exitAt"]["source"] = "someNewIdea"
_, _, _, _, ufails, _ = run(BASE, BASE_CAND, pol=unknown)
case("알 수 없는 exitAt 소스도 FAIL이다",
     any("exitAt 소스" in f for f in ufails) and any("누락" in f for f in ufails),
     f"fails={ufails}")

# ── 차이 4. 커버리지 분모는 분석 구간이다 ──────────────────────────
out_rows = series("000001", 0, 6)           # 마지막 거래일 DAYS[5] < analysisFrom
diag2, kept2, _, _, fails2, _ = run(BASE + out_rows, BASE_CAND + cand_of("000001"))
case("구간 밖 폐지는 확보 종목에는 들어간다",
     diag2["tickersWithData"] == CLEAN_N + 1, str(diag2["tickersWithData"]))
case("구간 밖 폐지는 분석 구간 분모에서 빠진다",
     diag2["tickersInAnalysisWindow"] == CLEAN_N
     and diag2["tickersOutOfAnalysisWindow"] == 1,
     f"in={diag2['tickersInAnalysisWindow']} out={diag2['tickersOutOfAnalysisWindow']}")
case("후보 전체 대비 비율은 게이트가 아니라 관측으로만 남는다",
     "rawCandidateCoverageRate" in diag2 and diag2["rawCandidateCoverageRate"] <= 1.0,
     f"rawCandidateCoverageRate={diag2['rawCandidateCoverageRate']}")
case("확보 실패=구간 밖이라는 가정이 스탬프로 남는다",
     diag2["coverageAssumesFailuresOutOfWindow"] is True)

# 규모 게이트가 실제로 막는가 — 정찰 전수 실측(631·572)이 근거인 유일한 FAIL 둘
small = BASE[:30 * 500]                      # 500종목만
small_tk = sorted({r["ticker"] for r in small})
_, _, _, _, sfails, _ = run(small, cand_of(*small_tk))
case("확보 종목이 임계 미만이면 FAIL",
     any("데이터 확보 종목" in f for f in sfails), f"fails={sfails}")
case("분석 구간 내 폐지가 임계 미만이면 FAIL",
     any("분석 구간" in f for f in sfails), f"fails={sfails}")

# ── 빈 응답률·A1b 오분류 신호는 WARN이다 ───────────────────────────
# 정찰 실측 구성을 그대로 만든다: 후보 = 확보 620 + 전 구간 0행 591.
# 빈 응답의 분모는 확보 종목이 아니라 후보 전체다.
EMPTY_TK = [f"8{n:05d}" for n in range(591)]
CAND_WITH_EMPTY = BASE_CAND + cand_of(*EMPTY_TK)
dE, _, _, _, _, w = run(BASE, CAND_WITH_EMPTY, empty_count=len(EMPTY_TK))
case("빈 응답 48%는 WARN이 아니다(구간 밖 폐지는 정상)",
     not any("빈 응답률" in x for x in w),
     f"emptyRate={dE['emptyRate']} · rawCandidateCoverageRate={dE['rawCandidateCoverageRate']}")
case("정찰이 커버리지로 읽지 말라고 한 51.6%가 게이트가 아니라 관측에 남는다",
     abs(dE["rawCandidateCoverageRate"] - 0.512) < 0.01,
     str(dE["rawCandidateCoverageRate"]))
_, _, _, _, _, w2 = run(BASE, CAND_WITH_EMPTY, empty_count=1000)
case("빈 응답률이 상한을 넘으면 WARN",
     any("빈 응답률" in x for x in w2), f"warns={w2}")

still = series("000002", 0, 40)               # 캘린더 끝까지 거래 = 폐지 아닐 수 있다
d3, _, _, _, f3, w3 = run(BASE + still, BASE_CAND + cand_of("000002"))
case("캘린더 끝까지 거래한 종목은 WARN으로 표시된다(A1b 오분류 신호)",
     "000002" in d3["stillTradingSuspects"] and any("거래 중일 수 있다" in x for x in w3),
     f"suspects={d3['stillTradingSuspects'][:3]}")
case("그 신호는 FAIL이 아니다(폐지 직전 종목이 정상적으로 걸린다)",
     not f3, f"fails={f3}")

# ── 차이 2. 빈 응답과 예외를 가른다 (서킷 브레이커의 전제) ──────────
class _StubDF:
    def __init__(self, empty):
        self.empty = empty


class _StubStock:
    """pykrx 대역. 빈 DataFrame과 예외를 각각 돌려준다."""
    def __init__(self, mode):
        self.mode = mode
        self.calls = 0

    def get_market_ohlcv_by_date(self, frm, to, ticker, adjusted=True):
        self.calls += 1
        if self.mode == "empty":
            return _StubDF(True)
        raise ConnectionError("차단")


s = _StubStock("empty")
df, kind, err = m.fetch_one(s, "000001", "20200101", "20200209", POL)
case("빈 응답은 kind='empty'로 구분된다", kind == "empty" and df is None, f"kind={kind}")
s2 = _StubStock("raise")
df2, kind2, err2 = m.fetch_one(s2, "000001", "20200101", "20200209", POL)
case("예외는 kind='exception'으로 구분된다",
     kind2 == "exception" and "ConnectionError" in (err2 or ""), f"kind={kind2} err={err2}")
case("문자열이 아니라 종류로 가른다(서킷이 조용히 반대로 돌지 않는다)",
     kind != kind2)
case("서킷 브레이커가 예외만 센다",
     POL["a2b"]["circuitBreaker"]["ignoreConsecutiveEmpty"] is True
     and POL["a2b"]["circuitBreaker"]["consecutiveExceptions"] > 0)

# ── 공유 계약 — 품질 판별은 A2a와 같아야 한다 ──────────────────────
perm = series("000003", 0, 30)
for i in range(15, 30):
    perm[i - 0] = row("000003", i, 253)
perm = [x for x in perm if x["date"] in {d for d in DAYS[0:30]}]
d4, kept4, exc4, _, f4, _ = run(BASE + perm, BASE_CAND + cand_of("000003"))
case("영구 계단 변화는 A2a와 같은 사유로 제외된다",
     {e["ticker"]: e["reason"] for e in exc4} == {"000003": "UNADJUSTED_CORPORATE_ACTION"},
     str({e["ticker"]: e["reason"] for e in exc4}))
case("제외 종목은 exitAt 산출에서도 빠진다",
     "000003" not in {x["ticker"] for x in kept4},
     "제외 종목이 exitAt을 받으면 없는 폐지일이 생긴다")

# 영숫자 티커는 정상이다 — 숫자 6자리로 좁히면 신규상장 코드를 위반으로 잡는다
alnum = series("0218L0", 0, 30)
d5, _, _, e5, f5, _ = run(BASE + alnum, BASE_CAND + cand_of("0218L0"))
case("영숫자 티커가 계약 위반으로 잡히지 않는다",
     d5["tickerContractViolations"] == 0 and not f5, f"fails={f5}")
case("영숫자 티커도 exitAt을 받는다",
     any(x["ticker"] == "0218L0" for x in e5))

print(f"\n{'✅' if not failed else '❌'} A2b {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
