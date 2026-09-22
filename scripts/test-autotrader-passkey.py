#!/usr/bin/env python3
"""autotrader 패스키 회귀 — **소프트웨어 인증기**(실제 P-256 서명)로 webauthn 라이브러리 검증까지 끝에서 끝으로 돈다.
가짜 검증 함수로 바꿔 끼우지 않는다 — 브라우저가 보내는 JSON 모양이 라이브러리와 맞는지가 핵심이라서.

핀하는 것: 등록은 로그인 + 새 인증앱 코드 뒤 5분만 · 챌린지 1회용(재전송 거부) · 다른 출처(피싱 사이트)의 응답 거부 ·
패스키가 있으면 실계좌 주문 켜기는 인증앱 코드로 안 된다 · 확인은 그 조작에만 묶인다 · 다른 키의 서명 거부 · 확인 문구 ·
웹에는 패스키 삭제 경로가 없다 · rp 설정이 없으면 꺼진다.

    python scripts/test-autotrader-passkey.py        (webauthn 이 없으면 건너뛴다 — pip install "webauthn>=2.2,<3")
"""
import base64
import hashlib
import json
import os
import struct
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autotrader import notify, web                                            # noqa: E402
from autotrader import web_auth as A                                          # noqa: E402
from autotrader.config import kill_file, load_profile, normalize_config       # noqa: E402
from autotrader.engine import KST                                             # noqa: E402

FAILS, COUNT = [], [0]
RP, ORIGIN = "example.test", "https://example.test"


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SoftAuthenticator:
    """폰의 패스키 역할 — P-256 키로 등록 응답·서명을 만든다."""

    def __init__(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        self.ec = ec
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cid = os.urandom(16)
        self.count = 0

    def _cose(self):
        import cbor2
        n = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def register(self, options_json, origin=ORIGIN, rp=RP):
        import cbor2
        o = json.loads(options_json)
        cdj = json.dumps({"type": "webauthn.create", "challenge": o["challenge"], "origin": origin, "crossOrigin": False}).encode()
        auth = (hashlib.sha256(rp.encode()).digest() + bytes([0x45]) + struct.pack(">I", 0)
                + bytes(16) + struct.pack(">H", len(self.cid)) + self.cid + self._cose())
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"id": b64u(self.cid), "rawId": b64u(self.cid), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64u(cdj), "attestationObject": b64u(att), "transports": ["internal"]}}

    def assert_(self, options_json, origin=ORIGIN, rp=RP, key=None):
        from cryptography.hazmat.primitives import hashes
        o = json.loads(options_json)
        self.count += 1
        cdj = json.dumps({"type": "webauthn.get", "challenge": o["challenge"], "origin": origin, "crossOrigin": False}).encode()
        auth = hashlib.sha256(rp.encode()).digest() + bytes([0x05]) + struct.pack(">I", self.count)
        sig = (key or self.key).sign(auth + hashlib.sha256(cdj).digest(), self.ec.ECDSA(hashes.SHA256()))
        return {"id": b64u(self.cid), "rawId": b64u(self.cid), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64u(cdj), "authenticatorData": b64u(auth), "signature": b64u(sig),
                             "userHandle": None}}


BASE = {"strategy": "target_weights", "mode": "paper", "markets": ["KR"], "symbol_allowlist": ["005930"]}


def main():
    if not A.passkey_available():
        print("webauthn 없음 — 건너뜀")
        return 0
    now = datetime(2026, 9, 22, 10, 0, tzinfo=KST)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        main_p = td / "autotrader.local.json"
        main_p.write_text(json.dumps({**BASE, "state_dir": str(td / "state")}), encoding="utf-8")
        (td / "profiles").mkdir()
        (td / "profiles" / "la.json").write_text(json.dumps({**BASE, "mode": "live", "auto": "off", "web_live_allowed": True}),
                                                 encoding="utf-8")
        (td / "profiles" / "pa.json").write_text(json.dumps({**BASE, "mode": "paper", "auto": "off"}), encoding="utf-8")
        sdir = td / "state"
        store = A.AuthStore(sdir / "web_auth.json")
        secret = A.new_totp_secret()
        store.save({"password": A.hash_password("pw-long-enough-1"), "totpSecret": secret})
        clk = [now.timestamp()]
        cfg = normalize_config({**BASE, "state_dir": str(sdir)})

        def mk(rp=RP, origin=ORIGIN):
            return web.WebApp(cfg, sdir, store, A.Sessions(clock=lambda: clk[0]), A.Lockout(clock=lambda: clk[0]),
                              clock=lambda: clk[0], secure_cookie=False, profiles=web._profile_loader(cfg, main_p),
                              rp_id=rp, origin=origin)
        app = mk()
        tok = app.sessions.create()
        csrf = app.sessions.get(tok)["csrf"]
        h = {"Cookie": f"at_sess={tok}"}

        def pj(path, obj):
            st, _, b = app.handle("POST", path, h, json.dumps(obj).encode(), "1.1.1.1")
            return st, b.decode()

        def code():
            clk[0] += 30
            return A.totp_now(secret, clk[0])

        # ---- 공개 부분·기본
        ck("로그인 없이 패스키 화면 404", app.handle("GET", "/passkey", {}, b"", "1.1.1.1")[0] == 404)
        st, hd, js = app.handle("GET", "/static/passkey.js", {}, b"", "1.1.1.1")
        ck("스크립트는 파일로(인라인 금지 CSP 유지)", st == 200 and b"navigator.credentials" in js
           and "script-src 'self'" in hd["Content-Security-Policy"] and "unsafe-inline" not in hd["Content-Security-Policy"].split("script-src")[1].split(";")[0])

        # ---- 등록
        ck("등록 시작 전엔 옵션 거부", pj("/passkey/register-options", {"csrf": csrf})[0] == 403)
        app.handle("POST", "/passkey/begin", h, f"csrf={csrf}&code={code()}".encode(), "1.1.1.1")
        ck("인증앱 코드로는 등록 시작 안 됨(피싱된 코드로 패스키 추가 불가 — M4)", pj("/passkey/register-options", {"csrf": csrf})[0] == 403)
        ek = store.issue_enroll_code(clk[0])
        app.handle("POST", "/passkey/begin", h, f"csrf={csrf}&code=AAAA-BBBB-CCCC".encode(), "1.1.1.1")
        ck("틀린 등록 코드 거부", pj("/passkey/register-options", {"csrf": csrf})[0] == 403)
        app.handle("POST", "/passkey/begin", h, f"csrf={csrf}&code={ek}".encode(), "1.1.1.1")
        ck("CSRF 없으면 거부", pj("/passkey/register-options", {})[0] == 403)
        st, opts = pj("/passkey/register-options", {"csrf": csrf})
        ck("코드 확인 뒤 등록 옵션", st == 200 and json.loads(opts)["rp"]["id"] == RP)
        dev = SoftAuthenticator()
        phish = dev.register(opts, origin="https://evil.test")
        st, _ = pj("/passkey/register", {"csrf": csrf, "credential": phish})
        ck("다른 출처(피싱)의 등록 응답 거부", st == 400 and not store.load().get("passkeys"))
        app.handle("POST", "/passkey/begin", h, f"csrf={csrf}&code={ek}".encode(), "1.1.1.1")
        ck("등록 코드는 1회용", pj("/passkey/register-options", {"csrf": csrf})[0] == 403)
        app.handle("POST", "/passkey/begin", h, f"csrf={csrf}&code={store.issue_enroll_code(clk[0] - 1000)}".encode(), "1.1.1.1")
        ck("15분 지난 등록 코드 거부", pj("/passkey/register-options", {"csrf": csrf})[0] == 403)
        app.handle("POST", "/passkey/begin", h, f"csrf={csrf}&code={store.issue_enroll_code(clk[0])}".encode(), "1.1.1.1")
        st, opts = pj("/passkey/register-options", {"csrf": csrf})
        cred = dev.register(opts)
        st, body = pj("/passkey/register", {"csrf": csrf, "credential": cred})
        ck("진짜 등록 응답은 저장(실제 서명 검증)", st == 200 and len(store.load()["passkeys"]) == 1)
        ck("같은 응답 재전송 거부(챌린지 1회용)", pj("/passkey/register", {"csrf": csrf, "credential": cred})[0] == 403)

        # ---- 패스키가 있으면 실계좌 주문 켜기는 인증앱 코드로 안 된다
        app.handle("POST", "/action", h, f"csrf={csrf}&p=la&op=auto-execute&code={code()}&phrase={web.LIVE_PHRASE}".encode(), "1.1.1.1")
        ck("인증앱 코드 + 문구로는 실계좌 주문 안 켜짐", load_profile(main_p, "la")["auto"] == "off")
        st, _, b = app.handle("GET", "/details?p=la", h, b"", "1.1.1.1")
        ck("상세 화면에 패스키 확인 폼", 'id="pk-action"' in b.decode() and "passkey.js" in b.decode())

        # ---- 패스키로 확인
        req = {"csrf": csrf, "p": "la", "op": "auto-execute", "phrase": web.LIVE_PHRASE}
        st, ao = pj("/passkey/action-options", req)
        other = SoftAuthenticator().key
        st, _ = pj("/passkey/action", {**req, "credential": dev.assert_(ao, key=other)})
        ck("다른 키의 서명 거부", st == 401 and load_profile(main_p, "la")["auto"] == "off")
        st, ao = pj("/passkey/action-options", {**req, "op": "resume"})
        st, _ = pj("/passkey/action", {**req, "credential": dev.assert_(ao)})
        ck("확인은 요청한 조작에만 묶인다(킬 해제로 받은 확인으로 주문 켜기 불가)", st == 403 and load_profile(main_p, "la")["auto"] == "off")
        ck("킬 켜기·모르는 조작은 패스키 확인 대상이 아니다", pj("/passkey/action-options", {**req, "op": "kill"})[0] == 404
           and pj("/passkey/action-options", {**req, "op": "nope"})[0] == 404)
        st, ao = pj("/passkey/action-options", req)
        st, _ = pj("/passkey/action", {**req, "phrase": "", "credential": dev.assert_(ao)})
        ck("확인 문구 없으면 거부", st == 400 and load_profile(main_p, "la")["auto"] == "off")
        st, ao = pj("/passkey/action-options", req)
        good = dev.assert_(ao)
        st, body = pj("/passkey/action", {**req, "credential": good})
        ck("패스키 + 문구면 실계좌 자동 주문 켜짐", st == 200 and load_profile(main_p, "la")["auto"] == "execute"
           and json.loads(body)["redirect"].startswith("/details?p=la"))
        ck("같은 서명 재전송 거부", pj("/passkey/action", {**req, "credential": good})[0] == 403)
        st, ao = pj("/passkey/action-options", req)
        st, _ = pj("/passkey/action", {**req, "credential": dev.assert_(ao, origin="https://evil.test")})
        ck("피싱 출처의 서명 거부", st == 401)
        ck("서명 카운트 저장", store.load()["passkeys"][0]["count"] >= 1)

        la = load_profile(main_p, "la")
        kill_file(la).write_text("x", encoding="utf-8")
        st, ao = pj("/passkey/action-options", {**req, "op": "resume"})
        st, _ = pj("/passkey/action", {**req, "op": "resume", "credential": dev.assert_(ao)})
        ck("실계좌 킬 해제는 패스키로 된다", st == 200 and not kill_file(la).exists())

        # ---- 패스키가 있으면 모의 조작도 지문으로(2026-09-22) — 인증앱 코드는 거부
        app.handle("POST", "/action", h, f"csrf={csrf}&p=pa&op=auto-dry&code={code()}".encode(), "1.1.1.1")
        ck("패스키가 있으면 모의 조작도 인증앱 코드로 안 됨", load_profile(main_p, "pa")["auto"] == "off")
        st, _, b = app.handle("GET", "/details?p=pa", h, b"", "1.1.1.1")
        ck("모의 상세에도 지문 폼(인증앱 칸 없음)", 'id="pk-action"' in b.decode() and "인증앱 6자리" not in b.decode())
        preq = {"csrf": csrf, "p": "pa", "op": "auto-dry"}
        st, ao = pj("/passkey/action-options", preq)
        st, _ = pj("/passkey/action", {**preq, "credential": dev.assert_(ao)})
        ck("모의 조작은 지문만으로(확인 문구 없이)", st == 200 and load_profile(main_p, "pa")["auto"] == "dry")
        st, ao = pj("/passkey/action-options", {**req, "op": "auto-off"})
        st, _ = pj("/passkey/action", {**req, "op": "auto-off", "phrase": "", "credential": dev.assert_(ao)})
        ck("실계좌 끄기(안전 쪽)는 문구 없이 지문만", st == 200 and load_profile(main_p, "la")["auto"] == "off")
        app.handle("POST", "/action", h, f"csrf={csrf}&p=pa&op=kill".encode(), "1.1.1.1")
        ck("킬 켜기는 여전히 확인 없이 즉시", kill_file(load_profile(main_p, "pa")).exists())

        # ---- 재인증(금액 보기)도 지문으로
        strict = web.WebApp(cfg, sdir, store, A.Sessions(clock=lambda: clk[0]), A.Lockout(clock=lambda: clk[0]),
                            clock=lambda: clk[0], secure_cookie=False, profiles=web._profile_loader(cfg, main_p),
                            rp_id=RP, origin=ORIGIN, require_reauth=True, accounts_fetch=lambda: {})
        t3 = strict.sessions.create()
        c3, h3 = strict.sessions.get(t3)["csrf"], {"Cookie": f"at_sess={t3}"}

        def pj3(path, obj):
            st, _, b = strict.handle("POST", path, h3, json.dumps(obj).encode(), "1.1.1.1")
            return st, b.decode()
        st, _, b = strict.handle("GET", "/accounts", h3, b"", "1.1.1.1")
        ck("재인증 화면에 지문 버튼(인증앱 칸 없음)", 'id="pk-reauth"' in b.decode() and "인증앱 6자리" not in b.decode())
        ck("재인증 전엔 실계좌 요약 안 열림", "한 번 더 확인" in b.decode())
        st, _, _ = strict.handle("POST", "/reauth", h3, f"csrf={c3}&code={code()}".encode(), "1.1.1.1")
        ck("패스키가 있으면 인증앱 코드 재인증 거부(N1)", st == 403 and not strict.sessions.is_fresh(strict.sessions.get(t3)))
        st, ao = pj3("/passkey/reauth-options", {"csrf": c3})
        st, _ = pj3("/passkey/reauth", {"csrf": c3, "next": "/accounts", "credential": dev.assert_(ao, key=SoftAuthenticator().key)})
        ck("다른 키로는 재인증 안 됨", st == 401 and not strict.sessions.is_fresh(strict.sessions.get(t3)))
        st, ao = pj3("/passkey/reauth-options", {"csrf": c3})
        st, body = pj3("/passkey/reauth", {"csrf": c3, "next": "https://evil.test/", "credential": dev.assert_(ao)})
        ck("지문 재인증 성공 + 외부 주소로는 안 보냄", st == 200 and json.loads(body)["redirect"] == "/details"
           and strict.sessions.is_fresh(strict.sessions.get(t3)))
        st, ao = pj3("/passkey/reauth-options", {"csrf": c3})
        st, body = pj3("/passkey/reauth", {"csrf": c3, "next": "/details?p=pa", "credential": dev.assert_(ao)})
        ck("재인증 뒤 보던 프로필로 돌아감", json.loads(body)["redirect"] == "/details?p=pa")
        ck("재인증 CSRF 없으면 거부", pj3("/passkey/reauth-options", {})[0] == 403)

        # ---- 오래 가는 로그인: 파일에 남아 재시작에도 유지, 토큰 원문은 파일에 없다
        sp = sdir / "web_sessions.json"
        D30 = 30 * 86400

        def S():
            return A.Sessions(idle_sec=D30, absolute_sec=D30, clock=lambda: clk[0], path=sp)
        s1 = S()
        tk = s1.create()
        ck("세션 파일에 토큰 원문 없음", tk not in sp.read_text(encoding="utf-8"))
        ck("재시작 뒤에도 로그인 유지(같은 CSRF)", S().get(tk) is not None and S().get(tk)["csrf"] == s1.get(tk)["csrf"])
        clk[0] += 29 * 86400
        ck("29일 뒤에도 유지", S().get(tk) is not None)
        clk[0] += 2 * 86400
        ck("30일 지나면 끝", S().get(tk) is None)
        s3 = S()
        tk2 = s3.create()
        s3.destroy(tk2)
        ck("로그아웃은 파일에서도 지워진다", S().get(tk2) is None)
        sp.write_text("{깨짐", encoding="utf-8")
        ck("깨진 세션 파일 = 전부 로그아웃(안전 쪽)", S().get(tk2) is None)
        lg = web.WebApp(cfg, sdir, store, A.Sessions(absolute_sec=D30, idle_sec=D30, clock=lambda: clk[0]), A.Lockout(clock=lambda: clk[0]),
                        clock=lambda: clk[0], secure_cookie=False)
        st, hd, _ = lg.handle("POST", "/login", {}, f"password=pw-long-enough-1&code={code()}".encode(), "2.2.2.2")
        ck("로그인 쿠키 수명 = 세션 수명(30일)", st == 303 and f"Max-Age={D30}" in hd.get("Set-Cookie", ""))

        # ---- 삭제는 서버에서만, 알림, rp 미설정

        ck("웹에 패스키 삭제 경로 없음", pj("/passkey/delete", {"csrf": csrf})[0] == 404)
        log = (sdir / "web_login.log").read_text(encoding="utf-8").splitlines()
        ck("등록은 텔레그램 알림", any("패스키 새로 등록됨" in m for m in notify.build_messages(log)))
        off = mk(rp="", origin="")
        t2 = off.sessions.create()
        st, _, b = off.handle("GET", "/passkey", {"Cookie": f"at_sess={t2}"}, b"", "1.1.1.1")
        ck("rp 설정 없으면 패스키 꺼짐 안내", st == 200 and "꺼져 있다" in b.decode())
        from autotrader import cli
        cli.cmd_passkey_reset(type("A", (), {"config": main_p, "profile": None})())
        ck("서버 명령으로 삭제", not store.load().get("passkeys"))

    print(f"\ntest-autotrader-passkey {COUNT[0] - len(FAILS)}/{COUNT[0]}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
