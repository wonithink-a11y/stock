#!/usr/bin/env python3
"""장 마감 리포트(.md)를 텔레그램 1:1 방으로 보낸다. market-report-telegram 워크플로가 부른다.

  python scripts/send-telegram-report.py reports/market-daily/2026-10-13-kr.md [...]

env: TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID (1:1 방) · REPORT_URL_BASE(선택, 끝에 원문 링크).
텔레그램 한 메시지 상한 4,096자 → 3,900자 이하로 줄 단위 분할. parse_mode 없음(마크다운 깨짐으로 발송 실패하지 않게).
보낸 메시지마다 3회 재시도(429 는 retry_after 존중). 하나라도 실패하면 exit 1 → notify-failure 가 장애 방에 알린다.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

LIMIT = 3900


def split(text, limit=LIMIT):
    chunks, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:  # 한 줄이 상한보다 길면 자른다
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) > limit:
            chunks.append(cur)
            cur = ""
        cur += line
    if cur.strip():
        chunks.append(cur)
    return [c.rstrip("\n") for c in chunks if c.strip()]


def send(token, chat, text):
    body = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if json.load(r).get("ok"):
                    return True
        except urllib.error.HTTPError as e:
            info = json.loads(e.read() or b"{}")
            print(f"  HTTP {e.code}: {info.get('description')}")
            wait = (info.get("parameters") or {}).get("retry_after")
            if wait:
                time.sleep(wait)
                continue
        except Exception as e:  # noqa: BLE001
            print(f"  {type(e).__name__}: {e}")
        time.sleep(2 ** (attempt + 1))
    return False


def _p(v):
    return "−" if v is None else f"{v:+.2f}%".replace("-", "−")


def short_message(md_path, facts, summary, dash_url=""):
    """facts.json(숫자) + summary.json(해석 뼈대) → 텔레그램용 짧은 요약. 전문은 대시보드 링크로."""
    import datetime as dt
    stem = os.path.basename(md_path)[:-3]                      # 2026-10-12-kr
    day, mkt = stem[:10], stem[11:]
    wd = "월화수목금토일"[dt.date.fromisoformat(day).weekday()]
    s = facts.get("series", [])
    L = [f"{'📊 한국장' if mkt == 'kr' else '🌎 미국장'} 마감 | {day}({wd})"]
    for r in s:
        if r.get("group") == "지수" and "close" in r:
            stale = "" if r.get("fresh", True) else f" [{r.get('barDate')} 값]"
            L.append(f"{r['name']} {r['close']:,.2f} {_p(r['chgPct'])} (5일 {_p(r.get('chg5dPct'))}){stale}")
    if mkt == "kr":
        for code, v in (facts.get("kr") or {}).items():
            f = v.get("flows억원") or {}
            if f.get("외국인") is not None:
                L.append(f"수급(억) {code} 외국인 {f['외국인']:+,.0f} · 기관 {f['기관']:+,.0f} · 개인 {f['개인']:+,.0f}".replace("-", "−"))
    else:
        tnx = next((r for r in s if r.get("sym") == "^TNX" and "close" in r), None)
        vix = next((r for r in s if r.get("sym") == "^VIX" and "close" in r), None)
        if tnx and vix:
            L.append(f"10년물 {tnx['close']:.2f}% ({tnx.get('chgBp', 0):+.1f}bp) · VIX {vix['close']:.2f} ({_p(vix['chgPct'])})".replace("-", "−"))
    L += ["", summary.get("headline", "")]
    causes = summary.get("causes") or []
    if causes:
        L += ["", "왜 움직였나"] + [f"{i}) {c.get('title', '')} ({c.get('confidence', '')})" for i, c in enumerate(causes[:3], 1)]
    sec = sorted((r for r in s if r.get("group") in ("업종ETF", "섹터") and r.get("chgPct") is not None),
                 key=lambda r: r["chgPct"], reverse=True)
    if len(sec) >= 6:
        fmt = lambda rs: " · ".join(f"{r['name'].replace('KODEX ', '').replace('TIGER ', '')} {_p(r['chgPct'])}" for r in rs)  # noqa: E731
        L += ["", f"강세: {fmt(sec[:3])}", f"약세: {fmt(sec[-3:][::-1])}"]
    if summary.get("watch"):
        L += ["", "체크: " + " · ".join(summary["watch"][:3])]
    if dash_url:
        L += ["", f"전체 분석·근거 → {dash_url}#mreport={stem}"]
    return "\n".join(L).strip()


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001 — 없거나 깨지면 전문 발송으로 대체
        return None


def main(paths):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 없음")
        return 1
    base = os.environ.get("REPORT_URL_BASE", "").rstrip("/")
    dash = os.environ.get("REPORT_DASHBOARD_URL", "")
    ok = True
    for p in paths:
        facts, summary = _load_json(p[:-3] + ".facts.json"), _load_json(p[:-3] + ".summary.json")
        if isinstance(facts, dict) and isinstance(summary, dict):
            text = short_message(p, facts, summary, dash)
        else:
            with open(p, encoding="utf-8") as f:
                text = f.read()
            if base:
                text += f"\n\n원문: {base}/{p}"
        parts = split(text)
        for i, part in enumerate(parts, 1):
            head = f"({i}/{len(parts)})\n" if len(parts) > 1 else ""
            sent = send(token, chat, head + part)
            print(f"{p} {i}/{len(parts)} {'보냄' if sent else '실패'}")
            ok &= sent
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
