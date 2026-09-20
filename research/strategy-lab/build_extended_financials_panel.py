#!/usr/bin/env python3
"""확장 연간 재무(A3e 연구 패널) 수집 — DART fnlttSinglAcntAll(전체 재무제표).

왜: A3(연간 재무)는 fnlttSinglAcnt(주요계정) 7개뿐이라 EV/EBITDA·FCF·매출총이익/자산·발생액·차입금 같은
지표를 만들 수 없다. 이 수집기는 같은 A3 격자(종목·회계연도)에 대해 전체 재무제표에서 **필요 계정의 원문 행**을
저장한다 — 어느 행이 무엇을 뜻하는지는 분석 단계가 정하고, 여기서는 이름 추정으로 산식을 굳히지 않는다.

**연구 전용 — production A-series 가 아니다.** build_quarterly_earnings_panel.py 와 같은 패턴: data/backfill/(규칙 4,
GH Actions 전용)에 안 쓰고, config/policies·워크플로 같은 정식 인프라는 채택이 결정된 뒤에 짓는다.
설계·프로브 실측: docs/control/A3e-확장재무수집-설계-2026-09-21.md

PIT: **당기(thstrm) 열만** 쓴다(교훈47 — 전기 열은 그 보고서 접수일로 기록되어 과거를 늦게 안 것으로 만든다).
availableFrom = 응답 rcept_no 의 앞 8자리(접수일). 정정공시가 최신본이면 접수일이 늦어 **보수적**이다.

DART_API_KEY 는 커밋 안 함, 실행 환경변수 또는 저장소 루트 .env. 일일 한도(공유 40,000)는 안전마진을 둔 --daily-budget
(기본 30,000)에서 멈추고 020(한도 초과)도 즉시 중단한다. state 파일이 있어 몇 번을 다시 실행해도 안전하다.

  python research/strategy-lab/build_extended_financials_panel.py --selftest
  python research/strategy-lab/build_extended_financials_panel.py --limit 20     # 시험
  python research/strategy-lab/build_extended_financials_panel.py                # 이어서 계속
"""
import argparse
import gzip
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
A3_DIR = REPO / "data" / "backfill" / "fundamentals" / "a3"
OUT_DIR = HERE / "data" / "fundamentals-ext"
OUT_PANEL = OUT_DIR / "annual-ext-panel.jsonl"
STATE_PATH = OUT_DIR / "_state.json"
BASE = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
KST = timezone(timedelta(hours=9))
SECRET_RE = re.compile(r"(crtfc_key=)[^&\s\"')]+")

# 저장할 행: 표준계정코드(account_id) 접미사 또는 계정명 정규식. 넓게 잡고 해석은 분석 단계가 한다.
ID_KEYS = ("Revenue", "GrossProfit", "OperatingIncomeLoss", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent",
           "Assets", "CurrentAssets", "Liabilities", "CurrentLiabilities", "Equity", "EquityAttributableToOwnersOfParent",
           "CashAndCashEquivalents", "Inventories", "FinanceCosts", "InterestExpense", "FinanceIncome",
           "CashFlowsFromUsedInOperatingActivities", "CashFlowsFromUsedInInvestingActivities",
           "PurchaseOfPropertyPlantAndEquipment", "PurchaseOfIntangibleAssets",
           "DepreciationAndAmortisationExpense", "DepreciationExpense", "AmortisationExpense",
           "DividendsPaid", "PaymentsToAcquireOrRedeemEntitysShares", "IncomeTaxExpenseContinuingOperations")
NAME_RX = re.compile(r"차입금|사채|감가상각|상각비|배당금|자기주식|리스부채|매출액|수익\(매출액\)|영업이익|이자비용|금융비용|법인세비용")


def redact(s):
    return SECRET_RE.sub(r"\1<redacted>", str(s))


def today_kst():
    return datetime.now(KST).strftime("%Y-%m-%d")


def keep_row(r):
    rid = (r.get("account_id") or "")
    tail = rid.split("_", 1)[-1] if "_" in rid else rid
    if any(tail.startswith(k) for k in ID_KEYS):
        return True
    return bool(NAME_RX.search(r.get("account_nm") or ""))


def compact(rows):
    """전체 응답 → 저장 행. 당기(thstrm)만, 숫자 변환 실패는 버리지 않고 None."""
    out = []
    for r in rows:
        if not keep_row(r):
            continue
        amt = r.get("thstrm_amount")
        try:
            amt = float(str(amt).replace(",", "")) if amt not in ("", None, "-") else None
        except ValueError:
            amt = None
        out.append([r.get("sj_div"), r.get("account_id"), r.get("account_nm"), amt])
    return out


def load_env():
    k = os.environ.get("DART_API_KEY", "")
    if not k and (REPO / ".env").exists():
        for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("DART_API_KEY="):
                k = line.split("=", 1)[1].strip()
    return k


def load_state():
    if STATE_PATH.exists():
        st = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    else:
        st = {"date": today_kst(), "callsUsedToday": 0, "doneKeys": [], "noDataKeys": []}
    if st["date"] != today_kst():
        st["date"], st["callsUsedToday"] = today_kst(), 0
    st["doneKeys"], st["noDataKeys"] = set(st["doneKeys"]), set(st.get("noDataKeys", []))
    return st


def save_state(st):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({**st, "doneKeys": sorted(st["doneKeys"]), "noDataKeys": sorted(st["noDataKeys"])},
                                     ensure_ascii=False, indent=1), encoding="utf-8")


def load_grid():
    rows = []
    for f in sorted(A3_DIR.glob("*.jsonl.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                d = json.loads(line)
                rows.append({"ticker": d["ticker"], "corp": d["corp"], "fiscalYear": d["fiscalYear"]})
    rows.sort(key=lambda r: (r["ticker"], r["fiscalYear"]))
    return rows


def dart_call(session, key, corp, year, fs_div, retries=3):
    """반환 (rows|None, 오류코드|None). 013(없음)은 오류가 아니라 (None,'013')."""
    params = {"crtfc_key": key, "corp_code": corp, "bsns_year": str(year), "reprt_code": "11011", "fs_div": fs_div}
    last = None
    for attempt in range(retries):
        try:
            r = session.get(BASE, params=params, timeout=(10, 60))
            body = r.json()
        except Exception as e:                           # 전송·파싱 실패는 재시도
            last = "transport:" + redact(str(e))[:80]
            time.sleep(1.5 * (attempt + 1))
            continue
        st = body.get("status")
        if st == "000":
            return body.get("list", []), None
        return None, st
    return None, last


def fetch_corp_year(call, corp, year):
    """CFS(연결) 우선, 없으면 OFS(별도). call(fs_div)->(rows,err). 반환 (rec|None, 호출수, 오류)."""
    n = 0
    for fs in ("CFS", "OFS"):
        rows, err = call(fs)
        n += 1
        if err in ("020",) or (err and err not in ("013",)):
            return None, n, err
        if rows:
            rn = rows[0].get("rcept_no") or ""
            return {"fsDiv": fs, "rceptNo": rn, "availableFrom": rn[:8], "rows": compact(rows)}, n, None
    return None, n, "013"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--daily-budget", type=int, default=30_000)
    ap.add_argument("--sleep", type=float, default=0.15)
    ap.add_argument("--limit", type=int, default=0, help="이번 실행에서 처리할 최대 corp-year(시험용)")
    ap.add_argument("--max-consecutive-empty", type=int, default=30)
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    key = load_env()
    if not key:
        print("DART_API_KEY 없음")
        sys.exit(1)
    import requests
    session = requests.Session()
    grid = load_grid()
    st = load_state()
    print(f"격자 {len(grid)} corp-year · 완료 {len(st['doneKeys'])} · 자료없음 {len(st['noDataKeys'])} · 오늘 사용 {st['callsUsedToday']}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = open(OUT_PANEL, "a", encoding="utf-8")
    n_done = n_rec = n_calls = 0
    fails, empty_run = Counter(), 0
    for row in grid:
        k = f"{row['ticker']}|{row['fiscalYear']}"
        if k in st["doneKeys"] or k in st["noDataKeys"]:
            continue
        if a.limit and n_done >= a.limit:
            break
        if st["callsUsedToday"] + 2 > a.daily_budget:
            print(f"일일 예산 도달({st['callsUsedToday']}/{a.daily_budget}) — 내일 이어서")
            break
        rec, n, err = fetch_corp_year(lambda fs: (time.sleep(a.sleep) or dart_call(session, key, row["corp"], row["fiscalYear"], fs)),
                                      row["corp"], row["fiscalYear"])
        st["callsUsedToday"] += n
        n_calls += n
        if err == "020":
            print("한도 초과(020) — 중단, 내일 이어서")
            break
        if err == "013":
            st["noDataKeys"].add(k)
            empty_run += 1
        elif err:
            fails[err] += 1
            empty_run += 1                       # 완료로 표시하지 않는다 — 다음 실행에서 재시도
        else:
            out.write(json.dumps({"ticker": row["ticker"], "corp": row["corp"], "fiscalYear": row["fiscalYear"], **rec},
                                 ensure_ascii=False) + "\n")
            st["doneKeys"].add(k)
            n_rec += 1
            empty_run = 0
        n_done += 1
        if empty_run >= a.max_consecutive_empty:
            print(f"서킷브레이커: {empty_run}건 연속 레코드 없음(오류 {fails.most_common(3)}) — outage 의심, 중단")
            break
        if n_done % 200 == 0:
            out.flush()
            save_state(st)
            print(f"  {n_done} 처리 · 레코드 {n_rec} · 호출 {n_calls}")
    out.close()
    save_state(st)
    print(f"이번 실행: 처리 {n_done} · 레코드 {n_rec} · 호출 {n_calls} · 오류 {dict(fails)} | 누적 완료 {len(st['doneKeys'])}/{len(grid)}")


def selftest():
    ok = True

    def check(n, c):
        nonlocal ok
        print(("PASS " if c else "FAIL ") + n)
        ok = ok and bool(c)

    rows = [{"account_id": "ifrs-full_GrossProfit", "account_nm": "매출총이익", "sj_div": "IS", "thstrm_amount": "1,000"},
            {"account_id": "-표준계정코드 미사용-", "account_nm": "단기차입금", "sj_div": "BS", "thstrm_amount": "500"},
            {"account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities", "account_nm": "영업활동현금흐름", "sj_div": "CF", "thstrm_amount": "-7"},
            {"account_id": "ifrs-full_Foo", "account_nm": "기타", "sj_div": "BS", "thstrm_amount": "9"},
            {"account_id": "dart_OperatingIncomeLoss", "account_nm": "영업이익", "sj_div": "IS", "thstrm_amount": ""}]
    c = compact(rows)
    check("필요 행만 저장(기타 제외)", len(c) == 4 and all(x[2] != "기타" for x in c))
    check("금액 파싱: 쉼표·음수·빈칸=None", c[0][3] == 1000.0 and c[2][3] == -7.0 and c[3][3] is None)
    check("표준계정코드 없는 행도 이름으로 저장(단기차입금)", any(x[2] == "단기차입금" for x in c))

    def mk(seq):
        it = iter(seq)
        return lambda fs: next(it)
    rec, n, err = fetch_corp_year(mk([(None, "013"), ([{"rcept_no": "20240315000123", **rows[0]}], None)]), "c", 2023)
    check("CFS 없음 → OFS 폴백, 접수일 8자리", rec and rec["fsDiv"] == "OFS" and rec["availableFrom"] == "20240315" and n == 2)
    rec, n, err = fetch_corp_year(mk([([{"rcept_no": "20240315000123", **rows[0]}], None)]), "c", 2023)
    check("CFS 있으면 1콜에 끝", rec["fsDiv"] == "CFS" and n == 1)
    rec, n, err = fetch_corp_year(mk([(None, "013"), (None, "013")]), "c", 2023)
    check("둘 다 없음 → 013(자료없음)", rec is None and err == "013" and n == 2)
    rec, n, err = fetch_corp_year(mk([(None, "020")]), "c", 2023)
    check("한도 초과는 즉시 반환(폴백 안 함)", err == "020" and n == 1)
    check("키 마스킹", "abc123" not in redact("crtfc_key=abc123&x=1"))
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    main()
