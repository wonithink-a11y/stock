#!/usr/bin/env python3
"""2026-08-21 PIT 버그 수정(scripts/build-fundamentals-a3d.py _pit_select_asof)이
기존 A3d split·reverseOrConsolidation 493건에 얼마나 영향을 주는지 로컬로만
재계산(DART 재수집 없음, 이미 있는 a3c 타임라인 + 이미 있는 disclosureDate로
a3c_bracket_ratio()를 다시 부른다).

python research/strategy-lab/probe_a3d_pit_fix_impact.py
"""
import gzip
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location(
    "a3d_build", os.path.join(ROOT, "scripts", "build-fundamentals-a3d.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def read_jsonl_gz(rel_path):
    with gzip.open(os.path.join(ROOT, rel_path), "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    timeline = m.load_a3c_timeline()
    rows = []
    for cat_file in ("split", "reverseOrConsolidation"):
        rows.extend(read_jsonl_gz(f"data/backfill/fundamentals/a3d/{cat_file}.jsonl.gz"))

    changed = 0
    now_missing = 0  # 수정 후 None(BRACKET_MISSING)이 되는 것 — 잘못된 값 대신 정직하게 유보
    now_direction_ok = 0  # reverseOrConsolidation인데 old에서 배수>1이던 게 fix 후 <1 또는 None이 된 것
    still_direction_bad = 0
    rows_out = []

    for r in rows:
        old_mult = r.get("multiplier")
        new_ratio = m.a3c_bracket_ratio(r["ticker"], r["disclosureDate"], timeline)
        new_mult = round(new_ratio, 6) if new_ratio is not None else None
        rec = {
            "ticker": r["ticker"], "category": r["category"], "disclosureDate": r["disclosureDate"],
            "oldMultiplier": old_mult, "newMultiplier": new_mult,
        }
        rows_out.append(rec)
        if new_mult != old_mult:
            changed += 1
        if new_mult is None:
            now_missing += 1
        if r["category"] == "reverseOrConsolidation":
            if old_mult is not None and old_mult > 1:
                if new_mult is None or new_mult < 1:
                    now_direction_ok += 1
                elif new_mult > 1:
                    still_direction_bad += 1

    out_dir = os.path.join(ROOT, "research", "strategy-lab", "findings", "a3d-bracket-candidates")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "pit-fix-impact.json"), "w", encoding="utf-8") as f:
        json.dump({
            "totalRecords": len(rows),
            "changedCount": changed,
            "nowMissingCount": now_missing,
            "reverseOrConsolidationDirectionFixedCount": now_direction_ok,
            "reverseOrConsolidationStillDirectionBadCount": still_direction_bad,
            "records": rows_out,
        }, f, ensure_ascii=False, indent=2)

    print(f"전체 {len(rows)}건 중 값이 바뀐 레코드 {changed}건")
    print(f"수정 후 None(BRACKET_MISSING, 정직한 유보)이 된 레코드 {now_missing}건")
    print(f"reverseOrConsolidation 방향모순(배수>1)이던 것 중 "
          f"수정으로 해소된 것 {now_direction_ok}건 / 여전히 모순인 것 {still_direction_bad}건")


def demo():
    assert m._pit_select_asof(
        [("20250814", 2025, "11012", 1), ("20251114", 2025, "11014", 2)], "20260225"
    )[3] == 2, "접수일이 늦은 레코드가 이겨야 한다"
    print("demo OK")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        demo()
    else:
        main()
