#!/usr/bin/env python3
"""가격 목표 알림 — 주문 없음. 정해 둔 가격에 닿으면 텔레그램(+카카오 '나에게')으로 한 번 알린다.

목표 목록은 서버에만 둔다(저장소 공개 — 매매 계획 노출 금지): PRICE_TARGETS_FILE (기본 ~/collector-venv/price-targets.json).
  python3 scripts/price-target-alert.py --add KR 005930 above 85000 "삼성전자 돌파"   (market KR|US, above|below)
  python3 scripts/price-target-alert.py --list
  python3 scripts/price-target-alert.py --remove 2        (--list 의 번호)
  python3 scripts/price-target-alert.py --rearm           (이미 울린 목표를 다시 켠다)
시세: KR 네이버 fchart(정규장 09:00~15:30 KST 에만 — 그 뒤 애프터(NXT) 가격이 섞인다) · US Yahoo chart(정규장 ET 09:30~16:00, 30분 넘게 낡은 값은 버림).
울린 목표는 state(PRICE_ALERT_STATE/fired.json)에 남아 다시 안 울린다. 환경: vix-signal-alert.py 와 같은 텔레그램·카카오 설정. --dry-run · --selftest
"""
import datetime as dt
import importlib.util
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
TARGETS = Path(os.environ.get("PRICE_TARGETS_FILE", Path.home() / "collector-venv" / "price-targets.json"))
FIRED = Path(os.environ.get("PRICE_ALERT_STATE", Path.home() / "collector-venv" / "price-alert")) / "fired.json"
KST, ET = ZoneInfo("Asia/Seoul"), ZoneInfo("America/New_York")


def _get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode("utf-8", "replace")


def market_open(market, now):
    if market == "KR":
        t = now.astimezone(KST)
        return t.weekday() < 5 and dt.time(9, 0) <= t.time() <= dt.time(15, 30)
    t = now.astimezone(ET)
    return t.weekday() < 5 and dt.time(9, 30) <= t.time() <= dt.time(16, 0)


def price_kr(code, now):
    rows = [m.split("|") for m in re.findall(r'<item data="([^"]+)"', _get(
        f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=2&requestType=0"))]
    last = rows[-1]
    if last[0] != now.astimezone(KST).strftime("%Y%m%d"):
        return None                                      # 휴장일의 직전 봉
    return float(last[4])


def price_us(sym, now):
    m = json.loads(_get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1d&interval=1d"))["chart"]["result"][0]["meta"]
    if now.timestamp() - m["regularMarketTime"] > 1800:
        return None
    return float(m["regularMarketPrice"])


def hit(t, px):
    return px >= t["price"] if t["dir"] == "above" else px <= t["price"]


def tid(t):
    return f'{t["market"]}:{t["symbol"]}:{t["dir"]}:{t["price"]}'


def message(t, px):
    word = "이상 도달" if t["dir"] == "above" else "이하 도달"
    unit = "원" if t["market"] == "KR" else "달러"
    return (f'[가격 목표] {t["symbol"]} {t["price"]:,.2f}{unit} {word} — 현재 {px:,.2f}'
            + (f'\n{t["note"]}' if t.get("note") else ""))


def check(targets, fired, now, fetch):
    """(알릴 메시지 목록, 새 fired). fetch(market, symbol, now) -> 가격|None."""
    out, fired = [], set(fired)
    for t in targets:
        if tid(t) in fired or not market_open(t["market"], now):
            continue
        px = fetch(t["market"], t["symbol"], now)
        if px is not None and hit(t, px):
            out.append(message(t, px)); fired.add(tid(t))
    return out, fired


def _fetch(market, sym, now):
    try:
        return (price_kr if market == "KR" else price_us)(sym, now)
    except Exception as e:                               # 한 종목 실패가 나머지를 막지 않는다
        print(f"시세 실패 {market}:{sym}: {e}", file=sys.stderr)
        return None


def _load(p, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def selftest():
    kr = dt.datetime(2026, 11, 9, 10, 0, tzinfo=KST)                      # 월요일 장중
    ts = [dict(market="KR", symbol="005930", dir="above", price=85000, note="돌파"),
          dict(market="US", symbol="NVDA", dir="below", price=170)]
    msgs, f = check(ts, set(), kr, lambda m, s, n: 86000.0 if m == "KR" else 160.0)
    assert len(msgs) == 1 and "005930" in msgs[0] and "돌파" in msgs[0], msgs          # US 는 이 시각 장 밖
    assert check(ts, f, kr, lambda m, s, n: 90000.0)[0] == []                          # 중복 없음
    assert check(ts, set(), kr, lambda m, s, n: 80000.0)[0] == []                      # 미도달
    assert not market_open("KR", dt.datetime(2026, 11, 9, 15, 40, tzinfo=KST))         # 애프터 제외
    assert not market_open("KR", dt.datetime(2026, 11, 7, 10, 0, tzinfo=KST))          # 토요일
    us = dt.datetime(2026, 11, 9, 23, 50, tzinfo=KST)                                  # 겨울 개장 20분 뒤
    assert market_open("US", us) and check(ts, set(), us, lambda m, s, n: 160.0)[0][0].startswith("[가격 목표] NVDA")
    print("selftest OK")


def main():
    a = sys.argv[1:]
    if "--selftest" in a:
        return selftest()
    ts = _load(TARGETS, [])
    if a[:1] == ["--add"]:
        mk, sym, d, px = a[1].upper(), a[2].upper(), a[3], float(a[4])
        assert mk in ("KR", "US") and d in ("above", "below"), "market KR|US, dir above|below"
        ts.append(dict(market=mk, symbol=sym, dir=d, price=px, note=" ".join(a[5:])))
        _save(TARGETS, ts); return print("추가 — 총", len(ts), "건")
    if a[:1] == ["--list"]:
        fired = set(_load(FIRED, []))
        for i, t in enumerate(ts, 1):
            print(i, t["market"], t["symbol"], t["dir"], t["price"], "울림" if tid(t) in fired else "대기", t.get("note", ""))
        return
    if a[:1] == ["--remove"]:
        ts.pop(int(a[1]) - 1); _save(TARGETS, ts); return print("삭제 — 총", len(ts), "건")
    if a[:1] == ["--rearm"]:
        _save(FIRED, []); return print("모두 다시 켬")
    now = dt.datetime.now(dt.timezone.utc)
    msgs, fired = check(ts, set(_load(FIRED, [])), now, _fetch)
    if not msgs:
        return print("울릴 목표 없음")
    sender = importlib.util.spec_from_file_location("vs", HERE / "vix-signal-alert.py")
    vs = importlib.util.module_from_spec(sender); sender.loader.exec_module(vs)
    for m in msgs:
        print(m)
        if "--dry-run" in a:
            continue
        for f in (vs.telegram, vs.kakao):
            try:
                f(m)
            except Exception as e:
                print(f"{f.__name__} 실패: {e}", file=sys.stderr)
    if "--dry-run" not in a:
        _save(FIRED, sorted(fired))


if __name__ == "__main__":
    main()
