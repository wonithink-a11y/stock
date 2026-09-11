"""build_ui_macro.py 의 _series_from() self-check. 네트워크·parquet 없음.

왜 있는가(실측 2026-09-11): 이 함수가 parquet 의 <col>AsOfDate 를 버리고 date 만
내보냈다. parquet 의 date 는 asof_join_kr() 의 PIT 규칙에 따라 **값을 쓸 수 있게
된 날**이고 값은 그 전 관측일의 것인데, 소비자는 그걸 "그날 종가"로 읽었다.

그 결과 두 곳이 조용히 틀렸다 - UI 의 코스피/코스닥 비교가 하루 어긋났고,
Beta 가 하루 밀린 두 계열의 상관이라 전부 0 근처(-0.04 · 0.01 · -0.06)로 나왔다.
한국 주식 베타가 0 일 리 없는데 표가 그렇게 말하고 있었다.

깨지는 방식: asOf 를 다시 떨구면 소비자가 date 로 되돌아가고 같은 오류가 재발한다.
★ parquet 의 date 를 asOf 로 덮어쓰는 "수정"은 더 나쁘다 - 그건 PIT 를 깨서
레짐 연구에 lookahead 를 넣는 것이다. 그래서 **둘 다** 나오는지를 본다.
"""
import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAB = os.path.join(REPO, "research", "strategy-lab")
sys.path.insert(0, LAB)

try:
    import pandas as pd
except ImportError:                                   # pragma: no cover
    print("pandas 없음 - 건너뜀")
    sys.exit(0)

_spec = importlib.util.spec_from_file_location(
    "build_ui_macro", os.path.join(LAB, "build_ui_macro.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


def _df():
    """PIT 조인 결과 모양 그대로 - date 는 쓸 수 있게 된 거래일, 값은 그 전 관측."""
    return pd.DataFrame({
        "date": ["2026-09-04", "2026-09-07", "2026-09-08"],
        "krKospi": [6687.21, 6995.39, 6954.52],
        "krKospiAsOfDate": ["2026-09-03", "2026-09-04", "2026-09-07"],
    })


def test_emits_both_date_and_asof():
    out = mod._series_from(_df(), {"krKospi": "코스피"})
    h = out["krKospi"]["history"]
    ok("세 점", len(h) == 3, h)
    ok("date 는 PIT 사용일 그대로", [p["date"] for p in h] ==
       ["2026-09-04", "2026-09-07", "2026-09-08"], h)
    ok("asOf 는 실제 관측일", [p["asOf"] for p in h] ==
       ["2026-09-03", "2026-09-04", "2026-09-07"], h)
    ok("값은 안 건드린다", h[0]["value"] == 6687.21, h)


def test_series_without_provenance_still_works():
    """AsOfDate 컬럼이 없는 시리즈(파생·직접계산)는 asOf 없이 그대로 나온다 -
    없는 것을 date 로 지어내지 않는다(교훈57)."""
    df = pd.DataFrame({"date": ["2026-09-04"], "krCreditSpreadBp": [55.0]})
    h = mod._series_from(df, {"krCreditSpreadBp": "신용스프레드"})["krCreditSpreadBp"]["history"]
    ok("asOf 키가 아예 없다", "asOf" not in h[0], h)
    ok("값은 그대로", h[0]["value"] == 55.0, h)


def test_drops_rows_with_missing_value_not_missing_asof():
    """값이 없는 날은 뺀다. 하지만 asOf 만 없는 날은 값이 있으므로 남긴다 -
    provenance 가 없다고 관측치를 버리면 없는 구멍이 생긴다."""
    df = pd.DataFrame({
        "date": ["2026-09-04", "2026-09-07"],
        "krKospi": [6687.21, None],
        "krKospiAsOfDate": [None, "2026-09-04"],
    })
    h = mod._series_from(df, {"krKospi": "코스피"})["krKospi"]["history"]
    ok("값 없는 날은 뺀다", [p["date"] for p in h] == ["2026-09-04"], h)
    ok("asOf 만 없으면 값은 남긴다", h[0]["value"] == 6687.21, h)


def run_all():
    for fn in (test_emits_both_date_and_asof,
               test_series_without_provenance_still_works,
               test_drops_rows_with_missing_value_not_missing_asof):
        fn()
    print(f"test-ui-macro-asof: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_all())
