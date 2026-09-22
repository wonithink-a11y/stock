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


FIXED_BP = 2 * 1.40527 + 2 * 0.3640                        # 3.54bp — 세금 0(사전등록 §4)


def build_panel(dom: set, start: str = START, end: str = END):
    """유동 국내주식형 ETF 종목일 패널(on·ret·pdh·volr·tk) + 거래일 목록. 결과 실험과 forward 그림자가 같은 코드를 쓴다.
    on(밤사이)은 다음 거래일 시가가 있어야 값이 있다 — 그림자는 on 이 빈 마지막 날을 다음 실행으로 미룬다."""
    import numpy as np
    import pandas as pd
    rows, _ = load_rows()
    num = lambda v: float(str(v).replace(",", "")) if str(v).replace(",", "").replace(".", "", 1).isdigit() else np.nan   # noqa: E731
    recs = [{"date": d, "ticker": c, "open": num(r.get("TDD_OPNPRC")), "high": num(r.get("TDD_HGPRC")),
             "low": num(r.get("TDD_LWPRC")), "close": num(r.get("TDD_CLSPRC")), "volume": num(r.get("ACC_TRDVOL")),
             "value": num(r.get("ACC_TRDVAL"))} for (d, c), r in rows.items() if start.replace("-", "") <= d <= end.replace("-", "")]
    a = pd.DataFrame(recs)
    valid = (a[["open", "high", "low", "close"]] > 0).all(axis=1) & (a.volume > 0)
    tdays = np.sort(a.loc[valid, "date"].unique())                # 거래일 = 거래가 한 건이라도 있는 날(휴장일 행 제외, §2-부록)
    a = a[valid & a.ticker.isin(dom)].copy()
    a["di"] = np.searchsorted(tdays, a.date)
    a = a.sort_values(["ticker", "di"]).reset_index(drop=True)
    g = a.groupby("ticker")
    prev_ok = g.di.shift(1) == a.di - 1                            # 바로 전 거래일에 이 종목이 있었나
    next_ok = g.di.shift(-1) == a.di + 1
    a["pc"] = np.where(prev_ok, g.close.shift(1), np.nan)
    a["pdh"] = np.where(prev_ok, g.high.shift(1), np.nan)
    a["ret"] = a.close / a.pc - 1
    cont20 = (a.di - g.di.shift(20)) == 20                         # 직전 20거래일이 빠짐없이 있다(§1: 20일 미만 이력 제외)
    a["liq"] = np.where(cont20, g.value.transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean()), np.nan)
    a["volr"] = a.volume / np.where(cont20, g.volume.transform(lambda s: s.shift(1).rolling(20, min_periods=20).mean()), np.nan)
    a["on"] = np.where(next_ok, g.open.shift(-1) / a.close - 1, np.nan) * 1e4
    a["date"] = pd.to_datetime(a.date)
    u = a[(a.liq >= 2e9) & a.ret.notna()].copy()
    tick = np.where((u.date >= "2023-12-11") & (u.close < 2000), 1.0, 5.0)   # ETF 호가단위(§4, 날짜별)
    u["tk"] = tick / u.close * 1e4
    return u, tdays, {"etf_total": len({c for _, c in rows}), "domestic_traded": int(a.ticker.nunique())}


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
    import numpy as np
    import pandas as pd
    sys.path.insert(0, str(REPO / "research" / "strategy-lab" / "futures"))
    from structure_phase4 import family, judge          # 개별주 실험과 같은 판정·바닥선(사전등록 §5)
    from short_horizon_study import tstat

    dom = {r["code"] for r in csv.DictReader(UNIV.open(encoding="utf-8")) if r["class"] == "국내주식형"}
    u, tdays, meta = build_panel(dom)
    u = u[u.on.notna()].copy()
    fixed = FIXED_BP
    cells_def = {"O0": u.ret.notna(), "O2b": (u.close > u.pdh) & (u.volr >= 1.5), "O3u": u.ret >= 0.05}
    mkt = u.groupby("date").on.mean()
    split = lambda d: "TRAIN" if d.year <= 2020 else ("VALID" if d.year <= 2022 else "TEST")   # noqa: E731
    cells, stats = {}, {}
    for cid, cond in cells_def.items():
        ev = u[cond & (u.ret < 0.28)]
        df = pd.DataFrame({"date": ev.date, "i": ev.on - ev.date.map(mkt), "g": ev.on, "tk": ev.tk}).groupby("date").mean()
        cells[cid] = [(dt, r.i, r.g, fixed, fixed + r.tk) for dt, r in df.iterrows()]
        rng = np.random.default_rng(7)
        oos = df[df.index.year >= 2021].g.to_numpy()
        boot = [rng.choice(oos, len(oos)).mean() for _ in range(2000)] if len(oos) else [np.nan]
        stats[cid] = {"events": int(len(ev)), "etfs": int(ev.ticker.nunique()), "days": {k: int(sum(split(d) == k for d in df.index)) for k in ("TRAIN", "VALID", "TEST")},
                      "gross_mean_bp": round(float(ev.on.mean()), 2) if len(ev) else None,
                      "gross_median_bp": round(float(ev.on.median()), 2) if len(ev) else None,
                      "oos_gross_day_bp": round(float(oos.mean()), 2) if len(oos) else None,
                      "oos_gross_ci95": [round(float(np.quantile(boot, q)), 2) for q in (0.025, 0.975)],
                      "breakeven_cost_bp": round(float(oos.mean()), 2) if len(oos) else None,
                      "oos_tick_bp": round(float(df[df.index.year >= 2021].tk.mean()), 2) if len(oos) else None}
    fam = family({c: cells[c] for c in ("O2b", "O3u")}, split, np.random.default_rng(20260922), {"O2b": {"long_only": True}, "O3u": {"long_only": True}})
    res = {"bar": fam["bar"], "cells": fam["cells"], "stats": stats, "cost_fixed_bp": round(fixed, 2),
           "universe": {"etf_total": meta["etf_total"], "domestic": len(dom),
                        "domestic_traded": meta["domestic_traded"], "liquid_etfs": int(u.ticker.nunique()),
                        "liquid_rows": int(len(u)), "trading_days": int(len(tdays))}}
    # O0 은 가족 밖 기준선(§3) — 같은 판정을 참고로만
    parts = {k: tuple(np.array(x, float) for x in zip(*[e[1:] for e in cells["O0"] if split(e[0]) == k]) or ([], [], [], [])) for k in ("TRAIN", "VALID", "TEST")}
    res["O0_reference"] = judge(parts, fam["bar"], long_only=True)
    for cid in ("O2b", "O3u"):                                    # 표본 부족 규칙(§5)
        d = stats[cid]["days"]
        if d["TRAIN"] < 100 or d["VALID"] < 30 or d["TEST"] < 30:
            res["cells"][cid]["verdict"] = "INCONCLUSIVE(표본 부족)"
    out = REPO / "research" / "strategy-lab" / "findings" / "etf-cross-section-close-open-results-2026-09.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit({"universe": cmd_universe, "run": cmd_run}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__) or 2)())
