#!/usr/bin/env python
"""분봉 EMPTY 가 진짜 결손인가 - 일봉 거래량으로 대조한다. (2026-09-11)

물음: `minute.v1.json` 의 `pendingT1.emptyResponseRetries` 를 올리면 분봉을 더
받는가. 그러려면 EMPTY 가 무엇인지부터 알아야 한다.

`collect-minute-kis.py` 의 정의로 EMPTY 는 **KIS 가 rt_cd 정상으로 답했는데
output2 가 0행**이고, 그 종목이 상장 중이며 거래정지도 폐지도 아니고 그날이
거래일인 경우다. 둘 중 하나다.

  (a) 그 종목이 그날 한 주도 안 팔렸다        -> EMPTY 가 진실. 재시도해도 0
  (b) 응답이 새서 그날 분봉을 통째로 잃었다   -> 하루 수십 종목씩 조용한 손실

가르는 방법: 같은 날 **A2a 일봉의 거래량이 0인 종목 수**와 맞춰 본다. 거래가
없었다면 일봉 거래량도 0이어야 한다. 거래정지(HALT)도 거래량 0이므로 함께 센다.

  EMPTY + HALT  ~=  일봉 거래량 0 종목 수      -> (a)
  EMPTY + HALT  <   일봉 거래량 0 종목 수      -> 설명 안 되는 결손이 있다 = (b)

네트워크를 쓰지 않는다. 저장소 데이터만 읽는다.

  python scripts/probe-minute-empty-accounting.py [--year 2026]
"""
import argparse
import collections
import glob
import gzip
import io
import json
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "data", "backfill", "minute", "manifest", "*.json")
A2A = os.path.join(ROOT, "data", "backfill", "price", "a2a", "%s.jsonl.gz")


def load_manifests():
    out = {}
    for f in sorted(glob.glob(MANIFEST)):
        d = json.load(io.open(f, encoding="utf-8"))
        g = d.get("gapReasons") or {}
        out[d["date"]] = {"EMPTY": g.get("EMPTY", 0), "HALT": g.get("HALT", 0),
                          "symbols": d.get("symbols")}
    return out


def zero_volume_by_date(year, want):
    """A2a 일봉에서 날짜별 '거래량 0' 종목 수. volume 이 없거나 0 이면 0 으로 센다."""
    zero, total = collections.Counter(), collections.Counter()
    path = A2A % year
    if not os.path.exists(path):
        return zero, total
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            d = r.get("date")
            if d not in want:
                continue
            total[d] += 1
            if not r.get("volume"):
                zero[d] += 1
    return zero, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="2026")
    ap.add_argument("--show", type=int, default=6, help="앞뒤로 보여줄 날 수")
    a = ap.parse_args()

    man = load_manifests()
    if not man:
        print("manifest 가 없다.")
        return 1
    zero, total = zero_volume_by_date(a.year, set(man))
    dates = sorted(set(man) & set(total))
    if not dates:
        print("%s 년에 겹치는 거래일이 없다 (A2a 는 월 1회 수집이라 뒤쪽이 비어 있을 수 있다)." % a.year)
        return 1

    rows = []
    for d in dates:
        m = man[d]
        s = m["EMPTY"] + m["HALT"]
        rows.append((d, m["EMPTY"], m["HALT"], s, zero[d], s - zero[d]))

    res = [r[5] for r in rows]
    unexplained = [r for r in rows if r[5] < 0]

    print("겹치는 거래일 %d개 (%s년)" % (len(rows), a.year))
    print("  잔차 = EMPTY+HALT − 일봉거래량0   최소 %d · 최대 %d · 중앙값 %d · 표준편차 %.2f"
          % (min(res), max(res), statistics.median(res), statistics.pstdev(res)))
    print("  ★ 설명 안 되는 결손이 있는 날(잔차 < 0): %d" % len(unexplained))
    print()
    head = rows[:a.show]
    tail = rows[-a.show:] if len(rows) > a.show else []
    print("  %-12s %7s %7s %7s %9s %7s" % ("date", "EMPTY", "HALT", "합", "일봉0", "잔차"))
    for r in head + ([("…",) + ("",) * 5] if tail else []) + tail:
        if r[0] == "…":
            print("  …")
            continue
        print("  %-12s %7d %7d %7d %9d %+7d" % r)

    print()
    if unexplained:
        print(">>> 판정: 설명 안 되는 결손이 %d일 있다 - EMPTY 를 재시도로 메울 여지가 있다."
              % len(unexplained))
        return 1
    print(">>> 판정: EMPTY 는 **데이터 손실이 아니다.** 전량 '그날 거래가 없었다'로 설명된다\n"
          "    (잔차가 양수로 일정한 것은 분봉 유니버스가 A2a 보다 그만큼 크기 때문).\n"
          "    emptyResponseRetries 를 올려도 얻을 봉이 없다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
