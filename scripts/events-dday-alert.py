#!/usr/bin/env python3
"""events-dday-alert.py — 아침 D-day 텔레그램(1:1 방). VM deploy/events-dday.{service,timer} 가 평일 07:50 KST 에 돌린다.

읽는 것: ~/collector/docs/data/events.json(Actions 가 매일 만들고 VM 이 06:30 에 pull) · config/holdings.json ·
         ~/.kis-holdings.json(실계좌 보유, 있으면). D-day 는 파일의 기준일이 아니라 **오늘(KST)** 로 다시 계산한다 —
         Actions 가 늦어 어제 파일이어도 날짜는 맞다. 파일이 3일 넘게 묵었으면 메시지에 경고를 붙인다.
보내는 것: 보유 종목 D-0~7 · 거시(FOMC·금통위·만기) D-0~3 · 국내 관심종목 실적 D-0~1. 미국 관심종목은 너무 많아 뺀다(대시보드 '일정' 탭).
보낼 게 없으면 보내지 않는다.

  python3 scripts/events-dday-alert.py [--dry-run]
env: TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
ICON = {"earnings": "📊", "exdiv": "💰", "fomc": "🇺🇸", "bok": "🇰🇷", "expiry": "⏳"}


def held_codes():
    codes = {h["code"] for h in json.loads((REPO / "config" / "holdings.json").read_text(encoding="utf-8")).get("holdings", [])}
    p = Path.home() / ".kis-holdings.json"
    if p.exists():
        for h in json.loads(p.read_text(encoding="utf-8")).get("holdings", []):
            c = h.get("code") or h.get("ticker") or h.get("pdno")
            if c:
                codes.add(str(c))
    return codes


def select(events, today, held):
    out = []
    for e in events:
        n = (date.fromisoformat(e["date"]) - today).days
        if n < 0:
            continue
        if (e.get("code") in held and n <= 7) or (e["scope"] == "macro" and n <= 3) \
                or (e.get("market") == "KR" and e["kind"] == "earnings" and n <= 1):
            out.append((n, e))
    return out


def fmt(items, stale_days, held):
    lines = [f"📅 다가오는 일정 ({datetime.now(KST):%m-%d})"]
    for n, e in items:
        who = f" {'📌' if e.get('code') in held else ''}{e['name']}" if e.get("name") else ""
        tag = "" if e["status"] in ("official", "rule") else (" (Nasdaq 확인)" if e.get("confirmedBy") else " (예상)")
        lines.append(f"{'오늘' if n == 0 else f'D-{n}'} {e['date'][5:]} {ICON.get(e['kind'], '')} {e['title']}{who}{tag}")
    if stale_days > 3:
        lines.append(f"⚠ 일정 파일이 {stale_days}일 전 것 — Actions 'Build events calendar' 확인")
    return "\n".join(lines)


def main():
    dry = "--dry-run" in sys.argv
    d = json.loads((REPO / "docs" / "data" / "events.json").read_text(encoding="utf-8"))
    today = datetime.now(KST).date()
    held = held_codes()
    items = select(d["events"], today, held)
    if not items:
        print("보낼 일정 없음")
        return
    text = fmt(items[:40], (today - date.fromisoformat(d["asOf"])).days, held)
    print(text)
    if dry:
        return
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        sys.exit("TELEGRAM_BOT_TOKEN/CHAT_ID 없음")
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=30) as r:
        if r.status != 200:
            sys.exit(f"텔레그램 HTTP {r.status}")


def selftest():
    today = date(2026, 10, 20)
    ev = [{"date": "2026-10-22", "kind": "bok", "scope": "macro", "status": "official", "title": "금통위"},
          {"date": "2026-10-28", "kind": "earnings", "scope": "watch", "code": "005930", "name": "삼성전자", "market": "KR", "status": "yahoo", "title": "실적 발표"},
          {"date": "2026-10-21", "kind": "earnings", "scope": "watch", "code": "000660", "name": "SK하이닉스", "market": "KR", "status": "yahoo", "title": "실적 발표"},
          {"date": "2026-10-21", "kind": "earnings", "scope": "watch", "code": "AAPL", "name": "Apple", "market": "US", "status": "yahoo", "title": "실적 발표"},
          {"date": "2026-10-19", "kind": "fomc", "scope": "macro", "status": "official", "title": "FOMC"}]
    s = select(ev, today, {"005930"})
    keys = sorted((n, e.get("code") or e["kind"]) for n, e in s)
    assert keys == [(1, "000660"), (2, "bok")], keys   # 005930 은 D-8 이라 보유여도 빠짐, 미국 관심·지난 FOMC 빠짐
    s2 = select(ev, today, {"005930", "AAPL"})
    assert (1, "AAPL") in sorted((n, e.get("code") or e["kind"]) for n, e in s2), "보유면 미국도"
    t = fmt(sorted(s, key=lambda x: x[0]), 5, set())
    assert "D-1" in t and "⚠" in t
    print("events-dday-alert selftest OK")


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
