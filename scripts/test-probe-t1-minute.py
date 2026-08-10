"""test-probe-t1-minute.py — T1 정찰 회귀 (합성 픽스처, 네트워크 없음)

T1이 틀리는 방식은 수집기와 다르다. 수집기는 데이터를 잃지만, 정찰은
**측정하지 못한 것을 측정한 것처럼 기록한다.** 그래서 여기서 재는 것은
'값이 맞는가'가 아니라 '모르는 것을 모른다고 적는가'다.

사용:
    python scripts/test-probe-t1-minute.py
    python scripts/probe-t1-minute.py --selftest
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


def load(name, fn):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / fn)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def rows(*specs):
    return [{"ticker": t, "ts": "2026-08-10T" + hm + "+09:00",
             "open": o, "high": h, "low": l, "close": c, "volume": v}
            for t, hm, o, h, l, c, v in specs]


def run_all(T=None):
    if T is None:
        T = load("probe_t1_minute", "probe-t1-minute.py")
    M = load("collect_minute_kis", "collect-minute-kis.py")
    tmp = Path(tempfile.mkdtemp(prefix="t1-"))

    try:
        base = rows(("005930", "09:00", 100, 110, 90, 105, 10),
                    ("005930", "09:01", 105, 115, 95, 110, 20))

        # 1 해시는 값의 성질이지 순서의 성질이 아니다
        check("같은 값이면 같은 해시",
              T.rows_sha(base) == T.rows_sha(list(base)))
        check("행 순서가 해시를 흔들지 않는다",
              T.rows_sha(base) == T.rows_sha(list(reversed(base))))
        moved = json.loads(json.dumps(base))
        moved[0]["volume"] = 11
        check("한 필드만 달라도 해시가 갈린다",
              T.rows_sha(base) != T.rows_sha(moved))

        # 2 대조 — '다르다'로 끝내지 않고 어디가 갈렸는지 지목한다
        c = T.compare_rows(base, base)
        check("동일하면 identical", c["identical"] and c["changedCount"] == 0, c)

        c = T.compare_rows(base, moved)
        check("volume 변경을 필드로 지목한다",
              not c["identical"] and c["changedFields"] == {"volume": 1}, c)
        check("변경 전후 값을 남긴다",
              c["samples"][0]["before"]["volume"] == 10
              and c["samples"][0]["after"]["volume"] == 11, c["samples"])
        check("거래량만 갈린 것을 수정주가로 읽지 않는다",
              not c["looksLikeAdjustment"], c)

        # ★ 수정주가의 지문 — 가격 넷이 한 비율로 움직인다
        # 105 // 2 = 52라 비율이 정확히 0.5가 아니다(0.4952). 정확일치로
        # 판정하면 실데이터에서는 영원히 안 걸린다 - 반올림 경계로 본다.
        adj = [{**r, "open": r["open"] // 2, "high": r["high"] // 2,
                "low": r["low"] // 2, "close": r["close"] // 2} for r in base]
        c = T.compare_rows(base, adj)
        check("반올림된 분할가도 수정주가로 잡는다",
              c["looksLikeAdjustment"], (c["looksLikeAdjustment"],
                                         c["priceRatioRange"]))
        check("비율을 점이 아니라 구간으로 남긴다",
              c["priceRatioRange"] and c["priceRatioRange"][0] <= 0.5
              <= c["priceRatioRange"][1], c["priceRatioRange"])
        check("네 가격이 다 움직인 행 수를 센다",
              c["rowsWithAllPricesChanged"] == 2,
              c["rowsWithAllPricesChanged"])

        # 비율 구간이 1.0을 품으면 재조정이 아니다 - 반올림 오차일 뿐이다.
        tiny = [{**r, "close": r["close"] + 0} for r in base]
        c = T.compare_rows(base, tiny)
        check("변화가 없으면 수정주가 신호도 없다",
              not c["looksLikeAdjustment"] and c["identical"], c)

        # 비율이 제각각이면 수정주가가 아니다. 이걸 구분 못 하면
        # 모든 가격 변경이 '분할'로 기록된다.
        messy = json.loads(json.dumps(base))
        messy[0]["open"] = 50
        messy[0]["high"] = 109
        messy[0]["low"] = 45
        messy[0]["close"] = 104
        c = T.compare_rows(base, messy)
        check("비율이 제각각이면 수정주가가 아니다",
              not c["looksLikeAdjustment"], c["priceRatioRange"])

        # 3 누락·추가를 방향까지 구분한다
        c = T.compare_rows(base, base[:1])
        check("두 번째에서 빠진 분을 잡는다",
              c["missingCount"] == 1 and c["addedCount"] == 0, c)
        c = T.compare_rows(base[:1], base)
        check("두 번째에서 늘어난 분을 잡는다",
              c["addedCount"] == 1 and c["missingCount"] == 0, c)

        # 4 dayVerdict를 계산하지 않고 읽어온다 (교훈73)
        # 표본 열 종목으로 날짜 판정을 흉내 내면 그건 추측이다.
        md = tmp / "man"
        md.mkdir(parents=True, exist_ok=True)
        (md / "2026-08-10.json").write_text(json.dumps(
            {"date": "2026-08-10", "dayVerdict": "TRADING_OBSERVED"}),
            encoding="utf-8")
        v, src = T.read_day_verdict(md, "2026-08-10")
        check("dayVerdict를 Broad manifest에서 읽는다",
              v == "TRADING_OBSERVED" and src == "broad-manifest", (v, src))
        v, src = T.read_day_verdict(md, "2026-08-11")
        check("manifest가 없으면 미측정이다 (추정하지 않는다)",
              v is None and "미측정" in src, (v, src))

        # 5 표본 — 못 채운 축을 미측정으로 남기는가
        # 이게 이 스크립트의 핵심 실패 모드다. 액면분할 표본이 없는데
        # '수정주가 변경 없음'을 확인으로 적으면 7일이 통째로 헛돈다(§6.1).
        raw = tmp / "raw"
        (raw / "_state").mkdir(parents=True, exist_ok=True)
        sample, unmeasured, missing = T.pick_sample(
            M, raw, universe_dir=tmp / "nouniverse", state_dir=raw / "_state")
        check("액면분할 축은 항상 미측정으로 남는다",
              any("액면분할" in u for u in unmeasured), unmeasured)
        check("미측정 축이 missing 목록에도 잡힌다",
              "액면분할이력" in missing, missing)
        check("유니버스가 없으면 대형주·소형주도 미측정",
              any("유니버스" in u for u in unmeasured), unmeasured)

        # 유니버스와 HALT 상태가 있으면 실제로 고른다
        ud = tmp / "uni"
        ud.mkdir(parents=True, exist_ok=True)
        (ud / "2026-08-10.jsonl").write_text("\n".join(json.dumps(r) for r in [
            {"ticker": "005930", "turnoverEok": 5000.0},
            {"ticker": "000660", "turnoverEok": 3000.0},
            {"ticker": "900100", "turnoverEok": 0.8},
            {"ticker": "900110", "turnoverEok": 0.5},
        ]), encoding="utf-8")
        (raw / "_state" / "state-2026-08-10.json").write_text(json.dumps(
            {"date": "2026-08-10", "symbols": {
                "111111": {"status": "GAP", "gapReason": "HALT"},
                "222222": {"status": "OK", "rows": 381}}}), encoding="utf-8")
        sample, unmeasured, missing = T.pick_sample(
            M, raw, universe_dir=ud, state_dir=raw / "_state")
        got = {s["axis"] for s in sample}
        check("대형주·소형주를 거래대금에서 고른다",
              "대형주" in got and "소형주" in got, sorted(got))
        check("거래정지 표본을 관측된 HALT에서 고른다 (추측 아님)",
              any(s["ticker"] == "111111" and s["axis"] == "거래정지이력"
                  for s in sample), sample)
        check("고른 이유를 함께 남긴다",
              all(s.get("why") for s in sample), sample)
        check("표본에 중복이 없다",
              len({s["ticker"] for s in sample}) == len(sample), sample)
        check("축을 다 채워도 액면분할은 여전히 미측정",
              any("액면분할" in u for u in unmeasured), unmeasured)

        # 6 대상 날짜는 이미 받은 날에서만 고른다
        # T1이 새 호출로 없던 날을 만들면 Broad manifest 참조가 끊긴다.
        for d in ("2026-08-06", "2026-08-07", "2026-08-10"):
            (raw / ("date=" + d)).mkdir(parents=True, exist_ok=True)
        ds = T.target_dates(M, {}, raw, back=2)
        check("수집된 날 중 최근 것을 대상으로 한다",
              ds == ["2026-08-07", "2026-08-10"], ds)
        check("수집물이 없으면 대상이 비어 있다",
              T.target_dates(M, {}, tmp / "empty", back=2) == [])

        # 7 임계를 미리 정하지 않았는가 (교훈51)
        # 여기가 통과로 바뀌는 순간 이 정찰은 답을 확인하는 절차가 된다.
        check("비교 방법은 리터럴로 고정돼 있다",
              T.REQUIRED_AXES == ["대형주", "소형주", "거래정지이력",
                                  "신규상장", "액면분할이력"], T.REQUIRED_AXES)

        # 8 T1은 manifest를 만들지 않는다
        src = (REPO / "scripts" / "probe-t1-minute.py").read_text(encoding="utf-8")
        check("write_manifest를 부르지 않는다",
              "write_manifest" not in src)
        check("run_day를 부르지 않는다 (수집이 아니다)",
              "run_day(" not in src)
        check("산출물에 acceptancePassed가 없다",
              "acceptancePassed" not in src)

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
