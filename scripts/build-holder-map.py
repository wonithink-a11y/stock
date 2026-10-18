#!/usr/bin/env python3
"""build-holder-map.py — 국내 상장사 전체 DART 5% 대량보유 → '기관 → 보유 종목' 표 docs/data/holders.json (2026-10-17)

  python scripts/build-holder-map.py --full        첫 전량(상장사 ≈2,580곳 × 2~3콜 ≈ 5.3k콜, 한도 2만) — 대량 수집, 사용자 확인 뒤
  python scripts/build-holder-map.py               증분: 직전 asOf 이후 D001(대량보유) 공시가 난 회사만 다시 받는다
  python scripts/build-holder-map.py --only 005930,000660 --out PATH     표본
  python scripts/build-holder-map.py --selftest    (네트워크 없음)

회사마다 ① majorstock(보고자별 비율·주식수) ② list D001(최근 5년 대량보유 보고 이력, 보고자·날짜만).
★ majorstock 은 **최근 약 2년치만** 준다(10-17 실측: 삼성전자 첫 행 2024-10-25). 그 창 밖에서 마지막으로 보고한
  보고자는 비율을 알 수 없다 — ②로 찾아 stale(비율 미상)로 따로 둔다. 실례: 국민연금 → 삼성전자(마지막 2022-09)·
  SK하이닉스·현대차(2024-09-25)는 majorstock 에 없다. ★ stale 의 상당수는 마지막 보고가 이탈 보고다
  (10-17 원문 표본 12건 중 8건이 0~4.6%) — 보유로 읽지 않는다.
★ 마지막 공시 비율 < 5% = 이탈(exited). 대표보고자 교체(Capital Group 등)는 계열 정규화(CANON)로 이어 붙인다.
★ report_tp 약식 = 단순투자 · 일반 = 일반투자 또는 경영참가(원문을 봐야 갈린다 — majorstock 행은 파싱 안 함).
★ stale 행은 마지막 D001 원문(document.xml, 건당 ~8KB)에서 비율·주식수·보유목적·작성기준일을 읽는다(src=doc).
  2021~22 이전 원문은 EUC-KR. 원문 비율 < 5% 면 exited. 한도(020)에 걸리면 남은 것은 다음 실행이 이어서 읽는다.
★ 국민연금은 data.go.kr '국민연금공단_국내주식 투자정보'(연말, 5% 미만 포함 전 종목 지분율) CSV 를 data/nps/ 에 두면
  종목명으로 붙인다 → out.nps · 국민연금 행의 ye(연말 지분율). 종목코드가 없어 이름 매핑이다(못 붙인 이름은 unmatched).
★ 관찰·맥락 표시용 — 점수·매매에 쓰지 않는다(절대 규칙 1). docs/data 는 Actions 만 쓴다(워크플로 연결은 사용자 GO 뒤).
"""
import argparse
import csv
import importlib.util
import io
import json
import re
import urllib.request
import zipfile
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "holders.json"
UNIVERSE = ROOT / "data" / "backfill" / "universe" / "a1a" / "current.jsonl"   # 현재 상장(SPAC·KONEX 제외)
NPS_DIR = ROOT / "data" / "nps"                                               # nps-kr-equity-YYYYMMDD.csv (data.go.kr 3070507)

_spec = importlib.util.spec_from_file_location("stock_events", ROOT / "scripts" / "build-stock-events.py")
se = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(se)
KST, dart, summarize_major, load_env = se.KST, se.dart, se.summarize_major, se.load_env

# 보고자 이름(공백·대소문자 제거 뒤) → 계열 이름. 위에서부터 첫 일치. 없으면 원래 이름(공백 제거)
CANON = [
    (r"^국민연금", "국민연금공단"),
    (r"blackrock|블랙록", "BlackRock"),
    (r"capitalresearch|capitalgroup|캐피탈리서치|캐피탈그룹", "Capital Group"),
    (r"j\.?p\.?morgan|제이피모간|제이피모건", "J.P.Morgan"),
    (r"morganstanley|모건스탠리", "Morgan Stanley"),
    (r"goldmansachs|골드만삭스", "Goldman Sachs"),
    (r"norgesbank|노르웨이", "Norges Bank"),
    (r"gicprivate|governmentofsingapore|싱가포르", "GIC(싱가포르 정부)"),
    (r"^fillimited|^fil(investment|investments)", "FIL(Fidelity International)"),
    (r"fidelitymanagement|피델리티매니지먼트", "Fidelity(FMR)"),
    (r"hermes", "Federated Hermes"),
    (r"firsteagle", "First Eagle"),
    (r"aramco", "Aramco"),
    (r"vanguard|뱅가드", "Vanguard"),
    (r"orbis", "Orbis"),
    (r"silchester", "Silchester"),
    (r"^ubs", "UBS"),
]
# ponytail: list 는 비율을 안 줘서 오래전 이탈자(다임러 2004 → 현대차 등)도 stale 로 보인다 — 최근 5년만 본다.
#   더 정확히 하려면 D001 원문(document.xml)의 비율을 파싱해야 한다.
STALE_YEARS = 5
TP = {"약식": "단순투자", "일반": "일반(경영참가 포함 가능)"}


def canon(name):
    n = re.sub(r"\s+|\(주\)|주식회사", "", name or "?")
    low = n.lower()
    for pat, c in CANON:
        if re.search(pat, low):
            return c
    return n


def holders_of(major_rows, d001_rows):
    """한 회사 → 보유자 목록. major: 비율 있는 최신 보고 · d001 중 major 에 없는 계열 = stale(비율 미상)."""
    out = []
    for m in summarize_major(major_rows, key=canon):
        h = {"who": m["who"], "names": m["names"], "rate": m["rate"], "qty": m["qty"], "chg": m["chg"],
             "date": m["date"], "tp": TP.get(m["tp"], m["tp"]), "rcept": m["rcept"]}
        if m["rate"] < 5:
            h["exited"] = True
        out.append(h)
    seen = {h["who"] for h in out}
    stale = {}
    for r in d001_rows:
        c = canon(r.get("flr_nm"))
        if c in seen:
            continue
        s = stale.setdefault(c, {"who": c, "names": set(), "date": "", "rcept": None, "stale": True})
        s["names"].add(r.get("flr_nm") or "?")
        if r["rcept_dt"] > s["date"]:
            s["date"], s["rcept"] = r["rcept_dt"], r.get("rcept_no")
    out += [{**s, "names": sorted(s["names"])} for s in stale.values()]
    return out


def fetch(key, cc, today):
    since = (datetime.strptime(today, "%Y%m%d") - timedelta(days=round(365.25 * STALE_YEARS))).strftime("%Y%m%d")
    d001 = []
    for p in range(1, 50):
        page = dart("list", key, corp_code=cc, bgn_de=since, end_de=today, pblntf_detail_ty="D001",
                    page_count=100, page_no=p)
        d001 += page
        if len(page) < 100:
            break
    return holders_of(dart("majorstock", key, corp_code=cc), d001)


def doc_text(key, rcept):
    b = urllib.request.urlopen(f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={key}&rcept_no={rcept}", timeout=60).read()
    if not b.startswith(b"PK"):                    # 오류는 zip 이 아니라 <status> XML 로 온다
        st = re.search(rb"<status>(\d+)</status>", b)
        raise RuntimeError(f"DART document {st.group(1).decode() if st else '?'}")
    z = zipfile.ZipFile(io.BytesIO(b))
    raw = z.read(z.namelist()[0])
    try:
        x = raw.decode("utf-8")
    except UnicodeDecodeError:
        x = raw.decode("cp949", "replace")         # 2021~22 이전 원문
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x))


def parse_d001(t):
    """대량보유 원문 요약정보 → 이번 보고서 주식수·비율, 보유목적, 작성기준일. 못 읽으면 None."""
    a = re.search(r"이번 ?보고서 ([\d,]+) ([\d.]+)", t)
    if not a:
        return None
    p = re.search(r"보유목적 ?(단순투자|일반투자|경영권|경영참가)", t)      # 옛 서식은 이 자리에 '본인은' 등이 온다
    d = re.search(r"보고서작성기준일 ?: ?(\d{4})년 ?(\d+)월 ?(\d+)일", t)
    return {"qty": se.num(a.group(1)), "rate": se.num(a.group(2)), "tp": p.group(1)[:10] if p else None,
            "asof": f"{d.group(1)}{int(d.group(2)):02d}{int(d.group(3)):02d}" if d else None}


def fill_stale(key, stocks):
    """stale 행을 원문으로 채운다. 한도(020)면 멈추고 남은 것은 src 없이 둔다(다음 실행이 이어서)."""
    todo = [h for hs in stocks.values() for h in hs if h.get("stale") and "src" not in h and h.get("rcept")]
    print(f"원문 읽기 {len(todo)}건")
    bad = 0
    for i, h in enumerate(todo, 1):
        try:
            p = parse_d001(doc_text(key, h["rcept"]))
        except Exception as e:
            if "020" in str(e):
                print(f"  한도 초과 — 원문 {len(todo) - i + 1}건 남김")
                break
            p = None
        h["src"] = "doc"
        if p:
            h.update(p)
            if p["rate"] is not None and p["rate"] < 5:
                h["exited"] = True
        else:
            bad += 1
        if i % 200 == 0:
            print(f"  원문 {i}/{len(todo)}")
        time.sleep(0.05)
    print(f"원문 못 읽음 {bad}건")


def nkey(name):
    return re.sub(r"\s+|\(주\)|주식회사|㈜", "", name or "").upper()


def load_nps(names):
    """data.go.kr 국민연금 연말 국내주식 → (asOf, {ticker: {rate, amt}}, 못 붙인 이름)."""
    files = sorted(NPS_DIR.glob("nps-kr-equity-*.csv"))
    if not files:
        return None, {}, []
    raw = files[-1].read_bytes()
    try:
        txt = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        txt = raw.decode("cp949")
    by_name = {nkey(n): t for t, n in names.items()}
    # 약칭(현대차·한국전력·KT&G) — a1a·A5 는 정식 법인명이라 관심종목 이름을 더한다(저장소에 있어 Actions 에서도 된다)
    wl = json.loads((ROOT / "config" / "watchlist.json").read_text(encoding="utf-8"))["tickers"]
    by_name.update({nkey(x["name"]): x["code"] for x in wl if x["code"] in names})
    krx = sorted((ROOT / "research" / "strategy-lab" / "data" / "krx-daily-ext").glob("*.parquet"))
    if krx:                                        # KRX 약칭(한국전력·KT&G) — a1a 는 정식 법인명. 로컬에만 있다(Actions 에선 a1a 이름만)
        import pandas as pd
        d = pd.read_parquet(krx[-1], columns=["ISU_CD", "ISU_NM"]).drop_duplicates("ISU_CD")
        by_name.update({nkey(n): c for c, n in zip(d.ISU_CD, d.ISU_NM) if c in names})
    got, miss = {}, []
    for row in list(csv.reader(io.StringIO(txt)))[1:]:
        if len(row) < 5:
            continue
        t = by_name.get(nkey(row[1]))
        if t:
            got[t] = {"rate": se.num(row[4]), "amt": se.num(row[2])}
        else:
            miss.append(row[1])
    return files[-1].stem[-8:], got, miss


def changed_corps(key, since, today):
    """since~today 사이 D001 공시가 난 corp_code. corp_code 없는 list 조회는 3개월 제한이다."""
    corps = set()
    for p in range(1, 500):
        page = dart("list", key, bgn_de=since, end_de=today, pblntf_detail_ty="D001", page_count=100, page_no=p)
        corps |= {r["corp_code"] for r in page}
        if len(page) < 100:
            break
    return corps


def pivot(stocks, names):
    """종목별 보유자 → 기관별 보유 종목 + 종목별 보유 기관 수."""
    inv, cnt = {}, {}
    for t, hs in stocks.items():
        c = cnt[t] = {"name": names.get(t), "n": 0, "nExited": 0, "nStale": 0}
        for h in hs:
            c["nExited" if h.get("exited") else "nStale" if h.get("stale") else "n"] += 1
            inv.setdefault(h["who"], []).append({"t": t, "name": names.get(t), **{k: v for k, v in h.items() if k != "who"}})
    investors = []
    for who, rows in inv.items():
        rows.sort(key=lambda r: (bool(r.get("exited")), bool(r.get("stale")), -(r.get("rate") or 0)))
        investors.append({"who": who, "n": sum(1 for r in rows if not r.get("exited") and not r.get("stale")), "rows": rows})
    investors.sort(key=lambda x: (-x["n"], x["who"]))
    return investors, cnt


def unpivot(investors):
    stocks = {}
    for inv in investors:
        for r in inv["rows"]:
            stocks.setdefault(r["t"], []).append({"who": inv["who"], **{k: v for k, v in r.items() if k not in ("t", "name")}})
    return stocks


def selftest():
    assert canon("BlackRock Fund Advisors") == "BlackRock" and canon("블랙록 인베스트먼트") == "BlackRock"
    assert canon("국민연금공단") == canon("국민연금 기금") == "국민연금공단"
    assert canon("TheCapitalGroupCompanies,Inc.") == canon("CapitalResearchandManagementCompany") == "Capital Group"
    assert canon("삼성자산운용") == "삼성자산운용" and canon("(주)한화") == "한화"
    hs = holders_of([
        {"rcept_dt": "2025-10-14", "rcept_no": "1", "repror": "TheCapitalGroupCompanies,Inc.", "stkrt": "6.40", "stkqy": "100", "report_tp": "약식"},
        {"rcept_dt": "2026-06-09", "rcept_no": "3", "repror": "CapitalResearchandManagementCompany", "stkrt": "3.53", "stkqy": "50", "report_tp": "약식"},
        {"rcept_dt": "2026-02-20", "rcept_no": "2", "repror": "BlackRockFundAdvisors", "stkrt": "5.00", "stkqy": "36,407,157", "report_tp": "일반"}],
        [{"flr_nm": "국민연금공단", "rcept_dt": "20220902", "rcept_no": "9"}, {"flr_nm": "국민연금공단", "rcept_dt": "20240925", "rcept_no": "8"},
         {"flr_nm": "BlackRockFundAdvisors", "rcept_dt": "20190207", "rcept_no": "7"}])
    by = {h["who"]: h for h in hs}
    cg = by["Capital Group"]
    assert cg["exited"] and cg["chg"] == -2.87 and cg["names"] == ["CapitalResearchandManagementCompany", "TheCapitalGroupCompanies,Inc."]
    assert by["BlackRock"]["qty"] == 36407157 and by["BlackRock"]["tp"] == "일반(경영참가 포함 가능)" and "exited" not in by["BlackRock"]
    assert by["국민연금공단"] == {"who": "국민연금공단", "names": ["국민연금공단"], "date": "20240925", "rcept": "8", "stale": True}
    assert len(hs) == 3                                                 # 블랙록 옛 D001 은 major 에 있으니 stale 아님
    inv, cnt = pivot({"000660": hs, "005930": [dict(by["BlackRock"])]}, {"000660": "SK하이닉스", "005930": "삼성전자"})
    assert inv[0]["who"] == "BlackRock" and inv[0]["n"] == 2
    assert cnt["000660"] == {"name": "SK하이닉스", "n": 1, "nExited": 1, "nStale": 1}
    back = unpivot(inv)
    assert sorted(back["000660"], key=lambda h: h["who"]) == sorted(hs, key=lambda h: h["who"])   # 증분용 왕복
    p = parse_d001("보고자 : 국민연금공단 보유주식등의 수 보유비율 직전 보고서 518,509,578 8.69 이번 보고서 458,637,667 7.68 "
                   "보고사유 단순추가취득/처분 보유목적 일반투자 ※ 보고서작성기준일 : 2022년 08월 16일")
    assert p == {"qty": 458637667, "rate": 7.68, "tp": "일반투자", "asof": "20220816"}
    assert parse_d001("이번보고서 0 0 보유목적 경영권")["rate"] == 0 and parse_d001("빈 문서") is None
    assert parse_d001("이번 보고서 1 5.1 보유목적 본인은 확인")["tp"] is None
    assert nkey("삼성전자(주)") == nkey("삼성 전자") == "삼성전자"
    print("selftest ok (18)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    key = load_env().get("DART_API_KEY")
    if not key:
        raise SystemExit("DART_API_KEY 가 필요하다")
    uni = {}
    for line in UNIVERSE.read_text(encoding="utf-8").splitlines():
        j = json.loads(line)
        if j.get("corp"):
            uni[j["ticker"]] = (j["corp"], j["name"])
    names = {t: v[1] for t, v in uni.items()}
    now = datetime.now(KST)
    today = now.strftime("%Y%m%d")
    out_p = Path(a.out)
    prev = json.loads(out_p.read_text(encoding="utf-8")) if out_p.exists() and not a.full and not a.only else None

    if a.only:
        targets, stocks = a.only.split(","), {}
    elif a.full:
        targets, stocks = list(uni), {}
    elif prev:
        if prev["asOf"] < (now - timedelta(days=85)).strftime("%Y%m%d"):
            raise SystemExit(f"직전 asOf {prev['asOf']} 가 3개월 가까이 지났다 — list 조회 제한, --full 로 다시 받는다")
        stocks = {t: [] for t in prev["stocks"] if t in uni}           # 보유자 0 종목도 남긴다(안 그러면 매번 '신규'로 다시 받는다)
        stocks.update((t, hs) for t, hs in unpivot(prev["investors"]).items() if t in uni)
        corp2t = {v[0]: t for t, v in uni.items()}
        targets = sorted({corp2t[c] for c in changed_corps(key, prev["asOf"], today) if c in corp2t}
                         | (set(uni) - set(prev["stocks"])) | (set(prev.get("retry", [])) & set(uni)))
        print(f"증분: {prev['asOf']} 이후 D001 · 신규 상장 · 재시도 → {len(targets)}곳")
    else:
        raise SystemExit(f"{out_p} 가 없다 — 첫 실행은 --full(대량 수집, 사용자 확인 뒤)")

    failed, quota = [], False
    for i, t in enumerate(targets, 1):
        if t not in uni:
            print(f"  {t} 현재 상장 명단(a1a)에 없음 — 건너뜀")
            continue
        try:
            stocks[t] = fetch(key, uni[t][0], today)
        except Exception as e:
            failed.append(t)
            print(f"  {t} {names.get(t)} 실패 {type(e).__name__}: {str(e)[:120]}")
            if "020" in str(e):                 # DART 일일 한도 초과 — 남은 것은 retry 로 넘겨 다음 실행이 이어받는다
                failed += targets[i:]
                quota = True
                print(f"  한도 초과 — {t} 부터 {len(failed)}곳 retry 로 남김")
                break
        if i % 100 == 0:
            print(f"  {i}/{len(targets)}")
        time.sleep(0.05)
    print(f"완료 {len(targets) - len(failed)} · 실패 {len(failed)}")
    if targets and not quota and len(failed) > len(targets) * 0.2:
        raise SystemExit(f"실패 {len(failed)}건(20% 초과) — 파일을 쓰지 않는다, 직전 파일 유지")
    fill_stale(key, stocks)
    nps_asof, nps, nps_miss = load_nps(names)
    for t, hs in stocks.items():
        for h in hs:
            if h["who"] == "국민연금공단" and t in nps:
                h["ye"] = nps[t]["rate"]
    investors, cnt = pivot(stocks, names)
    out = {"updatedAt": now.isoformat(timespec="seconds"), "asOf": today, "retry": failed,
           "count": {"stocks": len(cnt), "investors": len(investors), "rows": sum(len(x["rows"]) for x in investors)},
           "note": "DART 5% 대량보유 공시를 기관별로 묶었다. rate = 마지막 공시 비율(%) · chg = 같은 계열 직전 공시 대비 %p · "
                   "exited = 마지막 공시가 5% 미만 · stale = 2년 넘게 새 보고가 없어 DART 지분 API 가 비율을 안 주는 보고자 — 마지막 보고 원문에서 비율을 읽었다(src=doc, 그 뒤 1%p 미만 변화는 모른다). "
                   "tp 단순투자 = 약식 보고, '일반(경영참가 포함 가능)' 은 원문을 봐야 갈린다. 관찰용 — 점수·매매에 쓰지 않는다.",
           "investors": investors, "stocks": cnt}
    if nps_asof:
        out["nps"] = {"asOf": nps_asof, "src": "data.go.kr 국민연금공단_국내주식 투자정보(연말, 5% 미만 포함)",
                      "rows": [{"t": t, "name": names.get(t), **v} for t, v in nps.items()], "unmatched": nps_miss}
        print(f"국민연금 연말 {nps_asof}: 붙임 {len(nps)} · 못 붙임 {len(nps_miss)}")
    out_p.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("saved:", out_p, f"{out_p.stat().st_size / 1e6:.2f}MB", out["count"])


if __name__ == "__main__":
    sys.exit(main())
