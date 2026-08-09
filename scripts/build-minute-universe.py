"""build-minute-universe.py — 분봉 유니버스 스냅샷 (MN-1.0 §6.3)

**이 스냅샷은 수집 대상을 거르지 않는다.** Broad는 항상 전체다.
스냅샷이 정하는 것은 '그날 무엇을 Core로 알고 있었는가'이며, 백테스트가
그 시점의 지식만 쓰도록 만드는 장치다.

    Universe (분석 대상)          Raw Collector (수집 대상)
      Core / Extended / Conditional      Broad = 전체
            ↑ 분기마다 재계산                ↑ 선정과 무관하게 매일

`selectedAt`이 이 파일의 존재 이유다. 오늘의 거래대금 상위로 과거를 채점하면
"그때 그 종목이 뜰 걸 알았던" 상태가 된다. 스냅샷을 남기고 백테스트가
`selectedAt <= asOf`인 것만 읽으면 그 경로가 막힌다.

입력: data/backfill/price/a2a/{year}.jsonl.gz   거래대금(종가×거래량)
      data/backfill/universe/a1a/current.jsonl  시장·종목명
      config/policies/minute.v1.json            티어 경계
출력: data/backfill/minute/universe/{snapshotDate}.jsonl

경계는 정책이 아니라 이 스크립트 안에 있지 않다 — minute.v1.json의
`universeTiers`가 단일 출처다. 코드에서 숫자를 고치지 않는다.

사용:
    python scripts/build-minute-universe.py --as-of 2026-08-03
    python scripts/build-minute-universe.py --as-of 2026-08-03 --dry-run
"""

import argparse
import gzip
import json
import statistics as st
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
POLICY = REPO / "config" / "policies" / "minute.v1.json"
A2A_DIR = REPO / "data" / "backfill" / "price" / "a2a"
A1A = REPO / "data" / "backfill" / "universe" / "a1a" / "current.jsonl"
OUT_DIR = REPO / "data" / "backfill" / "minute" / "universe"
CALENDAR = REPO / "data" / "backfill" / "calendar.json"
KST = timezone(timedelta(hours=9))


def stamp():
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def load_policy():
    return json.loads(POLICY.read_text(encoding="utf-8"))


def trading_days():
    try:
        return json.loads(CALENDAR.read_text(encoding="utf-8"))["tradingDays"]
    except Exception:
        return []


def turnover_asof(as_of, window):
    """as_of 이전 window 거래일의 거래대금 중앙값.

    **as_of 이후 데이터를 읽지 않는다.** 이것이 PIT의 실체다 -
    파일에 미래가 들어 있어도 여기서 잘라야 스냅샷이 미래를 모른다.
    """
    years = sorted({as_of[:4], str(int(as_of[:4]) - 1)})
    rows = defaultdict(list)
    for y in years:
        p = A2A_DIR / (y + ".jsonl.gz")
        if not p.exists():
            continue
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r["date"] > as_of:
                    continue
                rows[r["ticker"]].append((r["date"], r["close"] * r["volume"]))
    med, obs = {}, {}
    for tk, v in rows.items():
        v.sort()
        tail = [x[1] for x in v[-window:]]
        if len(tail) >= max(20, window // 3):
            med[tk] = st.median(tail)
            obs[tk] = len(tail)
    return med, obs


def load_meta():
    meta = {}
    if A1A.exists():
        for line in A1A.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                meta[r["ticker"]] = {"market": r.get("market"),
                                     "name": r.get("name"),
                                     "listedAt": r.get("listedAt")}
            except Exception:
                pass
    return meta


def tier_of(turnover_eok, tiers):
    """경계는 정책이 정한다. 위에서부터 처음 맞는 것."""
    for t in tiers:
        lo = t["minTurnoverEok"]
        hi = t.get("maxTurnoverEok")
        if turnover_eok >= lo and (hi is None or turnover_eok < hi):
            return t
    return None


def build(as_of, pol):
    tiers = pol["universeTiers"]["tiers"]
    window = pol["universeTiers"]["turnoverWindowTradingDays"]
    med, obs = turnover_asof(as_of, window)
    meta = load_meta()

    rows = []
    for tk in sorted(med):
        eok = med[tk] / 1e8
        t = tier_of(eok, tiers)
        m = meta.get(tk) or {}
        rows.append({
            "snapshotDate": as_of,
            "selectedAt": as_of,
            "universeVersion": pol["version"],
            "ticker": tk,
            "market": m.get("market"),
            "name": m.get("name"),
            "turnoverEok": round(eok, 2),
            "turnoverWindow": obs[tk],
            "liquidityBucket": (t or {}).get("bucket"),
            "collectionTier": (t or {}).get("collectionTier"),
            "analysisTier": (t or {}).get("analysisTier"),
            "signalEligible": (t or {}).get("signalEligible"),
            "selectionReason": (t or {}).get("reason"),
        })
    return rows


def summarize(rows):
    per = defaultdict(int)
    for r in rows:
        per[r["analysisTier"]] += 1
    return dict(per)


def acceptance(rows, as_of, pol):
    checks = []

    def add(name, ok, detail):
        checks.append({"항목": name, "통과": bool(ok), "실측": detail})

    add("종목이 하나 이상", len(rows) > 0, {"종목": len(rows)})
    add("모든 행에 selectedAt", all(r["selectedAt"] == as_of for r in rows),
        {"as_of": as_of})
    unresolved = [r["ticker"] for r in rows if not r["analysisTier"]]
    add("티어가 정해지지 않은 종목 0", not unresolved,
        {"미분류": unresolved[:5]})
    # Broad가 전체인지 - 이것이 §6.3의 원칙이다.
    not_broad = [r["ticker"] for r in rows if r["collectionTier"] != "Broad"]
    add("수집 티어가 전 종목 Broad (유니버스로 Raw를 거르지 않는다)",
        not not_broad, {"예외": not_broad[:5]})
    dupes = len(rows) - len({r["ticker"] for r in rows})
    add("중복 종목 0", dupes == 0, {"중복": dupes})
    # 미래를 보지 않았는가. 창 관측치가 as_of 이전 거래일 수를 넘을 수 없다.
    add("관측 창이 정책 상한 이내",
        all(r["turnoverWindow"] <= pol["universeTiers"]
            ["turnoverWindowTradingDays"] for r in rows),
        {"상한": pol["universeTiers"]["turnoverWindowTradingDays"]})
    return checks, all(c["통과"] for c in checks)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    pol = load_policy()
    td = trading_days()
    if td and args.as_of not in td:
        print("  [주의] " + args.as_of + " 는 캘린더의 영업일이 아니다")

    rows = build(args.as_of, pol)
    checks, passed = acceptance(rows, args.as_of, pol)
    summary = summarize(rows)

    print()
    print("  분봉 유니버스 스냅샷  as-of " + args.as_of)
    print("  생성 " + stamp())
    print()
    for t in pol["universeTiers"]["tiers"]:
        n = summary.get(t["analysisTier"], 0)
        print("  " + str(t["analysisTier"]).ljust(18) +
              str(n).rjust(6) + "종목   " + t["bucket"])
    print("  " + "합계".ljust(18) + str(len(rows)).rjust(6) + "종목")
    print()
    for c in checks:
        print(("  PASS  " if c["통과"] else "  FAIL  ") + c["항목"] +
              ("" if c["통과"] else "  " +
               json.dumps(c["실측"], ensure_ascii=False)[:120]))
    print()

    if not passed:
        return 1
    if args.dry_run:
        print("  --dry-run: 쓰지 않았다")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / (args.as_of + ".jsonl")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("  " + str(out.relative_to(REPO)) + "  (" + str(len(rows)) + "행)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
