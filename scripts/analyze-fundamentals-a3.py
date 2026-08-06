#!/usr/bin/env python3
"""A3 재무 데이터 품질 분석 — 법인별 누락 패턴과 매칭 품질을 본다.

  python scripts/analyze-fundamentals-a3.py            # 요약
  python scripts/analyze-fundamentals-a3.py --holes    # 내부 구멍 법인 전체 목록
  python scripts/analyze-fundamentals-a3.py --json     # 기계가 읽을 형태

**읽기 전용이다.** 네트워크를 쓰지 않고 아무 파일도 쓰지 않는다. 여기서 나오는 것은
전부 파생 결과이므로 저장하지 않는다 — 원시 사실(레코드·recordGaps)만 축적하고
패턴·비율은 볼 때마다 다시 계산한다. 저장하면 원시 사실이 바뀔 때 조용히 낡는다.

입력은 둘 중 있는 것을 쓴다. finalize 전에도 돌려볼 수 있어야 분석기를 수집이
끝나기 전에 검증할 수 있고, 그래야 collect가 끝난 직후 바로 쓸 수 있다.

  data/backfill/fundamentals/a3/*.jsonl.gz     finalize 산출물 (전수)
  data/backfill/fundamentals/_shards/*.jsonl   수집 중간물 (부분)

**부분 표본이면 맨 위에 그렇게 찍는다.** 68%를 100%로 읽는 것이 이 스크립트가
낼 수 있는 가장 나쁜 결과다. 남은 법인은 임의 표본이 아니라 '아직 안 한 것'이라
편향의 방향을 모른다 — 그래서 임계값 확정(FN-1.4 measured)에는 쓰지 않는다.
"""
import argparse
import glob
import gzip
import json
import os
import sys
from collections import Counter, defaultdict

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = "data/backfill/fundamentals/a3"
SHARD_DIR = "data/backfill/fundamentals/_shards"
POLICY = "config/policies/fundamentals.v1.json"

ACCOUNTS = ["currentAssets", "currentLiab", "liabilities", "equity",
            "revenue", "opProfit", "netIncome"]
# 금융업 재무제표에는 유동자산·유동부채가 없다. 커버리지 분자에 넣으면 업종 구성이
# 데이터 품질로 둔갑한다(교훈48). 분자가 무엇인지 먼저 정하고 비율을 잰다.
CORE = ["liabilities", "equity", "revenue", "opProfit", "netIncome"]


def load_records():
    """(레코드, 출처, 전수 여부). 산출물이 있으면 그것을, 없으면 샤드를 읽는다."""
    gz = sorted(glob.glob(f"{OUT_DIR}/*.jsonl.gz"))
    if gz:
        rows = []
        for p in gz:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                rows += [json.loads(l) for l in f if l.strip()]
        return rows, f"{OUT_DIR} ({len(gz)}개 연도 파일)", True
    sh = sorted(glob.glob(f"{SHARD_DIR}/shard-*.jsonl"))
    if not sh:
        return [], "", True
    rows = []
    for p in sh:
        rows += [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    return rows, f"{SHARD_DIR} ({len(sh)}개 샤드 — 수집 중간물)", False


def load_state():
    """(완료 법인, 법인별 공백 사유, 담당 법인 수 합계).

    finalize 후에는 _shards/가 지워지므로 진단에서 읽는다. 두 경로가 같은 사실을
    들고 있고, 어느 쪽이 살아 있는지는 수집 단계에 달렸다.
    """
    done, gaps, assigned = set(), {}, 0
    states = sorted(glob.glob(f"{SHARD_DIR}/_state-*.json"))
    if states:
        for p in states:
            st = json.load(open(p, encoding="utf-8"))
            done |= set(st.get("corpsDone") or [])
            gaps.update(st.get("recordGaps") or {})
            assigned += st.get("corpsAssigned") or 0
        return done, gaps, assigned
    d = f"{OUT_DIR}/_diagnostics.json"
    if os.path.exists(d):
        dg = json.load(open(d, encoding="utf-8"))
        gaps = dg.get("recordGaps") or {}
        assigned = dg.get("corpsAssignedSum") or 0
    return done, gaps, assigned


def target_corps():
    """대상 법인 — 분모다. 없으면 None을 돌려주고 판정하지 않는다(교훈57)."""
    out = {}
    for path, group in [("data/backfill/universe/a1b/delisted.jsonl", "delisted"),
                        ("data/backfill/universe/a1a/current.jsonl", "current")]:
        if not os.path.exists(path):
            return None
        for l in open(path, encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                out[r["corp"]] = group
    return out


def analyze(rows, done, gaps, targets, pol):
    """모든 값이 파생이다. 여기서 나온 것은 저장하지 않는다."""
    y_from, y_to = pol["fiscalYearFrom"], pol["fiscalYearTo"]
    all_years = list(range(y_from, y_to + 1))

    years_by_corp = defaultdict(set)
    fsdiv_by_corp = defaultdict(set)
    for r in rows:
        years_by_corp[r["corp"]].add(r["fiscalYear"])
        fsdiv_by_corp[r["corp"]].add(r.get("fsDiv"))
    with_rec = set(years_by_corp)

    o = {"records": len(rows), "corpsWithRecords": len(with_rec),
         "corpsDone": len(done), "fiscalYearRange": [y_from, y_to]}

    # ── 누락 패턴 세 유형 ──────────────────────────────────────
    # 유형이 서로 배타적이지 않다. 한 법인이 '중간에 구멍'이면서 '뒤가 잘린' 수 있다.
    # 그래서 합계를 내지 않는다 — 합치면 이중계상이고, 각 유형은 다른 질문의 답이다.
    holes, tail_cut, head_late = [], [], []
    for c in with_rec:
        ys = sorted(years_by_corp[c])
        miss = [y for y in range(ys[0], ys[-1] + 1) if y not in years_by_corp[c]]
        if miss:
            holes.append({"corp": c, "from": ys[0], "to": ys[-1], "missing": miss,
                          "reasons": {str(y): gaps.get(c, {}).get(str(y)) for y in miss}})
        if ys[-1] < y_to:
            tail_cut.append({"corp": c, "lastYear": ys[-1]})
        if ys[0] > y_from:
            head_late.append({"corp": c, "firstYear": ys[0]})

    o["fullRange"] = sum(1 for c in with_rec if len(years_by_corp[c]) == len(all_years))
    o["internalHoles"] = len(holes)
    o["internalHolesDetail"] = sorted(holes, key=lambda x: x["corp"])
    o["tailCut"] = len(tail_cut)
    o["headLate"] = len(head_late)
    o["tailCutByLastYear"] = dict(sorted(Counter(x["lastYear"] for x in tail_cut).items()))

    # 사유를 아는 구멍과 모르는 구멍. recordGaps는 그 필드를 도입한 뒤 수집한
    # 법인에만 있다 — 이미 done인 법인은 재스캔하지 않으므로 영영 채워지지 않는다.
    known = sum(1 for h in holes for v in h["reasons"].values() if v)
    total_missing = sum(len(h["missing"]) for h in holes)
    o["holeYears"] = total_missing
    o["holeYearsWithReason"] = known
    o["holeYearsWithoutReason"] = total_missing - known

    # ── 레코드 0건으로 완료된 법인 ────────────────────────────
    # 정상이다 — 그 법인이 그 기간에 사업보고서를 낸 적이 없다는 뜻일 수 있다.
    # 다만 그것이 사실인지 손실인지는 recordGaps만 답한다.
    zero = sorted(done - with_rec)
    o["corpsDoneWithNoRecords"] = len(zero)
    o["corpsDoneWithNoRecordsWithReason"] = sum(1 for c in zero if gaps.get(c))

    # ── fsDiv 패턴 ────────────────────────────────────────────
    # OFS는 '그 (법인, 연도)에 연결이 없었다'는 뜻이다. 주요계정은 fs_div가 요청
    # 파라미터가 아니라 응답 행의 필드라 연결·별도가 함께 오고, 선별이 CFS를 먼저
    # 본다 — 그래서 '연결이 있었는데 별도만 수집했다'는 경우는 존재하지 않는다.
    o["fsDivRecords"] = dict(Counter(r.get("fsDiv") for r in rows))
    o["fsDivByCorp"] = {"+".join(sorted(k)): v for k, v in
                        Counter(tuple(sorted(v)) for v in fsdiv_by_corp.values()).items()}

    # ── 계정 매칭 ─────────────────────────────────────────────
    o["accountPresence"] = {}
    for a in ACCOUNTS:
        n = sum(1 for r in rows if r.get(a) is not None)
        o["accountPresence"][a] = {"n": n, "rate": round(n / len(rows), 4) if rows else None}
    src = Counter()
    for r in rows:
        for v in (r.get("accountSource") or {}).values():
            src[v or "MISS"] += 1
    o["accountSource"] = dict(src)
    o["accountSourceByAccount"] = {
        a: dict(Counter((r.get("accountSource") or {}).get(a) or "MISS" for r in rows))
        for a in ACCOUNTS}

    # 핵심 계정 전부를 가진 레코드의 비율. 유동자산·유동부채를 뺀 분자다.
    o["coreComplete"] = sum(1 for r in rows if all(r.get(a) is not None for a in CORE))
    o["coreCompleteRate"] = round(o["coreComplete"] / len(rows), 4) if rows else None

    # ── 공백 사유 분포 ────────────────────────────────────────
    o["recordGapCorps"] = len(gaps)
    o["recordGapReasons"] = dict(Counter(
        v.split(":", 1)[0] for g in gaps.values() for v in g.values()))

    # ── 그룹별 (현재 상장 / 폐지) ─────────────────────────────
    if targets:
        o["corpsTargeted"] = len(targets)
        g_rec, g_tgt = Counter(), Counter(targets.values())
        for c in with_rec:
            if c in targets:
                g_rec[targets[c]] += 1
        o["corpsWithRecordsByGroup"] = dict(g_rec)
        o["corpsTargetedByGroup"] = dict(g_tgt)
        o["corpsWithRecordsRateByGroup"] = {
            k: round(g_rec[k] / v, 4) for k, v in g_tgt.items() if v}
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holes", action="store_true", help="내부 구멍 법인 전체 목록")
    ap.add_argument("--json", action="store_true", help="기계가 읽을 형태")
    a = ap.parse_args()

    os.chdir(ROOT)
    pol = json.load(open(POLICY, encoding="utf-8"))
    rows, source, is_final = load_records()
    if not rows:
        print("A3 레코드가 없다 — 수집을 먼저 돌려라")
        return 1
    done, gaps, assigned = load_state()
    targets = target_corps()
    o = analyze(rows, done, gaps, targets, pol)
    o["source"] = source
    o["isFinalOutput"] = is_final

    if a.json:
        print(json.dumps(o, ensure_ascii=False, indent=2))
        return 0

    print(f"입력  {source}")
    if not is_final:
        # 부분 표본을 전수로 읽는 것이 이 스크립트가 낼 수 있는 가장 나쁜 결과다.
        pct = (f" ({o['corpsDone'] / len(targets) * 100:.1f}%)" if targets else "")
        print(f"\n  ⚠ 수집 중간물이다 — 완료 {o['corpsDone']}"
              f"{'/' + str(len(targets)) if targets else ''}법인{pct}")
        print("    남은 법인은 임의 표본이 아니라 '아직 안 한 것'이라 편향의 방향을 모른다.")
        print("    분석기 검증과 경향 파악에는 쓰고, FN-1.4 임계 확정에는 쓰지 않는다.")

    print(f"\n[규모] 레코드 {o['records']} · 레코드 보유 법인 {o['corpsWithRecords']}"
          f" · 완료 {o['corpsDone']}")
    print(f"  레코드 0건으로 완료된 법인 {o['corpsDoneWithNoRecords']}"
          f" (사유 아는 것 {o['corpsDoneWithNoRecordsWithReason']})")
    if "corpsWithRecordsRateByGroup" in o:
        for k, v in sorted(o["corpsWithRecordsRateByGroup"].items()):
            print(f"  {k:9s} {o['corpsWithRecordsByGroup'].get(k, 0)}"
                  f"/{o['corpsTargetedByGroup'][k]}  {v * 100:.1f}%")

    y0, y1 = o["fiscalYearRange"]
    print(f"\n[누락 패턴] 대상 사업연도 {y0}~{y1}")
    print(f"  전 연도 보유       {o['fullRange']}법인")
    print(f"  중간에 구멍        {o['internalHoles']}법인 · 빈 해 {o['holeYears']}건"
          f" (사유 앎 {o['holeYearsWithReason']} · 모름 {o['holeYearsWithoutReason']})")
    print(f"  뒤가 잘림          {o['tailCut']}법인  마지막 해 분포 {o['tailCutByLastYear']}")
    print(f"  앞이 늦게 시작     {o['headLate']}법인")
    print("  ※ 세 유형은 배타적이지 않다 — 합계를 내지 않는다")

    print(f"\n[연결/별도] 레코드 {o['fsDivRecords']}")
    print(f"  법인별 패턴 {o['fsDivByCorp']}")
    print("  OFS는 '그 (법인, 연도)에 연결이 없었다'는 뜻이다 — 선별이 CFS를 먼저 본다")

    print(f"\n[계정 매칭] 핵심 5계정 전부 보유 {o['coreComplete']}"
          f" ({o['coreCompleteRate'] * 100:.2f}%)")
    print(f"  매칭 수단 {o['accountSource']}")
    for acc, d in o["accountSourceByAccount"].items():
        miss = d.get("MISS", 0)
        if miss:
            print(f"    {acc:15s} MISS {miss}  ({miss / o['records'] * 100:.2f}%)")

    print(f"\n[공백 사유] 기록된 법인 {o['recordGapCorps']} · 사유 분포 {o['recordGapReasons']}")
    if o["recordGapCorps"] == 0:
        print("  아직 비어 있다. recordGaps는 그 필드를 도입한 뒤 수집한 법인에만 쌓인다 —")
        print("  이미 done인 법인은 재스캔하지 않으므로 그 공백의 사유는 채워지지 않는다.")

    if a.holes and o["internalHolesDetail"]:
        print(f"\n[내부 구멍 전체] {o['internalHoles']}법인")
        for h in o["internalHolesDetail"]:
            r = " ".join(f"{y}={h['reasons'][y] or '?'}" for y in sorted(h["reasons"]))
            print(f"  {h['corp']}  {h['from']}~{h['to']}  빠진 해 {h['missing']}  {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
