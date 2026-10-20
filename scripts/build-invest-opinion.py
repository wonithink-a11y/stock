"""관심종목 KR 증권사 투자의견 일지 → docs/data/invest-opinion.json (대시보드 '증권사 의견' 탭).

KIS 종목투자의견(FHKST663300C0) — 증권사·날짜·의견·직전 의견·목표가. 리포트 제목·본문은 없다.
매 실행 마지막 기준일 7일 전부터 다시 물어 늦게 들어온 행을 받고, 180일만 남긴다(첫 실행은 180일).
한 번 응답이 100행(상한)이면 기간을 반으로 나눠 다시 묻는다. 직전 목표가는 KIS 가 주지 않아
같은 종목·같은 증권사의 바로 앞 행에서 계산한다(180일 창 안에서만 — 창 밖이면 null).
맥락 전용 — 점수·등급·매매에 쓰지 않는다(절대 규칙 1).

  python scripts/build-invest-opinion.py            # 증분
  python scripts/build-invest-opinion.py --limit 5  # 시험(앞 5종목, 파일 안 씀)
  python scripts/build-invest-opinion.py --selftest # 네트워크 없음
"""
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data", "invest-opinion.json")
WATCHLIST = os.path.join(ROOT, "config", "watchlist.json")
KST = timezone(timedelta(hours=9))
PATH = "/uapi/domestic-stock/v1/quotations/invest-opinion"
TR = "FHKST663300C0"
KEEP_DAYS, OVERLAP_DAYS, CAP, SLEEP = 180, 7, 100, 0.35


def _load_a2b():
    spec = importlib.util.spec_from_file_location("a2b", os.path.join(ROOT, "scripts", "build-price-a2b.py"))
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    return b


def fetch(base, tok, key, secret, ticker, d1, d2, tries=4):
    """한 기간의 행. 실패면 예외 — 빈 응답과 실패를 섞지 않는다(교훈 57)."""
    headers = {"content-type": "application/json; charset=utf-8", "authorization": "Bearer " + tok,
               "appkey": key, "appsecret": secret, "tr_id": TR, "custtype": "P"}
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "16633", "FID_INPUT_ISCD": ticker,
              "FID_INPUT_DATE_1": "00" + d1, "FID_INPUT_DATE_2": "00" + d2}
    err = None
    for k in range(tries):
        time.sleep(SLEEP * (2 ** k))
        try:
            b = requests.get(base + PATH, headers=headers, params=params, timeout=20).json()
        except Exception as e:
            err = f"요청 예외 {type(e).__name__}"     # 주소(키 포함 가능)를 메시지에 넣지 않는다
            continue
        if b.get("rt_cd") == "0":
            rows = b.get("output") or []
            # 응답이 요청 기간 안인지 본다(교훈 81)
            if any(not (d1 <= str(r.get("stck_bsop_date", "")) <= d2) for r in rows):
                raise RuntimeError(f"{ticker} 기간 밖 행")
            return rows
        err = f"{b.get('msg_cd')} {b.get('msg1')}"
        if b.get("msg_cd") != "EGW00201":
            break
    raise RuntimeError(f"{ticker} {err}")


def fetch_range(fn, ticker, d1, d2):
    rows = fn(ticker, d1, d2)
    if len(rows) < CAP or d1 == d2:
        return rows
    a = datetime.strptime(d1, "%Y%m%d")
    mid = a + (datetime.strptime(d2, "%Y%m%d") - a) / 2
    return fetch_range(fn, ticker, d1, mid.strftime("%Y%m%d")) + \
        fetch_range(fn, ticker, (mid + timedelta(days=1)).strftime("%Y%m%d"), d2)


def to_row(t, r):
    tp = str(r.get("hts_goal_prc", "")).strip()
    return {"d": r["stck_bsop_date"], "t": t, "b": (r.get("mbcr_name") or "").strip(),
            "o": (r.get("invt_opnn") or "").strip(), "po": (r.get("rgbf_invt_opnn") or "").strip(),
            "tp": int(float(tp)) if tp not in ("", "0") else None,
            "pc": int(float(r["stck_prdy_clpr"])) if str(r.get("stck_prdy_clpr", "")).strip() not in ("", "0") else None}


def merge(old, new, cutoff):
    """같은 (날짜·종목·증권사·의견·목표가) 는 한 행. cutoff 이전은 버린다. 직전 목표가(ptp)는 다시 계산."""
    seen, out = set(), []
    for r in new + old:
        k = (r["d"], r["t"], r["b"], r["o"], r["tp"])
        if r["d"] >= cutoff and k not in seen:
            seen.add(k)
            out.append({x: r[x] for x in ("d", "t", "b", "o", "po", "tp", "pc")})
    out.sort(key=lambda r: (r["t"], r["b"], r["d"]))
    for i, r in enumerate(out):
        p = out[i - 1] if i else None
        r["ptp"] = p["tp"] if p and p["t"] == r["t"] and p["b"] == r["b"] else None
    out.sort(key=lambda r: (r["d"], r["t"], r["b"]), reverse=True)
    return out


def selftest():
    old = [{"d": "20260901", "t": "005930", "b": "A증권", "o": "BUY", "po": "BUY", "tp": 300000, "pc": 250000}]
    new = [{"d": "20261010", "t": "005930", "b": "A증권", "o": "BUY", "po": "BUY", "tp": 330000, "pc": 270000},
           dict(old[0])]
    m = merge(old, new, "20260801")
    assert len(m) == 2 and m[0]["d"] == "20261010" and m[0]["ptp"] == 300000 and m[1]["ptp"] is None
    assert merge(old, [], "20261001") == []
    calls = []
    def fake(t, d1, d2):
        calls.append((d1, d2))
        return [{}] * (CAP if d1 == "20260101" and d2 == "20260131" else 3)
    assert len(fetch_range(fake, "X", "20260101", "20260131")) == 6 and len(calls) == 3
    print("selftest ok")


def main():
    if "--selftest" in sys.argv:
        return selftest()
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    key, secret = os.environ.get("KIS_APP_KEY", ""), os.environ.get("KIS_APP_SECRET", "")
    if not (key and secret):
        env = os.path.join(ROOT, ".env")
        if os.path.exists(env):
            kv = dict(l.split("=", 1) for l in open(env, encoding="utf-8").read().splitlines() if "=" in l)
            key, secret = kv.get("KIS_APP_KEY", "").strip(), kv.get("KIS_APP_SECRET", "").strip()
    if not (key and secret):
        raise SystemExit("KIS_APP_KEY/KIS_APP_SECRET 없음")

    wl = [x for x in json.load(open(WATCHLIST, encoding="utf-8"))["tickers"] if x.get("market") == "KR"]
    names = {x["code"]: x["name"] for x in wl}
    old = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {"rows": []}
    today = datetime.now(KST).strftime("%Y%m%d")
    cutoff = (datetime.now(KST) - timedelta(days=KEEP_DAYS)).strftime("%Y%m%d")
    start = max(cutoff, (datetime.strptime(old["asOf"], "%Y%m%d") - timedelta(days=OVERLAP_DAYS)).strftime("%Y%m%d")) \
        if old.get("asOf") else cutoff

    B = _load_a2b()
    tok = B._kis_token(key, secret)
    fn = lambda t, d1, d2: fetch(B.KIS_BASE, tok, key, secret, t, d1, d2)
    new, fails, calls0 = [], [], time.time()
    for i, x in enumerate(wl[:limit] if limit else wl):
        try:
            new += [to_row(x["code"], r) for r in fetch_range(fn, x["code"], start, today)]
        except Exception as e:
            fails.append(f"{x['code']} {e}")
    print(f"{len(wl[:limit] if limit else wl)}종목 · {start}~{today} · 새로 받은 행 {len(new)} · 실패 {len(fails)} · {time.time() - calls0:.0f}초")
    for f in fails[:10]:
        print("  실패", f)
    if len(fails) > max(5, len(wl) * 0.05):     # 대량 실패면 쓰지 않는다 — 옛 파일 그대로
        raise SystemExit("실패가 많아 파일을 쓰지 않는다")
    if limit:
        print(json.dumps(new[:3], ensure_ascii=False))
        return
    rows = merge(old.get("rows", []), new, cutoff)
    json.dump({"asOf": today, "since": cutoff, "source": "KIS 종목투자의견(FHKST663300C0)",
               "note": "증권사 리포트의 의견·목표가만(제목·본문 없음). 맥락 전용 — 점수·매매 불사용.",
               "names": {t: names[t] for t in {r["t"] for r in rows} if t in names}, "rows": rows},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"→ {OUT} {len(rows)}행")


if __name__ == "__main__":
    main()
