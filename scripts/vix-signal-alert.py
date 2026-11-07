#!/usr/bin/env python3
"""VIX 인버스(SVIX) 신호 알림 — 주문 없음. 마감 VIX 종가로 scripts/vix-inverse-check.py 의 상태 기계를 돌려
ENTER/ADD/EXIT 가 나온 날 텔레그램(+카카오 '나에게')으로 한 번 알린다. 같은 날짜는 다시 보내지 않는다.

실행: 미국 마감 뒤(KST 07:10 화~토). 키 없이 Yahoo chart API. 오늘(ET) 일봉은 미완성이라 버린다.
환경: TELEGRAM_BOT_TOKEN · TELEGRAM_URGENT_CHAT_ID(없으면 TELEGRAM_CHAT_ID) · (카카오) KAKAO_REST_API_KEY·KAKAO_CLIENT_SECRET + KAKAO_STATE_DIR/token.json
옵션: --dry-run (보내지 않고 출력) · --selftest
"""
import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = Path(os.environ.get("VIX_ALERT_STATE", Path.home() / "collector-venv" / "vix-alert")) / "last.json"


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def vix_closes():
    from zoneinfo import ZoneInfo
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?range=3y&interval=1d"
    r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30))["chart"]["result"][0]
    et = ZoneInfo("America/New_York")
    out = [(dt.datetime.fromtimestamp(t, et).date(), float(c)) for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c]
    return [(d, v) for d, v in out if d < dt.datetime.now(et).date()]     # 오늘(미완성) 제외


def message(sig, n, d, v, levels):
    head = f"VIX 종가 {v:.2f} ({d})"
    if sig == "ENTER":
        return f"[SVIX 매수] {head}\n매수 구간 진입 — 오늘 미국 장 초반 1/4 칸부터(누적 {n}/{len(levels)}칸). 지정가는 시세 +0.5%."
    if sig == "ADD":
        return f"[SVIX 추가매수] {head}\n분할 단계 {n}/{len(levels)} — 오늘 장 초반 추가 1/4 칸. 지정가는 시세 +0.5%."
    return f"[SVIX 전량 매도] {head}\n16 이하 마감 — 오늘 장 초반 전량 매도. 지정가는 시세 −0.5%."


def telegram(text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_URGENT_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print("텔레그램 키 없음"); return
    urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage",
                           urllib.parse.urlencode({"chat_id": chat, "text": text}).encode(), timeout=30)


def kakao(text):
    k = _load("kk", "send-kakao-report.py")
    if not (Path(k.STATE) / "token.json").exists():
        print("카카오 token.json 없음 — 건너뜀"); return
    tpl = {"object_type": "text", "text": text, "link": {"web_url": k.DASH, "mobile_web_url": k.DASH}}
    r = k.post("https://kapi.kakao.com/v2/api/talk/memo/default/send", {"template_object": json.dumps(tpl, ensure_ascii=False)}, k.access_token())
    if r.get("result_code") != 0:
        raise RuntimeError(f"카카오 전송 실패: {r}")


def check(closes, last_sent):
    chk = _load("vc", "vix-inverse-check.py")
    (_, n), sig, _, (d, v) = chk.run(closes)
    if sig in ("ENTER", "ADD", "EXIT") and str(d) != last_sent:
        return message(sig, n, d, v, chk.LEVELS), str(d)
    return None, last_sent


def selftest():
    D = dt.date
    base = [(D(2024, 1, 1) + dt.timedelta(i), v) for i, v in enumerate([15, 15.5, 18, 20.5, 26, 14])]
    for k, want in ((4, "SVIX 매수"), (5, "SVIX 추가매수"), (6, "SVIX 전량 매도")):
        msg, d = check(base[:k], "")
        assert msg and want in msg, (k, msg)
        assert check(base[:k], d)[0] is None            # 같은 날 중복 없음
    assert check(base[:3], "")[0] is None               # 대기
    print("selftest OK")


def main():
    if "--selftest" in sys.argv:
        return selftest()
    last = json.loads(STATE.read_text())["date"] if STATE.exists() else ""
    msg, d = check(vix_closes(), last)
    if not msg:
        print("신호 없음/이미 보냄"); return
    print(msg)
    if "--dry-run" in sys.argv:
        return
    for f in (telegram, kakao):                          # 한쪽 실패가 다른 쪽을 막지 않는다
        try:
            f(msg)
        except Exception as e:
            print(f"{f.__name__} 실패: {e}", file=sys.stderr)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"date": d}))


if __name__ == "__main__":
    main()
