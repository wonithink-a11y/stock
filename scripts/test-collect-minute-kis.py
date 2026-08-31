"""test-collect-minute-kis.py — Collector v1 인수 조건 (합성 픽스처, 네트워크 없음)

이 테스트는 KIS를 부르지 않는다. transport를 갈아끼워 응답을 만든다.
조용히 무너지는 축은 게이트를 두 겹으로 건다(교훈49) — 인수 조건과 이 회귀다.

사용:
    python scripts/test-collect-minute-kis.py
    python scripts/collect-minute-kis.py --selftest
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from datetime import timedelta
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
    """캘린더가 2026-07-31 ~ 08-04를 덮는다. 그 밖은 '모른다'다.

    범위를 명시하는 이유는, 캘린더가 못 덮는 날짜를 휴장으로 부르는 것이
    이 수집기의 가장 조용한 실패이기 때문이다(교훈57).
    """
    return {"tradingDays": {"2026-07-31", "2026-08-03", "2026-08-04"},
            "calendarFrom": "2026-07-31", "calendarTo": "2026-08-04",
            "listedAt": {"111111": "2026-01-01", "222222": "2027-01-01"},
            "delistedAt": {}}


def open_ctx():
    """캘린더가 아예 없는 상태. 상시 운영이 실제로 서 있는 자리다."""
    return {"tradingDays": set(), "calendarFrom": None, "calendarTo": None,
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
        def row(ts, o, h, l, c, v_=1, tk="111111"):
            return {"ticker": tk, "ts": "2026-08-03T" + ts + "+09:00",
                    "open": o, "high": h, "low": l, "close": c, "volume": v_}

        bad = [row("09:00", 10, 20, 5, 15), row("09:00", 10, 20, 5, 15)]
        v, _ = M.validate_rows(bad, date, pol)
        check("중복 키를 잡는다",
              any(x["why"] == "duplicateKey" for x in v), v)

        v2, _ = M.validate_rows([row("09:00", 10, 5, 8, 15)], date, pol)
        check("low > high를 잡는다",
              any(x["why"] == "lowAboveHigh" for x in v2), v2)

        bad3 = [{"ticker": "111111", "ts": "2026-07-31T09:00+09:00", "open": 10,
                 "high": 20, "low": 5, "close": 15, "volume": 1}]
        v3, _ = M.validate_rows(bad3, date, pol)
        check("다른 날짜 행을 잡는다",
              any(x["why"] == "dateMismatch" for x in v3), v3)

        # 14b 09:00의 open 면제 — 실측 2026-08-10 (3일 중 2일이 이것으로 떨어졌다)
        # 09:00 봉의 open은 시가단일가 체결가라 그 1분의 [low,high] 밖일 수 있다.
        # 소스가 약속하지 않은 것을 단언하면 정상 데이터가 위반이 된다.
        # 면제가 어디까지인지를 여기서 못 박는다 - 넓어지면 진짜 손상이 숨는다.
        v4, o4 = M.validate_rows([row("09:00", 6880, 6810, 6810, 6810, 63)],
                                 date, pol)       # 실측 036220
        check("09:00의 open이 high 위여도 위반이 아니다", not v4, v4)
        check("면제한 것을 관측치로 센다",
              o4.get("openOutOfRangeAtSessionOpen") == 1, o4)

        v5, o5 = M.validate_rows([row("09:00", 9360, 9420, 9390, 9420, 603)],
                                 date, pol)       # 실측 272550 (아래로 벗어남)
        check("09:00의 open이 low 아래여도 위반이 아니다 (양방향)", not v5, v5)
        check("아래로 벗어난 것도 관측치로 센다",
              o5.get("openOutOfRangeAtSessionOpen") == 1, o5)

        # ★ 면제는 09:00 하나뿐이다. 여기가 새면 A의 근거가 사라진다.
        v6, o6 = M.validate_rows([row("09:01", 6880, 6810, 6810, 6810)],
                                 date, pol)
        check("09:01의 open 범위 이탈은 여전히 위반",
              any(x["why"] == "openOutOfRange" for x in v6), v6)
        check("09:01은 관측치로 새지 않는다", not o6, o6)
        v7, _ = M.validate_rows([row("15:30", 100, 90, 90, 90)], date, pol)
        check("종가단일가(15:30)도 면제 대상이 아니다",
              any(x["why"] == "openOutOfRange" for x in v7), v7)

        # ★ close는 09:00에서도 강제된다. 실측 5건 모두 close는 범위 안이었다.
        v8, _ = M.validate_rows([row("09:00", 6810, 6810, 6810, 9999)],
                                date, pol)
        check("09:00이어도 close 범위 이탈은 위반",
              any(x["why"] == "closeOutOfRange" for x in v8), v8)
        v9, _ = M.validate_rows([row("09:00", 6880, 6810, 6820, 6815)],
                                date, pol)
        check("09:00이어도 low > high는 위반",
              any(x["why"] == "lowAboveHigh" for x in v9), v9)

        # 14c 면제가 인수 조건까지 통과시키는가 (실운영에서 깨진 자리다)
        opened = candles(sent)
        opened[0]["stck_oprc"] = "99999"       # 09:00 봉의 open만 범위 밖으로
        res_ex = M.run_day(FakeTransport({("111111", sent): opened}),
                           ["111111"], date, pol, base_ctx(),
                           tmp / "exempt", tmp / "exemptst",
                           sleeper=slept.append)
        check("09:00 이상치가 있어도 하루가 인수 조건을 통과한다",
              res_ex["acceptancePassed"],
              [c for c in res_ex["manifest"]["acceptance"] if not c["통과"]])
        check("manifest가 면제 건수를 들고 있다",
              res_ex["manifest"]["observations"]
              .get("openOutOfRangeAtSessionOpen") == 1,
              res_ex["manifest"]["observations"])

        # 14d 정책이 계약을 단일 출처로 들고 있는가
        val = pol.get("validation") or {}
        check("면제 시각이 정책에 리터럴로 있다",
              val.get("openWithinRangeExemptMinutes") == ["09:00"],
              val.get("openWithinRangeExemptMinutes"))
        check("면제 사유가 실측과 함께 적혀 있다",
              "2026-08-10" in str(val.get("openWithinRangeExemptNote")))
        check("close·low<=high는 정책에서도 강제로 남아 있다",
              val.get("requireCloseWithinRange") is True
              and val.get("requireLowLeHigh") is True, val)
        check("정책 버전이 올라갔다 (완화는 버전 승격으로만)",
              pol["version"] == "MN-1.2", pol["version"])
        # collectionContract가 안 바뀌어야 이미 모은 것을 다시 쓸 수 있다.
        check("면제가 collectionContract를 건드리지 않았다",
              "validation" not in pol["collectionContract"]
              and set(pol["collectionContract"]) == {
                  "note", "marketDivCode", "pageSize", "pageSizeNote",
                  "cursorField", "cursorSeed", "pastDataFlag", "fakeTickFlag",
                  "sessionMinutes", "sessionMinutesNote",
                  "retentionTradingDays", "retentionNote"},
              sorted(pol["collectionContract"]))

        # 15 parquet 왕복 — 저장 계층을 실증한다
        # 쓰는 것만 보고 넘어가면 '저장했다'와 '되읽을 수 있다'가 갈린다.
        try:
            import pyarrow.parquet as pq
            have_pa = True
        except ImportError:
            have_pa = False

        if not have_pa:
            check("parquet 왕복 (pyarrow 없음 — 건너뜀)", True)
            check("writer가 부재를 조용히 넘기지 않는다",
                  M.write_parquet([], date, tmp / "nopa")[1] is not None)
        else:
            data2 = {("111111", sent): candles(sent),
                     ("333333", sent): candles(sent, n=200)}
            res3 = M.run_day(FakeTransport(data2), ["111111", "333333"], date,
                             pol, base_ctx(), tmp / "rt", tmp / "rtstate",
                             sleeper=slept.append)
            man = res3["manifest"]
            check("왕복: 인수 조건 통과", res3["acceptancePassed"], None)
            check("왕복: rawPath가 기록됐다", bool(man["rawPath"]), man["rawPath"])

            path = Path(man["rawPath"])
            check("왕복: 경로가 존재한다", path.exists(), str(path))
            check("왕복: rawPath가 date 파티션 디렉터리",
                  path.is_dir() and path.name == "date=2026-08-03", path.name)
            check("왕복: parts가 비어 있지 않다", len(man["parts"]) >= 1,
                  man["parts"])
            check("왕복: 모든 part 파일이 실재한다",
                  all((path / p["name"]).exists() for p in man["parts"]))
            check("왕복: 스테이징이 남아 있지 않다",
                  not (path / "_staging").exists())
            check("왕복: parts 행 합이 manifest rows",
                  sum(p["rows"] for p in man["parts"]) == man["rows"],
                  (sum(p["rows"] for p in man["parts"]), man["rows"]))

            t = pq.read_table(path)
            check("왕복: 행 수가 manifest와 같다",
                  t.num_rows == man["rows"] == len(res3["rows"]),
                  (t.num_rows, man["rows"], len(res3["rows"])))
            check("왕복: 스키마가 계약 순서 그대로",
                  t.column_names == M.SCHEMA, t.column_names)

            back = t.to_pylist()
            check("왕복: 값이 바이트 단위로 보존된다",
                  back == res3["rows"],
                  next((i for i, (a, b) in enumerate(zip(back, res3["rows"]))
                        if a != b), None))
            check("왕복: 필수 필드에 null이 없다",
                  all(all(r[k] is not None for k in M.SCHEMA) for r in back))
            check("왕복: ticker가 6자 유지 (선행 0 소실 없음)",
                  all(len(r["ticker"]) == 6 for r in back))

            recomputed = M.combined_sha(
                [{"name": p["name"],
                  "sha256": M.sha256_bytes((path / p["name"]).read_bytes())}
                 for p in man["parts"]])
            check("왕복: 결합 sha256이 manifest와 일치",
                  recomputed == man["sha256"],
                  (recomputed[:16], str(man["sha256"])[:16]))

            # 같은 입력을 다시 쓰면 같은 바이트인가.
            # 아니면 manifest의 sha256으로는 '재빌드 동일성'을 증명할 수 없고,
            # 검증은 행 단위 대조로만 가능하다. 지금 알아야 §5가 정확해진다.
            p2, _ = M.write_parquet(res3["rows"], date, tmp / "rt2")
            one = M.sha256_bytes((path / man["parts"][0]["name"]).read_bytes())
            check("왕복: 재작성이 바이트 동일 (결정적 쓰기)",
                  M.sha256_bytes(Path(p2).read_bytes()) == one,
                  "비결정적이면 manifest sha는 '이 파일이 안 바뀌었다'만 증명한다")

            # 조각이 여러 개일 때도 같은 계약이 서는가.
            # 1GB VM 때문에 배치로 쓰므로 Broad에서는 이쪽이 정상 경로다.
            pol_b = json.loads(json.dumps(pol))
            pol_b["output"]["flushEverySymbols"] = 1
            res4 = M.run_day(FakeTransport(data2), ["111111", "333333"], date,
                             pol_b, base_ctx(), tmp / "rt3", tmp / "rt3state",
                             sleeper=slept.append)
            m4 = res4["manifest"]
            check("배치: 조각이 2개 이상", len(m4["parts"]) >= 2, m4["parts"])
            check("배치: 행 합이 단일 조각과 같다",
                  m4["rows"] == man["rows"], (m4["rows"], man["rows"]))
            t4 = pq.read_table(Path(m4["rawPath"]))
            check("배치: 되읽은 행 수가 같다", t4.num_rows == m4["rows"],
                  (t4.num_rows, m4["rows"]))
            check("배치: 되읽은 값 집합이 단일 조각과 같다",
                  sorted(t4.to_pylist(), key=lambda r: (r["ticker"], r["ts"]))
                  == sorted(back, key=lambda r: (r["ticker"], r["ts"])))
            check("배치: 조각 수가 달라지면 결합 sha도 달라진다",
                  m4["sha256"] != man["sha256"],
                  "같으면 결합식이 조각 구성을 반영하지 못한다")

        # 16 인플라이트가 묶여 있는가 — 메모리의 실제 원인이었다
        # 행을 버려도 피크가 안 내려갔다. ThreadPoolExecutor.map이 전량을
        # 즉시 제출해 future가 결과를 쥐고 있었기 때문이다(388.7 → 371.4 → 374.6).
        # 청크 제출로 144.8MB가 됐다. 이 성질이 사라지면 1GB VM에서 죽는다.
        if have_pa:
            class WatchTransport(FakeTransport):
                def __init__(self, *a, **kw):
                    super().__init__(*a, **kw)
                    self.parts_seen_midway = None
                    self.n = 0
                    self.stage = None

                def fetch(self, ticker, sent_date, hour, pol):
                    self.n += 1
                    if self.n == 30 and self.stage:
                        self.parts_seen_midway = len(
                            list(self.stage.glob("part-*.parquet")))
                    return super().fetch(ticker, sent_date, hour, pol)

            many = {("%06d" % i, sent): candles(sent, n=20) for i in range(40)}
            wt = WatchTransport(many)
            polc = json.loads(json.dumps(pol))
            polc["output"]["flushEverySymbols"] = 5
            wt.stage = (tmp / "chunk" / ("date=" + date) /
                        polc["output"]["stagingDirName"])
            M.run_day(wt, ["%06d" % i for i in range(40)], date, polc,
                      base_ctx(), tmp / "chunk", tmp / "chunkstate",
                      sleeper=slept.append, keep_rows=False)
            check("인플라이트가 묶여 있다 (중간에 이미 조각이 쓰였다)",
                  wt.parts_seen_midway is not None and wt.parts_seen_midway > 0,
                  "전량 제출이면 마지막에야 조각이 생긴다: " +
                  str(wt.parts_seen_midway))

        # 17 운영 환경(Python 3.8)에 없는 API를 쓰지 않는가
        # 문법 검사(ast feature_version)는 구문만 본다. 런타임 API 차이는
        # 구조적으로 못 잡는다 - Path.write_text(newline=)이 3.10부터라
        # VM에서 TypeError로 죽었다(교훈82). 줄바꿈으로 감싼 호출도 본다.
        # 정규식으로 훑으면 주석 안의 'write_text(newline=)' 설명까지 잡는다.
        # AST로 호출 노드만 본다 - 문자열·주석에 영향받지 않는다.
        import ast as _ast
        offenders = []
        for f in sorted((REPO / "scripts").glob("*.py")):
            tree = _ast.parse(f.read_text(encoding="utf-8"))
            for node in _ast.walk(tree):
                if (isinstance(node, _ast.Call)
                        and isinstance(node.func, _ast.Attribute)
                        and node.func.attr == "write_text"
                        and any(k.arg == "newline" for k in node.keywords)):
                    offenders.append(f.name)
        check("3.8에 없는 write_text(newline=)을 쓰지 않는다",
              not offenders, sorted(set(offenders)))

        # 18 정책이 계약 문서와 어긋나지 않는가
        cc = pol["collectionContract"]
        check("정책의 sessionMinutes가 T0 실측 381",
              cc["sessionMinutes"] == 381, cc["sessionMinutes"])
        check("정책의 pageSize가 T0 실측 120",
              cc["pageSize"] == 120, cc["pageSize"])
        check("성공 게이트에 요청일자 검사가 켜져 있다",
              pol["successGate"]["requireRequestedDateInResponse"] is True)
        check("동시성 초기값이 문서화된 상한 4 이하 "
              "(EGW00201이 동시 4~6에서 실측, MN-1.2에서 2→4 승격)",
              pol["concurrency"]["initial"] <= 4, pol["concurrency"]["initial"])
        check("gapReason과 failureClass가 겹치지 않는다",
              not (set(pol["gapReason"]["values"])
                   & set(pol["failureClass"]["values"])),
              set(pol["gapReason"]["values"]) & set(pol["failureClass"]["values"]))
        check("pendingT1이 존재한다 (정책 미확정을 명시)",
              "pendingT1" in pol and "emptyResponseRetries" in pol["pendingT1"])

        # 19 캘린더 범위 밖을 휴장으로 부르지 않는다
        # A0.5 캘린더는 매일 갱신되지 않는다. 범위 밖을 '거래일 목록에 없다'는
        # 이유로 HOLIDAY로 굳히면, 캘린더가 하루 낡을 때마다 그날의 모든
        # 결손이 거짓 사유로 봉인된다 - 재수집으로도 못 되돌린다(교훈57·75).
        beyond = "2026-08-10"        # base_ctx의 calendarTo(08-04) 이후
        check("캘린더 범위 밖은 캘린더가 말하지 않는다",
              not M.calendar_covers(beyond, base_ctx()))
        check("캘린더 범위 안의 비거래일은 여전히 HOLIDAY",
              M.resolve_gap_reason("EMPTY", "111111", "2026-08-01",
                                   base_ctx()) == "HOLIDAY")
        tr = FakeTransport({})
        o = M.collect_symbol_day(tr, "111111", beyond, pol, base_ctx(),
                                 sleeper=slept.append)
        check("범위 밖 빈 응답이 HOLIDAY가 아니라 EMPTY",
              o.gap_reason == "EMPTY", o.gap_reason)
        tr = FakeTransport({("111111", "__substitute__"): candles("20260731")})
        o = M.collect_symbol_day(tr, "111111", beyond, pol, base_ctx(),
                                 sleeper=slept.append)
        check("범위 밖 일자대체가 HOLIDAY가 아니라 HALT",
              o.gap_reason == "HALT", o.gap_reason)

        # 20 날짜 단위 판정 — 종목 하나로는 잴 수 없는 것(교훈73)
        b = "20260810"
        data_open = {("111111", b): candles(b), ("333333", b): candles(b, 200)}
        res = M.run_day(FakeTransport(data_open), ["111111", "333333"], beyond,
                        pol, base_ctx(), tmp / "v1", tmp / "v1s",
                        sleeper=slept.append)
        check("행이 있으면 TRADING_OBSERVED",
              res["manifest"]["dayVerdict"] == "TRADING_OBSERVED",
              res["manifest"]["dayVerdict"])

        res = M.run_day(FakeTransport({}), ["111111", "333333"], beyond, pol,
                        base_ctx(), tmp / "v2", tmp / "v2s",
                        sleeper=slept.append)
        check("전 종목이 비면 CLOSED_INFERRED",
              res["manifest"]["dayVerdict"] == "CLOSED_INFERRED",
              res["manifest"]["dayVerdict"])
        check("휴장 추론이 개별 라벨을 HOLIDAY로 정정한다",
              res["manifest"]["gapReasons"].get("HOLIDAY") == 2,
              res["manifest"]["gapReasons"])

        res = M.run_day(FakeTransport({}, fail_plan=[{"transportError": "X"}] * 99),
                        ["111111", "333333"], beyond, pol, base_ctx(),
                        tmp / "v3", tmp / "v3s", sleeper=slept.append)
        check("장애가 있으면 휴장이라 단정하지 않는다 (UNKNOWN)",
              res["manifest"]["dayVerdict"] == "UNKNOWN",
              res["manifest"]["dayVerdict"])
        check("캘린더가 덮으면 캘린더가 진실이다 (TRADING_CONFIRMED)",
              M.day_verdict(date, [], base_ctx())[0] == "TRADING_CONFIRMED")
        check("캘린더가 덮는 비거래일은 CLOSED_CONFIRMED",
              M.day_verdict("2026-08-01", [], base_ctx())[0]
              == "CLOSED_CONFIRMED")

        # 21 NOT_QUERIED — '조회했더니 없음'과 '조회하지 않음'을 가른다(§2.1)
        res = M.run_day(FakeTransport({}), ["111111"], beyond, pol, base_ctx(),
                        tmp / "nq", tmp / "nqs", sleeper=slept.append,
                        not_queried=["333333", "444444"])
        check("부르지 않은 종목이 NOT_QUERIED로 남는다",
              res["manifest"]["gapReasons"].get("NOT_QUERIED") == 2,
              res["manifest"]["gapReasons"])
        check("manifest의 symbols가 부르지 않은 것까지 센다",
              res["manifest"]["symbols"] == 3, res["manifest"]["symbols"])
        check("NOT_QUERIED는 휴장 추론으로 덮이지 않는다",
              res["manifest"]["symbolsNotQueried"] == 2,
              res["manifest"]["symbolsNotQueried"])
        # 이것이 핵심이다. NOT_QUERIED를 GAP이라는 이유로 완료로 세면
        # 정찰로 건너뛴 종목이 다음 재개에서 영영 조회되지 않는다.
        check("resume이 NOT_QUERIED를 완료로 세지 않는다",
              not M.is_resolved({"status": "GAP", "gapReason": "NOT_QUERIED"}))
        check("resume이 EMPTY는 완료로 센다",
              M.is_resolved({"status": "GAP", "gapReason": "EMPTY"}))
        tr_nq = FakeTransport({("333333", b): candles(b, n=30)})
        M.run_day(tr_nq, ["333333"], beyond, pol, base_ctx(),
                  tmp / "nq", tmp / "nqs", resume=True, sleeper=slept.append)
        check("재개가 NOT_QUERIED 종목을 실제로 부른다",
              any(c[0] == "333333" for c in tr_nq.calls), tr_nq.calls[:3])

        # 22 resume이 앞 실행의 스테이징을 이어받는가
        # 이것이 없으면 인수 조건에 걸린 하루가 재개될 때, 이미 받아 놓은
        # 종목들의 행이 통째로 사라진다 - state는 그 종목을 완료로 알고
        # 있어 다시 부르지 않기 때문이다. 조용하고 되돌릴 수 없다.
        if have_pa:
            polx = json.loads(json.dumps(pol))
            polx["output"]["flushEverySymbols"] = 1
            good = {("%06d" % i, sent): candles(sent, n=10) for i in range(6)}
            allt = ["%06d" % i for i in range(6)] + ["999999"]
            # 999999는 계속 실패해 인수 조건을 못 넘긴다 (미해결 1/7 > 5%)
            tr_a = FakeTransport(good)
            orig = tr_a.fetch

            def flaky(ticker, sent_date, hour, p):
                if ticker == "999999":
                    return {"transportError": "X"}
                return orig(ticker, sent_date, hour, p)
            tr_a.fetch = flaky
            r1 = M.run_day(tr_a, allt, date, polx, base_ctx(),
                           tmp / "carry", tmp / "carrys", sleeper=slept.append)
            stage = (tmp / "carry" / ("date=" + date) /
                     polx["output"]["stagingDirName"])
            check("실패한 하루의 조각이 스테이징에 남는다",
                  not r1["acceptancePassed"]
                  and len(list(stage.glob("part-*.parquet"))) >= 6,
                  (r1["acceptancePassed"],
                   len(list(stage.glob("part-*.parquet")))))

            good2 = dict(good)
            good2[("999999", sent)] = candles(sent, n=10)
            r2 = M.run_day(FakeTransport(good2), allt, date, polx, base_ctx(),
                           tmp / "carry", tmp / "carrys", resume=True,
                           sleeper=slept.append)
            check("재개가 인수 조건을 통과한다", r2["acceptancePassed"],
                  [c for c in r2["manifest"]["acceptance"] if not c["통과"]])
            check("재개 뒤 행 수가 전 종목 합이다 (앞 실행분을 잃지 않았다)",
                  r2["manifest"]["rows"] == 70, r2["manifest"]["rows"])
            t5 = pq.read_table(Path(r2["manifest"]["rawPath"]))
            check("재개 뒤 parquet가 실제로 7종목을 담는다",
                  len(set(t5.column("ticker").to_pylist())) == 7,
                  len(set(t5.column("ticker").to_pylist())))
            check("재개 뒤 manifest 행 합이 parts 합과 같다",
                  sum(p["rows"] for p in r2["manifest"]["parts"])
                  == r2["manifest"]["rows"] == t5.num_rows,
                  (sum(p["rows"] for p in r2["manifest"]["parts"]),
                   r2["manifest"]["rows"], t5.num_rows))
            check("재개 뒤 조각 이름이 겹치지 않았다",
                  len({p["name"] for p in r2["manifest"]["parts"]})
                  == len(r2["manifest"]["parts"]), r2["manifest"]["parts"])
            check("재개 뒤 스테이징이 비었다", not stage.exists())
            recomb = M.combined_sha(
                [{"name": p["name"],
                  "sha256": M.sha256_bytes(
                      (Path(r2["manifest"]["rawPath"]) / p["name"]).read_bytes())}
                 for p in r2["manifest"]["parts"]])
            check("재개 뒤 결합 sha가 실제 파일과 일치",
                  recomb == r2["manifest"]["sha256"])

        # 22b resume이 이월 조각의 검증 위반까지 재검증하는가
        # 실측 2026-08-31 — KIS Broad 432980 09:02 openOutOfRange.
        # 22와 다른 지점: 여기선 두 종목 다 API 응답은 OK로 '완료'된다.
        # 위반은 09:00 예외 밖의 시각에 있는 행 안에만 있어 첫 실행이
        # 인수 조건에서 걸린다. resume은 두 종목 다 이미 완료로 알아
        # 다시 부르지 않으므로(정상), 이월 조각을 다시 읽어 재검증하지
        # 않으면 그 위반은 두 번째 실행에서 조용히 사라져 PASS로
        # 승격된다 — 이게 2026-08-31 실운영에서 실제로 벌어진 버그다.
        if have_pa:
            good_a = candles(sent, n=20)
            bad_b = candles(sent, n=20)
            bad_b[5]["stck_oprc"] = "99999"     # 세션 중반, 예외 시각 아님
            data_v = {("111111", sent): good_a, ("222222", sent): bad_b}
            polv = json.loads(json.dumps(pol))
            polv["output"]["flushEverySymbols"] = 1
            r1 = M.run_day(FakeTransport(data_v), ["111111", "222222"], date,
                           polv, base_ctx(), tmp / "resumeviol",
                           tmp / "resumeviolstate", sleeper=slept.append)
            v_check1 = next(c for c in r1["manifest"]["acceptance"]
                            if c["항목"].startswith("스키마"))
            check("22b 첫 실행이 openOutOfRange로 인수 조건 실패",
                  not r1["acceptancePassed"] and v_check1["실측"]["위반"] >= 1,
                  v_check1)

            tr2 = FakeTransport({})
            r2 = M.run_day(tr2, ["111111", "222222"], date, polv, base_ctx(),
                           tmp / "resumeviol", tmp / "resumeviolstate",
                           resume=True, sleeper=slept.append)
            check("22b resume이 완료된 두 종목을 다시 부르지 않는다 "
                  "(불필요한 재수집 없음)", tr2.calls == [], tr2.calls)
            v_check2 = next(c for c in r2["manifest"]["acceptance"]
                            if c["항목"].startswith("스키마"))
            check("22b resume이 이월 위반을 재검증해 여전히 FAIL "
                  "(재검증 없이 acceptancePassed=true 금지)",
                  not r2["acceptancePassed"] and v_check2["실측"]["위반"] >= 1,
                  v_check2)
            check("22b 재검증된 위반이 실제로 openOutOfRange다",
                  any(v["why"] == "openOutOfRange"
                      for v in v_check2["실측"]["샘플"]),
                  v_check2["실측"]["샘플"])

        # 23 정찰 — 하나라도 캔들이 오면 즉시 멈춘다
        tr_p = FakeTransport({("111111", b): candles(b, n=5)})
        outs = M.probe_market_open(tr_p, ["111111", "333333", "444444"],
                                   beyond, pol, base_ctx(),
                                   sleeper=slept.append)
        check("정찰이 첫 성공에서 멈춘다",
              len(outs) == 1 and outs[0].status == "OK",
              [(o.ticker, o.status) for o in outs])
        tr_p = FakeTransport({})
        outs = M.probe_market_open(tr_p, ["111111", "333333", "444444"],
                                   beyond, pol, base_ctx(),
                                   sleeper=slept.append)
        check("정찰이 전부 비면 셋을 다 본다",
              len(outs) == 3 and all(o.status == "GAP" for o in outs),
              [(o.ticker, o.status) for o in outs])

        # 24 유니버스 원천 — Broad는 스냅샷이 아니라 전체 상장이다
        if M.A1A_PATH.exists():
            bt = M.broad_tickers()
            check("Broad가 A1a 전체 상장에서 온다", len(bt) > 2000, len(bt))
            check("Broad 티커가 6자를 유지한다 (영숫자 코드 포함)",
                  all(len(t) == 6 for t in bt),
                  [t for t in bt if len(t) != 6][:5])
            check("Broad가 정렬·중복 없음", bt == sorted(set(bt)))
            check("상장일 이후만 담는다",
                  len(M.broad_tickers("1990-01-01")) < len(bt),
                  len(M.broad_tickers("1990-01-01")))
        else:
            check("Broad 유니버스 (A1a 없음 - 건너뜀)", True)

        # 25 토큰 — 무인 운영의 단일 실패점
        # 캐시가 살아 있는데 새로 받으면 발급 한도에 걸리고, 만료됐는데
        # 재사용하면 그날 수집이 통째로 죽는다. 양쪽을 다 본다.
        tokdir = tmp / "tok"
        tokdir.mkdir(parents=True, exist_ok=True)
        tp = tokdir / "cache.json"
        minted = []

        def fake_mint(k, s):
            minted.append(k)
            return {"access_token": "NEW",
                    "access_token_token_expired":
                        (M.now_kst() + timedelta(hours=24))
                        .strftime("%Y-%m-%d %H:%M:%S")}

        live = (M.now_kst() + timedelta(hours=5)
                ).strftime("%Y-%m-%d %H:%M:%S")
        tp.write_text(json.dumps({"accessToken": "OLD", "expiresAt": live,
                                  "appKeyTail": "cdef"}), encoding="utf-8")
        tok, how = M.get_token("abcdef", "s", cache=tp, mint=fake_mint)
        check("살아 있는 토큰을 재사용한다",
              tok == "OLD" and how == "cache" and not minted, (tok, how, minted))

        dead = (M.now_kst() - timedelta(hours=1)
                ).strftime("%Y-%m-%d %H:%M:%S")
        tp.write_text(json.dumps({"accessToken": "OLD", "expiresAt": dead,
                                  "appKeyTail": "cdef"}), encoding="utf-8")
        tok, how = M.get_token("abcdef", "s", cache=tp, mint=fake_mint)
        check("만료된 토큰은 새로 받는다",
              tok == "NEW" and how == "minted", (tok, how))
        check("발급 결과가 캐시에 남는다",
              json.loads(tp.read_text(encoding="utf-8"))["accessToken"] == "NEW")

        tp.write_text(json.dumps({"accessToken": "OLD", "expiresAt": live,
                                  "appKeyTail": "zzzz"}), encoding="utf-8")
        tok, _ = M.get_token("abcdef", "s", cache=tp, mint=fake_mint)
        check("앱키가 바뀌면 캐시를 믿지 않는다", tok == "NEW", tok)

        # 26 manifest 자리 — 통과만 manifest, 실패는 진단으로
        md = tmp / "mans"
        p_ok = M.write_manifest({"date": "2026-08-03", "acceptancePassed": True},
                                md)
        p_no = M.write_manifest({"date": "2026-08-03",
                                 "acceptancePassed": False}, md)
        check("통과한 것만 manifest 디렉터리에 쓴다",
              Path(p_ok).parent == md and Path(p_ok).name == "2026-08-03.json",
              str(p_ok))
        check("실패는 _failed/로 격리한다 (존재가 통과로 읽히지 않게)",
              Path(p_no).parent == md / "_failed", str(p_no))

        # 27 경로가 환경변수로 옮겨지는가 (VM 운영 기준 8)
        old = {k: os.environ.get(k) for k in
               ("MINUTE_RAW_ROOT", "MINUTE_STATE_DIR", "MINUTE_MANIFEST_DIR")}
        try:
            os.environ["MINUTE_RAW_ROOT"] = str(tmp / "envraw")
            os.environ.pop("MINUTE_STATE_DIR", None)
            os.environ.pop("MINUTE_MANIFEST_DIR", None)
            r_, s_, m_ = M.env_paths(pol)
            check("MINUTE_RAW_ROOT가 Raw 위치를 옮긴다",
                  r_ == tmp / "envraw", str(r_))
            check("state가 raw 아래로 따라간다",
                  s_ == tmp / "envraw" / "_state", str(s_))
            check("manifestDir이 cwd가 아니라 저장소 기준이다",
                  m_ == REPO / pol["output"]["manifestDir"], str(m_))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

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
