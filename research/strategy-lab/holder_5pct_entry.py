"""DART 5% 대량보유 신규 진입 공시 → 주가 — 계산 (사전등록 findings/holder-5pct-entry-preregistration-2026-10.md).

    python research/strategy-lab/holder_5pct_entry.py selftest
    python research/strategy-lab/holder_5pct_entry.py collect   # DART list D001, 2012-01~ 분기 창(≈1,500콜) — 사용자 확인 뒤
    python research/strategy-lab/holder_5pct_entry.py count     # 사건 수 + 원문 표본 150건 진입 일치율(수익률 없음)
    python research/strategy-lab/holder_5pct_entry.py run       # 사전등록·이 파일이 커밋된 상태에서만

사전등록에 없는 구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다):
- 수집 = list.json pblntf_detail_ty=D001 회사 지정 없이 분기 창(3개월 제한), 100건씩 끝까지. 창 파일이 있으면 건너뛴다(진행 중 분기는 다시 받는다).
  저장 data/dart_event_titles/d001_list/YYYYQn.jsonl(gitignore — dart_event_titles/ 아래). 폐지 회사도 stock_code 가 남아 함께 온다.
- 계열 = scripts/build-holder-map.py 의 canon(보고자명) — 같은 종목·같은 계열의 D001(정정 포함)이 직전 1,095일 안에 없던 첫 보고 = 사건.
  '[기재정정]'·'정정' 이 제목에 있는 보고는 사건이 되지 않는다(이력에는 넣는다).
- 셀: E3 = 계열 국민연금공단(제목 무관) · E1 = 제목 '(약식)' ∧ 국민연금 아님 · E2 = 제목 '(일반)' ∧ 국민연금 아님. 둘 다 아닌 제목은 버린다(rec 에 센다).
- 신호일 t = 접수일 이하 마지막 시장 거래일(A2a+A2b 유효 행이 있는 날 합집합). 그 종목의 t 행이 없으면(정지 등) 사건 아님.
- 일봉·적격·분위·대조·진입·청산·판정 = bb_lower_reentry 의 load_panel·events·returns·summarize 그대로(모듈 상수 SIGNALS·HS·PREREG·OUT 만 바꿔 쓴다).
  적격에 상장 경과(그 종목 유효 행 ≥ 250, 당일 제외)를 더한다 — 상장 직후 기존 주주의 의무 보고를 거른다. 시총·5일 수익률 분위는 bb 적격 집합 기준 그대로.
  대조 후보 = 같은 날·같은 시총 3분위·같은 5일 수익률 5분위의 적격 종목 중 그날 그 셀 사건이 아닌 종목(자기 제외), 최대 5.
- 원문 표본: 셀마다 사건(군집 제거 뒤, 공식) 무작위 50건(SEED) document.xml → '직전/이번 보고서' 비율. 진입 일치 = 이번 ≥ 5 ∧ (직전 없음 ∨ 직전 < 5).
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import time
from collections import Counter
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))

PREREG = HERE / "findings" / "holder-5pct-entry-preregistration-2026-10.md"
OUT = HERE / "findings" / "holder-5pct-entry-results-2026-10.json"
RAW = HERE / "data" / "dart_event_titles" / "d001_list"
CELLS = ("E1", "E2", "E3")
HS = (5, 20, 60)
LOOKBACK_DAYS = 1095
MIN_AGE = 250
SAMPLE = 50
SEED = 20261017
NPS = "국민연금공단"

_spec = importlib.util.spec_from_file_location("holder_map", REPO / "scripts" / "build-holder-map.py")
hm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hm)


def quarters(start=date(2012, 1, 1), end=None):
    end = end or date.today()
    y, q = start.year, 1
    while date(y, 3 * q - 2, 1) <= end:
        a = date(y, 3 * q - 2, 1)
        b = date(y + (q == 4), (3 * q) % 12 + 1, 1)
        yield f"{y}Q{q}", a.strftime("%Y%m%d"), min(date.fromordinal(b.toordinal() - 1), end).strftime("%Y%m%d"), b > end
        y, q = (y + 1, 1) if q == 4 else (y, q + 1)


def cmd_collect():
    key = hm.load_env().get("DART_API_KEY")
    if not key:
        raise SystemExit("DART_API_KEY 가 필요하다")
    RAW.mkdir(parents=True, exist_ok=True)
    calls = 0
    for name, a, b, partial in quarters():
        p = RAW / f"{name}.jsonl"
        if p.exists() and not partial:
            continue
        rows = []
        for pg in range(1, 1000):
            page = hm.dart("list", key, bgn_de=a, end_de=b, pblntf_detail_ty="D001", page_count=100, page_no=pg)
            calls += 1
            rows += [{k: r.get(k) for k in ("stock_code", "corp_code", "corp_cls", "corp_name", "flr_nm", "report_nm", "rcept_dt", "rcept_no")}
                     for r in page]
            time.sleep(0.05)
            if len(page) < 100:
                break
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        print(name, len(rows), "calls", calls)
    return 0


def load_raw():
    rows = []
    for p in sorted(RAW.glob("*.jsonl")):
        rows += [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x]
    return rows


def cell_of(r):
    who = hm.canon(r["flr_nm"])
    if who == NPS:
        return "E3"
    t = r["report_nm"] or ""
    return "E1" if "(약식)" in t else "E2" if "(일반)" in t else None


def first_reports(rows, rec):
    """[(ticker, rcept_dt int, cell, rcept_no)] — 같은 종목·계열의 직전 1,095일 안 보고(정정 포함)가 없던 첫 보고."""
    by = {}
    for r in rows:
        if r.get("stock_code") and re.fullmatch(r"[0-9A-Z]{6}", r["stock_code"]):
            by.setdefault((r["stock_code"], hm.canon(r["flr_nm"])), []).append(r)
    out = []
    for (tk, _), rs in by.items():
        rs.sort(key=lambda r: (r["rcept_dt"], r["rcept_no"]))
        last = None
        for r in rs:
            d = datetime.strptime(r["rcept_dt"], "%Y%m%d").date()
            new = last is None or (d - last).days > LOOKBACK_DAYS
            last = d
            if not new:
                continue
            if "정정" in (r["report_nm"] or ""):
                rec["skip_correction"] += 1
                continue
            c = cell_of(r)
            if c is None:
                rec["skip_title"] += 1
                continue
            out.append((tk, int(r["rcept_dt"]), c, r["rcept_no"]))
    return out


def mark(d, evs, rec):
    """사건 → 패널 행. 셀별 마스크 열 E1·E2·E3 와 (셀, 행) → rcept_no."""
    import numpy as np
    days = np.unique(d.di.values)
    idx = {(t, di): i for i, (t, di) in enumerate(zip(d.t.values, d.di.values))}
    for c in CELLS:
        d[c] = False
    rno = {}
    for tk, rd, c, no in evs:
        k = int(days.searchsorted(rd, side="right")) - 1
        i = idx.get((tk, int(days[k]))) if k >= 0 else None
        if i is None:
            rec[f"no_row_{c}"] += 1
            continue
        d.iat[i, d.columns.get_loc(c)] = True
        rno.setdefault((c, i), no)
    return rno


def prep(rec):
    import bb_lower_reentry as bb
    bb.SIGNALS, bb.HS, bb.PREREG, bb.OUT = CELLS, HS, PREREG, OUT
    d, arr, delisted = bb.load_panel()
    age = d.groupby("t", sort=False).cumcount()                 # 당일 제외 앞선 유효 행 수
    for tag in ("p", "r"):
        d[f"elig_{tag}"] &= age >= MIN_AGE
    rno = mark(d, first_reports(load_raw(), rec), rec)
    return bb, d, arr, delisted, rno


def parse_prev_now(t):
    """원문 → (직전 비율 또는 None, 이번 비율). 못 읽으면 None."""
    a = re.search(r"직전 ?보고서 ([\d,]+|-) ?([\d.]+|-)? ?이번 ?보고서 ([\d,]+) ([\d.]+)", t)
    if a:
        return (hm.se.num(a.group(2)) if a.group(2) not in (None, "-") else None), hm.se.num(a.group(4))
    p = hm.parse_d001(t)
    return (None, p["rate"]) if p else None


def cmd_count():
    import numpy as np
    rec = Counter()
    bb, d, arr, delisted, rno = prep(rec)
    key = hm.load_env().get("DART_API_KEY")
    rng = np.random.default_rng(SEED)
    out = {}
    for c in CELLS:
        ep, er = bb.events(d, c, "p", rec), bb.events(d, c, "r", rec)
        yr = Counter(int(d.di.values[i] // 10000) for i in ep)
        print(c, "primary", len(ep), "tickers", len(set(d.t.values[ep])), dict(sorted(yr.items())))
        print(c, "record(delisted incl.)", len(er), "delisted tickers", len({d.t.values[i] for i in er} & delisted))
        pick = rng.choice(ep, min(SAMPLE, len(ep)), replace=False) if ep else []
        q = Counter()
        for i in pick:
            try:
                r = parse_prev_now(hm.doc_text(key, rno[(c, int(i))]))
            except Exception as e:
                r = None
                q["err"] += 1
                print("  doc", rno[(c, int(i))], type(e).__name__, str(e)[:80])
            if r is None:
                q["unread"] += 1
            elif r[1] >= 5 and (r[0] is None or r[0] < 5):
                q["entry"] += 1
            elif r[1] < 5:
                q["below5"] += 1
            else:
                q["already5"] += 1
            time.sleep(0.05)
        out[c] = {"primary": len(ep), "record": len(er), "sample": dict(q), "entry_rate": round(q["entry"] / max(len(pick), 1), 3)}
        print(c, "sample", dict(q), "entry_rate", out[c]["entry_rate"])
    print("rec", dict(rec))
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_run():
    import pandas as pd
    from supply_mcap_flow import committed_clean
    for p in (PREREG, Path(__file__).resolve()):
        if not committed_clean(p):
            print(f"중단: {p.name} 이 커밋되지 않았거나 수정됐다 — 사전등록·코드 커밋 뒤에만 계산한다")
            return 2
    rec = Counter()
    bb, d, arr, delisted, _ = prep(rec)
    dfp, dfr = [], []
    for c in CELLS:
        ep, er = bb.events(d, c, "p", rec), bb.events(d, c, "r", rec)
        dfp.append(bb.returns(d, arr, delisted, ep, c, "p", rec))
        dfr.append(bb.returns(d, arr, delisted, er, c, "r", rec))
    out = bb.summarize(pd.concat(dfp, ignore_index=True), pd.concat(dfr, ignore_index=True), bb.semi_set())
    out["rec"], out["prereg"] = dict(rec), PREREG.name
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("bar", out["bar"])
    for c, v in out["cells"].items():
        s = v["stats"]
        print(c, v["verdict"], "events", s["events"], "oos gross", s["oos_gross_month_bp"], s["oos_gross_ci95"],
              "net33.5", s["oos_net_bp_33.5"], "t", s["t_by_split"], "info", s["info_by_split_bp"])
    print("저장", OUT.relative_to(REPO))
    return 0


def selftest():
    rec = Counter()
    R = lambda tk, who, dt, nm="주식등의대량보유상황보고서(약식)", no=None: {"stock_code": tk, "flr_nm": who, "report_nm": nm, "rcept_dt": dt,
                                                                       "rcept_no": no or dt + who[:2]}
    rows = [R("000001", "BlackRock Fund Advisors", "20160105"),
            R("000001", "블랙록 인베스트먼트", "20170105"),                         # 같은 계열 1년 뒤 → 사건 아님
            R("000001", "BlackRockFundAdvisors", "20200301"),                    # 3년 넘게 뒤 → 다시 첫 보고
            R("000001", "국민연금공단", "20160105", "주식등의대량보유상황보고서(일반)"),
            R("000001", "홍길동", "20160106", "[기재정정]주식등의대량보유상황보고서(일반)"),
            R("000001", "홍길동", "20160107", "주식등의대량보유상황보고서(일반)"),       # 정정 뒤 이틀 → 사건 아님
            R("000002", "삼성자산운용", "20160105", "주식등의대량보유상황보고서(일반)"),
            R("", "비상장", "20160105")]
    ev = sorted(first_reports(rows, rec))
    assert [(t, d, c) for t, d, c, _ in ev] == [("000001", 20160105, "E1"), ("000001", 20160105, "E3"),
                                                 ("000001", 20200301, "E1"), ("000002", 20160105, "E2")], ev
    assert rec["skip_correction"] == 1
    assert parse_prev_now("보유비율 직전 보고서 518,509,578 8.69 이번 보고서 458,637,667 7.68 보고사유") == (8.69, 7.68)
    assert parse_prev_now("직전 보고서 - - 이번 보고서 1,000 5.12") == (None, 5.12)
    assert parse_prev_now("빈 문서") is None
    qs = list(quarters(date(2012, 1, 1), date(2012, 11, 20)))
    assert [(n, a, b, p) for n, a, b, p in qs] == [("2012Q1", "20120101", "20120331", False), ("2012Q2", "20120401", "20120630", False),
                                                   ("2012Q3", "20120701", "20120930", False), ("2012Q4", "20121001", "20121120", True)], qs
    import numpy as np
    import pandas as pd
    d = pd.DataFrame({"t": ["A", "A", "A", "B"], "di": [20160104, 20160105, 20160108, 20160105]})
    r = Counter()
    rno = mark(d, [("A", 20160106, "E1", "x"), ("B", 20160108, "E2", "y"), ("C", 20160105, "E3", "z")], r)
    assert list(d.E1) == [False, True, False, False] and not d.E2.any() and rno == {("E1", 1): "x"}   # 06일 → 05일 행 · B 는 08일 행 없음
    assert r["no_row_E2"] == 1 and r["no_row_E3"] == 1
    print("selftest ok")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    sys.exit({"selftest": selftest, "collect": cmd_collect, "count": cmd_count, "run": cmd_run}.get(cmd, lambda: print(__doc__) or 1)())
