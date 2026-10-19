#!/usr/bin/env python3
"""수주 공시(단일판매ㆍ공급계약 체결·해지) 원문 수집 — 계약금액·매출액 대비 %·계약기간을 공시 당시 원본에서 읽는다.

공시 목록은 공시 제목 캐시(data/dart_event_titles, A5 패널 1,724종목 · 2015-12~)의 거래소공시(I)에서 고른다.
그 캐시는 현재 상장 종목뿐이라(폐지 6종목) `--extend-titles` 가 corpcode.jsonl 의 나머지 종목(폐지 1,240 포함)의
거래소공시 제목을 같은 기간으로 data/order-contracts/titles/ 에 받는다.
원본만 받는다([기재정정]·[첨부추가] 제외) — 공시 당시 시장이 본 숫자다. 정정 공시(대개 계약 종료 뒤 최종 금액)는 제목 수만 센다.
수익률은 계산하지 않는다. 본문 캐시 data/order-contracts/body/{접수번호}.json(정리된 본문 텍스트 + 파싱값) — 있으면 건너뛰어
중단 후 이어받기 가능. DART 한도(status 020)가 오면 그 자리에서 멈춘다.

    python research/strategy-lab/collect_dart_order_contracts.py --probe 40   # 해마다 고르게 40건만 받아 파싱률을 본다
    python research/strategy-lab/collect_dart_order_contracts.py --extend-titles   # 캐시 밖 종목 제목(종목당 1~수 콜)
    python research/strategy-lab/collect_dart_order_contracts.py              # 전량 → data/order-contracts/orders.jsonl
    python research/strategy-lab/collect_dart_order_contracts.py --reparse    # 네트워크 없이 캐시 본문만 다시 파싱
    python research/strategy-lab/collect_dart_order_contracts.py --selftest
"""
from __future__ import annotations

import argparse
import io
import json
import random
import re
import sys
import threading
import time
import zipfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import collect_dart_event_titles as cdt  # noqa: E402

TITLES = Path(cdt.CACHE)
OUT_DIR = HERE / "data" / "order-contracts"
BODY = OUT_DIR / "body"
EXT_TITLES = OUT_DIR / "titles"     # 제목 캐시 밖 종목(대부분 폐지)의 거래소공시 제목 — 생존편향을 막는다
CORPS = REPO / "data" / "backfill" / "dart" / "corpcode.jsonl"
WORKERS = 2      # 동시 요청 수. 2026-10-19 실측: 본문 4개 분당 ~240·8개 ~215(키당 상한) → 그 뒤 목록 API 4개에서
                 # OpenDART 가 이 IP 를 차단했다(연결 거부, dart.fss.or.kr 은 정상). 분당 제한 아래라도 몰아치면 막힌다
REFUSED_MAX = 20  # 연결 오류가 연달아 이만큼이면 차단으로 보고 멈춘다

RE_TITLE = re.compile(r"^단일판매.?공급계약(체결|해지)")
NUM = r"(-?[\d,]+(?:\.\d+)?)"
DATE = r"(\d{4})[-.년\s]+(\d{1,2})[-.월\s]+(\d{1,2})"


def pmap(fn, items, workers):
    """fn(x) 를 동시에 돌려 (x, 결과) 를 끝난 순서로 낸다. 예외(DART 한도 등)가 나면 남은 일을 취소하고 다시 던진다."""
    ex = ThreadPoolExecutor(workers)
    futs = {ex.submit(fn, x): x for x in items}
    try:
        for f in as_completed(futs):
            yield futs[f], f.result()
    finally:
        ex.shutdown(wait=True, cancel_futures=True)


def kind_of(nm: str):
    """제목 → (종류, 자율공시, 자회사) 또는 None. 정정·첨부추가는 None."""
    s = re.sub(r"\s+", "", nm)
    if s.startswith("["):
        return None
    m = RE_TITLE.match(s)
    if not m:
        return None
    return ("order" if m.group(1) == "체결" else "cancel"), "자율공시" in s, "자회사" in s


def _num(s):
    if s is None:
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _first(rx, text):
    m = re.search(rx, text)
    return m.group(1) if m else None


def _date(rx_label, text):
    m = re.search(rx_label + r"\s*" + DATE, text)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def parse_body(text: str) -> dict:
    """정리된 본문 → 파싱값. 못 읽은 값은 None(0 으로 채우지 않는다)."""
    t = text
    total = _first(r"계약금액\s*총액\s*\(원\)\s*" + NUM, t)
    fixed = _first(r"확정\s*계약금액\s*" + NUM, t)
    cond = _first(r"조건부\s*계약금액\s*" + NUM, t)
    plain = _first(r"계약금액\s*\(원\)\s*" + NUM, t)          # 2016 무렵 옛 서식
    amount = _num(total) or _num(plain) or _num(fixed)
    head = t.split("계약상대")[0]                              # 상대방의 '최근 매출액'과 섞이지 않게 앞쪽만
    sales = _num(_first(r"최근\s*매출액\s*\(원\)\s*" + NUM, head))
    pct = _num(_first(r"매출액\s*대비\s*\(%\)\s*" + NUM, head))
    rel = _first(r"회사와의\s*관계\s*(\S+)", t)
    return {
        "amount": amount,
        "amount_fixed": _num(fixed),
        "amount_cond": _num(cond),
        "conditional": bool(re.search(r"조건부\s*계약여부\s*해당", t)),
        "sales": sales,
        "pct": pct,
        "pct_calc": round(amount / sales * 100, 4) if amount and sales else None,
        "detail": _first(r"계약\s*구분\s*(공사수주|용역제공|기타\s*판매ㆍ공급계약|\S+)", t),   # 옛 서식만 있다(새 서식은 None)
        "content": (_first(r"(?:판매ㆍ공급계약|공급계약|계약)\s*내용\s*(.{1,80}?)\s*2\.", t) or "").strip() or None,
        "counterparty": _first(r"계약상대방?\s*(.{1,80}?)\s*-\s*(?:최근|회사와의)", t) or _first(r"계약상대방?\s*(.{1,80}?)\s*4\.", t),
        "related": None if rel is None else ("특수관계" in rel),
        "start": _date(r"시작일", t),
        "end": _date(r"종료일", t),
        "contract_date": _date(r"계약\s*\(수주\)\s*일(?:자)?", t),
        "cancel_date": _date(r"해지\s*일자", t),
        "withheld": bool(re.search(r"유보기한\s*\d{4}", t)),   # 공시 유보 — 금액·%가 '-'로 가려졌다
        "cancel_amount": _num(_first(r"해지금액\s*\(원\)\s*" + NUM, t)),
        "currency_note": bool(re.search(r"USD|EUR|JPY|미화|달러|외화", t[:600])),
    }


def clean(raw: bytes) -> str:
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        s = raw.decode("cp949", errors="replace")
    s = re.sub(r"(?is)<style.*?</style>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s).replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


def fetch(key, no, calls):
    p = BODY / f"{no}.json"
    if p.exists():
        return json.load(open(p, encoding="utf-8"))
    for attempt in range(3):
        try:
            r = requests.get("https://opendart.fss.or.kr/api/document.xml",
                             params={"crtfc_key": key, "rcept_no": no}, timeout=60)
            break
        except requests.RequestException as e:
            if attempt == 2:                       # 원래 예외 문구엔 API 키가 든 주소가 있다 — 로그에 남기지 않는다(절대 규칙 2)
                raise RuntimeError(f"DART 전송 실패({type(e).__name__}) — 접수번호 {no}") from None
            time.sleep(5)
    calls[0] += 1
    if r.content[:2] != b"PK":
        if b"020" in r.content[:300]:
            raise cdt.LimitReached(r.text[:200])
        out = {"text": None, "error": r.text[:200]}       # 문서 없음 등 — 다시 받지 않도록 기록
    else:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        out = {"text": clean(b" ".join(z.read(n) for n in z.namelist())), "error": None}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{threading.get_ident()}.tmp")
    json.dump(out, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
    tmp.replace(p)                         # 중단돼도 반쪽 캐시가 남지 않게
    time.sleep(0.1)
    return out


def listing():
    """제목 캐시 → 원본 수주·해지 공시 목록 + 정정 제목 수(기록)."""
    corp2t = {}
    for line in open(CORPS, encoding="utf-8"):
        j = json.loads(line)
        if j.get("corp") and j.get("ticker"):
            corp2t[j["corp"]] = (j["ticker"], j.get("corpName", ""))
    rows, amend = [], Counter()
    for p in sorted(TITLES.glob("*.json")) + sorted(EXT_TITLES.glob("*.json")):
        corp, src = p.stem, ("ext" if p.parent == EXT_TITLES else "cache")
        for r in json.load(open(p, encoding="utf-8")).get("I", []):
            nm = re.sub(r"\s+", "", r["nm"])
            if nm.startswith("[") and re.search(r"단일판매.?공급계약(체결|해지)", nm):
                amend[corp] += 1
            k = kind_of(r["nm"])
            if not k:
                continue
            t, name = corp2t.get(corp, (None, ""))
            rows.append({"rcept_no": r["no"], "filed": r["d"], "corp": corp, "ticker": t, "name": name,
                         "kind": k[0], "voluntary": k[1], "subsidiary": k[2], "title": r["nm"].strip(), "src": src})
    rows.sort(key=lambda x: x["rcept_no"])
    return rows, amend


def extend_titles(limit=None, workers=WORKERS):
    """corpcode.jsonl 종목 중 제목 캐시에 없는 회사의 거래소공시(I) 제목을 cdt.BGN~cdt.END 로 받는다. 있으면 건너뜀."""
    key = cdt.load_env().get("DART_API_KEY")
    if not key:
        sys.exit("DART_API_KEY 없음(.env)")
    have = {p.stem for p in TITLES.glob("*.json")}
    corps = sorted({json.loads(l)["corp"] for l in open(CORPS, encoding="utf-8")} - have)
    todo = [c for c in corps if not (EXT_TITLES / f"{c}.json").exists()][:limit]
    print(f"캐시 밖 {len(corps)}종목 · 남은 {len(todo)}")
    EXT_TITLES.mkdir(parents=True, exist_ok=True)
    calls, refused = [0], [0]

    def one(corp):
        try:
            _one(corp)
            refused[0] = 0
        except cdt.LimitReached:
            raise
        except Exception as e:             # 이 종목만 건너뛴다(파일이 없으니 다음 실행에서 다시 받는다)
            refused[0] += 1
            if refused[0] >= REFUSED_MAX:
                raise SystemExit(f"연결 오류 {REFUSED_MAX}회 연속 — OpenDART 차단 의심, 나중에 다시 실행: {e!r}")

    def _one(corp):
        rows, page = [], 1
        while True:
            lst, total = cdt.dart_list_range(key, corp, "I", page, cdt.BGN, cdt.END)
            calls[0] += 1
            rows += [{"d": r["rcept_dt"], "nm": r["report_nm"], "no": r["rcept_no"]} for r in lst]
            if page >= total:
                break
            page += 1
            time.sleep(0.05)
        tmp = EXT_TITLES / f"{corp}.json.tmp"
        json.dump({"I": rows, "_range": [cdt.BGN, cdt.END]}, open(tmp, "w", encoding="utf-8"), ensure_ascii=False)
        tmp.replace(EXT_TITLES / f"{corp}.json")

    try:
        for i, _ in enumerate(pmap(one, todo, workers), 1):
            if i % 200 == 0:
                print(f"  {i}/{len(todo)} 호출 {calls[0]}", flush=True)
    except cdt.LimitReached as e:
        sys.exit(f"DART 한도 도달 — 받은 종목은 보존, 다시 실행하면 이어서: {e}")
    print(f"제목 완료 · 호출 {calls[0]}")


def row_out(r, b):
    out = dict(r)
    out["error"] = b.get("error")
    out.update(parse_body(b["text"]) if b.get("text") else {})
    return out


def write(rows, amend, bodies):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n, ok = Counter(), Counter()
    with open(OUT_DIR / "orders.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            b = bodies.get(r["rcept_no"])
            if b is None:
                continue
            o = row_out(r, b)
            o["amend_titles_corp"] = amend.get(r["corp"], 0)
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
            n[r["kind"]] += 1
            if r["kind"] == "order" and (o.get("pct") is not None or o.get("pct_calc") is not None):
                ok["pct"] += 1
            if r["kind"] == "order" and o.get("end"):
                ok["end"] += 1
    print(f"orders.jsonl — 체결 {n['order']} · 해지 {n['cancel']} · 매출액 대비 % 있음 {ok['pct']}/{n['order']} · 종료일 {ok['end']}/{n['order']}")


def report(rows, bodies, show=8):
    miss = Counter()
    by_year = Counter()
    for r in rows:
        b = bodies.get(r["rcept_no"])
        if not b or r["kind"] != "order":
            continue
        by_year[r["filed"][:4]] += 1
        if not b.get("text"):
            miss["no_text"] += 1
            continue
        o = parse_body(b["text"])
        for k in ("amount", "sales", "pct", "start", "end", "contract_date", "counterparty"):
            if o[k] is None:
                miss[k] += 1
        if o["pct"] is not None and o["pct_calc"] is not None and abs(o["pct"] - o["pct_calc"]) > max(0.05, o["pct"] * 0.02):
            miss["pct_mismatch"] += 1
    tot = sum(by_year.values())
    print(f"체결 {tot}건 · 연도 {dict(sorted(by_year.items()))}")
    print("못 읽음:", {k: f"{v} ({v / max(tot, 1):.1%})" for k, v in miss.most_common()})
    bad = [r for r in rows if r["kind"] == "order" and bodies.get(r["rcept_no"], {}).get("text")
           and parse_body(bodies[r["rcept_no"]]["text"])["pct"] is None][:show]
    for r in bad:
        print("  % 없음:", r["rcept_no"], r["name"], bodies[r["rcept_no"]]["text"][:300])


def run(probe=None, reparse=False, workers=WORKERS):
    rows, amend = listing()
    print(f"원본 공시 {len(rows)}건(체결 {sum(r['kind'] == 'order' for r in rows)} · 해지 {sum(r['kind'] == 'cancel' for r in rows)})"
          f" · 정정 제목 {sum(amend.values())}건(기록만) · 종목 매핑 없음 {sum(r['ticker'] is None for r in rows)}")
    if probe:
        rng = random.Random(20261019)
        by_y = {}
        for r in rows:
            by_y.setdefault(r["filed"][:4], []).append(r)
        per = max(1, probe // len(by_y))
        rows = sorted((x for v in by_y.values() for x in rng.sample(v, min(per, len(v)))), key=lambda x: x["rcept_no"])
    bodies, calls = {}, [0]
    if reparse:
        for r in rows:
            p = BODY / f"{r['rcept_no']}.json"
            if p.exists():
                bodies[r["rcept_no"]] = json.load(open(p, encoding="utf-8"))
    else:
        key = cdt.load_env().get("DART_API_KEY")
        if not key:
            sys.exit("DART_API_KEY 없음(.env)")
        try:
            for i, (no, b) in enumerate(pmap(lambda no: fetch(key, no, calls), [r["rcept_no"] for r in rows], workers), 1):
                bodies[no] = b
                if i % 500 == 0:
                    print(f"  {i}/{len(rows)} 호출 {calls[0]}", flush=True)
        except cdt.LimitReached as e:
            print(f"DART 한도 도달 — 캐시 보존, 다시 실행하면 이어서: {e}")
            report(rows, bodies, show=0)
            sys.exit(2)
    print(f"호출 {calls[0]} · 본문 {len(bodies)}/{len(rows)}")
    report(rows, bodies, show=8 if probe else 3)
    if not probe:
        write(rows, amend, bodies)


def selftest():
    new = ("1. 판매ㆍ공급계약 내용 Boiler Package 제작 2. 계약내역 조건부 계약여부 미해당 확정 계약금액 9,916,500,000 "
           "조건부 계약금액 - 계약금액 총액(원) 9,916,500,000 최근 매출액(원) 82,034,829,154 매출액 대비(%) 12.09 "
           "3. 계약상대방 웰크론한텍 -최근 매출액(원) 251,911,709,297 -주요사업 플랜트 -회사와의 관계 특수관계자 "
           "4. 판매ㆍ공급지역 대구광역시 5. 계약기간 시작일 2018-12-13 종료일 2020-08-28 6. 주요 계약조건 - "
           "8. 계약(수주)일자 2018-12-13")
    o = parse_body(new)
    assert o["amount"] == 9916500000 and o["sales"] == 82034829154 and o["pct"] == 12.09, o
    assert abs(o["pct_calc"] - 12.0882) < 0.01 and o["related"] is True and o["conditional"] is False
    assert o["start"] == "2018-12-13" and o["end"] == "2020-08-28" and o["contract_date"] == "2018-12-13"
    assert o["counterparty"] == "웰크론한텍" and o["content"] == "Boiler Package 제작" and o["detail"] is None, o
    assert parse_body("1. 판매ㆍ공급계약 구분 공사수주 - 체결계약명 X 2. 계약내역")["detail"] == "공사수주"
    old = ("1. 공급계약 내용 LCD 장비 2. 계약금액(원) 1,200,000,000 최근 매출액(원) 30,000,000,000 매출액 대비(%) 4.0 "
           "3. 계약상대방 삼성디스플레이 4. 판매ㆍ공급지역 충남 5. 계약기간 시작일 2016. 3. 2 종료일 2016년 9월 30일")
    o = parse_body(old)
    assert o["amount"] == 1.2e9 and o["pct"] == 4.0 and o["start"] == "2016-03-02" and o["end"] == "2016-09-30", o
    assert o["related"] is None and o["sales"] == 3e10
    o = parse_body("3. 계약상대 SK하이닉스 - 회사와의 관계 - 4. 판매ㆍ공급지역 경기 7. 계약(수주)일 2019-04-24")
    assert o["counterparty"] == "SK하이닉스" and o["contract_date"] == "2019-04-24", o
    o = parse_body("계약금액 총액(원) - 최근 매출액(원) 5,350,047,190 매출액 대비(%) - 9. 공시유보 관련내용 유보기한 2027-09-29 유보사유 비밀")
    assert o["amount"] is None and o["pct"] is None and o["withheld"] is True, o
    o = parse_body("2. 해지내역 해지금액(원) 19,558,968,000 최근매출액(원) 74,923,370,933 매출액대비(%) 26.11 6. 해지일자 2017-11-06")
    assert o["cancel_amount"] == 19558968000 and o["pct"] == 26.11 and o["cancel_date"] == "2017-11-06", o
    assert clean(b"<style>.x{a:b}</style><td>1</td>") == "1"
    o = parse_body("계약 내용 없음")
    assert o["amount"] is None and o["pct"] is None and o["pct_calc"] is None     # 모르는 것은 0 이 아니다
    assert kind_of("단일판매ㆍ공급계약체결              ") == ("order", False, False)
    assert kind_of("단일판매ㆍ공급계약체결(자율공시)") == ("order", True, False)
    assert kind_of("단일판매ㆍ공급계약체결(자회사의 주요경영사항)") == ("order", False, True)
    assert kind_of("단일판매ㆍ공급계약해지") == ("cancel", False, False)
    assert kind_of("[기재정정]단일판매ㆍ공급계약체결") is None and kind_of("주권매매거래정지(단일판매공급계약)") is None
    assert clean("<p>a&nbsp;b</p>\n<td>c</td>".encode("utf-8")) == "a b c"
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--probe", type=int)
    ap.add_argument("--reparse", action="store_true")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--extend-titles", nargs="?", const=0, type=int, metavar="N", help="캐시 밖 종목 제목 받기(N 개만, 생략 시 전부)")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.extend_titles is not None:
        extend_titles(a.extend_titles or None, a.workers)
    else:
        run(a.probe, a.reparse, a.workers)
