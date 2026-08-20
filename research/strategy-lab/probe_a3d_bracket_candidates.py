#!/usr/bin/env python3
"""A5-3 N=20~30 표본 회귀용 후보 추출 (기계적 1차 조사, 판단 없음).

docs/control/세션인수인계-2026-08-20-c.md §3 "다음 순서 1"의 준비 단계.
data/backfill/fundamentals/a3d/{split,reverseOrConsolidation}.jsonl.gz의 전 레코드에
scripts/build-fundamentals-a3d.py의 실제 _clean_ratio_distance()를 그대로 적용해
(재구현하지 않음 — 로직 드리프트 방지) out-of-tolerance(dist>0.1) 153건 전수와
in-tolerance 대표 표본을 골라 후보 표(JSON)로 낸다. DART 교차검증(진짜 판단)은
Claude가 이 표를 보고 별도로 한다 — 이 스크립트는 후보를 좁히기만 한다.

python research/strategy-lab/probe_a3d_bracket_candidates.py
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
    rows = []
    for cat_file in ("split", "reverseOrConsolidation"):
        rows.extend(read_jsonl_gz(f"data/backfill/fundamentals/a3d/{cat_file}.jsonl.gz"))

    for r in rows:
        r["_dist"] = m._clean_ratio_distance(r.get("multiplier"))
        r["_year"] = str(r.get("disclosureDate") or "")[:4]

    out_of_tol = [r for r in rows if r["_dist"] is not None and r["_dist"] > 0.1]
    in_tol = [r for r in rows if r["_dist"] is not None and r["_dist"] <= 0.1]

    # in-tolerance 대표 표본 — 연도별 최대 2건, split/reverseOrConsolidation 섞어서.
    in_tol_sorted = sorted(in_tol, key=lambda r: (r["_year"], r["category"], r["ticker"]))
    in_tol_sample, seen_year_cat = [], {}
    for r in in_tol_sorted:
        key = (r["_year"], r["category"])
        if seen_year_cat.get(key, 0) >= 2:
            continue
        seen_year_cat[key] = seen_year_cat.get(key, 0) + 1
        in_tol_sample.append(r)
        if len(in_tol_sample) >= 20:
            break

    out_of_tol_sorted = sorted(out_of_tol, key=lambda r: -r["_dist"])

    result = {
        "generatedAt": __import__("datetime").datetime.now().isoformat(),
        "note": "dist=0.1 초과가 outOfTolerance(정책 acceptance.a3cBracketOutOfToleranceWarn). "
                "DART 교차검증은 별도 — 여기는 후보 선정만.",
        "counts": {
            "totalSplitLikeRecords": len(rows),
            "outOfTolerance": len(out_of_tol),
            "inTolerance": len(in_tol),
        },
        "outOfToleranceAll": out_of_tol_sorted,
        "inToleranceSample": in_tol_sample,
    }

    out_dir = os.path.join(ROOT, "research", "strategy-lab", "findings", "a3d-bracket-candidates")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "candidates.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"out-of-tolerance {len(out_of_tol)}건 · in-tolerance 표본 {len(in_tol_sample)}건 -> {out_path}")


def demo():
    """ponytail 최소 회귀 — _clean_ratio_distance 재사용 경로가 안 깨졌는지만 확인."""
    assert m._clean_ratio_distance(2.0) == 0
    assert abs(m._clean_ratio_distance(1.97) - 0.015) < 0.001
    assert m._clean_ratio_distance(None) is None
    print("demo OK")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        demo()
    else:
        main()
