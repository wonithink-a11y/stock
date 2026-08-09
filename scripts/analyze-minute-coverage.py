"""analyze-minute-coverage.py — 커버리지 정찰 산출물을 읽어 표로 만든다.

읽기 전용이다. 네트워크를 쓰지 않는다.
정찰 산출물에는 세션별 '캔들 수'가 들어 있고 비율은 여기서 만든다 -
파생 결과는 저장하지 않고 계산한다(교훈75).

세션 분모는 09:00 시작·15:30 종가단일가 기준이다.
  개장30분  09:00~09:29                    30
  중반      09:30~14:59                   330
  마감30분  15:00~15:19 + 15:30            21
                                    합계  381
15:20~15:29는 종가 단일가 구간이라 1분 캔들이 없다. 분모에 넣으면
마감 세션 커버리지가 구조적으로 낮게 나온다 - 분자가 무엇인지 먼저 정한다(교훈48).
"""

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "data" / "backfill" / "_probe-minute-coverage.json"

SESSION_DENOM = {"개장30분": 30, "중반": 330, "마감30분": 21}


def main():
    d = json.loads(SRC.read_text(encoding="utf-8"))
    buckets = [b["이름"] for b in d["구간정의억"]]
    bucket_of = {}
    for name, items in d["표본"].items():
        for it in items:
            bucket_of[it["ticker"]] = name

    rows = defaultdict(list)
    fails = defaultdict(list)
    for r in d["측정"]:
        b = bucket_of.get(r["ticker"])
        # 실패는 커버리지 0이 아니다. 섞으면 실패율이 품질로 둔갑한다(교훈57).
        (fails if r.get("error") else rows)[b].append(r)

    print()
    print("  구간            표본 실패  커버리지                 최장결측(분)     호출")
    print("                             중앙값   p10    최소   중앙   p90  최대  중앙")
    denom = d["분모"]["일자별"]
    for b in buckets:
        rs = rows.get(b) or []
        if not rs:
            continue
        nf = len(fails.get(b) or [])
        cov = sorted(r["candles"] / (denom.get(r["date"]) or 381) for r in rs)
        gaps = sorted(r.get("longestGapMin", 0) for r in rs)
        n = len(cov)
        print("  " + b.ljust(14) + str(n).rjust(4) + str(nf).rjust(5) +
              ("%8.3f" % st.median(cov)) +
              ("%7.3f" % cov[max(0, int(n * 0.1) - 1)]) +
              ("%7.3f" % cov[0]) +
              ("%7.0f" % st.median(gaps)) +
              ("%6.0f" % gaps[min(n - 1, int(n * 0.9))]) +
              ("%7.0f" % gaps[-1]) +
              ("%7.1f" % st.median(r["calls"] for r in rs)))

    print()
    print("  세션별 커버리지 (분모: 개장30분 30 · 중반 330 · 마감30분 21)")
    print("  구간            개장30분   중반    마감30분   균일도")
    for b in buckets:
        rs = [r for r in (rows.get(b) or []) if r.get("bySession")]
        if not rs:
            continue
        vals = {}
        for s, dn in SESSION_DENOM.items():
            vals[s] = st.median((r["bySession"].get(s, 0) / dn) for r in rs)
        spread = max(vals.values()) - min(vals.values())
        print("  " + b.ljust(14) +
              ("%8.3f" % vals["개장30분"]) +
              ("%8.3f" % vals["중반"]) +
              ("%9.3f" % vals["마감30분"]) +
              ("%9.3f" % spread))

    print()
    print("  일자별 차이 (같은 구간이 두 날 사이에 얼마나 흔들리는가)")
    print("  구간            " + "   ".join(d["일자"]) + "     차이")
    for b in buckets:
        rs = rows.get(b) or []
        if not rs:
            continue
        per = {}
        for dt in d["일자"]:
            v = [r["candles"] / (denom.get(dt) or 381)
                 for r in rs if r["date"] == dt]
            per[dt] = st.median(v) if v else float("nan")
        diff = abs(per[d["일자"][0]] - per[d["일자"][1]])
        print("  " + b.ljust(14) +
              ("%11.3f" % per[d["일자"][0]]) +
              ("%13.3f" % per[d["일자"][1]]) +
              ("%9.3f" % diff))

    print()
    print("  인수 조건")
    for a in d["acceptance"]:
        print("    " + ("PASS" if a["통과"] else "FAIL") + "  " + a["항목"])
        if not a["통과"]:
            print("          " + json.dumps(a["실측"], ensure_ascii=False)[:200])
    print()
    print("  하한 제안: " + json.dumps(d.get("하한제안"), ensure_ascii=False))
    print("  총 호출 " + str(d["callCount"]) + "회 · " +
          str(d["elapsedSeconds"]) + "초")
    print()


if __name__ == "__main__":
    main()
