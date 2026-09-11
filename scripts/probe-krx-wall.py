#!/usr/bin/env python
"""KRX 벽 진단 - 세션인가 IP인가. (2026-09-11)

관측: shares-snapshot 이 매 실행 어느 지점에서 성공이 **얼어붙고** 그 뒤 100% 실패한다
(벽 위치 112/166/214/233/107). 600초 쉬어도 안 풀린다(09-10 패스2 139시도 0성공).
벽은 호출 수로도 시각으로도 안 맞고 로그인 후 56~113초 사이에 온다. 우리 KRX
워크플로끼리 겹친 적도 없다(Actions 전수 대조) - 그래서 원인을 모른다.

이 프로브가 가르는 것:

  Phase A  막힐 때까지 민다. ★ 막힌 응답의 **실제 모양**을 찍는다(status·content-type·
           본문 앞부분). 여태 아무도 본 적이 없다 - JSON 파싱 실패 예외만 봤다.
           HTML 로그인 페이지면 세션 무효, 429/차단 문구면 유량 제한이다.
  Phase B  같은 프로세스·같은 IP 에서 **즉시 재로그인**하고 이어 돈다.
             살아난다 -> 세션 단위. 고칠 방법이 있다(막히면 재로그인)
             안 산다   -> 세션이 아니다. IP 또는 계정 단위
  Phase C  B 가 실패하면 60초 쉬고 재로그인해 10개만 더. 짧은 쿨다운인지 본다.

쓰기 없음 - 네트워크 읽기만 한다. 산출물도 안 만든다(로그가 전부다).

  python scripts/probe-krx-wall.py [--limit 400]
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST = os.path.join(ROOT, "config", "watchlist.json")
LOOKBACK_DAYS = 10
SLEEP_SECONDS = 0.2
HTTP_TIMEOUT = 20

_last = {"resp": None}


def install_hooks(seconds=HTTP_TIMEOUT):
    """timeout 없는 호출에 기본 타임아웃을 주고, 마지막 응답을 붙잡아 둔다.

    ★ socket.setdefaulttimeout 은 듣지 않는다(urllib3 2.x, 실측 2026-09-11) -
    어댑터에 넣어야 걸린다. build-shares-snapshot.py 와 같은 이유·같은 자리."""
    from requests.adapters import HTTPAdapter
    send = HTTPAdapter.send

    def send_hooked(self, request, **kw):
        if kw.get("timeout") is None:
            kw["timeout"] = seconds
        resp = send(self, request, **kw)
        _last["resp"] = resp
        return resp

    HTTPAdapter.send = send_hooked


def describe_last(label):
    """막힌 순간의 응답을 그대로 보여준다. 쿠키류는 찍지 않는다(규칙 2)."""
    r = _last["resp"]
    print("  --- %s ---" % label, flush=True)
    if r is None:
        print("  (응답 없음)", flush=True)
        return
    body = (r.text or "")
    for k in ("JSESSIONID", "Set-Cookie", "Cookie"):
        body = body.replace(k, "[%s]" % k)
    print("  status        %s" % r.status_code, flush=True)
    print("  content-type  %s" % r.headers.get("Content-Type"), flush=True)
    print("  length        %s" % r.headers.get("Content-Length"), flush=True)
    print("  url           %s" % r.url, flush=True)
    print("  body[:500]    %s" % repr(body[:500]), flush=True)


def relogin():
    from pykrx.website.comm import auth
    s = getattr(auth, "_auth_session", None)
    if s is None:
        print("  재로그인 불가 - 인증 세션이 없다", flush=True)
        return False
    try:
        ok = s.refresh(os.environ.get("KRX_ID"), os.environ.get("KRX_PW"))
    except Exception as e:                                        # noqa: BLE001
        # ★ 실측(2026-09-11): 막힌 뒤에는 **로그인 엔드포인트도** 같은 비-JSON 을 준다.
        #   로그인 URL 은 데이터 URL 과 다른 주소다 - 즉 세션 무효화가 아니라
        #   호출자 단위(IP 또는 계정) 차단이다. 죽지 말고 기록한다.
        print("  재로그인 예외: %s: %s" % (type(e).__name__, e), flush=True)
        describe_last("로그인 엔드포인트의 막힌 응답")
        return False
    print("  재로그인 %s" % ("성공" if ok else "실패"), flush=True)
    return ok


def run_batch(stock, tickers, from_date, to_date, label):
    """★ pykrx 는 JSONDecodeError 를 **스스로 잡아 찍고 빈 df 를 준다**(실측 2026-09-11).
    그래서 막힘은 예외가 아니라 '빈 응답'으로 온다 - 두 경로를 같은 실패로 센다."""
    ok = fail = streak = 0
    first_fail_at = None
    for i, t in enumerate(tickers, 1):
        got = False
        try:
            df = stock.get_shorting_balance_by_date(from_date, to_date, t)
            got = df is not None and len(df) > 0
            why = "빈 응답"
        except Exception as e:                                    # noqa: BLE001
            why = "%s: %s" % (type(e).__name__, e)

        if got:
            ok += 1
            streak = 0
        else:
            fail += 1
            streak += 1
            if first_fail_at is None:
                first_fail_at = i
                print("  [%s] 첫 실패 %d번째 (%s) - %s" % (label, i, t, why), flush=True)
                describe_last("막힌 응답 원문")

        if i % 25 == 0:
            print("  [%s] %d개 · 성공 %d · 실패 %d" % (label, i, ok, fail), flush=True)
        if streak >= 25:
            print("  [%s] %d연속 실패 - 조기 중단" % (label, streak), flush=True)
            break
        time.sleep(SLEEP_SECONDS)
    return ok, fail, first_fail_at


def main():
    from datetime import datetime, timedelta, timezone
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400)
    a = ap.parse_args()

    if not (os.environ.get("KRX_ID") and os.environ.get("KRX_PW")):
        print("KRX_ID/KRX_PW 미설정 - 프로브를 돌리지 않는다.")
        return 1

    install_hooks()
    with open(WATCHLIST, encoding="utf-8") as f:
        tickers = [r["code"] for r in json.load(f)["tickers"]
                   if r.get("market") == "KR" and r.get("code")][:a.limit]

    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    from_date = (today - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    to_date = today.strftime("%Y%m%d")

    t0 = time.time()
    from pykrx import stock                                       # 여기서 로그인한다
    print("로그인 완료 시각 t+%.1fs · 대상 %d종목 · %s~%s"
          % (time.time() - t0, len(tickers), from_date, to_date), flush=True)

    print("\n== Phase A - 막힐 때까지 민다 ==", flush=True)
    okA, failA, wall = run_batch(stock, tickers, from_date, to_date, "A")
    print("  Phase A: 성공 %d · 실패 %d · 벽 %s번째 · 로그인 후 %.0f초"
          % (okA, failA, wall, time.time() - t0), flush=True)

    if wall is None:
        print("\n벽이 안 나왔다 - 이 실행에서는 재현 실패. 판정 보류.", flush=True)
        return 0

    rest = tickers[wall:] if wall else []
    print("\n== Phase B - 즉시 재로그인 후 같은 IP 에서 이어 돈다 ==", flush=True)
    if relogin():
        okB, failB, _ = run_batch(stock, rest[:60], from_date, to_date, "B")
        print("  Phase B: 성공 %d · 실패 %d" % (okB, failB), flush=True)
    else:
        okB = 0
        print("  Phase B: 재로그인 자체가 실패 - 계정/IP 단위를 시사한다", flush=True)

    if okB > 0:
        print("\n>>> 판정: **세션 단위**. 재로그인으로 살아난다.", flush=True)
        return 0

    print("\n== Phase C - 60초 쉬고 재로그인 후 10개 ==", flush=True)
    time.sleep(60)
    okC = 0
    if relogin():
        okC, failC, _ = run_batch(stock, rest[60:70], from_date, to_date, "C")
        print("  Phase C: 성공 %d · 실패 %d" % (okC, failC), flush=True)

    if okC > 0:
        print("\n>>> 판정: 재로그인만으로는 부족하고 **짧은 쿨다운**이 필요하다.", flush=True)
    else:
        print("\n>>> 판정: 재로그인도 60초 쿨다운도 안 듣는다 - **세션 단위가 아니다**\n"
              "    (IP 또는 계정 단위). 다음 가름: 다른 IP 에서 같은 계정으로 재본다.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
