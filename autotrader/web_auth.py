"""웹 화면 인증 — 비밀번호 + 인증앱(TOTP), 세션, 로그인 잠금. **표준 라이브러리만** 쓴다(의존성 0).

이 모듈과 웹 서버는 KIS 키를 읽지 않는다. 인증 정보(비밀번호 해시·TOTP 비밀)는 `state/web_auth.json`(0600, gitignore)에만 있다.
시계는 함수 인자로 주입할 수 있다(회귀 테스트가 시간을 조작한다).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

PBKDF2_ITERS = 200_000


# ---------------------------------------------------------------- 비밀번호
def hash_password(password: str, salt: Optional[bytes] = None, iters: int = PBKDF2_ITERS) -> dict:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
    return {"salt": base64.b64encode(salt).decode(), "hash": base64.b64encode(dk).decode(), "iters": iters}


def verify_password(password: str, rec: dict) -> bool:
    salt = base64.b64decode(rec["salt"])
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rec["iters"]))
    return hmac.compare_digest(dk, base64.b64decode(rec["hash"]))


# ---------------------------------------------------------------- TOTP (RFC 6238, SHA1, 6자리, 30초)
def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_now(secret_b32: str, t: Optional[float] = None, step: int = 30) -> str:
    return _hotp(secret_b32, int((t if t is not None else time.time()) // step))


def totp_verify(secret_b32: str, code: str, t: Optional[float] = None, window: int = 1,
                last_step: Optional[int] = None, step: int = 30) -> Optional[int]:
    """맞으면 일치한 time-step 을, 틀리면 None. last_step 이하(이미 쓴 코드)는 재사용으로 거부한다."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != 6 or not code.isdigit():
        return None
    now_step = int((t if t is not None else time.time()) // step)
    for s in range(now_step - window, now_step + window + 1):
        if last_step is not None and s <= last_step:
            continue
        if hmac.compare_digest(_hotp(secret_b32, s), code):
            return s
    return None


def otpauth_uri(secret_b32: str, account: str, issuer: str = "autotrader") -> str:
    return f"otpauth://totp/{issuer}:{account}?secret={secret_b32}&issuer={issuer}&digits=6&period=30"


# ---------------------------------------------------------------- 저장소
class AuthStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.exists()

    def load(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, rec: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rec), encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def set_last_step(self, step: int) -> None:
        rec = self.load()
        rec["lastTotpStep"] = step
        self.save(rec)


# ---------------------------------------------------------------- 잠금
class Lockout:
    """IP 별 연속 실패 잠금 + 전체 실패 잠금(분산 추측 방어). 성공하면 그 IP 의 실패 횟수가 초기화된다."""

    def __init__(self, max_fail: int = 5, lock_sec: int = 900, global_max: int = 20,
                 global_window: int = 3600, global_lock: int = 1800, clock: Callable[[], float] = time.time):
        self.max_fail, self.lock_sec = max_fail, lock_sec
        self.global_max, self.global_window, self.global_lock = global_max, global_window, global_lock
        self.clock = clock
        self._fails: Dict[str, list] = {}
        self._locked: Dict[str, float] = {}
        self._all: list = []
        self._global_until = 0.0

    def is_locked(self, ip: str) -> bool:
        now = self.clock()
        if now < self._global_until:
            return True
        return now < self._locked.get(ip, 0.0)

    def fail(self, ip: str) -> None:
        now = self.clock()
        self._all = [t for t in self._all if now - t < self.global_window] + [now]
        if len(self._all) >= self.global_max:
            self._global_until = now + self.global_lock
        f = [t for t in self._fails.get(ip, []) if now - t < self.lock_sec] + [now]
        self._fails[ip] = f
        if len(f) >= self.max_fail:
            self._locked[ip] = now + self.lock_sec

    def ok(self, ip: str) -> None:
        self._fails.pop(ip, None)


# ---------------------------------------------------------------- 세션
class Sessions:
    def __init__(self, idle_sec: int = 900, absolute_sec: int = 8 * 3600, reauth_sec: int = 300,
                 clock: Callable[[], float] = time.time):
        self.idle, self.absolute, self.reauth_ttl = idle_sec, absolute_sec, reauth_sec
        self.clock = clock
        self._s: Dict[str, dict] = {}

    def create(self) -> str:
        tok = secrets.token_urlsafe(32)
        now = self.clock()
        self._s[tok] = {"created": now, "seen": now, "reauth": 0.0, "csrf": secrets.token_urlsafe(16)}
        return tok

    def get(self, tok: Optional[str]) -> Optional[dict]:
        s = self._s.get(tok or "")
        if not s:
            return None
        now = self.clock()
        if now - s["seen"] > self.idle or now - s["created"] > self.absolute:
            self._s.pop(tok, None)
            return None
        s["seen"] = now
        return s

    def mark_reauth(self, tok: str) -> None:
        if tok in self._s:
            self._s[tok]["reauth"] = self.clock()

    def is_fresh(self, s: dict) -> bool:
        return self.clock() - s["reauth"] <= self.reauth_ttl

    def destroy(self, tok: Optional[str]) -> None:
        self._s.pop(tok or "", None)


# ---------------------------------------------------------------- 패스키(WebAuthn) — 검증은 webauthn(Duo Labs) 라이브러리가 한다
# 우리는 JSON 을 넘기고 결과만 저장한다. 라이브러리는 이 함수들 안에서만 import 한다(없으면 패스키만 꺼지고 나머지는 돈다).
def passkey_available() -> bool:
    try:
        import webauthn  # noqa: F401
        return True
    except ImportError:
        return False


def passkey_reg_options(rp_id: str, existing_ids: List[str]):
    """등록 옵션 JSON 과 챌린지(bytes). 지문·화면잠금 등 **사용자 확인 필수**."""
    import webauthn
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor,
                                          ResidentKeyRequirement, UserVerificationRequirement)
    o = webauthn.generate_registration_options(
        rp_id=rp_id, rp_name="autotrader", user_name="autotrader", user_id=b"autotrader-owner",
        authenticator_selection=AuthenticatorSelectionCriteria(user_verification=UserVerificationRequirement.REQUIRED,
                                                               resident_key=ResidentKeyRequirement.PREFERRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(i)) for i in existing_ids])
    return webauthn.options_to_json(o), o.challenge


def passkey_reg_verify(credential: str, challenge: bytes, rp_id: str, origin: str) -> dict:
    """등록 응답 검증 → 저장할 {id, pk, count}. 실패하면 예외."""
    import webauthn
    from webauthn.helpers import bytes_to_base64url
    v = webauthn.verify_registration_response(credential=credential, expected_challenge=challenge, expected_rp_id=rp_id,
                                              expected_origin=origin, require_user_verification=True)
    return {"id": bytes_to_base64url(v.credential_id), "pk": bytes_to_base64url(v.credential_public_key),
            "count": int(v.sign_count)}


def passkey_auth_options(rp_id: str, ids: List[str]):
    import webauthn
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement
    o = webauthn.generate_authentication_options(
        rp_id=rp_id, allow_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(i)) for i in ids],
        user_verification=UserVerificationRequirement.REQUIRED)
    return webauthn.options_to_json(o), o.challenge


def passkey_auth_verify(credential: str, challenge: bytes, rp_id: str, origin: str, stored: List[dict]) -> Tuple[str, int]:
    """인증 응답 검증 → (쓴 패스키 id, 새 서명 카운트). 등록되지 않은 패스키·서명 불일치·카운트 역행이면 예외."""
    import webauthn
    from webauthn.helpers import base64url_to_bytes
    cid = json.loads(credential).get("id")
    rec = next((p for p in stored if p["id"] == cid), None)
    if rec is None:
        raise ValueError("등록되지 않은 패스키")
    v = webauthn.verify_authentication_response(
        credential=credential, expected_challenge=challenge, expected_rp_id=rp_id, expected_origin=origin,
        credential_public_key=base64url_to_bytes(rec["pk"]), credential_current_sign_count=int(rec.get("count", 0)),
        require_user_verification=True)
    return cid, int(v.new_sign_count)
