"""test-collect-minute-kis.py — Collector v1 인수 조건 (합성 픽스처, 네트워크 없음)

이 테스트는 KIS를 부르지 않는다. transport를 갈아끼워 응답을 만든다.
조용히 무너지는 축은 게이트를 두 겹으로 건다(교훈49) — 인수 조건과 이 회귀다.

사용:
    python scripts/test-collect-minute-kis.py
    python scripts/collect-minute-kis.py --selftest
"""

import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  " + str(detail)) if (detail and not cond) else ""))


# ---------------------------------------------------------------- 픽스처

def session_grid():
    """실제 정규장 격자. 09:00~15:19 + 15:30 = 381분.

    15:20~15:29는 종가 단일가라 캔들이 제도상 없다(T0 실측).
    픽스처가 이것을 반영하지 않으면 테스트가 현실과 다른 것을 검증한다.
    """
    g = ["%02d%02d00" % divmod(m, 60) for m in range(9 * 60, 15 * 60 + 20)]
    g.append("153000")
    return g


def candles(date, n=381, price=1000):
    """하루치 캔들. n이 381보다 작으면 뒤(늦은 시각)부터 채운다."""
    grid = session_grid()
    use = grid[-n:] if n < len(grid) else grid
    return [{
        "stck_bsop_date": date,
        "stck_cntg_hour": h,
        "stck_oprc": str(price), "stck_hgpr": str(price + 10),
        "stck_lwpr": str(price - 10), "stck_prpr": str(price + 5),
        "cntg_vol": str(100 + i),
    } for i, h in enumerate(use)]


class FakeTransport:
    """커서 페이지네이션을 흉내낸다. 스크립트가 진짜로 커서를 돌리는지 본다."""

    def __init__(self, data, page=120, fail_plan=None):
        self.data = data              # {(ticker, yyyymmdd): [candle...]}
        self.page = page
        self.fail_plan = list(fail_plan or [])   # 앞에서부터 소비하는 실패 목록
        self.calls = []

    def fetch(self, ticker, sent_date, hour, pol):
        self.calls.append((ticker, sent_date, hour))
        if self.fail_plan:
            f = self.fail_plan.pop(0)
            if f is not None:
                return f

        rows = self.data.get((ticker, sent_date))
        if rows is None:
            sub = self.data.get((ticker, "__substitute__"))
            if sub is not None:
                return {"http": 200, "body": {"rt_cd": "0", "msg_cd": "MCA00000",
                                              "output1": {}, "output2": sub}}
            return {"http": 200, "body": {"rt_cd": "0", "msg_cd": "MCA00000",
                                          "output1": {}, "output2": []}}

        older = [r for r in rows if r["stck_cntg_hour"] <= hour]
        older.sort(key=lambda r: r["stck_cntg_hour"], reverse=True)
        return {"http": 200, "body": {"rt_cd": "0", "msg_cd": "MCA00000",
                                      "output1": {},
                                      "output2": older[:self.page]}}


def base_ctx():
    return {"tradingDays": {"2026-08-03", "2026-08-04"},
            "listedAt": {"111111": "2026-01-01", "222222": "2027-01-01"},
            "delistedAt": {}}


# ---------------------------------------------------------------- 테스트

def run_all(M=None):
    if M is None:
        spec = importlib.util.spec_from_file_location(
            "collect_minute_kis", REPO / "scripts" / "collect-minute-kis.py")
        M = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(M)

    pol = M.load_policy()
    date = "2026-08-03"
    sent = "20260803"
    tmp = Path(tempfile.mkdtemp(prefix="mincol-"))
    slept = []

    try:
        # 1 정상 하루 — 커서로 전량을 모은다
        tr = FakeTransport({("111111", sent): candles(sent)})
        o = M.collect_symbol_day(tr, "111111", date, pol, base_ctx(),
                                 sleeper=slept.append)
        check("정상 하루가 OK이고 381행", o.status == "OK" and len(o.rows) == 381,
              (o.status, len(o.rows)))
        check("커서가 실제로 돌았다 (호출 2회 이상)", len(tr.calls) >= 2,
              len(tr.calls))
        check("스키마가 계약과 정확히 같다",
              list(o.rows[0].keys()) == M.SCHEMA, list(o.rows[0].keys()))
        check("ts가 KST 오프셋을 갖는다",
              o.rows[0]["ts"] == "2026-08-03T09:00+09:00", o.rows[0]["ts"])
        check("마지막 캔들이 15:30",
              o.rows[-1]["ts"].endswith("15:30+09:00"), o.rows[-1]["ts"])

        # 2 휴장일 — 다른 날짜로 대체된 응답
        tr = FakeTransport({("111111", "__substitute__"): candles("20260731")})
        o = M.collect_symbol_day(tr, "111111", "2026-08-02", pol, base_ctx(),
                                 sleeper=slept.append)
        check("휴장일 대체 응답이 GAP/HOLIDAY",
              o.status == "GAP" and o.gap_reason == "HOLIDAY",
              (o.status, o.gap_reason))
        check("일자대체가 failureClass로도 남는다",
              o.failure_class == "DATE_MISMATCH", o.failure_class)

        # 3 영업일인데 대체됨 = 거래정지
        tr = FakeTransport({("111111", "__substitute__"): candles("20260731")})
        o = M.collect_symbol_day(tr, "111111", date, pol, base_ctx(),
                                 sleeper=slept.append)
        check("영업일 대체 응답이 GAP/HALT",
              o.status == "GAP" and o.gap_reason == "HALT",
              (o.status, o.gap_reason))

        # 4 상장 전
        tr = FakeTransport({})
        o = M.collect_symbol_day(tr, "222222", date, pol, base_ctx(),
                                 sleeper=slept.append)
        check("상장 전 종목이 GAP/PRE_LIST",
              o.status == "GAP" and o.gap_reason == "PRE_LIST",
              (o.status, o.gap_reason))

        # 5 빈 응답
        tr = FakeTransport({})
        o = M.collect_symbol_day(tr, "111111", date, pol, base_ctx(),
                                 sleeper=slept.append)
        check("빈 응답이 GAP/EMPTY",
              o.status == "GAP" and o.gap_reason == "EMPTY",
              (o.status, o.gap_reason))

        # 6 EGW00201 후 성공
        rl = {"http": 200, "body": {"rt_cd": "1", "msg_cd": "EGW00201",
                                    "msg1": "초당 거래건수 초과"}}
        tr = FakeTransport({("111111", sent): candles(sent, n=100)},
                           fail_plan=[rl, rl, None])
        slept.clear()
        o = M.collect_symbol_day(tr, "111111", date, pol, base_ctx(),
                                 sleeper=slept.append, rnd=lambda: 0.5)
        check("유량초과 후 재시도로 성공", o.status == "OK", o.status)
        check("backoff가 지수적으로 늘었다",
              len(slept) >= 2 and slept[1] > slept[0], slept[:3])

        # 7 유량초과 지속 — GAP이 아니라 UNRESOLVED다 (이 테스트가 핵심이다)
        tr = FakeTransport({("111111", sent): candles(sent)},
                           fail_plan=[rl] * 10)
        o = M.collect_symbol_day(tr, "111111", date, pol, base_ctx(),
                                 sleeper=slept.append, rnd=lambda: 0.5)
        check("유량초과 소진이 UNRESOLVED (GAP 아님)",
              o.status == "UNRESOLVED" and o.failure_class == "RATE_LIMIT",
              (o.status, o.failure_class, o.gap_reason))
        check("일시적 장애가 gapReason으로 기록되지 않는다",
              o.gap_reason is None, o.gap_reason)
        check("재시도 횟수가 정책 상한을 넘지 않는다",
              o.attempts <= pol["retry"]["maxAttempts"], o.attempts)

        # 8 네트워크 오류
        tr = FakeTransport({("111111", sent): candles(sent)},
                           fail_plan=[{"transportError": "ConnectionError"}] * 10)
        o = M.collect_symbol_day(tr, "111111", date, pol, base_ctx(),
                                 sleeper=slept.append, rnd=lambda: 0.5)
        check("전송 오류 소진이 UNRESOLVED/NETWORK",
              o.status == "UNRESOLVED" and o.failure_class == "NETWORK",
              (o.status, o.failure_class))

        # 9 rt_cd 오류는 모르는 실패 — 기본값이 재시도 가능
        tr = FakeTransport({}, fail_plan=[{"http": 200,
                                           "body": {"rt_cd": "2",
                                                    "msg_cd": "OPSQ9999"}}] * 10)
        o = M.collect_symbol_day(tr, "111111", date, pol, base_ctx(),
                                 sleeper=slept.append, rnd=lambda: 0.5)
        check("모르는 API 오류가 재시도되고 UNRESOLVED로 남는다",
              o.status == "UNRESOLVED" and o.failure_class == "API_ERROR"
              and o.attempts > 1, (o.status, o.failure_class, o.attempts))

        # 10 하루 실행 + 인수 조건
        data = {("111111", sent): candles(sent),
                ("333333", sent): candles(sent, n=200)}
        tr = FakeTransport(data)
        res = M.run_day(tr, ["111111", "333333", "222222"], date, pol,
                        base_ctx(), tmp / "raw", tmp / "state",
                        sleeper=slept.append)
        check("인수 조건 통과", res["acceptancePassed"],
              [c for c in res["manifest"]["acceptance"] if not c["통과"]])
        check("행 수가 두 종목의 합", len(res["rows"]) == 581, len(res["rows"]))
        check("manifest에 gapReasons 집계",
              res["manifest"]["gapReasons"].get("PRE_LIST") == 1,
              res["manifest"]["gapReasons"])
        check("manifest에 policyHash가 있다",
              bool(res["manifest"]["policyHash"]), None)

        # 11 미해결이 많으면 인수 조건 실패 → parquet를 쓰지 않는다
        tr = FakeTransport({}, fail_plan=[{"transportError": "X"}] * 200)
        res2 = M.run_day(tr, ["111111", "333333"], date, pol, base_ctx(),
                         tmp / "raw2", tmp / "state2", sleeper=slept.append)
        check("미해결 과다 시 인수 조건 실패", not res2["acceptancePassed"], None)
        check("실패 시 parquet 경로가 없다",
              res2["manifest"]["rawPath"] is None,
              res2["manifest"]["rawPath"])
        check("실패해도 manifest는 남는다 (진단)",
              res2["manifest"]["unresolved"].get("NETWORK") == 2,
              res2["manifest"]["unresolved"])

        # 12 resume — 이미 끝난 종목을 다시 부르지 않는다
        tr3 = FakeTransport(data)
        M.run_day(tr3, ["111111"], date, pol, base_ctx(),
                  tmp / "raw3", tmp / "state3", sleeper=slept.append)
        before = len(tr3.calls)
        tr3.calls.clear()
        M.run_day(tr3, ["111111", "333333"], date, pol, base_ctx(),
                  tmp / "raw3", tmp / "state3", resume=True,
                  sleeper=slept.append)
        again = {c[0] for c in tr3.calls}
        check("resume이 완료 종목을 건너뛴다", "111111" not in again, again)
        check("resume이 남은 종목은 수집한다", "333333" in again, again)
        check("첫 실행이 실제로 호출했다", before > 0, before)

        # 13 resume 비호환 — 계약이 바뀌면 거부한다
        pol2 = json.loads(json.dumps(pol))
        pol2["collectionContract"]["pageSize"] = 60
        try:
            M.run_day(FakeTransport(data), ["111111"], date, pol2, base_ctx(),
                      tmp / "raw3", tmp / "state3", resume=True,
                      sleeper=slept.append)
            check("계약 변경 시 resume 거부", False, "예외가 안 났다")
        except SystemExit:
            check("계약 변경 시 resume 거부", True)

        # 14 검증기 — 중복·OHLC·일자
        bad = [{"ticker": "111111", "ts": "2026-08-03T09:00+09:00", "open": 10,
                "high": 20, "low": 5, "close": 15, "volume": 1},
               {"ticker": "111111", "ts": "2026-08-03T09:00+09:00", "open": 10,
                "high": 20, "low": 5, "close": 15, "volume": 1}]
        v = M.validate_rows(bad, date, pol)
        check("중복 키를 잡는다",
              any(x["why"] == "duplicateKey" for x in v), v)

        bad2 = [{"ticker": "111111", "ts": "2026-08-03T09:00+09:00", "open": 10,
                 "high": 5, "low": 8, "close": 15, "volume": 1}]
        v2 = M.validate_rows(bad2, date, pol)
        check("OHLC 모순을 잡는다",
              any(x["why"] == "ohlcInconsistent" for x in v2), v2)

        bad3 = [{"ticker": "111111", "ts": "2026-07-31T09:00+09:00", "open": 10,
                 "high": 20, "low": 5, "close": 15, "volume": 1}]
        v3 = M.validate_rows(bad3, date, pol)
        check("다른 날짜 행을 잡는다",
              any(x["why"] == "dateMismatch" for x in v3), v3)

        # 15 정책이 계약 문서와 어긋나지 않는가
        cc = pol["collectionContract"]
        check("정책의 sessionMinutes가 T0 실측 381",
              cc["sessionMinutes"] == 381, cc["sessionMinutes"])
        check("정책의 pageSize가 T0 실측 120",
              cc["pageSize"] == 120, cc["pageSize"])
        check("성공 게이트에 요청일자 검사가 켜져 있다",
              pol["successGate"]["requireRequestedDateInResponse"] is True)
        check("동시성 초기값이 2 이하 (EGW00201 실측 반영)",
              pol["concurrency"]["initial"] <= 2, pol["concurrency"]["initial"])
        check("gapReason과 failureClass가 겹치지 않는다",
              not (set(pol["gapReason"]["values"])
                   & set(pol["failureClass"]["values"])),
              set(pol["gapReason"]["values"]) & set(pol["failureClass"]["values"]))
        check("pendingT1이 존재한다 (정책 미확정을 명시)",
              "pendingT1" in pol and "emptyResponseRetries" in pol["pendingT1"])

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("  통과 %d · 실패 %d" % (len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("    FAIL " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(run_all())
