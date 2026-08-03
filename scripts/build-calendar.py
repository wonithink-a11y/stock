#!/usr/bin/env python3
"""
A0.5 — 거래일 캘린더 생성 (백필 체인의 첫 고리)

캘린더가 A1보다 먼저인 이유: 유니버스를 '월초 기준'으로 복원하는데 월초가 휴일이면
무엇을 조회할지 정할 수 없다. 캘린더가 유니버스의 입력이다.

출력: data/backfill/calendar.json
  tradingDays   실제 거래일 전량 (warm-up 포함 구간)
  snapshotDays  '그 주의 마지막 거래일' — 금요일이 휴장이면 목요일이다
  monthFirst    월별 첫 거래일 (A1 조회 기준일)
  warmupDays    첫 스냅샷 이전에 확보된 거래일 수

forward return의 d20/d60/d120은 달력일이 아니라 tradingDays 인덱스 오프셋이다.
"""
import json
import os
import sys
from datetime import date

# warm-up 시작점. 2015-01-01로 잡으면 첫 스냅샷(2016-01-08) 이전 거래일이 약 251일이라
# 현재 요구치 252를 1일 차이로 못 채운다. 여유를 두고 2014부터 받는다
# (지표 lookback이 늘어도 캘린더를 다시 만들지 않게 하기 위함).
FROM = os.environ.get("CAL_FROM", "20140101")
TO = os.environ.get("CAL_TO", date.today().strftime("%Y%m%d"))
ANALYSIS_FROM = os.environ.get("CAL_ANALYSIS_FROM", "2016-01-01")
KOSPI_INDEX = "1001"
OUT = "data/backfill/calendar.json"

# 지표 lookback의 최댓값. criteria의 technical 파라미터가 늘어나면 여기도 올린다.
# (A5는 criteria에서 런타임 산출한 값과 이 수치를 대조한다 — 문서만 고치고 잊는 것을 막는다)
REQUIRED_WARMUP = int(os.environ.get("CAL_REQUIRED_WARMUP", "252"))

fails = []


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def fetch_trading_days():
    from pykrx import stock
    df = stock.get_index_ohlcv_by_date(FROM, TO, KOSPI_INDEX)
    if df is None or df.empty:
        raise RuntimeError("KOSPI 지수 조회가 비었다 — 거래일을 복원할 수 없다")
    return [d.strftime("%Y-%m-%d") for d in df.index]


def build(days):
    # 주 단위 그룹: ISO 주차 기준. 연말/연초 주가 두 해에 걸쳐도 한 주로 묶인다.
    week_last = {}
    month_first = {}
    for d in days:
        y, m, dd = (int(x) for x in d.split("-"))
        iso = date(y, m, dd).isocalendar()
        week_last[(iso[0], iso[1])] = d          # 정렬된 입력이므로 마지막 대입이 그 주 마지막 거래일
        month_first.setdefault(f"{y:04d}-{m:02d}", d)

    snapshots = sorted(v for v in week_last.values() if v >= ANALYSIS_FROM)
    warmup = days.index(snapshots[0]) if snapshots else 0
    return snapshots, month_first, warmup


def validate(days, snapshots, month_first, warmup):
    print("[인수 조건]")
    chk(days == sorted(days), "tradingDays 오름차순")
    chk(len(days) == len(set(days)), "tradingDays 중복 없음")

    weekend = [d for d in days if date(*map(int, d.split("-"))).weekday() >= 5]
    chk(not weekend, f"주말 거래일 없음 (발견 {len(weekend)}건)")

    per_year = {}
    for d in days:
        per_year[d[:4]] = per_year.get(d[:4], 0) + 1
    full_years = [y for y in per_year if y not in (days[0][:4], days[-1][:4])]
    bad = {y: per_year[y] for y in full_years if not (200 <= per_year[y] <= 260)}
    chk(not bad, f"연도별 거래일 200~260 범위 (이상치 {bad})")

    dayset = set(days)
    chk(all(s in dayset for s in snapshots), "snapshotDays ⊂ tradingDays")
    chk(all(v in dayset for v in month_first.values()), "monthFirst ⊂ tradingDays")

    # 주간 스냅샷이므로 연 48~53개. 벗어나면 주 그룹핑이 깨진 것이다.
    per_year_snap = {}
    for s in snapshots:
        per_year_snap[s[:4]] = per_year_snap.get(s[:4], 0) + 1
    fy = [y for y in per_year_snap if y not in (snapshots[0][:4], snapshots[-1][:4])]
    bads = {y: per_year_snap[y] for y in fy if not (48 <= per_year_snap[y] <= 53)}
    chk(not bads, f"연도별 스냅샷 48~53개 (이상치 {bads})")

    chk(warmup >= REQUIRED_WARMUP,
        f"첫 스냅샷 이전 warm-up 거래일 {warmup} >= {REQUIRED_WARMUP}")


def main():
    days = fetch_trading_days()
    snapshots, month_first, warmup = build(days)

    validate(days, snapshots, month_first, warmup)
    if fails:
        print(f"\n인수 조건 {len(fails)}건 실패 — 캘린더를 쓰지 않는다")
        sys.exit(1)

    out = {
        "schemaVersion": "CAL-1.0",
        "market": "KR",
        "source": "pykrx:index_ohlcv:1001",
        "from": days[0],
        "to": days[-1],
        "analysisFrom": ANALYSIS_FROM,
        "warmupDays": warmup,
        "tradingDayCount": len(days),
        "snapshotCount": len(snapshots),
        "tradingDays": days,
        "snapshotDays": snapshots,
        "monthFirst": month_first,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # LF 고정 · BOM 없음 · UTF-8. newline='\n'을 빼면 플랫폼에 따라 CRLF가 섞여 해시가 갈린다.
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"\n{OUT} — 거래일 {len(days)} · 스냅샷 {len(snapshots)} · warm-up {warmup}")
    print(f"구간 {days[0]} ~ {days[-1]} / 첫 스냅샷 {snapshots[0]}")


if __name__ == "__main__":
    main()
