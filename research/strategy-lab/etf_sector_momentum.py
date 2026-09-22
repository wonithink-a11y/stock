"""업종 ETF 모멘텀 (사전등록 findings/etf-sector-momentum-preregistration-2026-09.md).

    python research/strategy-lab/etf_sector_momentum.py units     # 1단계: 기초지수 단위 목록 CSV(수익률 계산 없음)
    python research/strategy-lab/etf_sector_momentum.py run       # 2단계: 단위 CSV·수동 수정이 커밋돼 있어야만 돈다
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import etf_cross_section as X  # noqa: E402

UNITS = HERE / "findings" / "etf-sector-momentum-units-2026-09.csv"
MANUAL = HERE / "findings" / "etf-sector-momentum-manual-2026-09.json"      # 사람 검토 {정규화 지수명: [분류, 사유]}

# §1 시장 대표지수 제외 목록(동결) — 공백·대소문자 무시 정확 일치
BROAD = ["코스피", "코스피 TR", "코스피 50", "코스피 100", "코스피 200", "코스피 200 TR", "코스피 200 동일가중지수", "코스피 100 동일가중지수",
         "코스피 200 선물지수", "코스피200제외 코스피지수", "코스피 200 초대형제외 지수", "코스피 대형주", "코스피 중형주", "코스피 200 중소형주지수",
         "코스닥", "코스닥 150", "F-코스닥150 지수", "KRX 100", "KRX 100 동일가중지수", "KRX 300", "KTOP 30", "MSCI Korea Index",
         "MSCI Korea TR Index", "FnKorea 50 지수", "코스피200 롱 100% 코스닥150 숏"]


def norm(s: str) -> str:
    return "".join((s or "").split()).lower()


BROAD_N = {norm(b) for b in BROAD}


def cmd_units() -> int:
    dom = {r["code"]: r["names"].split(" | ")[-1] for r in csv.DictReader(X.UNIV.open(encoding="utf-8")) if r["class"] == "국내주식형"}
    rows, _ = X.load_rows()
    info = defaultdict(lambda: {"names": set(), "etfs": set(), "first": "99999999", "last": ""})
    for (d, c), r in rows.items():
        if c not in dom or not (X.START.replace("-", "") <= d <= X.END.replace("-", "")):
            continue
        idx = (r.get("IDX_IND_NM") or "").strip()
        if not idx:
            continue
        x = info[norm(idx)]
        x["names"].add(idx); x["etfs"].add(f"{c} {dom[c]}")
        x["first"], x["last"] = min(x["first"], d), max(x["last"], d)
    manual = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else {}
    out = []
    for k, x in sorted(info.items(), key=lambda kv: kv[1]["first"]):
        cls, why = ("제외", "시장 대표지수(§1 목록)") if k in BROAD_N else ("포함", "")
        if k in manual:                                 # [분류, 사유] 또는 ["병합", 사유, 합칠 단위키]
            cls, why = manual[k][0], "수동: " + manual[k][1] + (f" → {manual[k][2]}" if len(manual[k]) > 2 else "")
        out.append([k, " | ".join(sorted(x["names"])), len(x["etfs"]), " | ".join(sorted(x["etfs"]))[:300], x["first"], x["last"], cls, why])
    with UNITS.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["unit_key", "index_names", "n_etfs", "etfs", "first", "last", "class", "reason"])
        w.writerows(out)
    inc = sum(1 for r in out if r[6] == "포함")
    print(f"기초지수 {len(out)}개 → 포함 {inc} · 제외 {len(out) - inc}. 저장 {UNITS.relative_to(REPO)}")
    return 0


def cmd_run() -> int:
    for p in (UNITS, MANUAL):
        if p.exists() and not X._committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률 계산을 하지 않는다(사전등록 §1)")
            return 2
    if not UNITS.exists():
        print("단위 CSV 가 없다 — units 부터")
        return 2
    print("2단계는 단위 목록 커밋 뒤에 구현·실행한다.")
    return 0


if __name__ == "__main__":
    sys.exit({"units": cmd_units, "run": cmd_run}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__) or 2)())
