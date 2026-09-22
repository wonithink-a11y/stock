#!/usr/bin/env python3
"""autotrader 웹 화면 회귀 — 인증(비밀번호+TOTP)·세션·잠금·3단계 노출·읽기 전용·스냅샷. 키·네트워크 없음(로컬 소켓만).

    python scripts/test-autotrader-web.py
"""
import json
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autotrader import web, web_auth as A                                    # noqa: E402
from autotrader.broker import FakeBroker                                     # noqa: E402
from autotrader.config import normalize_config                               # noqa: E402
from autotrader.engine import KST                                            # noqa: E402
from autotrader.models import OpenOrder, Position                            # noqa: E402
from autotrader.snapshot import build_snapshot, write_snapshot               # noqa: E402

FAILS = []
COUNT = [0]


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def cookie_of(headers):
    sc = headers.get("Set-Cookie", "")
    return sc.split(";")[0] if sc.startswith(web.COOKIE) else ""


def _raises_cfg(extra):
    from autotrader.config import ConfigError
    try:
        normalize_config({"strategy": "x", "mode": "paper", "markets": ["KR"], **extra})
    except ConfigError:
        return True
    return False


def main():
    # ---------------------------------------------------------------- TOTP·비밀번호
    rfc = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"          # RFC 6238 부록 B 의 시험 비밀("12345678901234567890")
    ck("TOTP RFC 6238 시험 벡터 t=59 → 287082", A.totp_now(rfc, t=59) == "287082")
    ck("TOTP RFC 6238 시험 벡터 t=1111111109 → 081804", A.totp_now(rfc, t=1111111109) == "081804")
    s = A.new_totp_secret()
    ck("TOTP: 현재 코드는 통과, 틀린 코드·비숫자는 거부", A.totp_verify(s, A.totp_now(s, 1000), t=1000) is not None
       and A.totp_verify(s, "000000", t=1000) is None and A.totp_verify(s, "abcdef", t=1000) is None
       and A.totp_verify(s, "12345", t=1000) is None)
    ck("TOTP: ±1 스텝(30초)은 허용, ±2 는 거부", A.totp_verify(s, A.totp_now(s, 1000), t=1030) is not None
       and A.totp_verify(s, A.totp_now(s, 1000), t=1075) is None)
    st = A.totp_verify(s, A.totp_now(s, 1000), t=1000)
    ck("TOTP: 이미 쓴 코드(재사용)는 거부", A.totp_verify(s, A.totp_now(s, 1000), t=1000, last_step=st) is None)
    h = A.hash_password("correct horse battery")
    ck("비밀번호 해시: 맞는 것만 통과, 솔트가 매번 다름", A.verify_password("correct horse battery", h)
       and not A.verify_password("wrong", h) and A.hash_password("x")["salt"] != A.hash_password("x")["salt"])
    ck("비밀번호 원문이 해시 기록에 없다", "correct horse" not in json.dumps(h))

    # ---------------------------------------------------------------- 잠금·세션
    c = Clock(0.0)
    lk = A.Lockout(clock=c)
    for _ in range(4):
        lk.fail("1.1.1.1")
    ck("4번 실패까지는 안 잠긴다", not lk.is_locked("1.1.1.1"))
    lk.fail("1.1.1.1")
    ck("5번째 실패에 잠긴다(다른 IP 는 그대로)", lk.is_locked("1.1.1.1") and not lk.is_locked("2.2.2.2"))
    c.t = 901.0
    ck("15분 뒤 풀린다", not lk.is_locked("1.1.1.1"))
    lk.fail("3.3.3.3")
    lk.ok("3.3.3.3")
    for _ in range(4):
        lk.fail("3.3.3.3")
    ck("성공하면 실패 횟수가 초기화된다", not lk.is_locked("3.3.3.3"))
    c2 = Clock(0.0)
    g = A.Lockout(clock=c2)
    for i in range(20):
        g.fail(f"9.9.9.{i}")
    ck("여러 IP 의 분산 실패는 전체 잠금", g.is_locked("8.8.8.8"))

    ss = A.Sessions(clock=c)
    c.t = 0.0
    tok = ss.create()
    ck("세션 조회", ss.get(tok) is not None and ss.get("nope") is None and ss.get(None) is None)
    c.t = 901.0
    ck("15분 유휴면 세션 만료", ss.get(tok) is None)
    c.t = 0.0
    tok = ss.create()
    ss.mark_reauth(tok)
    sess = ss.get(tok)
    ck("재인증 직후는 fresh", ss.is_fresh(sess))
    c.t = 400.0
    ss._s[ss._h(tok)]["seen"] = c.t
    ck("5분 뒤에는 fresh 가 아니다", not ss.is_fresh(ss.get(tok)))

    # ---------------------------------------------------------------- 웹 앱 (소켓 없이)
    with tempfile.TemporaryDirectory() as td:
        sdir = Path(td) / "state"
        (sdir / "runs").mkdir(parents=True)
        cfg = normalize_config({"strategy": "x", "mode": "live", "markets": ["KR"], "symbol_allowlist": ["005930"],
                                "state_dir": str(sdir)})
        clk = Clock(datetime(2026, 9, 21, 10, 0, tzinfo=KST).timestamp())
        secret = A.new_totp_secret()
        store = A.AuthStore(sdir / "web_auth.json")
        app = web.WebApp(cfg, sdir, store, A.Sessions(clock=clk), A.Lockout(clock=clk), clock=clk, require_reauth=True)   # 엄격 모드(상세마다 재인증)
        ip = "10.0.0.1"

        st, h, b = app.handle("GET", "/healthz", {}, b"", ip)
        ck("healthz 는 정보 없이 ok", st == 200 and b == b"ok")
        st, h, b = app.handle("GET", "/", {}, b"", ip)
        ck("인증 저장소가 없으면 503(로그인 불가)", st == 503)

        store.save({"password": A.hash_password("a-very-long-password"), "totpSecret": secret})
        now = datetime.fromtimestamp(clk(), KST)
        run = {"runId": "r1", "at": now.isoformat(), "execute": True, "status": "ok", "mode": "live",
               "placed": [{"symbol": "005930", "side": "BUY", "qty": 3, "orderNo": "111", "reason": "<script>alert(1)</script>"}],
               "rejected": [{"symbol": "000660", "reason": "한도"}], "skipped": [], "errors": [], "planned": []}
        (sdir / "runs" / "r1.json").write_text(json.dumps(run, ensure_ascii=False), encoding="utf-8")
        (sdir / "ledger.jsonl").write_text(json.dumps({"kind": "order", "executed": True, "market": "KR", "day": "2026-09-21",
                                                        "value": 100000, "symbol": "005930", "side": "BUY", "qty": 3,
                                                        "ts": now.isoformat()}) + "\n", encoding="utf-8")
        snap = {"at": now.isoformat(), "mode": "live", "broker": "kis", "killSwitch": False,
                "gates": {"dry": [], "execute": ["환경변수 AUTOTRADER_ALLOW_LIVE 가 없다"]},
                "markets": {"KR": {"cash": 5000000.0, "positions": [{"symbol": "SECRETSYM", "qty": 7, "avgPrice": 123456.0}],
                                   "openOrders": []}}}
        (sdir / "snapshot.json").write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")

        st, h, b = app.handle("GET", "/", {}, b"", ip)
        ck("L0: 로그인 전에는 로그인 폼만(데이터 없음)", st == 200 and "비밀번호".encode() in b and b"005930" not in b and b"SECRETSYM" not in b)
        ck("로그인 전 다른 경로는 404(존재하지 않는 것처럼)", app.handle("GET", "/details", {}, b"", ip)[0] == 404
           and app.handle("GET", "/api/x", {}, b"", ip)[0] == 404 and app.handle("POST", "/logout", {}, b"", ip)[0] == 404)
        ck("보안 헤더(CSP·no-store·nosniff·프레임 금지)", "default-src 'none'" in h["Content-Security-Policy"]
           and h["Cache-Control"] == "no-store" and h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY")

        def login(pw, code, addr=ip):
            body = f"password={pw}&code={code}".encode()
            return app.handle("POST", "/login", {"content-type": "application/x-www-form-urlencoded"}, body, addr)

        st, h, b = login("wrong-password-xx", A.totp_now(secret, clk()))
        st2, h2, b2 = login("a-very-long-password", "000000")
        ck("틀린 비밀번호·틀린 코드는 같은 일반 메시지, 쿠키 없음", st == st2 == 401 and b.decode().count("로그인할 수 없습니다") == 1
           and b2.decode().count("로그인할 수 없습니다") == 1 and "Set-Cookie" not in h and "Set-Cookie" not in h2)
        for _ in range(3):
            login("wrong-password-xx", "000000")
        st, h, b = login("a-very-long-password", A.totp_now(secret, clk()))
        ck("5번 틀리면 올바른 자격증명도 잠금(429)", st == 429)

        ip2 = "10.0.0.2"
        code1 = A.totp_now(secret, clk())
        st, h, b = login("a-very-long-password", code1, ip2)
        ck("로그인 성공 → 303 + 쿠키(HttpOnly·SameSite=Strict·Secure)", st == 303 and "HttpOnly" in h["Set-Cookie"]
           and "SameSite=Strict" in h["Set-Cookie"] and "Secure" in h["Set-Cookie"])
        ck("로그인 코드 재사용 거부(같은 코드로 다시 로그인 불가)", login("a-very-long-password", code1, "10.0.0.3")[0] == 401)
        ck_cookie = {"cookie": cookie_of(h)}

        st, h, b = app.handle("GET", "/", ck_cookie, b"", ip2)
        body = b.decode()
        ck("L1: 요약은 보이되 종목·금액·보유는 없다", st == 200 and "오늘" in body and "SECRETSYM" not in body
           and "005930" not in body and "123456" not in body and "5,000,000" not in body)
        ck("L1: 카운트·게이트·한도 사용률", "접수된 주문" in body and "주문 잠김" in body and "10% 사용" in body)
        ck("L1: 자동 새로고침", 'http-equiv="refresh"' in body)

        st, h, b = app.handle("GET", "/details", ck_cookie, b"", ip2)
        ck("L2: 재인증 전에는 상세 대신 재인증 폼", st == 200 and "한 번 더 확인".encode() in b and b"SECRETSYM" not in b)
        m = b.decode()
        csrf = m.split('name="csrf" value="')[1].split('"')[0]

        st, h, b = app.handle("POST", "/reauth", ck_cookie, f"csrf={csrf}&code={code1}".encode(), ip2)
        ck("재인증에 방금 쓴 코드는 못 쓴다", st == 401)
        st, h, b = app.handle("POST", "/reauth", ck_cookie, f"csrf=WRONG&code={code1}".encode(), ip2)
        ck("CSRF 토큰이 틀리면 403", st == 403)
        clk.t += 30
        code2 = A.totp_now(secret, clk())
        st, h, b = app.handle("POST", "/reauth", ck_cookie, f"csrf={csrf}&code={code2}".encode(), ip2)
        ck("새 코드로 재인증 → 상세로 이동", st == 303 and h["Location"] == "/details")
        st, h, b = app.handle("GET", "/details", ck_cookie, b"", ip2)
        d = b.decode()
        ck("L2: 재인증 후에는 보유·잔고가 보인다", "SECRETSYM" in d and "5,000,000" in d and "123,456" in d)
        ck("XSS: 이유 문구의 스크립트가 이스케이프된다", "<script>" not in d and "&lt;script&gt;" in d)
        ck("계좌번호 관련 문자열이 어디에도 없다", "12345678" not in d and "12345678" not in body)
        clk.t += 301
        st, h, b = app.handle("GET", "/details", ck_cookie, b"", ip2)
        ck("재인증 5분 뒤에는 다시 재인증 폼", "한 번 더 확인".encode() in b and b"SECRETSYM" not in b)
        ck("읽기 전용: 주문·킬·설정 경로는 존재하지 않는다", all(app.handle("POST", p, ck_cookie, f"csrf={csrf}".encode(), ip2)[0] == 404
                                                       for p in ("/order", "/kill", "/config", "/execute")))

        st, h, b = app.handle("POST", "/logout", ck_cookie, b"csrf=WRONG", ip2)
        ck("로그아웃도 CSRF 확인(틀리면 403, 세션 유지)", st == 403 and app.handle("GET", "/", ck_cookie, b"", ip2)[0] == 200
           and "오늘".encode() in app.handle("GET", "/", ck_cookie, b"", ip2)[2])
        st, h, b = app.handle("POST", "/logout", ck_cookie, f"csrf={csrf}".encode(), ip2)
        ck("로그아웃하면 세션이 죽는다", st == 303 and "로그인".encode() in app.handle("GET", "/", ck_cookie, b"", ip2)[2])
        st, h, b = app.handle("GET", "/", {"cookie": web.COOKIE + "=forged"}, b"", ip2)
        ck("위조 쿠키는 로그인 폼", "비밀번호".encode() in b and b"005930" not in b)

        clk.t += 30
        st, h, b = login("a-very-long-password", A.totp_now(secret, clk()), "10.0.0.9")
        tok2 = {"cookie": cookie_of(h)}
        clk.t += 901
        ck("15분 유휴 후 세션 만료 → 로그인 폼", "비밀번호".encode() in app.handle("GET", "/", tok2, b"", "10.0.0.9")[2])
        log = (sdir / "web_login.log").read_text(encoding="utf-8")
        ck("로그인 시도가 기록되고 비밀번호·코드는 기록에 없다", "login-fail" in log and "login-ok" in log and "a-very-long" not in log
           and code1 not in log)

        # 킬 스위치 표시
        (sdir / "KILL").write_text("x", encoding="utf-8")
        clk.t += 30
        st, h, b = login("a-very-long-password", A.totp_now(secret, clk()), "10.0.0.10")
        ck("킬 스위치가 켜져 있으면 요약에 표시", "킬 스위치 ON".encode() in app.handle("GET", "/", {"cookie": cookie_of(h)}, b"", "10.0.0.10")[2])

        # ---------------------------------------------------------------- 기본 모드: 로그인 한 번으로 상세까지(재인증 없음)
        easy = web.WebApp(cfg, sdir, store, A.Sessions(idle_sec=1800, clock=clk), A.Lockout(clock=clk), clock=clk)
        clk.t += 30
        st, h, b = easy.handle("POST", "/login", {}, f"password=a-very-long-password&code={A.totp_now(secret, clk())}".encode(), "10.2.0.1")
        ec = {"cookie": cookie_of(h)}
        st, h, b = easy.handle("GET", "/details", ec, b"", "10.2.0.1")
        ck("기본 모드: 로그인 한 번으로 상세가 바로 보인다(재인증 없음)", st == 200 and b"SECRETSYM" in b and "한 번 더 확인".encode() not in b)
        ck("기본 모드: 요약의 링크에 '인증앱 코드 재입력' 문구가 없다", "재입력".encode() not in easy.handle("GET", "/", ec, b"", "10.2.0.1")[2])
        ck("기본 모드도 로그인 전에는 상세가 404", easy.handle("GET", "/details", {}, b"", "10.2.0.9")[0] == 404)
        clk.t += 20 * 60
        ck("유휴 30분 설정이면 20분 뒤에도 세션이 산다", b"SECRETSYM" in easy.handle("GET", "/details", ec, b"", "10.2.0.1")[2])
        clk.t += 31 * 60
        ck("유휴 30분을 넘기면 만료", b"SECRETSYM" not in easy.handle("GET", "/details", ec, b"", "10.2.0.1")[2])

        # ---------------------------------------------------------------- 경로 접두사(/autotrader) — 기존 nginx 뒤에서 쓰는 방식
        pref = web.WebApp(cfg, sdir, store, A.Sessions(clock=clk), A.Lockout(clock=clk), clock=clk, base="/autotrader", require_reauth=True)
        st, h, b = pref.handle("GET", "/autotrader/", {}, b"", "10.1.0.1")
        page = b.decode()
        ck("접두사: 로그인 폼의 action 이 접두사를 포함", st == 200 and 'action="/autotrader/login"' in page)
        ck("접두사: 접두사 밖의 경로는 404(같은 도메인의 다른 서비스와 섞이지 않는다)", pref.handle("GET", "/", {}, b"", "10.1.0.1")[0] == 404
           and pref.handle("GET", "/accounts", {}, b"", "10.1.0.1")[0] == 404 and pref.handle("GET", "/autotrader-x", {}, b"", "10.1.0.1")[0] == 404)
        ck("접두사: /autotrader 도 로그인 폼", pref.handle("GET", "/autotrader", {}, b"", "10.1.0.1")[0] == 200)
        ck("접두사: healthz", pref.handle("GET", "/autotrader/healthz", {}, b"", "10.1.0.1")[2] == b"ok")
        clk.t += 30
        st, h, b = pref.handle("POST", "/autotrader/login", {}, f"password=a-very-long-password&code={A.totp_now(secret, clk())}".encode(), "10.1.0.1")
        ck("접두사: 로그인 성공 → Location 과 쿠키 Path 가 접두사", st == 303 and h["Location"] == "/autotrader/"
           and "Path=/autotrader;" in h["Set-Cookie"])
        pc = {"cookie": cookie_of(h)}
        st, h, b = pref.handle("GET", "/autotrader/", pc, b"", "10.1.0.1")
        ck("접두사: 요약의 링크·로그아웃이 접두사를 포함", 'href="/autotrader/details"' in b.decode() and 'action="/autotrader/logout"' in b.decode())
        st, h, b = pref.handle("GET", "/autotrader/details", pc, b"", "10.1.0.1")
        ck("접두사: 재인증 폼 action 이 접두사를 포함", 'action="/autotrader/reauth"' in b.decode())

        # ---------------------------------------------------------------- 실제 소켓 (서버 통합)
        (sdir / "KILL").unlink()
        app2 = web.WebApp(cfg, sdir, store, A.Sessions(), A.Lockout(), secure_cookie=False)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(app2))
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5)
            ck("소켓: healthz", r.status == 200 and r.read() == b"ok")
            r = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5)
            page = r.read().decode()
            ck("소켓: 로그인 전 첫 화면은 로그인 폼이고 서버 정보 헤더가 없다", "비밀번호" in page and "Python" not in (r.headers.get("Server") or ""))
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/details", timeout=5)
                ck("소켓: 로그인 전 /details 는 404", False)
            except urllib.error.HTTPError as e:
                ck("소켓: 로그인 전 /details 는 404", e.code == 404)
            ck("서버는 로컬(127.0.0.1)에만 바인딩", httpd.server_address[0] == "127.0.0.1")
        finally:
            httpd.shutdown()

    # ---------------------------------------------------------------- 스냅샷
    with tempfile.TemporaryDirectory() as td:
        cfg = normalize_config({"strategy": "x", "mode": "paper", "markets": ["KR", "US"], "symbol_allowlist": ["005930"],
                                "state_dir": str(Path(td) / "state")})
        fb = FakeBroker(positions={"KR": [Position("005930", "KR", 3, 60000.0)]}, cash={"KR": 1000000.0},
                        open_orders=[OpenOrder("9", "005930", "KR", "BUY", 2, 0, 70000.0)], quotes={})
        env = {"KIS_VTS_APP_KEY": "k", "KIS_VTS_APP_SECRET": "s", "KIS_VTS_ACCOUNT_NO": "12345678-01"}
        snap = build_snapshot(cfg, fb, env, datetime(2026, 9, 21, 10, tzinfo=KST), repo_root=Path(td))
        ck("스냅샷: 보유·미체결·현금·게이트", snap["markets"]["KR"]["positions"][0]["qty"] == 3
           and snap["markets"]["KR"]["openOrders"][0]["remaining"] == 2 and snap["markets"]["KR"]["cash"] == 1000000.0
           and snap["gates"]["dry"] == [])

        class Bad(FakeBroker):
            def positions(self, market):
                if market == "US":
                    raise RuntimeError("조회 실패")
                return super().positions(market)
        snap2 = build_snapshot(cfg, Bad(cash={"KR": 1.0}), env, datetime(2026, 9, 21, 10, tzinfo=KST), repo_root=Path(td))
        ck("스냅샷: 한 시장 실패가 다른 시장을 막지 않는다", "error" in snap2["markets"]["US"] and "error" not in snap2["markets"]["KR"])
        p = write_snapshot(cfg, snap, repo_root=Path(td))
        ck("스냅샷 파일 저장(임시파일 남지 않음)", p.exists() and not (p.parent / "snapshot.json.tmp").exists())
        ck("스냅샷에 계좌번호·키가 없다", "12345678" not in p.read_text(encoding="utf-8") and '"k"' not in p.read_text(encoding="utf-8"))

    # ---------------------------------------------------------------- 소스 위생 — 웹 프로세스는 키를 안 본다
    web_src = (ROOT / "autotrader" / "web.py").read_text(encoding="utf-8") + (ROOT / "autotrader" / "web_auth.py").read_text(encoding="utf-8")
    ck("웹 소스는 KIS 키·환경 로더·브로커를 가져오지 않는다", "KIS_" not in web_src and "load_env" not in web_src
       and "from .kis" not in web_src and "make_broker" not in web_src and ".place(" not in web_src and ".cancel(" not in web_src)

    ck("설정: web 섹션 검증(알 수 없는 키·음수·잘못된 타입은 오류)", all(_bad for _bad in (
        _raises_cfg({"web": {"idle_min": -1}}), _raises_cfg({"web": {"nope": 1}}), _raises_cfg({"web": {"require_reauth_for_details": "yes"}}))))
    ck("설정: web 기본값이 채워진다", normalize_config({"strategy": "x", "mode": "paper", "markets": ["KR"]})["web"] == {})
    ck("웹 소스는 텔레그램·알림 모듈을 모른다(토큰이 웹 프로세스에 없다)", "TELEGRAM" not in web_src and "notify" not in web_src.lower())

    total = COUNT[0]
    print(f"\ntest-autotrader-web {total - len(FAILS)}/{total}" + ("" if not FAILS else f"  FAILED: {FAILS}"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
