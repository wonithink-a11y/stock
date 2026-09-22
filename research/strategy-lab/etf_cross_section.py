"""ETF 횡단면 — 종가→익일 시가 O2b·O3u (사전등록 findings/etf-cross-section-close-open-preregistration-2026-09.md).

    python research/strategy-lab/etf_cross_section.py universe     # 1단계: 분류 → 유니버스 CSV(수익률 계산 없음)
    python research/strategy-lab/etf_cross_section.py run          # 2단계: 수익률·판정 — 유니버스 CSV 가 커밋돼 있어야만 돈다

순서를 사람의 규율이 아니라 코드가 지킨다: `run` 은 CSV 가 git 에 커밋돼 있고 작업 트리 수정이 없을 때만 실행한다.
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "research" / "strategy-lab" / "data" / "etf-ohlc"
UNIV = REPO / "research" / "strategy-lab" / "findings" / "etf-cross-section-universe-2026-09.csv"
MANUAL = REPO / "research" / "strategy-lab" / "findings" / "etf-cross-section-manual-2026-09.json"   # 사람 검토 수정 {코드: [분류, 사유]}
START, END = "2010-01-04", "2026-09-21"                  # 표본 기간 고정(수집 기준일 = 사전등록 전날)

# §2 제외 키워드(동결). 영문 3자 이하 키워드는 단어 경계에서만 맞춘다(§2 "VN·CD").
KEYWORDS = {
    "해외": "미국 나스닥 NASDAQ S&P 다우 DOW 필라델피아 러셀 일본 니케이 NIKKEI TOPIX 중국 차이나 CHINA CSI 항셍 HANG 홍콩 인도 INDIA 니프티 "
            "베트남 VN 유럽 유로 EURO STOXX 독일 글로벌 GLOBAL 선진국 신흥국 MSCI_World 대만 브라질 라틴 러시아 호주 캐나다 아시아 ASIA 월드 WORLD 해외",
    "채권·금리·현금성": "채권 국채 회사채 국공채 금융채 특수채 크레딧 금리 CD KOFR SOFR 머니마켓 MMF 통안 단기 초단기 액티브채 TDF TIF 혼합 자산배분 밸런스",
    "원자재·통화": "금현물 골드 GOLD 은_선물 실버 구리 원유 WTI 브렌트 농산물 원자재 커머디티 달러 엔화 위안 통화",
    "구조가 다른 상품": "레버리지 인버스 2X 곱버스 -1X -2X 커버드콜 프리미엄 위클리 옵션 버퍼 타겟 합성 리츠 부동산 인프라",
}


def _pattern(kw: str):
    kw = kw.replace("_", " ")
    if re.fullmatch(r"[-A-Za-z0-9&]{1,3}", kw):
        return re.compile(r"(?<![A-Za-z])" + re.escape(kw) + r"(?![A-Za-z])", re.I)   # 영문자 사이만 막는다(VN30·CD금리는 걸린다)
    return re.compile(re.escape(kw), re.I)


RULES = [(group, kw, _pattern(kw)) for group, ws in KEYWORDS.items() for kw in ws.split()]


def classify(texts) -> str:
    """걸린 키워드 사유('무리:키워드') 또는 '' (= 국내 주식형)."""
    for group, kw, pat in RULES:
        for t in texts:
            if t and pat.search(t):
                return f"{group}:{kw.replace('_', ' ')}"
    return ""


def load_rows():
    """(BAS_DD, ISU_CD) 중복 제거. 표시 줄로 수집 완료 여부도 돌려준다."""
    rows, marks = {}, {}
    for f in sorted(DATA.glob("*.jsonl")):
        for line in f.open(encoding="utf-8"):
            r = json.loads(line)
            if "_day" in r:
                marks[r["_day"]] = r["n"]
            else:
                rows[(r["BAS_DD"], r["ISU_CD"])] = r
    return rows, marks


def cmd_universe() -> int:
    sys.path.insert(0, str(REPO / "research" / "strategy-lab"))
    import collect_etf_ohlc_krx as col
    done = col.done_days()
    todo = [d for d in col.days_to_ask(col.date.fromisoformat(START), col.date.fromisoformat(END)) if d not in done]
    if todo:
        print(f"수집 구멍 {len(todo)}일(예: {todo[:3]}) — 실행하지 않는다(사전등록 §1)")
        return 1
    rows, marks = load_rows()
    info = defaultdict(lambda: {"names": set(), "idx": set(), "first": "99999999", "last": ""})
    for (d, c), r in rows.items():
        x = info[c]
        x["names"].add((r.get("ISU_NM") or "").strip())
        x["idx"].add((r.get("IDX_IND_NM") or "").strip())
        x["first"], x["last"] = min(x["first"], d), max(x["last"], d)
    manual = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else {}
    out = []
    for c, x in sorted(info.items()):
        why = classify(sorted(x["names"]) + sorted(x["idx"]))
        cls = "제외" if why else "국내주식형"
        if c in manual:
            cls, why = manual[c][0], "수동: " + manual[c][1]
        out.append([c, " | ".join(sorted(n for n in x["names"] if n)), " | ".join(sorted(i for i in x["idx"] if i)),
                    x["first"], x["last"], cls, why])
    UNIV.parent.mkdir(parents=True, exist_ok=True)
    with UNIV.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["code", "names", "index_names", "first", "last", "class", "reason"])
        w.writerows(out)
    n_dom = sum(1 for r in out if r[5] == "국내주식형")
    by = defaultdict(int)
    for r in out:
        if r[5] == "제외":
            by[r[6].split(":")[0]] += 1
    print(f"ETF {len(out)}개(수집 {sum(1 for v in marks.values() if v)}거래일) → 국내주식형 {n_dom} · 제외 {len(out) - n_dom} {dict(by)}")
    print(f"저장 {UNIV.relative_to(REPO)} — 이름만 보고 검토한 뒤 커밋한다(수정은 {MANUAL.name})")
    return 0


def _committed_clean(p: Path) -> bool:
    rel = str(p.relative_to(REPO)).replace("\\", "/")
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=REPO, capture_output=True).returncode == 0
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel], cwd=REPO, capture_output=True, text=True).stdout.strip()
    return tracked and not dirty


def cmd_run() -> int:
    for p in (UNIV, MANUAL):
        if p.exists() and not _committed_clean(p):
            print(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률 계산을 하지 않는다(사전등록 §2-명확화)")
            return 2
    if not UNIV.exists():
        print("유니버스 CSV 가 없다 — universe 부터")
        return 2
    print("2단계(수익률·판정)는 유니버스 커밋 뒤에 구현·실행한다.")
    return 0


if __name__ == "__main__":
    sys.exit({"universe": cmd_universe, "run": cmd_run}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__) or 2)())
