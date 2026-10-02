#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""시장 전체 일별 급등 군집 -> docs/data/market-movers.json

KRX 공식 Open API(stk_bydd_trd·ksq_bydd_trd, KRX_OPENAPI_KEY)로 코스피·코스닥 전 종목의 마지막 영업일 종가를 받아
업종 그룹(config/sectorGroups.json 롤업 = 섹터강도 탭과 같은 분류)별로 '전일 대비 +5% 이상' 종목 수를 센다.
관심종목 352개만 보던 급등 군집 카드를 시장 전체로 넓히는 데이터다. 표시 전용 - 점수·추천과 무관.

정의(고정, 바꾸면 새 버전):
  급등 = 전일 대비 종가 등락률 >= +5.0%, 급락 = <= -5.0%
  적격 모집단 = 보통주 · 스팩 아님 · 당일 거래대금 >= 10억 원 (분자·분모 모두 같은 모집단)
  우선주 = 종목코드 끝자리가 '0' 이 아님. 스팩 = 이름에 '스팩'·'기업인수목적'
  업종 = A1a KSIC -> sectorGroups 롤업(+ tickerOverrides). 매핑 없는 종목은 unmapped 로 센다.
  그룹 표시 기준 = 적격 종목 5개 이상

KRX 는 당일 데이터를 장중에 주지 않는다(실측 2026-10-02 15:00 에 0행). 기본은 오늘부터 거꾸로 최대 8일을 훑어 행이 있는
첫 날짜를 쓴다. 타임스탬프를 넣지 않아서 같은 날 데이터면 파일이 바이트 동일하다.

  python scripts/build-market-movers.py [--date YYYYMMDD] [--out 경로]
  python scripts/build-market-movers.py --selftest
"""
import argparse
import importlib.util
import json
import os
import ssl
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data", "market-movers.json")
KST = timezone(timedelta(hours=9))
ENDPOINTS = {"KOSPI": "stk_bydd_trd", "KOSDAQ": "ksq_bydd_trd"}

UP_PCT = 5.0
MIN_TV = 1_000_000_000      # 거래대금 10억 원
MIN_MEMBERS = 5
TOP_N = 3
SCHEMA = "MM-1.0"


def _sector_mod():
    spec = importlib.util.spec_from_file_location("bss", os.path.join(ROOT, "scripts", "build-sector-strength.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def num(x):
    try:
        return float(str(x).replace(",", ""))
    except (TypeError, ValueError):
        return None


def is_preferred(code):
    return not code or code[-1] != "0"


def is_spac(name):
    return "스팩" in name or "기업인수목적" in name


def fetch_day(key, ymd):
    rows = []
    ctx = ssl.create_default_context()
    for mk, path in ENDPOINTS.items():
        req = urllib.request.Request(f"https://data-dbg.krx.co.kr/svc/apis/sto/{path}?basDd={ymd}",
                                     headers={"AUTH_KEY": key, "User-Agent": "Mozilla/5.0"})
        got = json.loads(urllib.request.urlopen(req, timeout=40, context=ctx).read().decode()).get("OutBlock_1") or []
        for r in got:
            r["_mk"] = mk
        rows += got
    return rows


def build(rows, sector_by_ticker, ymd):
    """순수 함수. rows = KRX OutBlock_1 합본."""
    ex = {"preferred": 0, "spac": 0, "illiquid": 0, "noReturn": 0}
    elig, unmapped = [], 0
    for r in rows:
        code, name = r.get("ISU_CD", ""), r.get("ISU_NM", "")
        if is_preferred(code):
            ex["preferred"] += 1; continue
        if is_spac(name):
            ex["spac"] += 1; continue
        tv, fr = num(r.get("ACC_TRDVAL")), num(r.get("FLUC_RT"))
        if fr is None:
            ex["noReturn"] += 1; continue
        if tv is None or tv < MIN_TV:
            ex["illiquid"] += 1; continue
        g = sector_by_ticker.get(code)
        if not g:
            unmapped += 1
        elig.append({"t": code, "n": name, "g": g, "r": round(fr / 100, 4), "tv": int(tv), "cap": int(num(r.get("MKTCAP")) or 0)})
    byg = {}
    for s in elig:
        if s["g"]:
            byg.setdefault(s["g"], []).append(s)
    groups = []
    for g, ms in byg.items():
        if len(ms) < MIN_MEMBERS:
            continue
        up = sorted([m for m in ms if m["r"] >= UP_PCT / 100], key=lambda m: (-m["r"], m["t"]))
        dn = [m for m in ms if m["r"] <= -UP_PCT / 100]
        groups.append({"group": g, "n": len(ms), "up": len(up), "dn": len(dn),
                       "top": [[m["t"], m["n"], m["r"]] for m in up[:TOP_N]]})
    groups.sort(key=lambda x: (-(x["up"] / x["n"]), -x["up"], x["group"]))
    movers = sorted([s for s in elig if s["r"] >= UP_PCT / 100], key=lambda s: (-s["r"], s["t"]))
    return {
        "schemaVersion": SCHEMA, "asOf": ymd,
        "definition": {"upPct": UP_PCT, "minTradingValueKRW": MIN_TV, "minGroupMembers": MIN_MEMBERS,
                       "excluded": "우선주(종목코드 끝자리≠0)·스팩", "sector": "A1a KSIC -> config/sectorGroups.json 롤업"},
        "universe": {"listed": len(rows), "eligible": len(elig), "up": len(movers),
                     "down": sum(1 for s in elig if s["r"] <= -UP_PCT / 100), "unmapped": unmapped, "excluded": ex},
        "groups": groups, "movers": movers,
    }


def selftest():
    def ok(c, m):
        if not c:
            print("selftest 실패:", m); sys.exit(1)
    ok(is_preferred("005935") and not is_preferred("005930") and not is_preferred("0218L0"), "우선주 판정")
    ok(is_spac("미래에셋비전스팩1호") and is_spac("OO기업인수목적") and not is_spac("삼성전자"), "스팩 판정")
    ok(num("1,234.5") == 1234.5 and num("-") is None and num(None) is None, "숫자 파싱")
    sec = {f"{i:05d}0": "반도체" for i in range(1, 8)}   # 보통주 코드는 끝자리 0
    mk = lambda code, name, fr, tv: {"ISU_CD": code, "ISU_NM": name, "FLUC_RT": str(fr), "ACC_TRDVAL": str(tv), "MKTCAP": "1000"}
    rows = [mk("000010", "A", 10.0, 2e9), mk("000020", "B", 5.0, 2e9), mk("000030", "C", 4.99, 2e9), mk("000040", "D", -6.0, 2e9),
            mk("000050", "E", 0.0, 2e9), mk("000060", "F", 20.0, 9e8),           # 거래대금 미달 -> 제외
            mk("000070", "G", 30.0, 2e9), mk("000080", "H", 9.0, 2e9),           # 000080: 업종 매핑 없음
            mk("000090", "I스팩", 29.0, 2e9), mk("000015", "J우", 29.0, 2e9)]     # 스팩·우선주 제외
    o = build(rows, sec, "20261001")
    u = o["universe"]
    ok(u["listed"] == 10 and u["eligible"] == 7 and u["up"] == 4 and u["down"] == 1 and u["unmapped"] == 1, f"집계 {u}")
    ok(u["excluded"] == {"preferred": 1, "spac": 1, "illiquid": 1, "noReturn": 0}, f"제외 {u['excluded']}")
    g = o["groups"][0]
    ok(g["group"] == "반도체" and g["n"] == 6 and g["up"] == 3 and g["dn"] == 1, f"그룹 {g}")   # A,B,G 급등 / D 급락, 매핑 없는 H 는 그룹에서 빠짐
    ok([t[0] for t in g["top"]] == ["000070", "000010", "000020"], f"상위 정렬 {g['top']}")
    ok(build(rows[:3], sec, "x")["groups"] == [], "5개 미만 그룹은 표시 안 함")
    ok(json.dumps(build(rows, sec, "20261001")) == json.dumps(o), "결정적")
    print("selftest OK - build-market-movers")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    key = os.environ.get("KRX_OPENAPI_KEY", "")
    if not key:
        print("KRX_OPENAPI_KEY 가 없다"); return 1
    day, rows = None, []
    d0 = datetime.strptime(a.date, "%Y%m%d") if a.date else datetime.now(KST).replace(tzinfo=None)
    for i in range(0 if a.date else 9):
        d = d0 - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        rows = fetch_day(key, f"{d:%Y%m%d}")
        if rows:
            day = f"{d:%Y%m%d}"; break
    if not rows:
        print("KRX 에서 가져온 행이 없다"); return 1
    bss = _sector_mod()
    sectors = bss.load_sector_by_ticker(bss.load_rollup())
    out = build(rows, sectors, day)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")
    u = out["universe"]
    print(f"market-movers {day}: 상장 {u['listed']} · 적격 {u['eligible']} · 급등 {u['up']} · 급락 {u['down']} · 미매핑 {u['unmapped']} · 제외 {u['excluded']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
