#!/usr/bin/env python3
"""월간 종목 예측(stock-forecast-forward) 후보 걸러내기 + 뉴스 제목 모으기 — 클라우드 세션에서도 돈다(2026-11-01).

10월은 PC 전용 quarterly-multi 패널(DART)로 걸렀다. 클라우드엔 DART 키가 없어 11월부터 네이버 분기 재무(키 없음)로 같은 문턱을 잰다:
  A = A3 갈래 A ∧ 시총 3천억↑ ∧ 20일 거래대금 30억↑ ∧ 최근 분기 매출 YoY +20%↑ ∧ 영업이익 YoY +30%↑(전년 흑자) ∧
      최근 4분기 영업이익률 8%↑ ∧ 부채비율 150% 미만 ∧ 최근 4분기 지배순이익 PER 20 이하
  B = A3 갈래 B ∧ 시총 2천억↑ ∧ 거래대금 20억↑ ∧ 최근 분기 매출 YoY +30%↑ ∧ 영업손익 개선
문턱을 바꾸면 예측 파일 process 칸에 적는다. 이 스크립트는 후보 표만 낸다 — 고르는 것은 사람(또는 루틴의 Claude)이다.

  python research/strategy-lab/forecast_screen.py screen            # → .cache/forecast/screen-YYYY-MM.json + 표 출력(네이버 약 800콜, 4분 안팎)
  python research/strategy-lab/forecast_screen.py news "검색어" …    # 구글 뉴스 RSS(그 달 1일 전 30일 ~ 오늘) 제목·날짜·링크 → .cache/forecast/news.json 에 누적
"""
import datetime as dt
import email.utils
import gzip
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = ROOT / ".cache" / "forecast"
KST = dt.timezone(dt.timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (stock-forecast-screen)"}
sys.path.insert(0, str(HERE))


def get_json(url):
    for i in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                return json.load(r)
        except Exception:  # noqa: BLE001 — 3번까지 다시
            time.sleep(1 + i)
    return None


def num(s):
    return None if s in (None, "", "-", "N/A") else float(str(s).replace(",", ""))


def listing(min_cap=2e11):
    out = []
    for mk in ("KOSPI", "KOSDAQ"):
        for page in range(1, 40):
            j = get_json(f"https://m.stock.naver.com/api/stocks/marketValue/{mk}?page={page}&pageSize=100")
            if not j or not j.get("stocks"):
                break
            for s in j["stocks"]:
                cap = (num(s.get("marketValue")) or 0) * 1e8
                if s.get("stockEndType") == "stock" and cap >= min_cap and not re.search(r"스팩|기업인수목적|리츠", s["stockName"]):
                    out.append({"t": s["itemCode"], "n": s["stockName"], "cap": cap})
            if (num(j["stocks"][-1].get("marketValue")) or 0) * 1e8 < min_cap:
                break
    return out


def tv20():
    """A2a 최근 연도 파일의 종목별 마지막 20거래일 평균 거래대금(원)."""
    p = max((ROOT / "data/backfill/price/a2a").glob("20*.jsonl.gz"))
    rows = {}
    with gzip.open(p, "rt") as f:
        for line in f:
            r = json.loads(line)
            rows.setdefault(r["ticker"], []).append((r["date"], r["close"] * r["volume"]))
    last = max(d for v in rows.values() for d, _ in v)
    return {t: sum(x for _, x in sorted(v)[-20:]) / min(20, len(v)) for t, v in rows.items()}, last


def quarter(x):
    q = get_json(f"https://m.stock.naver.com/api/stock/{x['t']}/finance/quarter")
    if not q or not q.get("financeInfo"):
        return None
    fi = q["financeInfo"]
    keys = [k["key"] for k in fi["trTitleList"] if k["isConsensus"] == "N"]
    return keys, {r["title"]: {k: num(r["columns"].get(k, {}).get("value")) for k in keys} for r in fi["rowList"]}


def metrics(x, keys, q):
    """최근 확정 분기 L 과 전년 같은 분기 L-100 비교 + 최근 4분기 합. 계산 못 하면 None."""
    if not keys:
        return None
    L = keys[-1]
    P = str(int(L[:4]) - 1) + L[4:]
    last4 = keys[-4:]
    rv, op = q.get("매출액", {}), q.get("영업이익", {})
    ni = q.get("지배주주순이익") or q.get("당기순이익") or {}
    if P not in keys or len(last4) < 4 or any(rv.get(k) is None or op.get(k) is None for k in last4 + [P]):
        return None
    rt, ot, nt = sum(rv[k] for k in last4), sum(op[k] for k in last4), sum(ni.get(k) or 0 for k in last4)
    return {"quarter": L, "rg": rv[L] / rv[P] - 1 if rv[P] else None,
            "og": op[L] / op[P] - 1 if op[P] and op[P] > 0 else None, "opPrev": op[P], "opLast": op[L],
            "om": ot / rt if rt else None, "debt": (q.get("부채비율") or {}).get(L),
            "per": x["cap"] / (nt * 1e8) if nt > 0 else None}


def classify(m, cap, tv, weak):
    if m is None or weak is None:
        return None
    if (weak is False and cap >= 3e11 and tv >= 3e9 and m["rg"] is not None and m["rg"] >= .2 and m["og"] is not None
            and m["og"] >= .3 and m["om"] and m["om"] >= .08 and m["debt"] is not None and m["debt"] < 150
            and m["per"] and m["per"] <= 20 and m["opLast"] > 0):
        return "A"
    if weak is True and cap >= 2e11 and tv >= 2e9 and m["rg"] is not None and m["rg"] >= .3 and m["opLast"] > m["opPrev"]:
        return "B"
    return None


def cmd_screen():
    import run_stock_forecast_forward as sf
    today = dt.datetime.now(KST).date()
    a3 = sf.a3_latest(today.isoformat())
    lst = listing()
    tv, a2a_last = tv20()
    with ThreadPoolExecutor(4) as ex:
        qs = list(ex.map(quarter, lst))
    rows = []
    for x, q in zip(lst, qs):
        m = metrics(x, *q) if q else None
        weak = sf.is_weak(a3[x["t"]]) if x["t"] in a3 else None
        lane = classify(m, x["cap"], tv.get(x["t"], 0), weak)
        if lane:
            rows.append({"lane": lane, "ticker": x["t"], "name": x["n"], "capEok": round(x["cap"] / 1e8), "tv20Eok": round(tv.get(x["t"], 0) / 1e8, 1),
                         **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()},
                         "a3FY": a3[x["t"]]["fiscalYear"]})
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"asOf": today.isoformat(), "a2aLast": a2a_last, "listed": len(lst), "withFinance": sum(1 for q in qs if q), "rows": rows}
    (OUT / f"screen-{today:%Y-%m}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"상장 {len(lst)} · 재무 {res['withFinance']} · A2a 마지막 {a2a_last} → {OUT / f'screen-{today:%Y-%m}.json'}")
    for lane in "AB":
        rs = sorted((r for r in rows if r["lane"] == lane), key=lambda r: -r["capEok"])
        print(f"\n갈래 {lane} {len(rs)}개 (분기 {rs[0]['quarter'] if rs else '-'})")
        for r in rs:
            f = lambda v, pct=True: "-" if v is None else (f"{v * 100:.0f}%" if pct else f"{v:.1f}")  # noqa: E731
            print(f"  {r['ticker']} {r['name'][:10]:10} 시총 {r['capEok']:>9,}억 거래 {r['tv20Eok']:>7}억 매출 {f(r['rg'])} 영업 {f(r['og'])} "
                  f"({r['opPrev']:,.0f}→{r['opLast']:,.0f}) 이익률 {f(r['om'])} 부채 {r['debt']} PER {f(r['per'], False)}")


def cmd_news(queries):
    today = dt.datetime.now(KST).date()
    start = today.replace(day=1) - dt.timedelta(days=30)
    path = OUT / "news.json"
    OUT.mkdir(parents=True, exist_ok=True)
    store = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for q in queries:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{q} after:{start} before:{today + dt.timedelta(days=1)}")
               + "&hl=ko&gl=KR&ceid=KR:ko")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                root = ET.fromstring(r.read())
        except Exception as e:  # noqa: BLE001
            print(f"## {q}: 실패 {e}")
            continue
        items = []
        for it in root.iter("item"):
            t = email.utils.parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST)
            src = it.findtext("source") or ""
            title = it.findtext("title") or ""
            if src and title.endswith(" - " + src):
                title = title[: -len(" - " + src)]
            if t.date() <= today:
                items.append({"date": t.date().isoformat(), "source": src, "title": title, "url": it.findtext("link")})
        items.sort(key=lambda x: x["date"], reverse=True)
        store[q] = items
        print(f"## {q} ({len(items)})")
        for x in items[:8]:
            print(f"  {x['date']} {x['source']} | {x['title'][:90]}")
    path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")


def selftest():
    keys = ["202506", "202509", "202512", "202603", "202606"]
    q = {"매출액": dict(zip(keys, [100, 110, 120, 130, 150])), "영업이익": dict(zip(keys, [10, 11, 12, 13, 20])),
         "지배주주순이익": dict(zip(keys, [60, 60, 60, 60, 60])), "부채비율": {"202606": 50.0}}
    m = metrics({"cap": 4e11}, keys, q)
    assert m["quarter"] == "202606" and abs(m["rg"] - .5) < 1e-9 and abs(m["og"] - 1) < 1e-9
    assert abs(m["om"] - 56 / 510) < 1e-9 and abs(m["per"] - 4e11 / 240e8) < 1e-9      # 4분기 = 202509~202606
    assert classify(m, 4e11, 5e9, False) == "A" and classify(m, 4e11, 5e9, None) is None
    assert classify({**m, "per": 25}, 4e11, 5e9, False) is None                         # PER 문턱
    assert classify(m, 4e11, 5e9, True) == "B" and classify({**m, "opLast": 9}, 4e11, 5e9, True) is None
    assert metrics({"cap": 1}, keys[1:], q) is None and metrics({"cap": 1}, [], q) is None   # 전년 같은 분기 없음 · 확정 분기 없음
    print("selftest ok")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
    elif a[0] == "--selftest":
        selftest()
    elif a[0] == "screen":
        cmd_screen()
    elif a[0] == "news":
        cmd_news(a[1:])
    else:
        sys.exit(f"모르는 명령: {a[0]}")
