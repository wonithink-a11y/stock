"""읽기 전용 웹 화면 — 폰에서 autotrader 상태를 본다.

★ 이 프로세스는 **KIS 키를 읽지 않는다**(systemd 유닛이 `.env` 접근을 막는다). 상태 파일(`state/`)만 읽는다.
★ **읽기 전용**이다. 주문·킬 스위치·설정 변경 기능이 없다 — 화면이 뚫려도 볼 수만 있다.
★ 로그인하지 않으면 아무것도 안 보인다(404 만 나간다). 3단계 노출:
    L0 로그인 전   : 로그인 폼 하나
    L1 로그인 후   : 모드·게이트·킬 스위치·오늘 실행 횟수·한도 사용률(금액·종목 없음)
    L2 재인증 5분  : 보유·잔고·미체결·주문 내역(인증앱 코드를 **다시** 입력해야 열린다, 계좌번호는 어디에도 안 나온다)
HTTPS 는 앞단(Caddy/nginx)이 맡는다 — 이 서버는 127.0.0.1 에만 붙는다.
"""
from __future__ import annotations

import html
import json
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from .config import state_dir
from .engine import Ledger
from .web_auth import AuthStore, Lockout, Sessions, totp_verify, verify_password

KST = timezone(timedelta(hours=9))
COOKIE = "at_sess"
SNAPSHOT_STALE_SEC = 30 * 60

CSS = """
:root{--bg:#f6f7f9;--fg:#1c1f24;--card:#fff;--mut:#6b7280;--ok:#0a7d3c;--bad:#b42318;--warn:#b54708;--line:#e5e7eb}
@media(prefers-color-scheme:dark){:root{--bg:#0f1115;--fg:#e8eaed;--card:#181b21;--mut:#9aa0a6;--ok:#4ade80;--bad:#f87171;--warn:#fbbf24;--line:#2a2f37}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Malgun Gothic",sans-serif}
main{max-width:720px;margin:0 auto;padding:16px}h1{font-size:20px;margin:8px 0 12px}h2{font-size:16px;margin:0 0 8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:0 0 12px}
.row{display:flex;justify-content:space-between;gap:8px;padding:4px 0;border-bottom:1px solid var(--line)}.row:last-child{border:0}
.mut{color:var(--mut);font-size:14px}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
.pill{display:inline-block;padding:2px 10px;border-radius:99px;border:1px solid var(--line);font-size:13px;margin-right:6px}
input,button{font:inherit;padding:12px;border-radius:8px;border:1px solid var(--line);width:100%;margin:6px 0;background:var(--card);color:var(--fg)}
button{background:var(--fg);color:var(--bg);cursor:pointer}a{color:inherit}table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left}
"""

E = html.escape


def _page(title: str, body: str, refresh: bool = False) -> bytes:
    meta = '<meta http-equiv="refresh" content="30">' if refresh else ""
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex,nofollow">{meta}<title>{E(title)}</title><style>{CSS}</style></head>'
            f'<body><main>{body}</main></body></html>').encode("utf-8")


def _load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_view(cfg: dict, sdir: Path, now: datetime) -> dict:
    day = now.strftime("%Y-%m-%d")
    runs = []
    rdir = Path(sdir) / "runs"
    if rdir.exists():
        for p in sorted(rdir.glob("*.json"))[-20:]:
            r = _load_json(p)
            if r:
                runs.append(r)
    ledger = Ledger(sdir).rows()
    snap = _load_json(Path(sdir) / "snapshot.json")
    spent = {}
    for m, lim in (cfg.get("risk") or {}).items():
        used = sum(float(r.get("value") or 0) for r in ledger if r.get("kind") == "order" and r.get("executed")
                   and r.get("market") == m and r.get("day") == day)
        spent[m] = {"used": used, "limit": lim.get("max_daily_value", 0)}
    today_runs = [r for r in runs if str(r.get("at", "")).startswith(day)]
    return {"now": now, "day": day, "mode": cfg.get("mode"), "kill": (Path(sdir) / "KILL").exists(),
            "runs": runs, "todayRuns": today_runs, "ledger": ledger, "snapshot": snap, "spent": spent}


def render_dashboard(v: dict, csrf: str, base: str = "", strict: bool = False) -> bytes:
    mode_txt = "실전(실계좌)" if v["mode"] == "live" else "모의투자"
    kill = ('<span class="pill bad">킬 스위치 ON — 주문 중단</span>' if v["kill"]
            else '<span class="pill ok">킬 스위치 OFF</span>')
    snap = v["snapshot"]
    if snap:
        age = (v["now"] - datetime.fromisoformat(snap["at"])).total_seconds()
        stale = age > SNAPSHOT_STALE_SEC
        snap_line = (f'<span class="{"warn" if stale else "ok"}">{int(age // 60)}분 전 갱신'
                     + (" — 오래됨(스냅샷 작업 확인)" if stale else "") + "</span>")
        ex = (snap.get("gates") or {}).get("execute") or []
        gates = ('<span class="ok">실행 조건 충족 — 주문은 --execute 로 실행할 때만 나갑니다(지금 자동 실행 중이라는 뜻이 아님)</span>' if not ex
                 else f'<span class="warn">주문 잠김 — 미충족 {len(ex)}개</span>')
        gate_items = "".join(f"<div class='mut'>· {E(str(x))}</div>" for x in ex)
    else:
        snap_line, gates, gate_items = '<span class="warn">스냅샷 없음</span>', "-", ""
    t = v["todayRuns"]
    cnt = lambda k: sum(len(r.get(k) or []) for r in t)   # noqa: E731
    limits = "".join(
        f'<div class="row"><span>{E(m)} 일일 한도</span><span>{s["used"] / s["limit"] * 100 if s["limit"] else 0:.0f}% 사용</span></div>'
        for m, s in v["spent"].items())
    recent = "".join(
        f'<div class="row"><span>{E(str(r.get("at", ""))[5:16].replace("T", " "))} {E("주문" if r.get("execute") else "dry-run")}</span>'
        f'<span class="{"ok" if r.get("status") == "ok" else "bad"}">{E(str(r.get("status")))} · 접수 {len(r.get("placed") or [])}'
        f' 거부 {len(r.get("rejected") or [])}</span></div>' for r in reversed(v["runs"][-5:]))
    body = f'''<h1>autotrader</h1>
<div class="card"><span class="pill">{mode_txt}</span>{kill}<div class="mut" style="margin-top:6px">상태 조회: {snap_line}</div></div>
<div class="card"><h2>실주문 게이트</h2><div>{gates}</div>{gate_items}</div>
<div class="card"><h2>오늘 ({E(v["day"])})</h2>
<div class="row"><span>실행 횟수</span><span>{len(t)}</span></div>
<div class="row"><span>접수된 주문</span><span>{cnt("placed")}</span></div>
<div class="row"><span>위험 검사 거부</span><span>{cnt("rejected")}</span></div>
<div class="row"><span>건너뜀</span><span>{cnt("skipped")}</span></div>
<div class="row"><span>오류</span><span class="{"bad" if cnt("errors") else ""}">{cnt("errors")}</span></div></div>
<div class="card"><h2>한도 사용률</h2>{limits or '<span class="mut">-</span>'}</div>
<div class="card"><h2>최근 실행</h2>{recent or '<span class="mut">아직 실행 기록 없음</span>'}</div>
<div class="card"><a href="{base}/details">보유·주문 상세 보기{" (인증앱 코드 재입력)" if strict else ""}</a></div>
<form method="post" action="{base}/logout"><input type="hidden" name="csrf" value="{E(csrf)}"><button>로그아웃</button></form>'''
    return _page("autotrader", body, refresh=True)


def render_details(v: dict, csrf: str, base: str = "", strict: bool = False) -> bytes:
    snap = v["snapshot"] or {}
    rows = []
    for m, d in (snap.get("markets") or {}).items():
        if d.get("error"):
            rows.append(f'<div class="card"><h2>{E(m)}</h2><span class="bad">{E(str(d["error"]))}</span></div>')
            continue
        pos = "".join(f'<tr><td>{E(str(p["symbol"]))}</td><td>{p["qty"]}</td><td>{p["avgPrice"]:,.2f}</td></tr>'
                      for p in d.get("positions", []))
        oo = "".join(f'<tr><td>{E(str(o["symbol"]))}</td><td>{E(str(o["side"]))}</td><td>{o["remaining"]}/{o["qty"]}</td>'
                     f'<td>{o["price"]:,.2f}</td></tr>' for o in d.get("openOrders", []))
        cash = d.get("cash")
        rows.append(f'''<div class="card"><h2>{E(m)}</h2>
<div class="row"><span>주문가능 현금</span><span>{"-" if cash is None else f"{cash:,.0f}"}</span></div>
<h2 style="margin-top:10px">보유</h2><table><tr><th>종목</th><th>수량</th><th>평단</th></tr>{pos or "<tr><td colspan=3 class=mut>없음</td></tr>"}</table>
<h2 style="margin-top:10px">미체결</h2><table><tr><th>종목</th><th>방향</th><th>잔량/수량</th><th>가격</th></tr>{oo or "<tr><td colspan=4 class=mut>없음</td></tr>"}</table></div>''')
    led = "".join(
        f'<tr><td>{E(str(r.get("ts", ""))[5:16].replace("T", " "))}</td><td>{E(str(r.get("market")))}</td><td>{E(str(r.get("symbol")))}</td>'
        f'<td>{E(str(r.get("side")))}</td><td>{E(str(r.get("qty")))}</td><td>{E(str(r.get("kind")))}</td></tr>'
        for r in reversed(v["ledger"][-30:]))
    last = v["runs"][-1] if v["runs"] else None
    lastblk = ""
    if last:
        def lines(k, label):
            return "".join(f'<div class="mut">{label} {E(str(x.get("symbol", "")))} {E(str(x.get("side", "")))} {E(str(x.get("qty", "")))}'
                           f' — {E(str(x.get("reason", "")))}</div>' for x in (last.get(k) or []) if isinstance(x, dict))
        lastblk = (f'<div class="card"><h2>마지막 실행 {E(str(last.get("at", ""))[5:16].replace("T", " "))}</h2>'
                   + lines("planned", "계획") + lines("placed", "접수") + lines("rejected", "거부") + lines("skipped", "건너뜀") + "</div>")
    body = f'''<h1>상세{" (재인증 후 5분간 열림)" if strict else ""}</h1>{"".join(rows) or '<div class="card mut">스냅샷이 없다</div>'}{lastblk}
<div class="card"><h2>주문 원장(최근 30)</h2><table><tr><th>시각</th><th>시장</th><th>종목</th><th>방향</th><th>수량</th><th>종류</th></tr>{led or "<tr><td colspan=6 class=mut>없음</td></tr>"}</table></div>
<div class="card"><a href="{base}/">← 요약으로</a></div>
<form method="post" action="{base}/logout"><input type="hidden" name="csrf" value="{E(csrf)}"><button>로그아웃</button></form>'''
    return _page("autotrader 상세", body, refresh=False)


def render_login(msg: str = "", base: str = "") -> bytes:
    m = f'<div class="bad">{E(msg)}</div>' if msg else ""
    return _page("로그인", f'''<h1>로그인</h1><div class="card">{m}
<form method="post" action="{base}/login" autocomplete="off">
<input type="password" name="password" placeholder="비밀번호" autocomplete="current-password" required>
<input name="code" placeholder="인증앱 6자리 코드" inputmode="numeric" autocomplete="one-time-code" maxlength="7" required>
<button>로그인</button></form></div>''')


def render_reauth(csrf: str, msg: str = "", base: str = "") -> bytes:
    m = f'<div class="bad">{E(msg)}</div>' if msg else ""
    return _page("재인증", f'''<h1>한 번 더 확인</h1><div class="card">{m}
<div class="mut">금액·보유 내용은 인증앱 코드를 <b>새로</b> 입력해야 열립니다. 방금 로그인에 쓴 코드는 못 씁니다 — 코드가 바뀔 때까지(최대 30초) 기다렸다가 입력하세요.</div>
<form method="post" action="{base}/reauth"><input type="hidden" name="csrf" value="{E(csrf)}">
<input name="code" placeholder="인증앱 6자리 코드" inputmode="numeric" autocomplete="one-time-code" maxlength="7" required>
<button>확인</button></form></div><div class="card"><a href="{base}/">← 요약으로</a></div>''')


class WebApp:
    """소켓 없이 테스트할 수 있는 요청 처리기. handle(...) -> (status, headers, body)."""

    def __init__(self, cfg: dict, sdir: Path, store: AuthStore, sessions: Sessions, lockout: Lockout,
                 clock: Callable[[], float] = time.time, secure_cookie: bool = True,
                 fail_delay: float = 0.0, sleep: Callable[[float], None] = time.sleep, base: str = "",
                 require_reauth: bool = False):
        self.cfg, self.sdir, self.store = cfg, Path(sdir), store
        self.sessions, self.lockout, self.clock = sessions, lockout, clock
        self.secure_cookie, self.fail_delay, self._sleep = secure_cookie, fail_delay, sleep
        self.base = "/" + base.strip("/") if base.strip("/") else ""      # 예: "/autotrader" (앞단이 이 접두사 아래로 넘겨준다)
        self.require_reauth = require_reauth                              # True 면 상세를 볼 때마다 인증앱 코드를 다시 묻는다
        self.log_path = self.sdir / "web_login.log"

    # -------------------------------------------------------------- 유틸
    def _now(self) -> datetime:
        return datetime.fromtimestamp(self.clock(), KST)

    def _log(self, ip: str, event: str) -> None:
        try:
            self.sdir.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(f"{self._now().isoformat()} {ip} {event}\n")
        except OSError:
            pass

    def _hdrs(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        h = {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
             "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
             "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"}
        if extra:
            h.update(extra)
        return h

    def _cookie(self, tok: str, max_age: int) -> str:
        return f"{COOKIE}={tok}; HttpOnly; SameSite=Strict; Path={self.base or '/'}; Max-Age={max_age}" + ("; Secure" if self.secure_cookie else "")

    @staticmethod
    def _session_token(headers: Dict[str, str]) -> Optional[str]:
        for part in (headers.get("cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return None

    def _not_found(self) -> Tuple[int, Dict[str, str], bytes]:
        return 404, self._hdrs(), _page("404", "<h1>404</h1>")

    def _redirect(self, to: str, extra: Optional[Dict[str, str]] = None):
        return 303, self._hdrs({"Location": self.base + to, **(extra or {})}), b""

    # -------------------------------------------------------------- 진입점
    def handle(self, method: str, raw_path: str, headers: Dict[str, str], body: bytes,
               ip: str) -> Tuple[int, Dict[str, str], bytes]:
        headers = {k.lower(): v for k, v in headers.items()}
        path = urlsplit(raw_path).path
        if self.base:                                   # 접두사 밖의 경로는 존재하지 않는 것으로 취급
            if path == self.base:
                path = "/"
            elif path.startswith(self.base + "/"):
                path = path[len(self.base):]
            else:
                return self._not_found()
        if path == "/healthz":
            return 200, {"Content-Type": "text/plain", "Cache-Control": "no-store"}, b"ok"
        if not self.store.exists():
            return 503, self._hdrs(), _page("설정 필요", "<h1>설정 필요</h1><div class='card mut'>서버에서 web-setup 을 먼저 실행해야 한다.</div>")
        tok = self._session_token(headers)
        sess = self.sessions.get(tok)
        form = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True) if method == "POST" else {}
        field = lambda k: (form.get(k) or [""])[0]   # noqa: E731

        if method == "POST" and path == "/login":
            return self._login(field("password"), field("code"), ip)
        if method == "GET" and path in ("/", "/index.html"):
            if not sess:
                return 200, self._hdrs(), render_login(base=self.base)
            return 200, self._hdrs(), render_dashboard(load_view(self.cfg, self.sdir, self._now()), sess["csrf"], self.base, self.require_reauth)
        if not sess:                                    # 로그인 전에는 나머지 경로가 존재하지 않는 것처럼
            return self._not_found()
        if method == "GET" and path == "/details":
            if self.require_reauth and not self.sessions.is_fresh(sess):
                return 200, self._hdrs(), render_reauth(sess["csrf"], base=self.base)
            return 200, self._hdrs(), render_details(load_view(self.cfg, self.sdir, self._now()), sess["csrf"], self.base, self.require_reauth)
        if method == "POST" and path in ("/reauth", "/logout"):
            if field("csrf") != sess["csrf"]:
                self._log(ip, "csrf-fail")
                return 403, self._hdrs(), _page("403", "<h1>요청이 거부됨</h1>")
            if path == "/logout":
                self.sessions.destroy(tok)
                self._log(ip, "logout")
                return self._redirect("/", {"Set-Cookie": self._cookie("", 0)})
            return self._reauth(field("code"), tok, sess, ip)
        return self._not_found()

    # -------------------------------------------------------------- 로그인·재인증
    def _login(self, password: str, code: str, ip: str):
        if self.lockout.is_locked(ip):
            self._log(ip, "locked")
            return 429, self._hdrs(), render_login("잠시 후 다시 시도하세요.", self.base)
        rec = self.store.load()
        pw_ok = verify_password(password, rec["password"])                       # 둘 다 항상 계산(어느 쪽이 틀렸는지 안 알려 준다)
        step = totp_verify(rec["totpSecret"], code, t=self.clock(), last_step=rec.get("lastTotpStep"))
        if pw_ok and step is not None:
            self.store.set_last_step(step)
            self.lockout.ok(ip)
            tok = self.sessions.create()
            self._log(ip, "login-ok")
            return self._redirect("/", {"Set-Cookie": self._cookie(tok, 8 * 3600)})
        self.lockout.fail(ip)
        self._log(ip, "login-fail")
        if self.fail_delay:
            self._sleep(self.fail_delay)
        return 401, self._hdrs(), render_login("로그인할 수 없습니다.", self.base)

    def _reauth(self, code: str, tok: str, sess: dict, ip: str):
        if self.lockout.is_locked(ip):
            return 429, self._hdrs(), render_reauth(sess["csrf"], "잠시 후 다시 시도하세요.", self.base)
        rec = self.store.load()
        step = totp_verify(rec["totpSecret"], code, t=self.clock(), last_step=rec.get("lastTotpStep"))
        if step is None:
            self.lockout.fail(ip)
            self._log(ip, "reauth-fail")
            if self.fail_delay:
                self._sleep(self.fail_delay)
            return 401, self._hdrs(), render_reauth(sess["csrf"], "코드가 맞지 않습니다.", self.base)
        self.store.set_last_step(step)
        self.lockout.ok(ip)
        self.sessions.mark_reauth(tok)
        self._log(ip, "reauth-ok")
        return self._redirect("/details")


def make_handler(app: WebApp):
    class H(BaseHTTPRequestHandler):
        timeout = 10
        server_version = "at"
        sys_version = ""

        def _client_ip(self) -> str:
            peer = self.client_address[0]
            if peer in ("127.0.0.1", "::1"):                      # 앞단 프록시가 넣은 실제 접속 IP
                fwd = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
                return fwd or peer
            return peer

        def _do(self, method: str):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(min(n, 4096)) if n else b""
            status, hdrs, out = app.handle(method, self.path, dict(self.headers), body, self._client_ip())
            self.send_response(status)
            for k, v in hdrs.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self):
            self._do("GET")

        def do_POST(self):
            self._do("POST")

        def log_message(self, fmt, *args):                       # 쿼리·본문은 남기지 않는다
            path = urlsplit(self.path).path if hasattr(self, "path") else "-"
            import sys
            sys.stderr.write(f"{self._client_ip()} {self.command} {path} {args[1] if len(args) > 1 else ''}\n")

    return H


def serve(cfg: dict, host: str = "127.0.0.1", port: int = 8787, secure_cookie: bool = True, base: str = "") -> None:
    sdir = state_dir(cfg)
    w = cfg.get("web", {})
    sessions = Sessions(idle_sec=int(w.get("idle_min", 30)) * 60, absolute_sec=int(w.get("session_hours", 8)) * 3600,
                        reauth_sec=int(w.get("reauth_min", 5)) * 60)
    app = WebApp(cfg, sdir, AuthStore(sdir / "web_auth.json"), sessions, Lockout(),
                 secure_cookie=secure_cookie, fail_delay=0.5, base=base,
                 require_reauth=bool(w.get("require_reauth_for_details", False)))
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"autotrader web — http://{host}:{port} (앞단 HTTPS 프록시 뒤에서만 쓴다)", flush=True)
    httpd.serve_forever()
