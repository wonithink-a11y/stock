#!/usr/bin/env python3
"""build-stock-events.py — 종목별 '지분·이벤트' 맥락 → docs/data/stock-events.json (2026-09-26)

  python scripts/build-stock-events.py [--only 005930,012450] [--out PATH]
  python scripts/build-stock-events.py --selftest          (네트워크 없음)

관심종목(config/watchlist.json KR)마다 DART 4콜(하루 ~1,400콜, 한도 2만):
  ① majorstock  5% 이상 대량보유 — 보고자별 최신 비율·직전 대비·추이(국민연금 포함 전원)
  ② elestock    임원·주요주주 소유 — 10%이상주주는 비율 흐름, 임원은 **건수만**
                (주식보상과 장내매수가 구분되지 않는다 — 삼성전자 2년 3,390건 대부분이 보상. 매수로 해석하지 않는다)
  ③ list B·I    최근 1년 주요사항·거래소 공시 중 이벤트(수주·증자·CB/BW·자사주·출자·기술수출·해명 등)
★ 두 지분 API 는 **최근 약 2년치만** 준다(2026-09 실측) — 맥락 표시용이다. 이것으로 '따라 사기'를 검증하지 않는다.
★ 첫 보고는 증감 = 보유 전량으로 찍힌다 → 'first' 로 따로 표시(매수 아님).
★ 관찰용 — 점수·매매에 쓰지 않는다(절대 규칙 1). docs/data 는 Actions(stock-events.yml)만 쓴다(절대 규칙 4 취지).
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "stock-events.json"
KST = timezone(timedelta(hours=9))

# 제목 → 분류. 위에서부터 첫 일치. 없는 것(주총·IR·기준일 등)은 버린다
EVENT_RULES = [
    ("수주", r"단일판매.?공급계약"),
    ("희석", r"유상증자결정|전환사채권발행결정|신주인수권부사채권발행결정|교환사채권발행결정"),
    ("자사주", r"자기주식(취득|처분|소각)|주식소각결정|자기주식취득신탁"),
    ("출자·인수", r"타법인주식및출자증권(취득|처분)|영업양수|영업양도|자산양수|자산양도|회사합병|회사분할|주식교환"),
    ("기술·계약", r"투자판단관련주요경영사항|기술도입|기술이전|기술제휴|신규시설투자"),
    ("주주환원", r"현금.?현물배당결정|무상증자결정"),
    ("감자·최대주주", r"감자결정|최대주주변경"),
    ("해명", r"풍문또는보도에대한해명"),
]


def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    if os.environ.get("DART_API_KEY"):
        env["DART_API_KEY"] = os.environ["DART_API_KEY"]
    return env


def num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def dart(api, key, **q):
    qs = "&".join(f"{k}={v}" for k, v in q.items())
    for attempt in range(3):
        try:
            d = json.load(urllib.request.urlopen(
                f"https://opendart.fss.or.kr/api/{api}.json?crtfc_key={key}&{qs}", timeout=60))
            break
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)
    st = d.get("status")
    if st == "013":                      # 조회된 데이터 없음 — 0건이지 실패가 아니다
        return []
    if st != "000":
        raise RuntimeError(f"DART {api} {st} {d.get('message')}")
    return d.get("list", [])


def summarize_major(rows):
    """5% 대량보유 — 보고자별 최신 비율·직전 대비·최근 4개 추이."""
    by = {}
    for r in sorted(rows, key=lambda x: (x.get("rcept_dt", ""), x.get("rcept_no", ""))):
        rate = num(r.get("stkrt"))
        if rate is None:
            continue
        by.setdefault(r.get("repror") or "?", []).append((r["rcept_dt"].replace("-", ""), rate, r.get("report_resn") or ""))
    out = []
    for who, h in by.items():
        d, rate, resn = h[-1]
        prev = h[-2][1] if len(h) > 1 else None
        out.append({"who": who, "rate": rate, "chg": None if prev is None else round(rate - prev, 2),
                    "date": d, "reason": resn[:30], "hist": [[x[0], x[1]] for x in h[-4:]]})
    out.sort(key=lambda x: -x["rate"])
    return out


def summarize_ele(rows, since):
    """임원·주요주주 — 10%이상주주는 비율 흐름, 임원은 최근 건수만(보상·매수 구분 불가)."""
    big, execs = {}, {"n": 0, "up": 0, "down": 0}
    for r in sorted(rows, key=lambda x: (x.get("rcept_dt", ""), x.get("rcept_no", ""))):
        d = (r.get("rcept_dt") or "").replace("-", "")
        cnt, irds = num(r.get("sp_stock_lmp_cnt")), num(r.get("sp_stock_lmp_irds_cnt"))
        # DART 가 0% 임원에게도 '10%이상주주' 를 붙이는 행이 있다(삼성전자 상무 6건 실측) — 비율 1% 미만은 임원으로 센다
        if "10%" in (r.get("isu_main_shrholdr") or "") and (num(r.get("sp_stock_lmp_rate")) or 0) >= 1:
            first = cnt is not None and irds is not None and cnt > 0 and abs(cnt - irds) < 1
            big.setdefault(r.get("repror") or "?", []).append(
                {"date": d, "rate": num(r.get("sp_stock_lmp_rate")), "irds": irds, "first": first})
        elif d >= since:
            execs["n"] += 1
            if irds and irds > 0:
                execs["up"] += 1
            elif irds and irds < 0:
                execs["down"] += 1
    holders = [{"who": w, **h[-1], "hist": [[x["date"], x["rate"]] for x in h[-4:]]} for w, h in big.items()]
    holders.sort(key=lambda x: -(x["rate"] or 0))
    return holders, execs


def classify(report_nm):
    nm = re.sub(r"\s+", "", report_nm or "")
    for cat, pat in EVENT_RULES:
        if re.search(pat, nm):
            return cat
    return None


def summarize_events(rows):
    ev = []
    for r in rows:
        cat = classify(r.get("report_nm"))
        if cat:
            ev.append({"d": r["rcept_dt"], "cat": cat, "nm": re.sub(r"\s+", " ", r["report_nm"]).strip()[:60],
                       "rcept": r["rcept_no"]})
    ev.sort(key=lambda x: x["d"], reverse=True)
    return ev[:40]


def selftest():
    maj = summarize_major([
        {"rcept_dt": "2026-01-02", "repror": "국민연금공단", "stkrt": "8.31", "report_resn": "단순추가취득/처분"},
        {"rcept_dt": "2026-04-01", "repror": "국민연금공단", "stkrt": "9.35", "report_resn": "단순추가취득/처분"},
        {"rcept_dt": "2025-11-01", "repror": "블랙록", "stkrt": "5.01", "report_resn": "신규"},
        {"rcept_dt": "2025-11-02", "repror": "X", "stkrt": "-"}])
    assert maj[0]["who"] == "국민연금공단" and maj[0]["chg"] == 1.04 and maj[0]["hist"][0] == ["20260102", 8.31]
    assert maj[1]["chg"] is None and len(maj) == 2                    # 비율 없는 행은 버린다(0 아님)
    big, ex = summarize_ele([
        {"rcept_dt": "2026-09-14", "repror": "국민연금공단", "isu_main_shrholdr": "10%이상주주",
         "sp_stock_lmp_cnt": "11,314,188", "sp_stock_lmp_irds_cnt": "11,314,188", "sp_stock_lmp_rate": "9.70"},
        {"rcept_dt": "2026-09-20", "repror": "홍길동", "isu_main_shrholdr": "-", "sp_stock_lmp_irds_cnt": "300"},
        {"rcept_dt": "2026-09-21", "repror": "김철수", "isu_main_shrholdr": "-", "sp_stock_lmp_irds_cnt": "-36"},
        {"rcept_dt": "2025-01-01", "repror": "옛임원", "isu_main_shrholdr": "-", "sp_stock_lmp_irds_cnt": "10"}], "20260326")
    assert big[0]["first"] is True and ex == {"n": 2, "up": 1, "down": 1}   # 첫 보고는 매수가 아니다 · 기간 밖 제외
    big2, _ = summarize_ele([{"rcept_dt": "2026-02-02", "repror": "박정호", "isu_main_shrholdr": "10%이상주주",
                              "sp_stock_lmp_cnt": "2,660", "sp_stock_lmp_irds_cnt": "1,054", "sp_stock_lmp_rate": "0.00"}], "20260101")
    assert big2 == []                                                         # 0% '10%이상주주' 표시는 오표기
    assert classify("단일판매ㆍ공급계약체결(자율공시)") == "수주"
    assert classify("[기재정정]유상증자결정") == "희석"
    assert classify("주요사항보고서(자기주식취득결정)") == "자사주"
    assert classify("기업설명회(IR)개최") is None
    print("selftest ok (8)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    key = load_env().get("DART_API_KEY")
    if not key:
        raise SystemExit("DART_API_KEY 가 필요하다")
    wl = json.loads((ROOT / "config" / "watchlist.json").read_text(encoding="utf-8"))
    targets = {t["code"]: t.get("name") for t in wl["tickers"] if (t.get("market") or "KR") == "KR"}
    if a.only:
        targets = {t: targets.get(t) for t in a.only.split(",")}
    corp = {}
    for line in (ROOT / "data" / "backfill" / "dart" / "corpcode.jsonl").read_text(encoding="utf-8").splitlines():
        j = json.loads(line)
        corp[j.get("ticker")] = j.get("corp")
    now = datetime.now(KST)
    y1 = (now - timedelta(days=365)).strftime("%Y%m%d")
    m6 = (now - timedelta(days=182)).strftime("%Y%m%d")
    items, failed, nocorp = {}, [], []
    for i, (t, name) in enumerate(targets.items(), 1):
        cc = corp.get(t)
        if not cc:
            nocorp.append(t)
            continue
        try:
            maj = summarize_major(dart("majorstock", key, corp_code=cc))
            big, execs = summarize_ele(dart("elestock", key, corp_code=cc), m6)
            ev = []
            for ty in ("B", "I"):
                ev += dart("list", key, corp_code=cc, bgn_de=y1, end_de=now.strftime("%Y%m%d"), pblntf_ty=ty, page_count=100)
            items[t] = {"name": name, "major": maj, "bigHolders": big, "execs6m": execs, "events": summarize_events(ev)}
        except Exception as e:
            failed.append(t)
            print(f"  {t} {name} 실패 {type(e).__name__}: {str(e)[:120]}")
            if "020" in str(e):                 # DART 일일 한도 초과 — 이어서 불러 봐야 전부 실패다
                break
        if i % 50 == 0:
            print(f"  {i}/{len(targets)}")
        time.sleep(0.05)
    print(f"완료 {len(items)} · 실패 {len(failed)} · corp_code 없음 {len(nocorp)}")
    if not items:
        raise SystemExit("전부 실패 — 파일을 쓰지 않는다")
    if len(failed) > len(targets) * 0.2:
        raise SystemExit(f"실패 {len(failed)}건(20% 초과) — 파일을 쓰지 않는다, 직전 파일 유지")
    out = {"updatedAt": now.isoformat(timespec="seconds"), "count": len(items),
           "note": "DART 지분 API 는 최근 약 2년치만 준다 — 그 안에 보고가 없는 5% 주주(예: 변동이 1%p 미만인 국민연금)는 목록에 없다. 임원 증감은 주식보상과 매수를 구분할 수 없다. 관찰용 — 점수·매매에 쓰지 않는다.",
           "items": items}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("saved:", a.out, f"{Path(a.out).stat().st_size / 1e6:.2f}MB")


if __name__ == "__main__":
    sys.exit(main())
