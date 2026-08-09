"""test-minute-universe.py — 분봉 유니버스 스냅샷 회귀 (합성 픽스처)

가장 중요한 검사는 **미래를 보지 않는가**다. 나머지는 그것을 떠받친다.
스냅샷이 as_of 이후를 읽으면 백테스트가 조용히 좋아지고 아무도 눈치채지 못한다 —
게이트를 두 겹으로 거는 자리다(교훈49).
"""

import gzip
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
PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  PASS  " if cond else "  FAIL  ") + name +
          (("  " + str(detail)) if (detail and not cond) else ""))


def write_a2a(dirpath, year, rows):
    p = Path(dirpath) / (year + ".jsonl.gz")
    with gzip.open(p, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def run_all():
    spec = importlib.util.spec_from_file_location(
        "build_minute_universe", REPO / "scripts" / "build-minute-universe.py")
    M = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)
    pol = M.load_policy()
    tiers = pol["universeTiers"]["tiers"]

    # ---- 티어 경계 -----------------------------------------------------
    cases = [(1000, "Core"), (200, "Core"), (199.99, "Extended"),
             (50, "Extended"), (49.99, "Conditional"), (20, "Conditional"),
             (19.99, "QualityLimited"), (5, "QualityLimited"),
             (4.99, "SignalExcluded"), (0, "SignalExcluded")]
    ok = True
    for eok, want in cases:
        got = (M.tier_of(eok, tiers) or {}).get("analysisTier")
        if got != want:
            ok = False
            check("티어 경계 " + str(eok), False, (got, want))
    check("티어 경계 10건이 정책대로", ok)

    check("경계가 닫힌 구간이라 겹치지 않는다",
          all((M.tier_of(e, tiers) or {}).get("analysisTier") is not None
              for e in (0, 4.99, 5, 19.99, 20, 49.99, 50, 199.99, 200, 1e6)))

    # ---- PIT : as_of 이후를 읽지 않는다 --------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="minuniv-"))
    try:
        rows = []
        # AAA: 과거엔 얇고(1억) 미래에 폭증(1000억)
        for d in range(1, 41):
            rows.append({"ticker": "AAAAAA", "date": "2026-01-%02d" % d,
                         "close": 1000, "volume": 10000})       # 1억
        for d in range(1, 41):
            rows.append({"ticker": "AAAAAA", "date": "2026-06-%02d" % d,
                         "close": 1000, "volume": 10000000})    # 100억
        # BBB: 계속 큰 종목 (대조군)
        for d in range(1, 41):
            rows.append({"ticker": "BBBBBB", "date": "2026-01-%02d" % d,
                         "close": 1000, "volume": 50000000})    # 500억
        write_a2a(tmp, "2026", rows)

        orig_dir, orig_a1a = M.A2A_DIR, M.A1A
        M.A2A_DIR = tmp
        M.A1A = tmp / "nonexistent.jsonl"

        past = M.build("2026-02-01", pol)
        fut = M.build("2026-07-01", pol)
        pa = {r["ticker"]: r for r in past}
        fu = {r["ticker"]: r for r in fut}

        check("as_of 이전 스냅샷이 미래 폭증을 모른다",
              pa["AAAAAA"]["analysisTier"] == "SignalExcluded",
              (pa["AAAAAA"]["analysisTier"], pa["AAAAAA"]["turnoverEok"]))
        check("as_of 이후 스냅샷은 그것을 안다",
              fu["AAAAAA"]["analysisTier"] in ("Core", "Extended"),
              (fu["AAAAAA"]["analysisTier"], fu["AAAAAA"]["turnoverEok"]))
        check("대조군은 두 시점에서 같다",
              pa["BBBBBB"]["analysisTier"] == fu["BBBBBB"]["analysisTier"] == "Core",
              (pa["BBBBBB"]["analysisTier"], fu["BBBBBB"]["analysisTier"]))
        check("selectedAt이 as_of와 같다",
              all(r["selectedAt"] == "2026-02-01" for r in past))
        check("snapshotDate가 모든 행에 있다",
              all(r["snapshotDate"] == "2026-02-01" for r in past))
        check("universeVersion이 정책 버전",
              all(r["universeVersion"] == pol["version"] for r in past))
        check("selectionReason이 비어 있지 않다",
              all(r["selectionReason"] for r in past))

        # 같은 as_of는 같은 결과를 준다
        again = M.build("2026-02-01", pol)
        check("같은 as_of가 같은 스냅샷을 낸다", again == past)

        # ---- 인수 조건 ------------------------------------------------
        checks, passed = M.acceptance(past, "2026-02-01", pol)
        check("정상 스냅샷이 인수 조건 통과", passed,
              [c for c in checks if not c["통과"]])

        broken = json.loads(json.dumps(past))
        broken[0]["collectionTier"] = "Core"
        _, p2 = M.acceptance(broken, "2026-02-01", pol)
        check("수집 티어가 Broad가 아니면 실패 (§6.3 원칙)", not p2)

        broken2 = json.loads(json.dumps(past))
        broken2.append(json.loads(json.dumps(broken2[0])))
        _, p3 = M.acceptance(broken2, "2026-02-01", pol)
        check("중복 종목이 있으면 실패", not p3)

        broken3 = json.loads(json.dumps(past))
        broken3[0]["selectedAt"] = "2026-03-01"
        _, p4 = M.acceptance(broken3, "2026-02-01", pol)
        check("selectedAt이 어긋나면 실패", not p4)

        broken4 = json.loads(json.dumps(past))
        broken4[0]["analysisTier"] = None
        _, p5 = M.acceptance(broken4, "2026-02-01", pol)
        check("티어 미분류가 있으면 실패", not p5)

        M.A2A_DIR, M.A1A = orig_dir, orig_a1a
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 정책이 §6.3과 어긋나지 않는가 ---------------------------------
    check("모든 티어의 collectionTier가 Broad",
          all(t["collectionTier"] == "Broad" for t in tiers),
          [t["bucket"] for t in tiers if t["collectionTier"] != "Broad"])
    check("Core만 246일 백필 대상",
          [t["analysisTier"] for t in tiers if t["backfill246d"] == "yes"]
          == ["Core"])
    check("SignalExcluded만 signalEligible false",
          [t["analysisTier"] for t in tiers if not t["signalEligible"]]
          == ["SignalExcluded"])
    check("Conditional·QualityLimited에 주의문이 있다",
          all(t["signalCaveat"] for t in tiers
              if t["analysisTier"] in ("Conditional", "QualityLimited")))
    check("각 티어에 실측 근거가 붙어 있다",
          all(t.get("measured") for t in tiers))

    print()
    print("  통과 %d · 실패 %d" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("    FAIL " + f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(run_all())
