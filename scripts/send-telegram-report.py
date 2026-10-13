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


def main(paths):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 없음")
        return 1
    base = os.environ.get("REPORT_URL_BASE", "").rstrip("/")
    ok = True
    for p in paths:
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
