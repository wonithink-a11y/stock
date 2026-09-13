#!/usr/bin/env python3
"""반도체 사이클 연구 파일럿 — 삼성전자·SK하이닉스 분기 매출·영업이익 (DART).

사용자 GO(2026-09-13): SOXL 산업사이클 연구의 1순위 파일럿. 새 외부소스가
아니라 기존 DART API(scripts/build-fundamentals-a3.py와 동일 엔드포인트)의
다른 문서유형(분기·반기보고서)만 추가로 부른다 — production A3 파이프라인은
건드리지 않는다(연구 전용, research/strategy-lab/ 격리).

★ 실측(2026-09-13)으로 뒤집힌 가정: DART 분기·반기보고서 응답의 `thstrm_amount`는
누적치가 **아니라 이미 그 보고서 직전 3개월(단독 분기)** 값이다 — 누적치는 별도
필드 `thstrm_add_amount`에 온다(반기보고서 실측: thstrm_amount=Q2단독 3.94조,
thstrm_add_amount=H1누적 7.60조. 3분기보고서도 동일 패턴: thstrm_amount=Q3단독,
thstrm_add_amount=9M누적). 처음엔 "11012/11014가 누적"이라 가정하고 amount끼리
차감했는데, 그러면 thstrm_amount(이미 단독분기)를 또 한 번 빼는 이중차감이 되어
Q2·Q3가 실제보다 훨씬 작게, Q4가 훨씬 크게 나왔다(SK하이닉스 2016 Q2가 2,852억으로
찍힘 — 실제는 3.94조). 올바른 계산:
    Q1 = 1분기보고서 thstrm_amount (원래 3개월 단위라 누적/단독 구분 없음)
    Q2 = 반기보고서 thstrm_amount (이미 단독 Q2)
    Q3 = 3분기보고서 thstrm_amount (이미 단독 Q3)
    Q4 = 사업보고서(연간, 기존 A3 데이터 재사용) − 3분기보고서 thstrm_add_amount(9M누적)
Q4만 실제 차감이 필요하다 — 유일하게 그 분기만 전용 보고서가 없다.

계정 매칭은 A3와 같은 관례(연결 우선, 매출액/영업이익 nameExact) — 별도
정책 파일을 새로 안 만들고 이 스크립트 안에 인라인했다(연구용 1회성 파일럿,
production 계약 아님).

    python research/strategy-lab/semiconductor_cycle_dart_quarterly.py --dry-run
    python research/strategy-lab/semiconductor_cycle_dart_quarterly.py
    python research/strategy-lab/semiconductor_cycle_dart_quarterly.py --selftest
"""
import argparse
import gzip
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root
OUT_DIR = Path(__file__).resolve().parent / "data" / "semiconductor-cycle"
BASE = "https://opendart.fss.or.kr/api"

CORPS = {"005930": "00126380", "000660": "00164779"}  # 삼성전자, SK하이닉스
YEARS = range(2015, 2026)
REPRT = {"Q1": "11013", "H1": "11012", "9M": "11014"}  # 사업보고서(FY)는 A3 재사용

ACCOUNT_SPEC = {
    "revenue": {"sj": ("IS", "CIS"), "exact": ("매출액", "수익(매출액)")},
    "opProfit": {"sj": ("IS", "CIS"), "exact": ("영업이익",)},
}
FS_PREFERENCE = ("CFS", "OFS")


def _load_key():
    key = os.environ.get("DART_API_KEY", "")
    if key:
        return key
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DART_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def to_amount(raw):
    if raw is None:
        return None
    t = str(raw).replace(",", "").strip()
    if not t or t == "-":
        return None
    try:
        return int(float(t))
    except ValueError:
        return None


def match_account(rows, spec):
    """(단독분기 thstrm_amount, 누적 thstrm_add_amount). 후자는 Q4 역산에만 쓴다."""
    cand = [r for r in rows if str(r.get("sj_div", "")) in spec["sj"]] or rows
    for r in cand:
        if str(r.get("account_nm", "")).replace(" ", "") in spec["exact"]:
            return to_amount(r.get("thstrm_amount")), to_amount(r.get("thstrm_add_amount"))
    return None, None


def pick_fs_rows(rows):
    by_div = {}
    for r in rows:
        by_div.setdefault(str(r.get("fs_div", "")), []).append(r)
    for pref in FS_PREFERENCE:
        if pref in by_div:
            return by_div[pref], pref
    return rows, None


def dart_call(key, corp, year, reprt_code, tries=5):
    import requests
    params = {"crtfc_key": key, "corp_code": corp, "bsns_year": str(year), "reprt_code": reprt_code}
    for i in range(tries):
        try:
            r = requests.get(f"{BASE}/fnlttSinglAcnt.json", params=params, timeout=20)
            j = r.json()
        except Exception:
            time.sleep(1.5 * (i + 1))
            continue
        status = j.get("status")
        if status == "000":
            return j.get("list", []), None
        if status == "013":  # 조회된 데이터 없음 - 정상 사실
            return [], "013"
        time.sleep(1.5 * (i + 1))
    return [], "FAIL"


def fetch_period(key, corp, year, reprt_code):
    rows, status = dart_call(key, corp, year, reprt_code)
    if not rows:
        return None
    fs_rows, fs_div = pick_fs_rows(rows)
    revenue, revenue_cum = match_account(fs_rows, ACCOUNT_SPEC["revenue"])
    op_profit, op_profit_cum = match_account(fs_rows, ACCOUNT_SPEC["opProfit"])
    rcept = str(rows[0].get("rcept_no", "")).strip()
    available_from = f"{rcept[:4]}-{rcept[4:6]}-{rcept[6:8]}" if len(rcept) >= 8 else None
    return {"revenue": revenue, "opProfit": op_profit, "revenueCum": revenue_cum,
            "opProfitCum": op_profit_cum, "fsDiv": fs_div, "availableFrom": available_from}


def load_fy_annual(ticker, year):
    """기존 A3 연간 데이터 재사용 (Q4 = FY - 9M 계산용)."""
    path = ROOT / "data" / "backfill" / "fundamentals" / "a3" / f"{year}.jsonl.gz"
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("ticker") == ticker:
                return {"revenue": rec.get("revenue"), "opProfit": rec.get("opProfit"),
                         "availableFrom": rec.get("availableFrom")}
    return None


def collect(dry_run=False):
    key = _load_key()
    if not key and not dry_run:
        print("DART_API_KEY 없음 (.env 또는 환경변수)"); return []
    records = []
    for ticker, corp in CORPS.items():
        for year in YEARS:
            cum = {}
            for label, code in REPRT.items():
                if dry_run:
                    print(f"[dry-run] {ticker} {year} {label}({code})")
                    continue
                cum[label] = fetch_period(key, corp, year, code)
                time.sleep(0.3)
            if dry_run:
                continue
            fy = load_fy_annual(ticker, year)
            q1, h1, nm = cum.get("Q1"), cum.get("H1"), cum.get("9M")

            def sub_cum(a_total, b_cum, field):
                """FY 총계에서 9M누적을 빼 Q4를 낸다 — 유일하게 필요한 차감."""
                if a_total is None or b_cum is None or a_total.get(field) is None or b_cum.get(f"{field}Cum") is None:
                    return None
                return a_total[field] - b_cum[f"{field}Cum"]

            quarters = {
                # Q1/Q2/Q3는 각 보고서의 thstrm_amount가 이미 단독 분기값이다(위 docstring 실측).
                "Q1": {"revenue": q1["revenue"], "opProfit": q1["opProfit"],
                       "availableFrom": q1["availableFrom"]} if q1 else None,
                "Q2": {"revenue": h1["revenue"], "opProfit": h1["opProfit"],
                       "availableFrom": h1["availableFrom"]} if h1 else None,
                "Q3": {"revenue": nm["revenue"], "opProfit": nm["opProfit"],
                       "availableFrom": nm["availableFrom"]} if nm else None,
                "Q4": {"revenue": sub_cum(fy, nm, "revenue"), "opProfit": sub_cum(fy, nm, "opProfit"),
                       "availableFrom": fy["availableFrom"] if fy else None} if (fy and nm) else None,
            }
            for q, vals in quarters.items():
                if vals is None or vals.get("revenue") is None:
                    continue
                records.append({"ticker": ticker, "fiscalYear": year, "quarter": q,
                                 "revenue": vals["revenue"], "opProfit": vals["opProfit"],
                                 "availableFrom": vals["availableFrom"]})
            print(f"{ticker} {year}: Q1={'ok' if q1 else 'x'} H1={'ok' if h1 else 'x'} "
                  f"9M={'ok' if nm else 'x'} FY={'ok' if fy else 'x'}")
    return records


def save(records):
    import pandas as pd
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records).sort_values(["ticker", "fiscalYear", "quarter"])
    out = OUT_DIR / "samsung_hynix_quarterly.parquet"
    df.to_parquet(out, index=False)
    print(f"\n저장: {out}  ({len(df)}행)")
    return out


def selftest() -> int:
    fails = []

    def ck(name, cond):
        print(("ok   " if cond else "FAIL ") + name)
        if not cond:
            fails.append(name)

    fy = {"revenue": 100, "opProfit": 10}
    nm = {"revenueCum": 60, "opProfitCum": 4}

    def sub_cum(a_total, b_cum, field):
        if a_total is None or b_cum is None or a_total.get(field) is None or b_cum.get(f"{field}Cum") is None:
            return None
        return a_total[field] - b_cum[f"{field}Cum"]

    ck("Q4 = FY총계 - 9M누적(revenue)", sub_cum(fy, nm, "revenue") == 40)
    ck("Q4 = FY총계 - 9M누적(opProfit)", sub_cum(fy, nm, "opProfit") == 6)
    ck("결측 입력이면 None(추정하지 않는다)", sub_cum(None, nm, "revenue") is None)

    rows = [{"sj_div": "IS", "fs_div": "CFS", "account_nm": "매출액",
             "thstrm_amount": "1,234", "thstrm_add_amount": "9,999"},
            {"sj_div": "IS", "fs_div": "CFS", "account_nm": "영업이익",
             "thstrm_amount": "56", "thstrm_add_amount": "888"}]
    ck("매출액 nameExact 매칭(단독)", match_account(rows, ACCOUNT_SPEC["revenue"])[0] == 1234)
    ck("매출액 누적치도 같이 잡힘", match_account(rows, ACCOUNT_SPEC["revenue"])[1] == 9999)
    ck("영업이익 nameExact 매칭(단독)", match_account(rows, ACCOUNT_SPEC["opProfit"])[0] == 56)
    ck("쉼표 포함 금액 파싱", to_amount("1,234,567") == 1234567)
    ck("'-'는 None(0 아님)", to_amount("-") is None)

    fs_rows, div = pick_fs_rows([{"fs_div": "OFS", "x": 1}, {"fs_div": "CFS", "x": 2}])
    ck("연결(CFS) 우선", div == "CFS" and fs_rows[0]["x"] == 2)

    total = 9
    print(f"\nselftest {total - len(fails)}/{total}" + ("" if not fails else f"  FAILED: {fails}"))
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    records = collect(dry_run=a.dry_run)
    if a.dry_run:
        return 0
    if records:
        save(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
