"""웹 화면 — 폰에서 autotrader 상태를 보고 프로필을 조작한다.

★ 이 프로세스는 **KIS 키를 읽지 않는다**(systemd 유닛이 허용목록 격리). 주문을 직접 내지 않는다 — 조작은 요청 파일·킬 파일만
  쓰고, 주문은 키를 가진 run-due 가 모든 게이트를 통과해야 낸다.
★ 로그인하지 않으면 아무것도 안 보인다(404 만 나간다). 노출 단계:
    L0 로그인 전   : 로그인 폼 하나(비밀번호 + 인증앱 코드). 로그인은 30일 유지(세션 세대로 일괄 무효화 가능)
    L1 로그인 후   : 모드·게이트·킬·오늘 실행·한도 사용률 — **금액·보유 없음**(보안 재검토 N2)
    L2 재확인 5분  : 금액·보유·주문 내역·실계좌 요약. 패스키가 있으면 지문으로만(N1), 계좌번호는 어디에도 안 나온다
★ 조작(켜기·끄기·실행·킬 해제)은 패스키가 있으면 지문으로만. 실계좌 주문성 조작은 지문 + 확인 문구. 킬 켜기만 확인 없이.
HTTPS 는 앞단(Caddy/nginx)이 맡는다 — 이 서버는 127.0.0.1 에만 붙는다.
"""
from __future__ import annotations

import html
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlsplit

from .config import (ConfigError, kill_file, list_profiles, load_profile, state_dir, web_request_run,
                     web_set_auto)
from .engine import Ledger
from .names import names_for
from .web_auth import (AuthStore, Lockout, Sessions, passkey_auth_options, passkey_auth_verify, passkey_available,
                       passkey_reg_options, passkey_reg_verify, totp_verify, verify_password)

KST = timezone(timedelta(hours=9))
COOKIE = "at_sess"
ACCOUNTS_URL = "http://127.0.0.1:8766/accounts"   # 같은 VM 의 실계좌 요약 API. 2026-09-22 부터 인터넷에는 닫고(nginx) 여기서만 보여 준다
LIVE_PHRASE = "실계좌주문"      # 실계좌 주문 켜기·실행 때 입력하는 확인 문구(실수 클릭 방지 — 보안은 인증앱 코드와 서버 한도가 맡는다)
SNAPSHOT_STALE_SEC = 30 * 60

CSS = """
:root{--bg:#f2f4f8;--fg:#111827;--card:#fff;--mut:#6b7280;--line:#e6e8ee;--chip:#f4f5f9;--acc:#4f46e5;--acc2:#7c3aed;
--up:#e0284a;--dn:#2563eb;--ok:#059669;--bad:#dc2626;--warn:#d97706;--sh:0 1px 2px rgba(16,24,40,.05),0 4px 14px rgba(16,24,40,.06)}
@media(prefers-color-scheme:dark){:root{--bg:#0b0d12;--fg:#e8eaf0;--card:#151922;--mut:#9aa3b2;--line:#252a35;--chip:#1c212b;
--acc:#818cf8;--acc2:#a78bfa;--up:#fb7185;--dn:#60a5fa;--ok:#34d399;--bad:#f87171;--warn:#fbbf24;--sh:none}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Malgun Gothic",system-ui,sans-serif;
font-variant-numeric:tabular-nums}
.top{position:sticky;top:0;z-index:5;background:linear-gradient(135deg,var(--acc),var(--acc2));color:#fff;padding:14px 16px 12px;box-shadow:0 2px 10px rgba(79,70,229,.25)}
.top .in{max-width:760px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:10px}
.top .brand{font-weight:800;font-size:18px;letter-spacing:-.3px;color:#fff;text-decoration:none}.top .sub{font-size:12px;opacity:.85}
.top .tp{display:inline-block;background:rgba(255,255,255,.18);border-radius:99px;padding:2px 10px;font-size:12px;margin-left:4px}
main{max-width:760px;margin:0 auto;padding:14px 14px 40px}
h1{font-size:21px;margin:10px 2px 12px;letter-spacing:-.4px}h2{font-size:15px;margin:0 0 10px;letter-spacing:-.2px}
.sec{font-size:13px;font-weight:700;color:var(--mut);margin:20px 4px 8px;letter-spacing:.2px}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin:0 0 12px;box-shadow:var(--sh)}
.card.hl{border-left:4px solid var(--acc)}
.hd{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}.hd h2{margin:0;font-size:17px}
.row{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line)}.row:last-child{border:0}
.row>span:first-child{color:var(--mut);font-size:14px}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:4px 0 10px}
.kpi{background:var(--chip);border-radius:12px;padding:10px 12px;min-width:0}
.kpi .l{font-size:12px;color:var(--mut)}.kpi .v{font-size:17px;font-weight:700;letter-spacing:-.3px;overflow-wrap:anywhere}
.kpi .s{font-size:12px;font-weight:600}
.mut{color:var(--mut);font-size:13px}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.up{color:var(--up)}.dn{color:var(--dn)}
.pill{display:inline-block;padding:3px 10px;border-radius:99px;background:var(--chip);font-size:12px;font-weight:600;margin:0 4px 4px 0}
.pill.ok{background:rgba(5,150,105,.12)}.pill.bad{background:rgba(220,38,38,.12)}.pill.warn{background:rgba(217,119,6,.12)}.pill.acc{background:rgba(79,70,229,.12);color:var(--acc)}
input,button,select{font:inherit;padding:12px 14px;border-radius:12px;border:1px solid var(--line);width:100%;margin:6px 0;background:var(--card);color:var(--fg)}
button{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:700;cursor:pointer}button.ghost{background:transparent;color:var(--fg)}
a{color:var(--acc);text-decoration:none}
.nav{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:4px 0 12px}
.nav a{display:block;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;color:var(--fg);font-weight:600;box-shadow:var(--sh)}
.nav a small{display:block;color:var(--mut);font-weight:400;font-size:12px;margin-top:2px}
.btn{display:block;text-align:center;background:var(--acc);color:#fff;border-radius:12px;padding:11px;font-weight:700;margin-top:8px}
.tw{overflow-x:auto;margin:0 -4px}table{width:100%;border-collapse:collapse;font-size:14px}
th{font-size:12px;color:var(--mut);font-weight:600;text-align:left;padding:6px 6px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 6px;border-bottom:1px solid var(--line);vertical-align:top}tr:last-child td{border-bottom:0}
td.n,th.n{text-align:right;white-space:nowrap}
.nm{font-weight:700;display:block;line-height:1.3}.code{font-size:11px;color:var(--mut)}
.bar{height:6px;background:var(--chip);border-radius:99px;overflow:hidden;margin-top:4px}.bar i{display:block;height:100%;background:var(--acc)}
code{background:var(--chip);padding:2px 6px;border-radius:6px;font-size:12px;word-break:break-all}
"""

E = html.escape


def _page(title: str, body: str, refresh: bool = False, base: str = "", sub: str = "") -> bytes:
    meta = '<meta http-equiv="refresh" content="30">' if refresh else ""
    top = (f'<header class="top"><div class="in"><a class="brand" href="{E(base)}/">📈 autotrader</a>'
           f'<span class="sub">{sub}</span></div></header>')
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="#4f46e5">{meta}<title>{E(title)}</title>'
            f'<style>{CSS}</style></head><body>{top}<main>{body}</main></body></html>').encode("utf-8")


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
            "runs": runs, "todayRuns": today_runs, "ledger": ledger, "snapshot": snap, "spent": spent,
            "names": names_for([snap])}


def _money(m: str, x) -> str:
    if x is None:
        return "-"
    return f"${x:,.2f}" if m == "US" else f"{x:,.0f}원"


def _px(m: str, x) -> str:
    """가격 표기 — 국내는 원 단위 정수, 해외는 센트까지."""
    return "-" if not x else (f"{x:,.2f}" if m == "US" else f"{x:,.0f}")


def _sign_cls(x) -> str:
    """국내 관례: 오르면 빨강(up), 내리면 파랑(dn)."""
    return "" if x is None else ("up" if x > 0 else ("dn" if x < 0 else ""))


def _signed(m: str, x) -> str:
    return "-" if x is None else ("+" if x > 0 else "") + _money(m, x)


_KR_CODE = re.compile(r"^[0-9][0-9A-Z]{5}$")


def _sym(sym, names: Optional[Dict[str, str]] = None) -> str:
    """종목 이름 + 코드. 이름을 모르면 코드만."""
    s = str(sym or "")
    n = (names or {}).get(s, "")
    if not n:
        return f'<span class="nm">{E(s)}</span>'
    if _KR_CODE.match(s):                               # 국내: 숫자 코드보다 이름이 알아보기 쉽다
        return f'<span class="nm">{E(n)}</span><span class="code">{E(s)}</span>'
    return f'<span class="nm">{E(s)}</span><span class="code">{E(n.title())}</span>'   # 해외: 티커가 이름보다 짧고 익숙하다


def _ago(v: dict, snap: Optional[dict]) -> str:
    if not snap:
        return '<span class="warn">조회 없음</span>'
    age = (v["now"] - datetime.fromisoformat(snap["at"])).total_seconds()
    return f'<span class="{"warn" if age > SNAPSHOT_STALE_SEC else "mut"}">{int(age // 60)}분 전 갱신</span>'


def _pnl_html(m: str, t: dict) -> str:
    if not t or t.get("pnl") is None:
        return '<span class="mut">현재가 없음</span>'
    pct = f' ({t["pnlPct"]:+.2f}%)' if t.get("pnlPct") is not None else ""
    return f'<span class="{_sign_cls(t["pnl"])}">{_signed(m, t["pnl"])}{pct}</span>'


def _kpi(label: str, value: str, sub: str = "") -> str:
    return f'<div class="kpi"><div class="l">{label}</div><div class="v">{value}</div>{f"<div class=s>{sub}</div>" if sub else ""}</div>'


def render_money_rows(snap: Optional[dict]) -> str:
    """시장별 투자금·평가·평가손익·실현손익 타일."""
    out = []
    rz = (snap or {}).get("realized") or {}
    for m, d in ((snap or {}).get("markets") or {}).items():
        t = d.get("totals")
        if not t:
            continue
        tiles = [_kpi(f"{E(m)} 투자금(원가)", _money(m, t["cost"])), _kpi(f"{E(m)} 평가금액", _money(m, t["value"])),
                 _kpi(f"{E(m)} 평가손익(보유분)", _pnl_html(m, t))]
        if "realized" in (snap or {}):
            r = rz.get(m) or {"realized": 0.0, "incomplete": False}
            warn = '<span class="warn">원가 모르는 매도 있음</span>' if r["incomplete"] else "수수료·세금 전"
            tiles.append(_kpi(f"{E(m)} 실현손익", f'<span class="{_sign_cls(r["realized"])}">{_signed(m, r["realized"])}</span>', warn))
        out.append('<div class="kpis">' + "".join(tiles) + "</div>")
    if (snap or {}).get("realizedError"):
        out.append('<div class="row"><span>실현손익</span><span class="warn">체결 조회 실패 — 다음 갱신에 다시</span></div>')
    return "".join(out)


def render_sells(snap: Optional[dict], names: Optional[Dict[str, str]] = None) -> str:
    rows = []
    for m, r in ((snap or {}).get("realized") or {}).items():
        for x in reversed(r.get("sells", [])[-30:]):
            rows.append(f'<tr><td>{E(str(x.get("day", "")))}</td><td>{_sym(x["symbol"], names)}</td><td class="n">{E(str(x["qty"]))}</td>'
                        f'<td class="n">{_px(m, x["avg"])}<br><small class="mut">→ {_px(m, x["price"])}</small></td><td class="n {_sign_cls(x["pnl"])}">{_signed(m, x["pnl"])}</td></tr>')
    if "realized" not in (snap or {}):
        return ""
    return ('<div class="card"><h2>실현손익 내역 <span class="mut">매도 체결 · 최근 30</span></h2><div class="tw"><table><tr><th>날짜</th><th>종목</th>'
            '<th class="n">수량</th><th class="n">평단 → 체결가</th><th class="n">손익</th></tr>'
            + ("".join(rows) or "<tr><td colspan=5 class=mut>아직 매도 체결 없음</td></tr>") + "</table></div></div>")


AUTO_TXT = {"off": "자동 꺼짐", "dry": "자동 dry-run", "execute": "자동 주문"}


def render_profiles(items: List[Tuple[dict, dict]], base: str = "", hide_money: bool = False) -> str:
    """프로필(키 묶음+전략)마다 한 장 — 투자금·손익 타일, 상태, 상세 링크. hide_money 면 금액·보유를 빼고 상태만(N2)."""
    out = []
    for cfg, v in items:
        name = str(cfg.get("profile", ""))
        snap = v["snapshot"]
        t = v["todayRuns"]
        cnt = lambda k: sum(len(r.get(k) or []) for r in t)   # noqa: E731
        last = v["runs"][-1] if v["runs"] else None
        last_txt = (f'<span class="{"ok" if last.get("status") == "ok" else "bad"}">{E(str(last.get("at", ""))[5:16].replace("T", " "))}'
                    f' · {E("주문" if last.get("execute") else "dry-run")} · {E(str(last.get("status")))}</span>') if last else '<span class="mut">아직 없음</span>'
        auto = cfg.get("auto", "off")
        auto_cls = {"execute": "bad", "dry": "ok"}.get(auto, "")
        held = []
        for m, d in ((snap or {}).get("markets") or {}).items():
            for p in d.get("positions") or []:
                px = p.get("price") or 0
                pc = (px / p["avgPrice"] - 1) * 100 if px and p["avgPrice"] else None
                held.append(f'<tr><td>{_sym(p["symbol"], v["names"])}</td><td class="n">{E(str(p["qty"]))}</td>'
                            f'<td class="n {_sign_cls(pc)}">{"-" if pc is None else f"{pc:+.1f}%"}</td></tr>')
        held_tbl = (f'<div class="tw"><table><tr><th>보유</th><th class="n">수량</th><th class="n">수익률</th></tr>{"".join(held[:8])}</table></div>'
                    + (f'<div class="mut">외 {len(held) - 8}종목 — 상세에서</div>' if len(held) > 8 else "")) if held else ""
        out.append(f'''<div class="card hl"><div class="hd"><h2>{E(name)}</h2>{_ago(v, snap)}</div>
<span class="pill acc">{E(str(cfg.get("strategy")))}</span><span class="pill">{"실전" if cfg.get("mode") == "live" else "모의"}</span>
<span class="pill {auto_cls}">{E(AUTO_TXT.get(auto, auto))} {E(",".join(cfg.get("run_at") or []))}</span>
{'<span class="pill bad">킬 ON</span>' if v["kill"] else ""}
{"" if hide_money else render_money_rows(snap)}
{"" if hide_money else held_tbl}
<div class="row"><span>오늘 실행 · 접수 · 오류</span><span>{len(t)} · {cnt("placed")} · <span class="{"bad" if cnt("errors") else ""}">{cnt("errors")}</span></span></div>
<div class="row"><span>마지막 실행</span>{last_txt}</div>
<a class="btn" href="{base}/details?p={quote(name)}">상세 보기 · 조작</a></div>''')
    return ('<div class="sec">프로필</div>' + "".join(out)) if out else ""


def render_dashboard(v: dict, csrf: str, base: str = "", strict: bool = False, extra: str = "") -> bytes:
    mode_txt = "실전(실계좌)" if v["mode"] == "live" else "모의투자"
    snap = v["snapshot"]
    ex = ((snap or {}).get("gates") or {}).get("execute") or []
    gates = ('<span class="ok">주문 조건 충족</span> <span class="mut">— --execute 로 실행할 때만 나간다</span>' if snap and not ex
             else (f'<span class="warn">주문 잠김 · 미충족 {len(ex)}개</span>' if snap else '<span class="mut">-</span>'))
    gate_items = "".join(f"<div class='mut'>· {E(str(x))}</div>" for x in ex)
    t = v["todayRuns"]
    cnt = lambda k: sum(len(r.get(k) or []) for r in t)   # noqa: E731
    limits = "".join(
        f'<div class="row"><span>{E(m)} 일일 한도</span><span>{s["used"] / s["limit"] * 100 if s["limit"] else 0:.0f}% 사용</span></div>'
        f'<div class="bar"><i style="width:{min(100, s["used"] / s["limit"] * 100 if s["limit"] else 0):.0f}%"></i></div>'
        for m, s in v["spent"].items())
    recent = "".join(
        f'<div class="row"><span>{E(str(r.get("at", ""))[5:16].replace("T", " "))} {E("주문" if r.get("execute") else "dry-run")}</span>'
        f'<span class="{"ok" if r.get("status") == "ok" else "bad"}">{E(str(r.get("status")))} · 접수 {len(r.get("placed") or [])}'
        f' 거부 {len(r.get("rejected") or [])}</span></div>' for r in reversed(v["runs"][-5:]))
    reauth = " (재확인)" if strict else ""
    err_html = f'<span class="{"bad" if cnt("errors") else ""}">{cnt("errors")}</span>'
    body = f'''<div class="nav">
<a href="{base}/accounts">💰 실계좌 요약<small>업비트·빗썸·KIS·RV20{reauth}</small></a>
<a href="{base}/details">📋 기본 계좌 상세<small>보유·주문·원장{reauth}</small></a>
<a href="{base}/passkey">🔑 패스키 관리<small>지문 등록·상태</small></a>
<a href="#today">🗓 오늘 기록<small>실행·한도·게이트</small></a></div>
{extra}
<div class="sec" id="today">기본 설정 · 오늘 {E(v["day"])}</div>
<div class="card"><div class="hd"><h2>{mode_txt}</h2>{_ago(v, snap)}</div>
<span class="pill {"bad" if v["kill"] else "ok"}">{"킬 스위치 ON — 주문 중단" if v["kill"] else "킬 스위치 OFF"}</span>
<div class="kpis">{_kpi("실행", str(len(t)))}{_kpi("접수된 주문", str(cnt("placed")))}{_kpi("위험 검사 거부", str(cnt("rejected")))}
{_kpi("오류", err_html)}</div>
<div class="row"><span>실주문 게이트</span><span>{gates}</span></div>{gate_items}
{limits}</div>
<div class="card"><h2>최근 실행</h2>{recent or '<span class="mut">아직 실행 기록 없음</span>'}</div>
<form method="post" action="{base}/logout"><input type="hidden" name="csrf" value="{E(csrf)}"><button class="ghost">로그아웃</button></form>'''
    return _page("autotrader", body, refresh=True, base=base, sub=f'<span class="tp">{mode_txt}</span>')


def render_controls(cfg: dict, csrf: str, base: str, msg: str = "", has_pk: bool = False) -> str:
    """프로필 조작 폼. 킬 켜기만 확인 없이. 패스키가 있으면 **모든 조작을 지문으로**(2026-09-22 사용자 요청), 없으면 인증앱 코드.
    실계좌의 주문 켜기·실행·킬 해제는 패스키로만 + 확인 문구(보안 검토 M2·M3·M4 — 피싱된 인증앱 코드로는 실계좌 주문에 닿지 않는다)."""
    name = str(cfg.get("profile", ""))
    live = cfg.get("mode") == "live"
    web_live = live and bool(cfg.get("web_live_allowed"))
    opts = [("auto-off", "자동 끄기"), ("auto-dry", "자동 dry-run (주문 없이 계획만)")]
    if not live:
        opts += [("auto-execute", "자동 주문 켜기 (모의투자)"), ("run", "지금 한 번 실행 (현재 자동 설정대로, 5분 안에)"),
                 ("resume", "킬 스위치 해제")]
    elif has_pk:
        opts += ([("auto-execute", "⚠ 실계좌 자동 주문 켜기")] if web_live else []) +                 [("run", "지금 한 번 실행 (자동이 '주문'이면 ⚠ 실계좌 주문)"), ("resume", "실계좌 킬 스위치 해제")]
    else:
        opts.append(("run", "지금 한 번 실행 — 자동이 '주문'이 아닐 때만(dry-run)"))
    sel = "".join(f'<option value="{k}">{E(t)}</option>' for k, t in opts)
    m = f'<div class="warn">{E(msg)}</div>' if msg else ""
    if not live:
        note = "<div class='mut'>'주문'은 서버 타이머에도 --execute 가 있어야 실제로 나간다.</div>"
    elif not has_pk:
        note = ("<div class='warn'>실계좌의 주문 켜기·실행·킬 해제는 <b>패스키로만</b> 된다 — 먼저 '패스키(지문) 관리'에서 등록"
                "(등록 코드는 서버에서 발급).</div>")
    else:
        note = ""
    if has_pk:
        phrase = (f'<input name="phrase" placeholder="실계좌 주문일 때만 확인 문구: {E(LIVE_PHRASE)}" autocomplete="off">' if live else "")
        form = f'''<form id="pk-action" data-base="{E(base)}" data-csrf="{E(csrf)}" data-profile="{E(name)}">
<select name="op">{sel}</select>{phrase}<button>🔑 지문으로 확인</button><div id="pk-action-msg"></div></form>
<script src="{E(base)}/static/passkey.js"></script>'''
    else:
        form = f'''<form method="post" action="{base}/action"><input type="hidden" name="csrf" value="{E(csrf)}"><input type="hidden" name="p" value="{E(name)}">
<select name="op">{sel}</select>
<input name="code" placeholder="인증앱 6자리 코드(새 코드)" inputmode="numeric" autocomplete="one-time-code" maxlength="7" required>
<button>적용</button></form>'''
    return f'''<div class="card"><h2>조작</h2>{m}
<div class="row"><span>지금 자동 설정</span><span>{E({"off": "꺼짐", "dry": "dry-run", "execute": "주문"}.get(cfg.get("auto"), str(cfg.get("auto"))))} {E(",".join(cfg.get("run_at") or []))}</span></div>
{form}{note}
<form method="post" action="{base}/action" style="margin-top:10px"><input type="hidden" name="csrf" value="{E(csrf)}"><input type="hidden" name="p" value="{E(name)}">
<input type="hidden" name="op" value="kill"><button style="background:var(--bad);border-color:var(--bad)">킬 스위치 켜기 (확인 없이 즉시 — 주문 중단)</button></form></div>'''


def render_details(v: dict, csrf: str, base: str = "", strict: bool = False, title: str = "", controls: str = "") -> bytes:
    snap = v["snapshot"] or {}
    names = v.get("names") or {}
    rows = []
    for m, d in (snap.get("markets") or {}).items():
        if d.get("error"):
            rows.append(f'<div class="card"><h2>{E(m)}</h2><span class="bad">{E(str(d["error"]))}</span></div>')
            continue

        def prow(p, m=m):
            px = p.get("price") or 0
            pnl = (px - p["avgPrice"]) * p["qty"] if px else None
            pc = (px / p["avgPrice"] - 1) * 100 if px and p["avgPrice"] else None
            cls = _sign_cls(pnl)
            return (f'<tr><td>{_sym(p["symbol"], names)}</td><td class="n">{E(str(p["qty"]))}</td>'
                    f'<td class="n">{_px(m, p["avgPrice"])}<br><small class="mut">→ {_px(m, px)}</small></td>'
                    f'<td class="n {cls}">{_signed(m, pnl)}{"" if pc is None else f"<br><small>{pc:+.1f}%</small>"}</td></tr>')
        pos = "".join(prow(p) for p in d.get("positions", []))
        oo = "".join(f'<tr><td>{_sym(o["symbol"], names)}</td><td>{"매수" if o["side"] == "BUY" else "매도"}</td>'
                     f'<td class="n">{E(str(o["remaining"]))}/{E(str(o["qty"]))}</td><td class="n">{_px(m, o["price"])}</td></tr>'
                     for o in d.get("openOrders", []))
        cash = d.get("cash")
        rz = {"realized": snap["realized"]} if "realized" in snap else {}
        rows.append(f'''<div class="card"><div class="hd"><h2>{E(m)} {"국내" if m == "KR" else "해외"}</h2><span class="mut">주문가능 {"-" if cash is None else _money(m, cash)}</span></div>
{render_money_rows({"markets": {m: d}, **rz})}
<h2 style="margin-top:6px">보유 <span class="mut">{len(d.get("positions") or [])}종목</span></h2><div class="tw"><table><tr><th>종목</th><th class="n">수량</th><th class="n">평단→현재</th><th class="n">손익</th></tr>{pos or "<tr><td colspan=4 class=mut>없음</td></tr>"}</table></div>
<h2 style="margin-top:12px">미체결</h2><div class="tw"><table><tr><th>종목</th><th>방향</th><th class="n">잔량/수량</th><th class="n">가격</th></tr>{oo or "<tr><td colspan=4 class=mut>없음</td></tr>"}</table></div></div>''')
    led = "".join(
        f'<tr><td>{E(str(r.get("ts", ""))[5:16].replace("T", " "))}</td><td>{_sym(r.get("symbol"), names)}</td>'
        f'<td>{"매수" if r.get("side") == "BUY" else ("매도" if r.get("side") == "SELL" else E(str(r.get("side"))))}</td>'
        f'<td class="n">{E(str(r.get("qty")))}</td><td class="{"bad" if r.get("kind") == "error" else "mut"}">{E(str(r.get("kind")))}</td></tr>'
        for r in reversed(v["ledger"][-30:]))
    last = v["runs"][-1] if v["runs"] else None
    lastblk = ""
    if last:
        def lines(k, label):
            return "".join(f'<tr><td>{label}</td><td>{_sym(x.get("symbol", ""), names)}</td><td>{E(str(x.get("side", "")))} {E(str(x.get("qty", "")))}</td>'
                           f'<td class="mut">{E(str(x.get("reason", "")))}</td></tr>' for x in (last.get(k) or []) if isinstance(x, dict))
        body_rows = lines("planned", "계획") + lines("placed", "접수") + lines("rejected", "거부") + lines("skipped", "건너뜀")
        lastblk = (f'<div class="card"><h2>마지막 실행 <span class="mut">{E(str(last.get("at", ""))[5:16].replace("T", " "))} · '
                   f'{"주문" if last.get("execute") else "dry-run"} · {E(str(last.get("status")))}</span></h2>'
                   + (f'<div class="tw"><table>{body_rows}</table></div>' if body_rows else '<span class="mut">낸 주문 없음</span>') + "</div>")
    head = f'<h1>{E(title) if title else "기본 계좌"}{" <span class=mut>(재인증 후 5분)</span>" if strict else ""}</h1>'
    body = f'''{head}{"".join(rows) or '<div class="card mut">스냅샷이 없다</div>'}{controls}{render_sells(snap, names)}{lastblk}
<div class="card"><h2>주문 원장 <span class="mut">최근 30</span></h2><div class="tw"><table><tr><th>시각</th><th>종목</th><th>방향</th><th class="n">수량</th><th>종류</th></tr>{led or "<tr><td colspan=5 class=mut>없음</td></tr>"}</table></div></div>
<a class="btn" href="{base}/">← 요약으로</a>
<form method="post" action="{base}/logout"><input type="hidden" name="csrf" value="{E(csrf)}"><button class="ghost">로그아웃</button></form>'''
    return _page(f"상세 · {title}" if title else "상세", body, refresh=False, base=base, sub=E(f"상세 · {title}" if title else "상세"))


def is_live_order(c: dict, op: str) -> bool:
    """실계좌 주문으로 이어질 수 있는 조작 — 주문 켜기, 주문 상태의 지금 실행, 킬 해제(M2: 해제하면 예약 주문이 다시 나간다)."""
    return c.get("mode") == "live" and (op in ("auto-execute", "resume") or (op == "run" and c.get("auto") == "execute"))


def _fetch_accounts() -> dict:
    import urllib.request
    with urllib.request.urlopen(ACCOUNTS_URL, timeout=10) as r:        # 127.0.0.1 고정 — 외부 주소를 받지 않는다
        return json.loads(r.read().decode("utf-8"))


def _pct(v) -> str:
    return "" if v is None else f" ({v:+.1f}%)"


def render_accounts(d: Optional[dict], err: str, csrf: str, base: str = "") -> bytes:
    # 실계좌 요약(업비트·빗썸·KIS 실계좌·RV20 선물). 전엔 인터넷에 인증 없이 열려 있던 /accounts 의 내용이다.
    won = lambda v: "-" if v is None else f"{v:,.0f}원"                   # noqa: E731
    sw = lambda v: "-" if v is None else ("+" if v > 0 else "") + f"{v:,.0f}원"   # noqa: E731
    cards = []
    if err:
        cards.append(f'<div class="card"><span class="bad">실계좌 요약을 못 읽었다: {E(err)}</span></div>')
    real = (d or {}).get("real") or {}
    for key, label in (("upbit", "업비트"), ("bithumb", "빗썸")):
        a = real.get(key)
        if not a:
            continue
        pnl, cost = a.get("totalPnlKrw"), a.get("totalCostKrw")
        pct = (pnl / cost * 100) if (pnl is not None and cost) else None
        rows = "".join(
            f'<tr><td><span class="nm">{E(str(h.get("currency")))}</span></td><td class="n">{E(str(h.get("balance")))}</td>'
            f'<td class="n">{won(h.get("evalKrw"))}</td><td class="n {_sign_cls(h.get("pnlKrw"))}">{sw(h.get("pnlKrw"))}'
            f'{_pct_small(h.get("pnlPct"))}</td></tr>'
            for h in a.get("holdings") or [])
        cards.append(f'''<div class="card hl"><div class="hd"><h2>{label} 실계좌</h2><span class="mut">갱신 {E(str(a.get("generatedAtKST", "-"))[5:16].replace("T", " "))}</span></div>
<div class="kpis">{_kpi("평가 합계", won(a.get("totalKrw")))}{_kpi("매입 합계", won(cost))}
{_kpi("평가손익", f'<span class="{_sign_cls(pnl)}">{sw(pnl)}</span>', "" if pct is None else f'<span class="{_sign_cls(pnl)}">{pct:+.2f}%</span>')}</div>
<div class="tw"><table><tr><th>자산</th><th class="n">수량</th><th class="n">평가</th><th class="n">손익</th></tr>{rows or "<tr><td colspan=4 class=mut>없음</td></tr>"}</table></div></div>''')
    k = real.get("kis")
    if k:
        acc = k.get("account") or {}
        cards.append(f'''<div class="card hl"><div class="hd"><h2>KIS 실계좌</h2><span class="mut">갱신 {E(str(k.get("generatedAtKST", "-"))[5:16].replace("T", " "))}</span></div>
<div class="kpis">{_kpi("총평가", won(acc.get("totalValueKrw")))}{_kpi("예수금", won(acc.get("cashKrw")))}
{_kpi("주식 평가", won(acc.get("stockValueKrw")))}{_kpi("보유 종목", f'{len(k.get("holdings") or [])}개')}</div></div>''')
    rv = ((d or {}).get("paper") or {}).get("rv20")
    if rv:
        fm = rv.get("frontMonth") or {}
        cards.append(f'''<div class="card hl"><div class="hd"><h2>RV20 선물 <span class="pill">모의</span></h2><span class="mut">갱신 {E(str(rv.get("generatedAtKST", "-"))[5:16].replace("T", " "))}</span></div>
<div class="kpis">{_kpi("보유 계약", E(str(rv.get("heldContracts"))))}{_kpi("근월물", E(str(fm.get("name", "-"))), E(str(fm.get("price", ""))))}</div></div>''')
    body = (f'<h1>실계좌 요약</h1><div class="mut" style="margin:-4px 2px 12px">수집 {E(str((d or {}).get("fetchedAt", "-")))[5:16].replace("T", " ")} · '
            f'조회만 한다(autotrader 주문과 무관)</div>{"".join(cards)}'
            f'<a class="btn" href="{base}/">← 요약으로</a>'
            f'<form method="post" action="{base}/logout"><input type="hidden" name="csrf" value="{E(csrf)}"><button class="ghost">로그아웃</button></form>')
    return _page("실계좌 요약", body, base=base, sub="실계좌 요약")


def _pct_small(v) -> str:
    return "" if v is None else f"<br><small>{v:+.1f}%</small>"


def render_passkey(n: int, enabled: str, csrf: str, ready: bool, base: str = "") -> bytes:
    # 패스키 관리 — 등록만 한다. **삭제는 서버에서만**(웹에서 지울 수 있으면 공격자가 지우고 인증앱 코드 방식으로 되돌린다).
    if enabled:
        inner = f'<div class="warn">{E(enabled)}</div>'
    elif ready:
        inner = (f'<button id="pk-register" data-base="{E(base)}" data-csrf="{E(csrf)}">이 기기로 패스키 등록(지문·화면잠금)</button>'
                 f'<div id="pk-msg" class="mut">5분 안에 누르세요.</div><script src="{E(base)}/static/passkey.js"></script>')
    else:
        inner = ('<div class="mut">등록 코드는 서버에서만 나온다(피싱된 인증앱 코드로 남의 패스키를 추가하지 못하게):<br>'
                 '<code>cd ~/collector &amp;&amp; ~/collector-venv/bin/python3 -m autotrader --config ~/collector-venv/autotrader/autotrader.local.json passkey-enroll</code> (15분·1회용)</div>'
                 f'<form method="post" action="{base}/passkey/begin"><input type="hidden" name="csrf" value="{E(csrf)}">'
                 '<input name="code" placeholder="서버 등록 코드 (예: 3F2A-9C01-77BE)" autocomplete="off" maxlength="20" required>'
                 '<button>등록 시작</button></form>')
    body = (f'<h1>패스키(지문)</h1><div class="card"><div class="row"><span>등록된 패스키</span><span>{n}개</span></div>'
            '<div class="mut">패스키가 하나라도 있으면 <b>실계좌 주문 켜기·실행은 패스키로만</b> 된다(인증앱 코드는 안 받는다 — 피싱 방지). '
            '삭제는 서버에서만: <code>cd ~/collector &amp;&amp; ~/collector-venv/bin/python3 -m autotrader --config ~/collector-venv/autotrader/autotrader.local.json passkey-reset</code></div></div>'
            f'<div class="card">{inner}</div><div class="card"><a href="{base}/">← 요약으로</a></div>')
    return _page("패스키", body, base=base, sub="패스키")


def render_login(msg: str = "", base: str = "") -> bytes:
    m = f'<div class="bad">{E(msg)}</div>' if msg else ""
    return _page("로그인", f'''<h1 style="margin-top:28px">안녕하세요 👋</h1><div class="card">{m}
<form method="post" action="{base}/login" autocomplete="off">
<input type="password" name="password" placeholder="비밀번호" autocomplete="current-password" required>
<input name="code" placeholder="인증앱 6자리 코드" inputmode="numeric" autocomplete="one-time-code" maxlength="7" required>
<button>로그인</button></form><div class="mut" style="margin-top:8px">비밀번호 + 인증앱 코드. 실계좌 주문은 로그인 뒤 패스키(지문)로 한 번 더 확인한다.</div></div>''', base=base, sub="로그인")


def render_reauth(csrf: str, msg: str = "", base: str = "", pk: bool = False, nxt: str = "/details") -> bytes:
    m = f'<div class="bad">{E(msg)}</div>' if msg else ""
    if pk:
        return _page("재인증", f'''<h1>한 번 더 확인</h1><div class="card">{m}
<div class="mut">금액·보유 내용은 지문(패스키)으로 확인해야 열립니다.</div>
<button id="pk-reauth" data-base="{E(base)}" data-csrf="{E(csrf)}" data-next="{E(nxt)}">지문으로 확인</button>
<div id="pk-reauth-msg"></div></div><a class="btn" href="{base}/">← 요약으로</a>
<script src="{E(base)}/static/passkey.js"></script>''', base=base, sub="재인증")
    return _page("재인증", f'''<h1>한 번 더 확인</h1><div class="card">{m}
<div class="mut">금액·보유 내용은 인증앱 코드를 <b>새로</b> 입력해야 열립니다. 방금 로그인에 쓴 코드는 못 씁니다 — 코드가 바뀔 때까지(최대 30초) 기다렸다가 입력하세요.</div>
<form method="post" action="{base}/reauth"><input type="hidden" name="csrf" value="{E(csrf)}">
<input name="code" placeholder="인증앱 6자리 코드" inputmode="numeric" autocomplete="one-time-code" maxlength="7" required>
<button>확인</button></form></div><a class="btn" href="{base}/">← 요약으로</a>''', base=base, sub="재인증")


class WebApp:
    """소켓 없이 테스트할 수 있는 요청 처리기. handle(...) -> (status, headers, body)."""

    def __init__(self, cfg: dict, sdir: Path, store: AuthStore, sessions: Sessions, lockout: Lockout,
                 clock: Callable[[], float] = time.time, secure_cookie: bool = True,
                 fail_delay: float = 0.0, sleep: Callable[[float], None] = time.sleep, base: str = "",
                 require_reauth: bool = False, profiles: Optional[Callable[[], List[dict]]] = None,
                 accounts_fetch: Optional[Callable[[], dict]] = None, rp_id: str = "", origin: str = ""):
        self.cfg, self.sdir, self.store = cfg, Path(sdir), store
        self.sessions, self.lockout, self.clock = sessions, lockout, clock
        self.secure_cookie, self.fail_delay, self._sleep = secure_cookie, fail_delay, sleep
        self.base = "/" + base.strip("/") if base.strip("/") else ""      # 예: "/autotrader" (앞단이 이 접두사 아래로 넘겨준다)
        self.require_reauth = require_reauth                              # True 면 상세를 볼 때마다 인증앱 코드를 다시 묻는다
        self.log_path = self.sdir / "web_login.log"
        self._msgs: set = set()
        self._auth_lock = threading.Lock()
        self.fetch_accounts = accounts_fetch or _fetch_accounts
        self.rp_id, self.origin = rp_id, origin                            # 패스키: 도메인·출처(설정 web.rp_id / web.origin)
        self.profiles = profiles or (lambda: [])                          # 프로필 설정 목록(키 없음 — 파일만 읽는다)

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
             "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
                                        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"}
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

    def _json(self, status: int, obj: dict):
        return status, self._hdrs({"Content-Type": "application/json; charset=utf-8"}), json.dumps(obj, ensure_ascii=False).encode()

    def _passkeys(self) -> list:
        return self.store.load().get("passkeys") or []

    def _pk_ready(self) -> bool:
        return bool(self._passkeys()) and not self._pk_disabled()

    def _pk_disabled(self) -> str:
        if not (self.rp_id and self.origin):
            return "서버 설정에 web.rp_id / web.origin 이 없어 패스키가 꺼져 있다"
        if not passkey_available():
            return "서버에 webauthn 라이브러리가 없어 패스키가 꺼져 있다"
        return ""

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
        if method == "GET" and path == "/static/passkey.js":       # 공개 저장소의 코드 그대로 — 비밀 없음
            js = (Path(__file__).resolve().parent / "static" / "passkey.js").read_bytes()
            return 200, self._hdrs({"Content-Type": "application/javascript; charset=utf-8"}), js
        if not self.store.exists():
            return 503, self._hdrs(), _page("설정 필요", "<h1>설정 필요</h1><div class='card mut'>서버에서 web-setup 을 먼저 실행해야 한다.</div>")
        if method == "POST":
            with self._auth_lock:                       # 동시 요청으로 잠금 검사를 한꺼번에 통과하지 못하게 — 1인용이라 직렬로 충분
                return self._handle(method, path, raw_path, headers, body, ip)
        return self._handle(method, path, raw_path, headers, body, ip)

    def _handle(self, method, path, raw_path, headers, body, ip):
        tok = self._session_token(headers)
        sess = self.sessions.get(tok)
        if sess and sess.get("gen", 0) != self.store.session_gen():     # 비밀번호·패스키 재설정·logout-all 뒤의 옛 로그인(N3)
            self.sessions.destroy(tok)
            sess = None
        form = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True) if method == "POST" else {}
        field = lambda k: (form.get(k) or [""])[0]   # noqa: E731

        if method == "POST" and path == "/login":
            return self._login(field("password"), field("code"), ip)
        if method == "GET" and path in ("/", "/index.html"):
            if not sess:
                return 200, self._hdrs(), render_login(base=self.base)
            now = self._now()
            locked = self.require_reauth and not self.sessions.is_fresh(sess)     # N2: 금액·보유는 재확인 뒤에만
            unlock = (f'<div class="card"><div class="mut">🔒 금액·보유 종목은 확인 뒤에 보입니다(5분).</div>'
                      + (f'<button id="pk-reauth" data-base="{E(self.base)}" data-csrf="{E(sess["csrf"])}" data-next="/">지문으로 보기</button>'
                         f'<div id="pk-reauth-msg"></div><script src="{E(self.base)}/static/passkey.js"></script>' if self._pk_ready()
                         else f'<a class="btn" href="{self.base}/details">인증앱 코드로 확인</a>') + '</div>') if locked else ""
            extra = unlock + render_profiles([(c, load_view(c, state_dir(c), now)) for c in self.profiles()], self.base, hide_money=locked)
            return 200, self._hdrs(), render_dashboard(load_view(self.cfg, self.sdir, now), sess["csrf"], self.base,
                                                       self.require_reauth, extra)
        if not sess:                                    # 로그인 전에는 나머지 경로가 존재하지 않는 것처럼
            return self._not_found()
        if method == "GET" and path == "/accounts":
            if self.require_reauth and not self.sessions.is_fresh(sess):
                return 200, self._hdrs(), render_reauth(sess["csrf"], base=self.base, pk=self._pk_ready(), nxt="/accounts")
            try:
                d, err = self.fetch_accounts(), ""
            except Exception as e:                      # noqa: BLE001 — API 가 죽어도 화면은 뜬다
                d, err = None, type(e).__name__
            return 200, self._hdrs(), render_accounts(d, err, sess["csrf"], self.base)
        if method == "GET" and path == "/details":
            want = (parse_qs(urlsplit(raw_path).query).get("p") or [""])[0]
            if self.require_reauth and not self.sessions.is_fresh(sess):
                return 200, self._hdrs(), render_reauth(sess["csrf"], base=self.base, pk=self._pk_ready(),
                                                            nxt="/details" + (f"?p={quote(want)}" if want else ""))
            if not want:
                return 200, self._hdrs(), render_details(load_view(self.cfg, self.sdir, self._now()), sess["csrf"], self.base, self.require_reauth)
            match = [c for c in self.profiles() if c.get("profile") == want]     # 목록에 있는 이름만 — 경로로 쓰지 않는다
            if not match:
                return self._not_found()
            c = match[0]
            msg = (parse_qs(urlsplit(raw_path).query).get("m") or [""])[0]
            msg = msg if msg in self._msgs else ""
            has_pk = self._pk_ready()
            return 200, self._hdrs(), render_details(load_view(c, state_dir(c), self._now()), sess["csrf"], self.base,
                                                     self.require_reauth, want, render_controls(c, sess["csrf"], self.base, msg, has_pk))
        if path.startswith("/passkey"):
            return self._passkey_route(method, path, sess, tok, body, field, ip)
        if method == "POST" and path == "/action":
            if field("csrf") != sess["csrf"]:
                self._log(ip, "csrf-fail")
                return 403, self._hdrs(), _page("403", "<h1>요청이 거부됨</h1>")
            return self._action(field("p"), field("op"), field("code"), ip, field("phrase"))
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

    # -------------------------------------------------------------- 조작(요청 파일만 쓴다 — 주문은 키를 가진 run-due 가 낸다)
    OPS = ("auto-off", "auto-dry", "auto-execute", "run", "kill", "resume")

    def _action(self, name: str, op: str, code: str, ip: str, phrase: str = ""):
        match = [c for c in self.profiles() if c.get("profile") == name]      # 목록에 있는 이름만 — 경로로 쓰지 않는다
        if not match or op not in self.OPS:
            return self._not_found()
        c = match[0]
        live = c.get("mode") == "live"
        # 실계좌 주문으로 이어질 수 있는 조작(주문 켜기·주문 상태의 지금 실행)은 확인 문구까지 요구한다
        live_order = is_live_order(c, op)
        def back(m: str):
            return self._redirect(self._back_url(name, m))
        if live_order:                                  # 패스키가 없거나 쓸 수 없어도 코드로 내려가지 않는다(M3)
            return back("실계좌 주문 켜기·실행·킬 해제는 패스키로만 됩니다 — 아래 '패스키(지문)로 확인'")
        if op != "kill" and self._pk_ready():           # 패스키가 있으면 조작은 지문으로만(인증앱 코드는 패스키가 없을 때의 대체)
            return back("조작은 지문(패스키)으로 확인합니다 — 아래 '지문으로 확인'")
        if op != "kill":                                # 킬 켜기(안전 쪽)만 코드 없이. 나머지는 새 인증앱 코드
            if self.lockout.is_locked(ip):
                return back("잠시 후 다시 시도하세요")
            rec = self.store.load()
            step = totp_verify(rec["totpSecret"], code, t=self.clock(), last_step=rec.get("lastTotpStep"))
            if step is None:
                self.lockout.fail(ip)
                self._log(ip, "action-fail")
                if self.fail_delay:
                    self._sleep(self.fail_delay)
                return back("인증앱 코드가 맞지 않습니다(방금 쓴 코드는 못 씁니다 — 새 코드를 기다리세요)")
            self.store.set_last_step(step)
            self.lockout.ok(ip)
        return back(self._execute(c, name, op, ip))

    def _back_url(self, name: str, m: str) -> str:
        self._msgs.add(m)                               # 이 서버가 낸 문구만 화면에 띄운다(주소창으로 가짜 안내를 못 넣게)
        return f"/details?p={quote(name)}&m={quote(m)}"

    def _execute(self, c: dict, name: str, op: str, ip: str) -> str:
        """인증이 끝난 조작을 실행하고 안내 문구를 돌려준다. 요청 파일·킬 파일만 쓴다."""
        live = c.get("mode") == "live"
        now = self._now()
        if op.startswith("auto-"):
            err = web_set_auto(c, op[5:], now)
            if err:
                return err
            msg = {"off": "자동 실행을 껐습니다", "dry": "자동 dry-run 으로 바꿨습니다",
                   "execute": "자동 주문을 켰습니다(서버 타이머에 --execute 가 있어야 실제 주문)"}[op[5:]]
        elif op == "run":
            web_request_run(c, now)
            msg = "실행을 요청했습니다 — 5분 안에 돌고 결과는 텔레그램·최근 실행에 뜹니다"
        elif op == "kill":
            kf = kill_file(c)
            kf.parent.mkdir(parents=True, exist_ok=True)
            kf.write_text(now.isoformat(), encoding="utf-8")
            msg = "킬 스위치를 켰습니다 — 이 프로필의 주문이 멈춥니다"
        else:
            kill_file(c).unlink(missing_ok=True)
            msg = "킬 스위치를 해제했습니다"
        self._log(ip, f"action:{name}:{op}{'-live' if live else ''}")
        return msg

    # -------------------------------------------------------------- 패스키
    def _passkey_route(self, method, path, sess, tok, body, field, ip):
        now = self.clock()
        if method == "GET" and path == "/passkey":
            return 200, self._hdrs(), render_passkey(len(self._passkeys()), self._pk_disabled(), sess["csrf"],
                                                     sess.get("pkRegUntil", 0) > now, self.base)
        if method != "POST" or self._pk_disabled():
            return self._not_found()
        if path == "/passkey/begin":                    # 등록 시작 = 서버가 발급한 1회용 등록 코드 → 5분간 등록 허용
            if field("csrf") != sess["csrf"]:
                return 403, self._hdrs(), _page("403", "<h1>요청이 거부됨</h1>")
            if self.lockout.is_locked(ip):
                return self._redirect("/passkey")
            if not self.store.take_enroll_code(field("code"), now):
                self.lockout.fail(ip)
                self._log(ip, "passkey-fail")
                return self._redirect("/passkey")
            self.lockout.ok(ip)
            sess["pkRegUntil"] = now + 300
            return self._redirect("/passkey")
        try:
            j = json.loads(body.decode("utf-8"))
        except ValueError:
            return self._json(400, {"error": "형식 오류"})
        if not isinstance(j, dict) or j.get("csrf") != sess["csrf"]:
            self._log(ip, "csrf-fail")
            return self._json(403, {"error": "요청이 거부됨"})
        if path == "/passkey/register-options":
            if sess.get("pkRegUntil", 0) <= now:
                return self._json(403, {"error": "등록 시작(인증앱 코드)부터 다시"})
            opts, chal = passkey_reg_options(self.rp_id, [p["id"] for p in self._passkeys()])
            sess["pkRegChal"] = chal
            return 200, self._hdrs({"Content-Type": "application/json; charset=utf-8"}), opts.encode()
        if path == "/passkey/register":
            chal = sess.pop("pkRegChal", None)          # 챌린지는 한 번만
            if not chal or sess.get("pkRegUntil", 0) <= now:
                return self._json(403, {"error": "등록 시작(인증앱 코드)부터 다시"})
            sess.pop("pkRegUntil", None)
            try:
                rec_pk = passkey_reg_verify(json.dumps(j.get("credential")), chal, self.rp_id, self.origin)
            except Exception:                           # noqa: BLE001 — 라이브러리 검증 실패
                self._log(ip, "passkey-fail")
                return self._json(400, {"error": "패스키 검증 실패"})
            added = {**rec_pk, "added": self._now().isoformat()}
            self.store.update(lambda r: r.__setitem__("passkeys", (r.get("passkeys") or []) + [added]))
            self._log(ip, "passkey-added")
            return self._json(200, {"message": "패스키를 등록했습니다"})
        if path == "/passkey/reauth-options":
            if not self._passkeys():
                return self._json(404, {"error": "없음"})
            opts, chal = passkey_auth_options(self.rp_id, [p["id"] for p in self._passkeys()])
            sess["pkReauth"] = {"chal": chal, "until": now + 120}
            return 200, self._hdrs({"Content-Type": "application/json; charset=utf-8"}), opts.encode()
        if path == "/passkey/reauth":
            pend = sess.pop("pkReauth", None)           # 챌린지는 한 번만
            if not pend or pend["until"] <= now:
                return self._json(403, {"error": "확인 요청이 만료됐다 — 다시"})
            if self.lockout.is_locked(ip):
                return self._json(429, {"error": "잠시 후 다시 시도하세요"})
            try:
                cid, count = passkey_auth_verify(json.dumps(j.get("credential")), pend["chal"], self.rp_id, self.origin,
                                                 self._passkeys())
            except Exception:                           # noqa: BLE001
                self.lockout.fail(ip)
                self._log(ip, "reauth-fail")
                return self._json(401, {"error": "패스키 확인 실패"})
            self.lockout.ok(ip)
            self._bump(cid, count)
            self.sessions.mark_reauth(tok)
            self._log(ip, "reauth-ok")
            ok_next = {"/", "/accounts", "/details"} | {f"/details?p={quote(str(c.get('profile', '')))}" for c in self.profiles()}
            nxt = j.get("next") if j.get("next") in ok_next else "/details"   # 허용목록 — 열린 리디렉션 금지
            return self._json(200, {"redirect": self.base + nxt})
        if path == "/passkey/action-options":
            match = [c for c in self.profiles() if c.get("profile") == j.get("p")]
            if not match or j.get("op") not in self.OPS or j.get("op") == "kill" or not self._passkeys():
                return self._json(404, {"error": "없음"})
            opts, chal = passkey_auth_options(self.rp_id, [p["id"] for p in self._passkeys()])
            sess["pkAct"] = {"chal": chal, "p": j["p"], "op": j["op"], "until": now + 120}   # 이 조작에만 묶인다
            return 200, self._hdrs({"Content-Type": "application/json; charset=utf-8"}), opts.encode()
        if path == "/passkey/action":
            pend = sess.pop("pkAct", None)              # 챌린지는 한 번만
            if not pend or pend["until"] <= now or pend["p"] != j.get("p") or pend["op"] != j.get("op"):
                return self._json(403, {"error": "확인 요청이 만료됐거나 조작이 다르다 — 다시"})
            if self.lockout.is_locked(ip):
                return self._json(429, {"error": "잠시 후 다시 시도하세요"})
            stored = self._passkeys()
            try:
                cid, count = passkey_auth_verify(json.dumps(j.get("credential")), pend["chal"], self.rp_id, self.origin, stored)
            except Exception:                           # noqa: BLE001
                self.lockout.fail(ip)
                self._log(ip, "passkey-fail")
                return self._json(401, {"error": "패스키 확인 실패"})
            self.lockout.ok(ip)
            self._bump(cid, count)
            c = [x for x in self.profiles() if x.get("profile") == pend["p"]][0]
            if is_live_order(c, pend["op"]) and str(j.get("phrase", "")).strip() != LIVE_PHRASE:
                return self._json(400, {"error": f"확인 문구({LIVE_PHRASE})를 정확히 입력"})
            msg = self._execute(c, pend["p"], pend["op"], ip)
            return self._json(200, {"redirect": self.base + self._back_url(pend["p"], msg)})
        return self._not_found()

    def _bump(self, cid: str, count: int) -> None:
        def fn(r):
            for pk in r.get("passkeys") or []:
                if pk["id"] == cid:
                    pk["count"] = max(int(pk.get("count") or 0), count)
        self.store.update(fn)

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
            tok = self.sessions.create(gen=self.store.session_gen())
            self._log(ip, "login-ok")
            return self._redirect("/", {"Set-Cookie": self._cookie(tok, int(self.sessions.absolute))})
        self.lockout.fail(ip)
        self._log(ip, "login-fail")
        if self.fail_delay:
            self._sleep(self.fail_delay)
        return 401, self._hdrs(), render_login("로그인할 수 없습니다.", self.base)

    def _reauth(self, code: str, tok: str, sess: dict, ip: str):
        if self._pk_ready():                            # 패스키가 있으면 재인증도 지문으로만(보안 재검토 N1 — 피싱된 인증앱 코드로 금액 보기 차단)
            self._log(ip, "reauth-totp-refused")
            return 403, self._hdrs(), render_reauth(sess["csrf"], "지문(패스키)으로 확인하세요.", self.base, pk=True)
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
            body = self.rfile.read(min(n, 16384)) if n else b""        # 패스키 응답(JSON) 여유. 더 큰 본문은 잘려 검증에서 실패한다
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


def _profile_loader(cfg: dict, config_path) -> Callable[[], List[dict]]:
    def load() -> List[dict]:
        out = []
        for n in list_profiles(config_path):
            try:
                out.append(load_profile(config_path, n, cfg))
            except (ConfigError, ValueError):
                continue                                # 깨진 프로필 하나가 화면 전체를 막지 않는다
        return out
    return load


def serve(cfg: dict, host: str = "127.0.0.1", port: int = 8787, secure_cookie: bool = True, base: str = "",
          config_path=None) -> None:
    sdir = state_dir(cfg)
    w = cfg.get("web", {})
    hours = float(w.get("session_hours", 30 * 24))     # 기본 30일 유지 — 조작·실계좌 보기는 매번 지문(패스키)이 막는다
    sessions = Sessions(idle_sec=int(float(w.get("idle_min", hours * 60)) * 60), absolute_sec=int(hours * 3600),
                        reauth_sec=int(w.get("reauth_min", 5)) * 60, path=sdir / "web_sessions.json")
    app = WebApp(cfg, sdir, AuthStore(sdir / "web_auth.json"), sessions, Lockout(),
                 secure_cookie=secure_cookie, fail_delay=0.5, base=base,
                 require_reauth=bool(w.get("require_reauth_for_details", True)),
                 profiles=_profile_loader(cfg, config_path) if config_path else None,
                 rp_id=str(w.get("rp_id", "")), origin=str(w.get("origin", "")))
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"autotrader web — http://{host}:{port} (앞단 HTTPS 프록시 뒤에서만 쓴다)", flush=True)
    httpd.serve_forever()
