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
import math
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
KR_INTRADAY_URL = "http://127.0.0.1:8766/kr-intraday"   # 장중 알림(10분)이 남긴 관심종목 현재가 — 키 없이 같은 VM 에서
LIVE_PHRASE = "실계좌주문"      # 실계좌 주문 켜기·실행 때 입력하는 확인 문구(실수 클릭 방지 — 보안은 인증앱 코드와 서버 한도가 맡는다)
SNAPSHOT_STALE_SEC = 30 * 60

CSS = """
:root{--bg:#0b1020;--fg:#e7e9f3;--card:#121933;--card2:#172042;--mut:#8a93ad;--line:#232c4d;--chip:#1b2447;
--acc:#6d6ff5;--acc2:#8b7cf6;--accs:rgba(109,111,245,.16);--up:#f25f6e;--dn:#5b8cff;--ok:#34d399;--bad:#f87171;--warn:#fbbf24;
--oks:rgba(52,211,153,.13);--bads:rgba(248,113,113,.14);--warns:rgba(251,191,36,.14);--r:18px}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%;background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Pretendard","Malgun Gothic",system-ui,sans-serif;
font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
svg.i{width:22px;height:22px;flex:none;stroke:currentColor;fill:none;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round}
.top{position:sticky;top:0;z-index:5;background:rgba(11,16,32,.92);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-bottom:1px solid var(--line);padding:12px 16px}
.top .in{max-width:760px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:10px}
.top .brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:20px;letter-spacing:-.4px;color:var(--fg);text-decoration:none}
.logo{width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--acc),var(--acc2));display:grid;place-items:center;color:#fff}
.logo svg.i{width:20px;height:20px}
.top .sub{font-size:12px;font-weight:600;color:var(--fg);background:var(--chip);border:1px solid var(--line);border-radius:99px;padding:5px 12px}
main{max-width:760px;margin:0 auto;padding:14px 14px 96px}
h1{font-size:22px;margin:10px 2px 12px;letter-spacing:-.5px}h2{font-size:15px;margin:0 0 10px;letter-spacing:-.2px}
.sec{font-size:19px;font-weight:800;color:var(--fg);margin:22px 4px 10px;letter-spacing:-.4px}
.sec small{font-size:12px;font-weight:500;color:var(--mut)}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px;margin:0 0 12px}
.card.hl{background:linear-gradient(180deg,var(--card2),var(--card))}
.hd{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}.hd h2{margin:0;font-size:17px}
.row{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid var(--line)}.row:last-child{border:0}
.row>span:first-child{color:var(--mut);font-size:14px}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:4px 0 10px}
.kpi{background:var(--chip);border:1px solid var(--line);border-radius:14px;padding:10px 12px;min-width:0}
.kpi .l{font-size:12px;color:var(--mut);display:flex;align-items:center;gap:6px}.kpi .v{font-size:18px;font-weight:800;letter-spacing:-.3px;overflow-wrap:anywhere}
.kpi .s{font-size:12px;font-weight:600}
.stat{display:grid;grid-template-columns:repeat(3,1fr) auto;gap:8px;align-items:stretch}
.stat .kpi{padding:10px}.stat .kpi .v{font-size:26px;margin-top:4px}.stat .kpi .l{white-space:nowrap;font-size:12.5px}
.stat .kill{display:flex;align-items:center}
@media(max-width:420px){.stat{grid-template-columns:repeat(3,1fr)}.stat .kill{grid-column:1/-1}}
.ic{width:24px;height:24px;border-radius:8px;display:inline-grid;place-items:center}.ic svg.i{width:16px;height:16px}
.ic.g{background:var(--oks);color:var(--ok)}.ic.b{background:var(--accs);color:var(--acc)}.ic.y{background:var(--warns);color:var(--warn)}.ic.r{background:var(--bads);color:var(--bad)}
.tile{width:46px;height:46px;border-radius:14px;background:var(--accs);color:#a5a7ff;display:grid;place-items:center;flex:none}
.tile svg.i{width:24px;height:24px}
.sc-h{display:flex;align-items:center;gap:12px;margin-bottom:10px}.sc-h .t{flex:1;min-width:0}
.sc-h .nm{font-size:19px;font-weight:800;letter-spacing:-.4px;display:inline}.sc-h .pf{color:var(--mut);font-size:14px;margin-left:6px}
.sc-h .go{color:var(--mut)}
.mut{color:var(--mut);font-size:13px}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.up{color:var(--up)}.dn{color:var(--dn)}
.pill{display:inline-flex;align-items:center;gap:5px;padding:3px 11px;border-radius:99px;background:var(--chip);border:1px solid var(--line);font-size:12.5px;font-weight:600;margin:0 4px 4px 0;color:var(--fg)}
.pill.ok{background:var(--oks);border-color:rgba(52,211,153,.35);color:var(--ok)}
.pill.bad{background:var(--bads);border-color:rgba(248,113,113,.35);color:var(--bad)}
.pill.warn{background:var(--warns);border-color:rgba(251,191,36,.35);color:var(--warn)}
.pill.acc{background:var(--accs);border-color:rgba(109,111,245,.35);color:#a5a7ff}
input,button,select{font:inherit;padding:12px 14px;border-radius:12px;border:1px solid var(--line);width:100%;margin:6px 0;background:var(--chip);color:var(--fg)}
input::placeholder{color:#5f6886}
button{background:linear-gradient(135deg,var(--acc),var(--acc2));border:0;color:#fff;font-weight:700;cursor:pointer}
button.ghost{background:transparent;border:1px solid var(--acc);color:#a5a7ff}
a{color:#a5a7ff;text-decoration:none}
.nav{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:4px 0 12px}
.nav a{display:flex;align-items:center;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px;color:var(--fg);font-weight:700}
.nav a small{display:block;color:var(--mut);font-weight:400;font-size:12px;margin-top:2px}
.nav a .tile{width:40px;height:40px;border-radius:12px}
.btn{display:block;text-align:center;border:1px solid var(--acc);color:#a5a7ff;border-radius:12px;padding:10px;font-weight:700;margin-top:8px}
.btn.fill{background:linear-gradient(135deg,var(--acc),var(--acc2));border:0;color:#fff}
.btns{display:flex;gap:8px;flex-wrap:wrap}.btns>*{flex:1;min-width:120px}
.tw{overflow-x:auto;margin:0 -4px}table{width:100%;border-collapse:collapse;font-size:14px}
th{font-size:12px;color:var(--mut);font-weight:600;text-align:left;padding:6px 6px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 6px;border-bottom:1px solid var(--line);vertical-align:top}tr:last-child td{border-bottom:0}
td.n,th.n{text-align:right;white-space:nowrap}
.nm{font-weight:700;display:block;line-height:1.3}.code{font-size:11px;color:var(--mut)}
.bar{height:6px;background:var(--chip);border-radius:99px;overflow:hidden;margin-top:4px}.bar i{display:block;height:100%;background:var(--acc)}
.pf label{display:block;font-size:12px;color:var(--mut);margin:8px 2px -2px}
code{background:var(--chip);padding:2px 6px;border-radius:6px;font-size:12px;word-break:break-all}
.side{display:inline-block;min-width:38px;text-align:center;border-radius:8px;padding:2px 6px;font-size:12px;font-weight:700}
.side.b{background:var(--bads);color:var(--up)}.side.s{background:rgba(91,140,255,.16);color:var(--dn)}
.tabbar{position:fixed;left:0;right:0;bottom:0;z-index:6;background:rgba(14,20,40,.96);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
border-top:1px solid var(--line);padding:8px 6px calc(8px + env(safe-area-inset-bottom))}
.tabbar .in{max-width:760px;margin:0 auto;display:grid;grid-template-columns:repeat(5,1fr)}
.tabbar a{display:flex;flex-direction:column;align-items:center;gap:3px;color:var(--mut);font-size:12px;font-weight:600}
.tabbar a.on{color:#8f91ff}.tabbar svg.i{width:24px;height:24px}
"""

E = html.escape


_ICON = {
    "trend": '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    "home": '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
    "orders": '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1"/>',
    "inf": '<path d="M7 9c-4 0-4 6 0 6 2.5 0 3.5-3 5-3s2.5 3 5 3c4 0 4-6 0-6-2.5 0-3.5 3-5 3S9.5 9 7 9z"/>',
    "cal": '<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
    "play": '<circle cx="12" cy="12" r="9"/><path d="M10 8.5l5 3.5-5 3.5z"/>',
    "clip": '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4h6v3H9zM9 11h6M9 15h4"/>',
    "alert": '<path d="M12 3 2 20h20z"/><path d="M12 10v4M12 17h.01"/>',
    "shield": '<path d="M12 3l7 3v5c0 5-3.5 8.5-7 10-3.5-1.5-7-5-7-10V6z"/><path d="M9 12l2 2 4-4"/>',
    "user": '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4 4.5-6 8-6s7 2 8 6"/>',
    "doc": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4M9 12h6M9 16h6"/>',
    "news": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 9h6M7 13h10M7 16h10"/>',
    "key": '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3"/>',
    "chev": '<path d="M9 6l6 6-6 6"/>',
    "out": '<path d="M15 4h4v16h-4M10 17l5-5-5-5M15 12H3"/>',
    "wallet": '<rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 10h18M16 15h.01"/>',
    "server": '<rect x="4" y="4" width="16" height="7" rx="2"/><rect x="4" y="13" width="16" height="7" rx="2"/><path d="M8 7.5h.01M8 16.5h.01"/>',
}
STRAT_ICON = {"plan_trader": "cal", "infinite_buying": "inf", "target_weights": "target"}
TABS = (("home", "/", "홈"), ("strat", "/strategies", "전략"), ("orders", "/orders", "주문"), ("log", "/log", "기록"),
        ("set", "/settings", "설정"))
TAB_ICON = {"home": "home", "strat": "trend", "orders": "orders", "log": "clock", "set": "gear"}


def ic(name: str) -> str:
    return f'<svg class="i" viewBox="0 0 24 24" aria-hidden="true">{_ICON.get(name, "")}</svg>'


def _page(title: str, body: str, refresh: bool = False, base: str = "", sub: str = "", tab: Optional[str] = None) -> bytes:
    """tab 을 주면 아래 탭 막대를 붙인다(로그인 뒤 화면). 로그인·재인증 화면은 탭 없이."""
    meta = '<meta http-equiv="refresh" content="30">' if refresh else ""
    top = (f'<header class="top"><div class="in"><a class="brand" href="{E(base)}/"><span class="logo">{ic("trend")}</span>autotrader</a>'
           + (f'<span class="sub">{sub}</span>' if sub else "") + '</div></header>')
    bar = ("" if tab is None else '<nav class="tabbar"><div class="in">' + "".join(
        f'<a href="{E(base)}{path}" class="{"on" if key == tab else ""}">{ic(TAB_ICON[key])}{label}</a>' for key, path, label in TABS)
        + "</div></nav>")
    return (f'<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="#0b1020">{meta}<title>{E(title)}</title>'
            f'<style>{CSS}</style></head><body>{top}<main>{body}</main>{bar}</body></html>').encode("utf-8")


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
STRAT_KO = {"plan_trader": "계획 매매", "infinite_buying": "무한매수", "target_weights": "목표 비중"}
HEARTBEAT_STALE_SEC = 12 * 60        # run-due 는 5분마다 — 두 번 넘게 빠지면 '타이머가 안 돈다'


def server_state(sdir: Path, now: datetime) -> Tuple[bool, str]:
    """서버 주문 허용(타이머 --execute) — run-due 가 5분마다 남기는 run_due.json. 묵었으면 켜짐으로 읽지 않는다."""
    hb = _load_json(Path(sdir) / "run_due.json") or {}
    try:
        age = (now - datetime.fromisoformat(hb["at"])).total_seconds()
    except (KeyError, ValueError, TypeError):
        age = None
    if age is None:
        return False, '<span class="warn">모름 — 예약 타이머 기록이 아직 없다</span>'
    if age > HEARTBEAT_STALE_SEC:
        return False, f'<span class="bad">타이머 멈춤? 마지막 {age / 60:.0f}분 전</span>'
    return bool(hb.get("execute")), (('<span class="pill ok" style="margin:0">켜짐</span>' if hb.get("execute")
                                      else '<span class="pill warn" style="margin:0">꺼짐</span>')
                                     + f'<br><small class="mut">{age / 60:.0f}분 전</small>')


def server_card(srv: str) -> str:
    return (f'<div class="card"><div class="row"><span style="display:flex;align-items:center;gap:10px"><span class="ic b">{ic("server")}</span>'
            f'<span style="color:var(--fg);font-weight:700">서버 주문 허용<br><small class="mut" style="font-weight:400">VM · 전략 공통</small></span></span><span style="text-align:right">{srv}</span></div>'
            '<div class="mut">서버 허용이 꺼져 있으면 모든 전략이 계획만 낸다. 주문은 서버 허용 + 그 전략의 "주문 켜짐"일 때만. 버튼은 지문 한 번.</div></div>')


def switch_pill(c: dict, server_on: bool) -> str:
    auto = c.get("auto", "off")
    if kill_file(c).exists():
        return '<span class="pill bad">킬 ON</span>'
    if auto == "execute":
        return '<span class="pill ok">주문 켜짐</span>' if server_on else '<span class="pill warn">주문 대기(서버 허용 꺼짐)</span>'
    return '<span class="pill">계획만</span>' if auto == "dry" else '<span class="pill">꺼짐</span>'


def switch_btn(c: dict, csrf: str, base: str, pk: bool) -> str:
    """켜기/끄기 한 번(지문). 실계좌·패스키 없음은 상세 화면으로(확인 문구·인증앱 코드 흐름)."""
    name = str(c.get("profile", ""))
    if c.get("mode") == "live" or not pk:
        return f'<a class="mut" href="{base}/details?p={quote(name)}">상세에서 조작 →</a>'
    on = c.get("auto") == "execute"
    style = ";background:var(--bads);color:var(--bad);border:1px solid rgba(248,113,113,.4)" if on else ""
    return (f'<form class="pk-act" data-base="{E(base)}" data-csrf="{E(csrf)}" data-profile="{E(name)}" style="margin:0">'
            f'<input type="hidden" name="op" value="{"auto-off" if on else "auto-execute"}">'
            f'<button style="padding:8px 16px;margin:0;width:auto{style}">{"끄기" if on else "주문 켜기"}</button><div class="pk-msg"></div></form>')


def _tile(strategy: str) -> str:
    return f'<span class="tile">{ic(STRAT_ICON.get(strategy, "trend"))}</span>'


def _strat_name(c: dict) -> str:
    return E(STRAT_KO.get(c.get("strategy"), str(c.get("strategy"))))


def render_switches(items: List[dict], sdir: Path, csrf: str, base: str, now: datetime, pk: bool,
                    paper_engine: Optional[dict] = None) -> str:
    """전략 목록(전략 탭) — 프로필마다 상태 + 켜기/끄기(지문). 금액 없음 — 로그인만으로 보인다."""
    server_on, srv = server_state(sdir, now)
    rows = []
    for c in items:
        name, live = str(c.get("profile", "")), c.get("mode") == "live"
        rows.append(f'<div class="card"><div class="sc-h">{_tile(c.get("strategy"))}<div class="t">'
                    f'<span class="nm">{_strat_name(c)}</span><span class="pf">{E(name)}</span><br>'
                    f'<span class="pill">{"실전" if live else "모의"}</span>{switch_pill(c, server_on)}</div>'
                    f'{switch_btn(c, csrf, base, pk)}</div></div>')
    pe = ""
    if paper_engine:
        strat = paper_engine.get("strategies") or {}
        pe = ('<div class="sec">페이퍼 엔진 슬리브 <small>별도 엔진 · 항상 켜짐 · 여기서 조작 안 함</small></div><div class="card">'
              + "".join(f'<div class="row"><span style="color:var(--fg)">{E(k)}</span><span class="mut">보유 '
                        f'{sum(1 for p in (v.get("positions") or []) if p.get("status") == "OPEN")}종목</span></div>'
                        for k, v in strat.items())
              + f'<div class="mut">기준 {E(str(paper_engine.get("updatedAt", ""))[:16].replace("T", " "))}</div></div>')
    return (f'<div class="sec">전략 스위치</div>{server_card(srv)}'
            + ("".join(rows) or '<div class="card mut">프로필이 없다</div>') + pe)


def render_profiles(items: List[Tuple[dict, dict]], base: str = "", hide_money: bool = False, csrf: str = "", pk: bool = False,
                    server_on: bool = False) -> str:
    """프로필(키 묶음+전략)마다 한 장 — 상태·켜기/끄기·투자금·손익·보유·상세 링크. hide_money 면 금액·보유를 빼고 상태만(N2)."""
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
        sw = f'<div class="row"><span>{switch_pill(cfg, server_on)}</span>{switch_btn(cfg, csrf, base, pk)}</div>' if csrf else ""
        plan_btn = f'<a class="btn fill" href="{base}/plans?p={quote(name)}">매매 계획</a>' if cfg.get("strategy") == "plan_trader" else ""
        out.append(f'''<div class="card hl"><div class="sc-h">{_tile(cfg.get("strategy"))}<div class="t">
<span class="nm">{_strat_name(cfg)}</span><span class="pf">{E(name)}</span></div>
<a class="go" href="{base}/details?p={quote(name)}">{ic("chev")}</a></div>
<span class="pill acc">{E(str(cfg.get("strategy")))}</span><span class="pill">{"실전" if cfg.get("mode") == "live" else "모의"}</span>
<span class="pill {auto_cls}">{E(AUTO_TXT.get(auto, auto))} {E(",".join(cfg.get("run_at") or []))}</span>
{'<span class="pill bad">킬 ON</span>' if v["kill"] else ""}
{"" if hide_money else render_money_rows(snap)}
{"" if hide_money else held_tbl}
<div class="row"><span>오늘 실행 · 접수 · 오류</span><span>{len(t)} · {cnt("placed")} · <span class="{"bad" if cnt("errors") else ""}">{cnt("errors")}</span></span></div>
{sw}
<div class="row"><span>마지막 실행</span>{last_txt}</div>
<div class="row"><span>스냅샷</span>{_ago(v, snap)}</div>
<div class="btns"><a class="btn" href="{base}/details?p={quote(name)}">상세 보기 · 조작</a>{plan_btn}</div></div>''')
    return ('<div class="sec">전략 스위치</div>' + "".join(out)) if out else ""


def render_dashboard(v: dict, csrf: str, base: str = "", strict: bool = False, extra: str = "", top: str = "",
                     agg: Optional[dict] = None) -> bytes:
    """홈 — 오늘 숫자(전체 합) · 서버 주문 허용 · 전략 카드(extra) · 계좌 바로가기 · 기본 설정(게이트·한도·최근 실행)."""
    mode_txt = "실전(실계좌)" if v["mode"] == "live" else "모의투자"
    snap = v["snapshot"]
    ex = ((snap or {}).get("gates") or {}).get("execute") or []
    gates = ('<span class="ok">주문 조건 충족</span> <span class="mut">— --execute 로 실행할 때만 나간다</span>' if snap and not ex
             else (f'<span class="warn">주문 잠김 · 미충족 {len(ex)}개</span>' if snap else '<span class="mut">-</span>'))
    gate_items = "".join(f"<div class='mut'>· {E(str(x))}</div>" for x in ex)
    t = v["todayRuns"]
    cnt = lambda k: sum(len(r.get(k) or []) for r in t)   # noqa: E731
    a = agg or {"runs": len(t), "placed": cnt("placed"), "errors": cnt("errors"), "kill": v["kill"]}
    limits = "".join(
        f'<div class="row"><span>{E(m)} 일일 한도</span><span>{s["used"] / s["limit"] * 100 if s["limit"] else 0:.0f}% 사용</span></div>'
        f'<div class="bar"><i style="width:{min(100, s["used"] / s["limit"] * 100 if s["limit"] else 0):.0f}%"></i></div>'
        for m, s in v["spent"].items())
    recent = "".join(
        f'<div class="row"><span>{E(str(r.get("at", ""))[5:16].replace("T", " "))} {E("주문" if r.get("execute") else "dry-run")}</span>'
        f'<span class="{"ok" if r.get("status") == "ok" else "bad"}">{E(str(r.get("status")))} · 접수 {len(r.get("placed") or [])}'
        f' 거부 {len(r.get("rejected") or [])}</span></div>' for r in reversed(v["runs"][-5:]))
    reauth = " (재확인)" if strict else ""

    def kpi(i, cls, label, val):
        return f'<div class="kpi"><div class="l"><span class="ic {cls}">{ic(i)}</span>{label}</div><div class="v">{val}</div></div>'
    err = f'<span class="{"bad" if a["errors"] else ""}">{a["errors"]}</span>'
    kill = (f'<span class="pill {"bad" if a["kill"] else "ok"}" style="padding:8px 14px;margin:0">{ic("shield")}'
            f'{"킬 스위치 ON" if a["kill"] else "킬 스위치 OFF"}</span>')
    body = f'''<div class="card"><div class="stat">{kpi("play", "g", "오늘 실행", a["runs"])}{kpi("clip", "b", "접수된 주문", a["placed"])}
{kpi("alert", "r" if a["errors"] else "y", "오류", err)}<div class="kill">{kill}</div></div></div>
{top}{extra}
<div class="sec">계좌 바로가기</div><div class="nav">
<a href="{base}/accounts"><span class="tile">{ic("user")}</span><span>실계좌 요약<small>업비트·빗썸·KIS·RV20{reauth}</small></span></a>
<a href="{base}/details"><span class="tile">{ic("doc")}</span><span>기본 계좌 상세<small>보유·주문·원장{reauth}</small></span></a>
<a href="{base}/channels"><span class="tile">{ic("news")}</span><span>채널 소식<small>자이앤트·크립토·월가월부</small></span></a>
<a href="{base}/passkey"><span class="tile">{ic("key")}</span><span>패스키 관리<small>지문 등록·상태</small></span></a></div>
<div class="sec" id="today">기본 설정 <small>오늘 {E(v["day"])}</small></div>
<div class="card"><div class="hd"><h2>{mode_txt}</h2>{_ago(v, snap)}</div>
<div class="row"><span>실주문 게이트</span><span>{gates}</span></div>{gate_items}
{limits}
<div class="row"><span>위험 검사 거부(오늘)</span><span>{cnt("rejected")}</span></div></div>
<div class="card"><h2>최근 실행</h2>{recent or '<span class="mut">아직 실행 기록 없음</span>'}</div>'''
    return _page("autotrader", body, refresh=True, base=base, sub=mode_txt, tab="home")


def render_log(profiles: List[dict], base: str = "") -> bytes:
    """기록 탭 — 모든 프로필의 최근 실행(금액 없음 — 로그인만으로 보인다)."""
    rows = []
    for c in profiles:
        rdir = state_dir(c) / "runs"
        for p in (sorted(rdir.glob("*.json"))[-30:] if rdir.exists() else []):
            r = _load_json(p)
            if r:
                rows.append((str(r.get("at", "")), c, r))
    rows.sort(key=lambda x: x[0], reverse=True)
    html_rows = "".join(
        f'<div class="row"><span style="display:flex;gap:10px;align-items:center;color:var(--fg)">{_tile(c.get("strategy"))}'
        f'<span>{_strat_name(c)} <small class="mut">{E(str(c.get("profile", "")))}</small><br>'
        f'<small class="mut">{E(at[5:16].replace("T", " "))} · {"주문" if r.get("execute") else "dry-run"}</small></span></span>'
        f'<span style="text-align:right"><span class="pill {"ok" if r.get("status") == "ok" else "bad"}">{E(str(r.get("status")))}</span><br>'
        f'<small class="mut">접수 {len(r.get("placed") or [])} · 거부 {len(r.get("rejected") or [])} · 오류 {len(r.get("errors") or [])}</small></span></div>'
        for at, c, r in rows[:60])
    body = f'<h1>실행 기록</h1><div class="card">{html_rows or "<span class=mut>아직 실행 기록 없음</span>"}</div>'
    return _page("기록", body, base=base, sub="기록", tab="log")


def render_orders(profiles: List[dict], base: str = "") -> bytes:
    """주문 탭 — 프로필마다 우리가 낸 주문(원장)과 체결(스냅샷 체결 원장)·미체결. 재확인(지문) 뒤에만."""
    from .pnl import load_book
    items, opens, snaps = [], [], []
    for c in profiles:
        sdir = state_dir(c)
        snap = _load_json(sdir / "snapshot.json")
        snaps.append(snap)
        fills = ((load_book(c) or {}).get("fills")) or {}
        for r in Ledger(sdir).rows():
            if r.get("kind") in ("order", "error"):
                items.append((str(r.get("ts", "")), c, r, fills.get(r.get("orderNo") or "")))
        for m, d in ((snap or {}).get("markets") or {}).items():
            for o in d.get("openOrders") or []:
                opens.append((c, m, o))
    names = names_for(snaps)
    items.sort(key=lambda x: x[0], reverse=True)

    def side(sd):
        return f'<span class="side {"b" if sd == "BUY" else "s"}">{"매수" if sd == "BUY" else "매도"}</span>'

    def state(r, f):
        if r.get("kind") == "error":
            return '<span class="pill bad">실패</span>'
        if f and float(f.get("qty") or 0) >= float(r.get("qty") or 0):
            return '<span class="pill ok">체결</span>'
        if f and float(f.get("qty") or 0) > 0:
            return f'<span class="pill warn">일부 {E(str(f.get("qty")))}</span>'
        return '<span class="pill">접수</span>'
    rows = "".join(
        f'<div class="row"><span style="display:flex;gap:10px;align-items:center;color:var(--fg)">{side(r.get("side"))}'
        f'<span>{_sym(r.get("symbol"), names)}<small class="mut">{E(str(r.get("qty")))}주'
        f'{" · " + _px(r.get("market", "KR"), f["price"]) if f and f.get("price") else ""} · {_strat_name(c)}</small></span></span>'
        f'<span style="text-align:right">{state(r, f)}<br><small class="mut">{E(ts[5:16].replace("T", " "))}</small></span></div>'
        + (f'<div class="mut" style="margin:-4px 0 6px">{E(str(r.get("reason")))}</div>' if r.get("reason") else "")
        for ts, c, r, f in items[:80])
    ot = "".join(f'<div class="row"><span style="display:flex;gap:10px;align-items:center;color:var(--fg)">{side(o["side"])}{_sym(o["symbol"], names)}</span>'
                 f'<span class="mut">{E(str(o["remaining"]))}/{E(str(o["qty"]))} · {_px(m, o["price"])}</span></div>' for c, m, o in opens)
    body = (f'<h1>주문 · 거래 내역</h1><div class="sec">미체결</div><div class="card">{ot or "<span class=mut>없음</span>"}</div>'
            f'<div class="sec">주문 기록 <small>최근 80 · 체결은 5분마다 갱신</small></div><div class="card">{rows or "<span class=mut>아직 낸 주문이 없다</span>"}</div>')
    return _page("주문", body, base=base, sub="주문", tab="orders")


def render_settings(csrf: str, base: str, n_pk: int, pk_disabled: str) -> bytes:
    def item(icon, href, label, sub):
        return (f'<a class="row" href="{base}{href}" style="color:var(--fg)"><span style="display:flex;gap:12px;align-items:center;color:var(--fg)">'
                f'<span class="tile" style="width:40px;height:40px">{ic(icon)}</span><span>{label}<br><small class="mut">{sub}</small></span></span>'
                f'<span class="mut">{ic("chev")}</span></a>')
    pk = pk_disabled or f"등록 {n_pk}개 — 조작·금액 보기는 지문"
    body = f'''<h1>설정</h1><div class="card">
{item("key", "/passkey", "패스키(지문) 관리", E(pk))}
{item("user", "/accounts", "실계좌 요약", "업비트·빗썸·KIS·RV20 (재확인)")}
{item("doc", "/details", "기본 계좌 상세", "보유·주문·원장 (재확인)")}
{item("news", "/channels", "채널 소식", "매경 자이앤트·크립토·월가월부")}</div>
<div class="card mut">키·한도·허용 종목·전략 규칙은 서버의 프로필 파일에서만 바뀐다 — 웹이 뚫려도 손실 상한은 서버 한도다.</div>
<form method="post" action="{base}/logout"><input type="hidden" name="csrf" value="{E(csrf)}">
<button style="background:var(--bads);color:var(--bad);border:1px solid rgba(248,113,113,.4)">로그아웃</button></form>'''
    return _page("설정", body, base=base, sub="설정", tab="set")


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
    return _page(f"상세 · {title}" if title else "상세", body, refresh=False, base=base, sub=E(f"상세 · {title}" if title else "상세"), tab="strat")


PLAN_FIELDS = ("symbol", "entryLow", "entryHigh", "stop", "target", "riskPct", "validDays", "invalidation", "thesis", "tag")


def _spct(x) -> str:
    return "-" if x is None else f"{x:+.1f}%"


def _won(x) -> str:
    return "-" if x is None else f"{x:,.0f}"


def _plan_search(base: str, name: str, q: str, matches) -> str:
    rows = "".join(f'<div class="row"><a href="{base}/plans?p={quote(name)}&q={quote(code)}">{E(nm)}</a><span class="code">{E(code)}</span></div>'
                   for code, nm in (matches or []))
    none = '<div class="mut">찾는 종목이 없다 — 관심종목 국내만 조회된다</div>' if q and matches == [] else ""
    return f'''<div class="card"><h2>종목 조회</h2><form method="get" action="{base}/plans"><input type="hidden" name="p" value="{E(name)}">
<input name="q" value="{E(q)}" placeholder="종목명 또는 코드 (예: 삼성전자)" autocomplete="off"><button>조회</button></form>{rows}{none}</div>'''


_EPS_FLAGS = {
    "restated": "정정 재공시로 원본 EPS 가 없는 기간이 있다(그 구간 TTM 은 결측일 수 있다)",
    "split_uncertain": "액면분할 기준 판정이 약한 공시가 있다",
    "discontinued_ops": "중단영업 일회성 이익·손실이 총 EPS 에 섞인 기간이 있다(계속영업 기준으로 계산)",
    "eps_row_fallback": "주당이익 행 이름이 비표준이라 대체 규칙으로 읽었다",
}
_EPS_NONE = {"non_december_fy": "12월 결산이 아니라 분기 라벨을 다루지 않는다", "fy_unknown": "결산월을 몰라 계산하지 않았다",
             "no_corp": "DART 법인코드가 없다", "no_filings": "분기 공시를 아직 못 받았다(수집 중)",
             "quarter_gap": "최근 4개 분기가 다 모이지 않았다(정정 재공시로 4분기가 비는 경우 포함) — 지어내지 않는다"}


def _render_eps(e: Optional[dict]) -> str:
    """이익 대비 가격(EPS × PER) — 공시 EPS 로 계산한 값. 저평가·고평가 신호가 아니다."""
    h = '<h2 style="margin-top:12px">이익 대비 가격 (EPS × PER)</h2>'
    if not e or e.get("status") == "nofile":
        return h + '<div class="mut">분기 EPS 데이터가 아직 없다(수집 전)</div>'
    if e.get("status") == "pending":
        return h + f'<div class="mut">이 종목의 분기 EPS 를 아직 못 받았다 — 수집 중(남은 조회 {E(str(e.get("pending")))}건)</div>'
    if e.get("status") == "none":
        return h + f'<div class="mut">TTM PER 없음 — {E(_EPS_NONE.get(e.get("reason"), str(e.get("reason"))))}</div>'
    row = lambda a, b: f'<div class="row"><span>{a}</span><span>{b}</span></div>'   # noqa: E731
    eps = e["ttmEps"]
    if e.get("per"):
        per = f'{e["per"]:.1f}배'
    else:
        per = '<span class="mut">' + ("적자(EPS ≤ 0) — PER 없음" if e.get("perNote") == "loss" else "EPS 가 주가의 1% 미만 — 숫자가 의미 낮음") + "</span>"
    if e.get("perTotal"):
        per += f' <small class="mut">총 EPS(중단영업 포함) 기준 {e["perTotal"]:.1f}배</small>'
    per_range = (f'{e["periods"][0]} ~ {e["periods"][-1]}' if e.get("periods") else "-")
    ann = e.get("annual")
    ann_txt = ("-" if not ann else (f'FY{ann["fy"]} EPS {_won(ann["eps"])}원 → ' + (f'{ann["per"]:.1f}배' if ann.get("per") else "PER 없음")
                                    + ' <small class="mut">최대 12개월 묵은 값 — 비교용</small>'))
    rows = [row("TTM EPS (최근 4분기)", f'{_won(eps)}원 <small class="mut">{E(per_range)} · 최신 공시 {e["ageDays"]}일 전'
                + (f' · 총 EPS {_won(e["ttmEpsTotal"])}원' if e.get("ttmEpsTotal") is not None else "") + "</small>"),
            row("TTM PER (현재가 ÷ TTM EPS)", per), row("연간 EPS 기준 PER", ann_txt)]
    notes = "".join(f'<div class="warn">{E(_EPS_FLAGS[f])}</div>' for f in e.get("flags", []) if f in _EPS_FLAGS)
    ys = [y for y in e.get("yearly", []) if y.get("price")][-7:]
    tbl = ""
    if ys:
        body = ""
        for i, y in enumerate(ys):
            a = y.get("attr")
            if a:
                dec = (f'가격 {(math.exp(a["lnP"]) - 1) * 100:+.0f}% = EPS {(math.exp(a["lnEps"]) - 1) * 100:+.0f}% × PER {(math.exp(a["lnPer"]) - 1) * 100:+.0f}%')
            elif i == 0:
                dec = "<span class=mut>-</span>"
            elif y.get("ttmEps") is None:
                dec = "<span class=mut>TTM 결측(분기 공시 부족·정정 재공시) — 분해 없음</span>"
            elif y["ttmEps"] <= 0:
                dec = "<span class=mut>적자 — 분해 없음</span>"
            elif y.get("tiny"):
                dec = "<span class=mut>EPS 가 너무 작아 PER·분해 의미 낮음</span>"
            elif ys[i - 1].get("ttmEps") is None:
                dec = "<span class=mut>전 연말 TTM 결측 — 분해 없음</span>"
            elif ys[i - 1]["ttmEps"] <= 0:
                dec = "<span class=mut>전 연말이 적자 — 분해 없음</span>"
            else:
                dec = "<span class=mut>전 연말 EPS 가 너무 작아 분해 의미 낮음</span>"
            per_ = "-" if not y.get("per") else f'{y["per"]:.1f}'
            d_ = str(y["d"])
            label = d_ if not d_.isdigit() else d_[:4] + "-" + d_[4:6] + "-" + d_[6:]
            body += (f'<tr><td>{E(label)}</td><td class="n">{_won(y["price"])}</td>'
                     f'<td class="n">{"-" if y.get("ttmEps") is None else _won(y["ttmEps"])}</td><td class="n">{per_}</td>'
                     f'<td class="n">{"-" if not y.get("annPer") else format(y["annPer"], ".1f")}</td><td>{dec}</td></tr>')
        tbl = ('<details><summary class="mut">연말별 분해 — 가격 변화가 이익 증가인지 PER 재평가인지 (수정주가 · 공시된 TTM 기준)</summary>'
               '<div class="tw"><table><tr><th>기준일</th><th class="n">가격</th><th class="n">TTM EPS</th><th class="n">TTM PER</th><th class="n">연간 PER</th><th>전 연말 대비</th></tr>'
               f'{body}</table></div></details>')
    foot = ('<div class="mut" style="margin-top:6px">공시된 분기 EPS 의 합으로 계산한 값(기본 계속영업). 저평가·고평가 신호가 아니다 — 자기 과거 대비 밸류에이션 밴드는 시험에서 기각됐다. '
            f'공시 기준일 {E(str(e.get("asOf") or "-"))} · 데이터 갱신 {E(str(e.get("updatedAt") or "-")[:10])}</div>')
    return h + "".join(rows) + notes + tbl + foot


def render_card(card: Optional[dict]) -> str:
    """종목 분석 카드 — 참고 자료 + 규칙 계산값(검증 결과를 같이 적는다). 투자 자문 아님."""
    if not card:
        return ""
    from .stockcard import RULE_NOTE
    t, sc, lv = card.get("target"), card.get("score"), card.get("levels")
    row = lambda a, b: f'<div class="row"><span>{a}</span><span>{b}</span></div>'   # noqa: E731
    pbr = ("-" if card["pbr"] is None else f'{card["pbr"]:.2f}배'
           + ("" if card["pbrPct"] is None else f' <small class="mut">관심종목 중 낮은 순 {card["pbrPct"]:.0f}% 지점(0%=가장 쌈)</small>'))
    sec = ("-" if not card.get("sectorMedianPbr") else
           f'{E(str(card["sector"]))} 중앙 {card["sectorMedianPbr"]:.2f}배 ({card["sectorPeers"]}종목) → 그 PBR 이면 {_won(card["sectorFairPrice"])}원 <small class="mut">검증 안 된 참고치</small>')
    lvl = (f'''<h2 style="margin-top:12px">규칙 계산값</h2>
{row("진입 구간", f"{_won(lv['entryLow'])} ~ {_won(lv['entryHigh'])}")}
{row("손절가", f"<span class=dn>{_won(lv['stop'])}</span> <small class=mut>{_spct(lv['stopPct'])}</small>")}
{row("목표가", f"<span class=up>{_won(lv['target'])}</span> <small class=mut>{_spct(lv['targetPct'])}</small>")}
<div class="mut" style="margin-top:6px">{E(RULE_NOTE)}</div>''' if lv else '<div class="warn">ATR 을 몰라 손절·목표를 계산하지 않았다(지어내지 않는다)</div>')
    return f'''<div class="card hl"><div class="hd"><h2>{E(card["name"])} <span class="code">{E(card["code"])}</span></h2>
<span class="mut">{E(card["priceSrc"])}</span></div>
<div class="kpis">{_kpi("현재가", _won(card["price"]) + "원", _spct(card["chg1d"]) + " 오늘")}
{_kpi("1주 · 1달", _spct(card["chg1w"]) + " · " + _spct(card["chg1m"]))}
{_kpi("52주 위치", "-" if card["pos52"] is None else f'{card["pos52"]:.0f}%', f'{_won(card["lo52"])} ~ {_won(card["hi52"])}')}
{_kpi("하루 평균 변동폭(ATR14)", _won(card["atr"]) + "원", "-" if card["atrPct"] is None else f'{card["atrPct"]:.1f}%')}</div>
{row("20일선 · 60일선", f"{_won(card['ma20'])} · {_won(card['ma60'])}")}
{row("PBR", pbr)}
{row("업종 PBR 기준", sec)}
{_render_eps(card.get("eps"))}
{row("PBR 전략(모의) 보유", "<span class=ok>보유 중 — 이번 달 편입 조건 충족</span>" if card["pbrSleeve"] else "<span class=mut>아님</span>")}
{row("증권사 목표가", f"{_won(t['median'])} <small class=mut>중앙값 · {t['brokers']}개사 · {E(str(t['lastDate']))}</small>" if t else "<span class=mut>없음</span>")}
{row("우리 점수", f"{sc['total']} · {E(str(sc['grade']))}" if sc and sc.get("total") is not None else "<span class=mut>-</span>")}
<div class="mut">일봉 기준일 {E(card["dailyAsOf"])} · ATR 기준일 {E(str(card.get("atrAsOf") or "-"))} · 뉴스·목표가·점수는 맥락일 뿐 매매 신호가 아니다</div>
{lvl}</div>'''


def _plan_form(base: str, hid: str, cap, card: Optional[dict], vals: Optional[dict], notes) -> str:
    """입력 폼. 값 우선순위: 미리보기로 돌아온 입력 > 카드의 규칙 계산값 > 빈칸. '미리보기'는 저장하지 않고 점검만 보여 준다."""
    v = dict(vals or {})
    if not vals and card:
        v["symbol"] = card["code"]
        for k in ("entryLow", "entryHigh", "stop", "target"):
            if card.get("levels"):
                v[k] = str(card["levels"][k])
    val = lambda k, d="": E(str(v.get(k) or d))   # noqa: E731
    nts = "".join(f'<div class="{"warn" if lvl == "warn" else "mut"}">· {E(t)}</div>' for lvl, t in (notes or []))
    return f'''<div class="card"><h2>새 계획</h2><div class="mut">자본 {"미설정 — 프로필 params.capital" if not cap else f"{float(cap):,.0f}원"} ·
수량은 (자본 × 1회 손실 %) ÷ (진입 상단 − 손절). 진입 구간에 들어오면 시장가로 사고, 손절·목표에 닿으면 시장가로 판다(5분마다 점검, 장중만).</div>
{('<h2 style="margin-top:10px">점검</h2>' + nts) if nts else ""}
<form method="post" action="{base}/plans" class="pf">{hid}
<label>종목코드</label><input name="symbol" value="{val("symbol")}" placeholder="종목코드 6자리 (허용 종목만)" maxlength="6" required autocomplete="off">
<label>진입 하단 · 상단</label><input name="entryLow" value="{val("entryLow")}" placeholder="진입 하단" inputmode="decimal" required><input name="entryHigh" value="{val("entryHigh")}" placeholder="진입 상단(비우면 하단과 같게)" inputmode="decimal">
<label>손절가</label><input name="stop" value="{val("stop")}" placeholder="손절가" inputmode="decimal" required><label>목표가</label><input name="target" value="{val("target")}" placeholder="목표가" inputmode="decimal" required>
<label>1회 손실 한도 % (자본 대비)</label><input name="riskPct" value="{val("riskPct", "1")}" placeholder="1회 손실 한도 %(자본 대비)" inputmode="decimal" required>
<label>진입 대기 일수</label><input name="validDays" value="{val("validDays", "14")}" placeholder="진입 대기 일수" inputmode="numeric">
<label>무효 조건 · 근거 · 분류 (선택)</label><input name="invalidation" value="{val("invalidation")}" placeholder="무효 조건(이게 깨지면 계획을 버린다)" maxlength="200">
<input name="thesis" value="{val("thesis")}" placeholder="근거 한 줄" maxlength="200"><input name="tag" value="{val("tag")}" placeholder="분류(돌파·눌림·실적 …)" maxlength="20">
<button name="op" value="preview" class="ghost">미리보기 (저장 안 함)</button><button name="op" value="new">계획 저장</button></form></div>'''


def render_plans(c: dict, sdir: Path, csrf: str, base: str = "", msg: str = "", q: str = "", matches=None,
                 card: Optional[dict] = None, vals: Optional[dict] = None, notes=None) -> bytes:
    """직접매매 계획 카드(plan_trader 프로필) — 입력 폼·진행 중·종료(R 배수)·통계. 재확인(지문) 뒤에만 불린다."""
    from .plans import (CLOSED, MIN_SAMPLE, MIN_TAG_SAMPLE, STATUS_KO, fills_by_plan, load_plans, outcome,
                        reward_risk, summarize)
    from .pnl import load_book
    name = str(c.get("profile", ""))
    plans = load_plans(sdir)
    st = ((_load_json(Path(sdir) / "strategy_plan_trader.json") or {}).get("plans")) or {}
    fb = fills_by_plan(Ledger(sdir).rows(), load_book(c))
    names = names_for([_load_json(Path(sdir) / "snapshot.json")])
    hid = f'<input type="hidden" name="csrf" value="{E(csrf)}"><input type="hidden" name="p" value="{E(name)}">'

    def btn(pid, op, label):
        return (f'<form method="post" action="{base}/plans" style="margin:0">{hid}<input type="hidden" name="op" value="{op}">'
                f'<input type="hidden" name="id" value="{E(pid)}"><button class="ghost" style="padding:6px;margin:2px 0">{label}</button></form>')

    act, done, rs, tags = [], [], [], {}
    for p in reversed(plans):
        s = st.get(p["id"]) or {"status": "wait"}
        status = s.get("status", "wait")
        rr = reward_risk((p["entryLow"] + p["entryHigh"]) / 2, p["stop"], p["target"])
        head = (f'<td>{_sym(p["symbol"], names)}<small class="mut">{E(p.get("tag") or "")}</small></td>'
                f'<td>{E(STATUS_KO.get(status, status))}</td>')
        if status in CLOSED:
            o = outcome(p, fb.get(p["id"], {}))
            if o["R"] is not None:
                rs.append(o["R"])
                tags.setdefault(p.get("tag") or "(없음)", []).append(o["R"])
            done.append(f'<tr>{head}<td class="n">{_px("KR", o["entry"]) if o["entry"] else "-"} → {_px("KR", o["exit"]) if o["exit"] else "-"}'
                        f'<br><small class="mut">{E(str(s.get("exitReason") or ""))}</small></td>'
                        f'<td class="n {_sign_cls(o["R"])}">{"-" if o["R"] is None else format(o["R"], "+.2f") + "R"}</td></tr>')
            continue
        req = "취소 요청됨" if p.get("cancel") else ("청산 요청됨" if p.get("closeReq") else "")
        ctl = (f'<span class="warn">{req}</span>' if req else
               btn(p["id"], "cancel", "취소") if status == "wait" else
               btn(p["id"], "close", "지금 청산") if status in ("held", "exiting") else "")
        act.append(f'<tr>{head}<td class="n">{p["entryLow"]:,.0f}~{p["entryHigh"]:,.0f}<br><small class="mut">손절 {p["stop"]:,.0f} · 목표 {p["target"]:,.0f}</small></td>'
                   f'<td class="n">{p["qty"]}주<br><small class="mut">손익비 {"-" if rr is None else "1:" + format(rr, ".2f")} · ~{E(p["validUntil"][5:])}</small></td>'
                   f'<td>{ctl}</td></tr>'
                   + (f'<tr><td colspan=5 class="mut">무효: {E(p["invalidation"])}</td></tr>' if p.get("invalidation") else ""))
    sm = summarize(rs)
    if sm["n"]:
        f2 = lambda x: "-" if x is None else format(x, "+.2f")     # noqa: E731
        n, short = sm["n"], ("" if sm["enough"] else f"표본 부족 {sm['n']}/{MIN_SAMPLE}")
        stat = (f'<div class="kpis">{_kpi("종료(체결 확인)", str(n) + "건")}{_kpi("승률", format(sm["winRate"] * 100, ".0f") + "%")}'
                f'{_kpi("기대값", f2(sm["expectancy"]) + "R", short)}'
                f'{_kpi("평균 이익 / 손실", f2(sm["avgWin"]) + " / " + f2(sm["avgLoss"]))}</div>'
                f'<div class="row"><span>−1R 보다 크게 잃은 건(손절 밀림·갭)</span><span>{sm["worseThan1R"]}</span></div>'
                + "".join(f'<div class="row"><span>{E(t)} <small class="mut">n={len(v)}{"" if len(v) >= MIN_TAG_SAMPLE else " · 비교 불가"}</small></span>'
                          f'<span>{f2(sum(v) / len(v))}R</span></div>' for t, v in sorted(tags.items())))
    else:
        stat = '<span class="mut">아직 체결로 끝난 계획이 없다</span>'
    cap = (c.get("params") or {}).get("capital")
    search_html, card_html, form_html = _plan_search(base, name, q, matches), render_card(card), _plan_form(base, hid, cap, card, vals, notes)
    m = f'<div class="warn">{E(msg)}</div>' if msg else ""
    body = f'''<h1>매매 계획 · {E(name)} <span class="pill">모의</span></h1>{m}
{search_html}{card_html}{form_html}
<div class="card"><h2>진행 중</h2><div class="tw"><table><tr><th>종목</th><th>상태</th><th class="n">진입 · 손절/목표</th><th class="n">수량</th><th></th></tr>
{"".join(act) or "<tr><td colspan=5 class=mut>없음</td></tr>"}</table></div></div>
<div class="card"><h2>결과 <span class="mut">실제 체결가 기준 R 배수</span></h2>{stat}
<div class="mut" style="margin-top:6px">종료 {MIN_SAMPLE}건 전에는 기대값으로 판단하지 않는다 · 태그별 비교는 {MIN_TAG_SAMPLE}건부터 · 계획을 적은 매매만 센다.</div>
<div class="tw"><table><tr><th>종목</th><th>상태</th><th class="n">진입 → 청산</th><th class="n">R</th></tr>{"".join(done[:50]) or "<tr><td colspan=4 class=mut>없음</td></tr>"}</table></div></div>
<a class="btn" href="{base}/details?p={quote(name)}">← 프로필 상세</a>'''
    return _page(f"매매 계획 · {name}", body, base=base, sub="매매 계획", tab="strat")


def is_live_order(c: dict, op: str) -> bool:
    """실계좌 주문으로 이어질 수 있는 조작 — 주문 켜기, 주문 상태의 지금 실행, 킬 해제(M2: 해제하면 예약 주문이 다시 나간다)."""
    return c.get("mode") == "live" and (op in ("auto-execute", "resume") or (op == "run" and c.get("auto") == "execute"))


def _fetch_intraday() -> dict:
    import urllib.request
    with urllib.request.urlopen(KR_INTRADAY_URL, timeout=3) as r:     # 127.0.0.1 고정
        return json.loads(r.read().decode("utf-8"))


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
    return _page("실계좌 요약", body, base=base, sub="실계좌 요약", tab="home")


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
    return _page("패스키", body, base=base, sub="패스키", tab="set")


def render_channels(d: Optional[dict], want: str, base: str = "") -> bytes:
    """텔레그램 채널 소식(개인 열람 — 로그인 뒤에만). 글자는 전부 이스케이프, 원문은 t.me 링크."""
    from .channels import CHANNELS
    posts = [p for p in (d or {}).get("posts") or [] if not want or p.get("channel") == want][:150]
    tabs = "".join(f'<a class="pill{" acc" if k == want else ""}" href="{base}/channels{("?c=" + quote(k)) if k else ""}">{E(v)}</a>'
                   for k, v in [("", "전체")] + list(CHANNELS.items()))
    items = []
    for p in posts:
        try:
            when = datetime.fromisoformat(p["at"]).astimezone(KST).strftime("%m-%d %H:%M")
        except (KeyError, ValueError):
            when = ""
        text = str(p.get("text") or "") or "(사진·영상)"
        head, rest = text[:280], text[280:]
        br = lambda s: E(s).replace(chr(10), "<br>")   # noqa: E731
        body = br(head) + (f'<details><summary>더 보기</summary>{br(rest)}</details>' if rest else "")
        items.append(f'<div class="card"><div class="hd"><span class="pill">{E(CHANNELS.get(p.get("channel"), p.get("channel", "")))}</span>'
                     f'<span class="mut">{E(when)}</span></div><div>{body}</div>'
                     f'<a class="mut" href="https://t.me/{quote(str(p.get("id", "")))}" target="_blank" rel="noopener noreferrer">원문 ↗</a></div>')
    errs = "".join(f'<div class="warn">{E(CHANNELS.get(k, k))}: 읽기 실패 — {E(v)}</div>' for k, v in ((d or {}).get("errors") or {}).items())
    upd = E(str((d or {}).get("updatedAt", ""))[5:16].replace("T", " ")) or "아직 없음"
    body = (f'<h1>채널 소식</h1><div>{tabs}</div><div class="mut">갱신 {upd} · 15분마다 · 개인 열람용(공유 금지)</div>{errs}'
            + ("".join(items) or '<div class="card mut">아직 읽은 글이 없습니다.</div>') + f'<a class="btn" href="{base}/">← 요약으로</a>')
    return _page("채널 소식", body, base=base, sub="채널 소식", tab="set")


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
                 accounts_fetch: Optional[Callable[[], dict]] = None, rp_id: str = "", origin: str = "",
                 intraday_fetch: Optional[Callable[[], dict]] = None, data_root: Optional[Path] = None):
        self.cfg, self.sdir, self.store = cfg, Path(sdir), store
        self.sessions, self.lockout, self.clock = sessions, lockout, clock
        self.secure_cookie, self.fail_delay, self._sleep = secure_cookie, fail_delay, sleep
        self.base = "/" + base.strip("/") if base.strip("/") else ""      # 예: "/autotrader" (앞단이 이 접두사 아래로 넘겨준다)
        self.require_reauth = require_reauth                              # True 면 상세를 볼 때마다 인증앱 코드를 다시 묻는다
        self.log_path = self.sdir / "web_login.log"
        self._msgs: set = set()
        self._auth_lock = threading.Lock()
        self.fetch_accounts = accounts_fetch or _fetch_accounts
        self.fetch_intraday = intraday_fetch or _fetch_intraday
        self.data_root = data_root                                        # 종목 카드 데이터(저장소 루트). None = 기본
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
                         f'<div id="pk-reauth-msg"></div>' if self._pk_ready()
                         else f'<a class="btn" href="{self.base}/details">인증앱 코드로 확인</a>') + '</div>') if locked else ""
            from .stockcard import _load as _load_repo
            profs = self.profiles()
            pk = self._pk_ready()
            js = f'<script src="{E(self.base)}/static/passkey.js"></script>' if pk else ""   # 한 번만 — 두 번 실으면 버튼마다 지문이 두 번 뜬다
            server_on, srv = server_state(self.sdir, now)
            base_v = load_view(self.cfg, self.sdir, now)
            views = [(c, load_view(c, state_dir(c), now)) for c in profs]
            allv = [base_v] + [pv for _, pv in views]
            n = lambda k: sum(len(r.get(k) or []) for x in allv for r in x["todayRuns"])   # noqa: E731
            agg = {"runs": sum(len(x["todayRuns"]) for x in allv), "placed": n("placed"), "errors": n("errors"),
                   "kill": any(x["kill"] for x in allv)}
            extra = unlock + js + render_profiles(views, self.base, hide_money=locked, csrf=sess["csrf"], pk=pk, server_on=server_on)
            return 200, self._hdrs(), render_dashboard(base_v, sess["csrf"], self.base, self.require_reauth, extra,
                                                       server_card(srv), agg)
        if not sess:                                    # 로그인 전에는 나머지 경로가 존재하지 않는 것처럼
            return self._not_found()
        if method == "GET" and path == "/strategies":
            from .stockcard import _load as _load_repo
            pk = self._pk_ready()
            pe = _load_repo("ui/data/positions.json", *([self.data_root] if self.data_root else []))
            body = (render_switches(self.profiles(), self.sdir, sess["csrf"], self.base, self._now(), pk, pe)
                    + (f'<script src="{E(self.base)}/static/passkey.js"></script>' if pk else ""))
            return 200, self._hdrs(), _page("전략", body, base=self.base, sub="전략", tab="strat")
        if method == "GET" and path == "/log":
            return 200, self._hdrs(), render_log(self.profiles(), self.base)
        if method == "GET" and path == "/orders":
            if self.require_reauth and not self.sessions.is_fresh(sess):
                return 200, self._hdrs(), render_reauth(sess["csrf"], base=self.base, pk=self._pk_ready(), nxt="/orders")
            return 200, self._hdrs(), render_orders(self.profiles(), self.base)
        if method == "GET" and path == "/settings":
            return 200, self._hdrs(), render_settings(sess["csrf"], self.base, len(self._passkeys()), self._pk_disabled())
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
        if method == "GET" and path == "/channels":
            from .channels import CHANNELS
            want = (parse_qs(urlsplit(raw_path).query).get("c") or [""])[0]
            want = want if want in CHANNELS else ""        # 목록에 있는 채널만
            return 200, self._hdrs(), render_channels(_load_json(self.sdir / "channels.json"), want, self.base)
        if path == "/plans":
            return self._plans(method, raw_path, sess, field, ip)
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

    # -------------------------------------------------------------- 매매 계획(plan_trader 프로필만)
    def _plans(self, method, raw_path, sess, field, ip):
        """보기·입력 모두 재확인(지문) 5분 안에서만. 웹은 plans.json 만 쓴다 — 주문은 run-due 가 엔진 검사를 거쳐 낸다."""
        from .plans import CLOSED, build_plan, load_plans, save_plans
        q = parse_qs(urlsplit(raw_path).query)
        name = field("p") if method == "POST" else (q.get("p") or [""])[0]
        match = [c for c in self.profiles() if c.get("profile") == name and c.get("strategy") == "plan_trader"]
        if not match:
            return self._not_found()
        c = match[0]
        url = f"/plans?p={quote(name)}"
        if method == "POST" and field("csrf") != sess["csrf"]:
            self._log(ip, "csrf-fail")
            return 403, self._hdrs(), _page("403", "<h1>요청이 거부됨</h1>")
        if self.require_reauth and not self.sessions.is_fresh(sess):
            return 200, self._hdrs(), render_reauth(sess["csrf"], "확인 5분이 지났습니다 — 다시 확인 뒤 입력하세요" if method == "POST" else "",
                                                    base=self.base, pk=self._pk_ready(), nxt=url)
        sdir = state_dir(c)
        if method == "GET":
            msg = (q.get("m") or [""])[0]
            qs = (q.get("q") or [""])[0].strip()[:30]
            matches = self._search(qs) if qs else None
            card = self._card(matches[0][0]) if matches and len(matches) == 1 else None
            return 200, self._hdrs(), render_plans(c, sdir, sess["csrf"], self.base, msg if msg in self._msgs else "",
                                                   qs, None if card else matches, card)
        op, plans = field("op"), load_plans(sdir)
        if op == "preview":                             # 저장하지 않고 점검만 — 같은 폼을 값 그대로 다시 그린다
            from .stockcard import checks
            vals = {k: field(k) for k in PLAN_FIELDS}
            card = self._card(vals["symbol"].strip().upper())
            plan, why = build_plan(vals, c, self._now(), 0)
            notes = [("warn", why)] if why else [("info", f"수량 {plan['qty']}주 · 금액 약 {plan['qty'] * plan['entryHigh']:,.0f}원 · 손익비 1:"
                                                          f"{(plan['target'] - plan['entryHigh']) / (plan['entryHigh'] - plan['stop']):.2f}"
                                                          f" · 손절 시 약 −{plan['qty'] * (plan['entryHigh'] - plan['stop']):,.0f}원")]
            if plan:
                notes += checks(card, plan["entryLow"], plan["entryHigh"], plan["stop"], plan["target"])
            return 200, self._hdrs(), render_plans(c, sdir, sess["csrf"], self.base, "", "", None, card, vals, notes)
        if op == "new":
            st = ((_load_json(sdir / "strategy_plan_trader.json") or {}).get("plans")) or {}
            active = sum(1 for p in plans if (st.get(p["id"]) or {}).get("status", "wait") not in CLOSED)
            plan, msg = build_plan({k: field(k) for k in PLAN_FIELDS}, c, self._now(), active)
            if plan:
                from .stockcard import context_for_plan
                plan["context"] = context_for_plan(self._card(plan["symbol"]))       # 30건 뒤 내 데이터로 규칙을 보려고
                save_plans(sdir, plans + [plan])
                msg = f"계획을 저장했습니다 — {plan['symbol']} {plan['qty']}주, 다음 점검(5분, 장중)부터 봅니다"
        elif op in ("cancel", "close"):
            hit = [p for p in plans if p["id"] == field("id")]
            if not hit:
                return self._not_found()
            hit[0]["cancel" if op == "cancel" else "closeReq"] = True
            save_plans(sdir, plans)
            msg = "취소를 요청했습니다(진입 전일 때만)" if op == "cancel" else "청산을 요청했습니다 — 다음 점검에서 시장가로 팝니다(장중)"
        else:
            return self._not_found()
        self._log(ip, f"action:{name}:plan-{op}")
        self._msgs.add(msg)
        return self._redirect(f"{url}&m={quote(msg)}")

    # -------------------------------------------------------------- 조작(요청 파일만 쓴다 — 주문은 키를 가진 run-due 가 낸다)
    def _search(self, qs: str):
        from .stockcard import search
        return search(qs, **({"root": self.data_root} if self.data_root else {}))

    def _card(self, code: str) -> Optional[dict]:
        """종목 카드. 장중 현재가는 오늘 날짜 스냅샷일 때만 쓴다 — 못 가져오면 종가로(화면에 어느 쪽인지 적힌다)."""
        from .stockcard import build_card
        try:
            intra = self.fetch_intraday()
            intra = intra if str(intra.get("date")) == self._now().strftime("%Y%m%d") else None
        except Exception:                               # noqa: BLE001 — 장 밖·API 없음이면 종가 기준
            intra = None
        try:
            return build_card(code, intra, **({"root": self.data_root} if self.data_root else {}))
        except Exception:                               # noqa: BLE001 — 데이터 파일이 깨져도 계획 화면은 뜬다
            return None

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
            if self.lockout.is_locked(ip, include_global=False):
                return self._json(429, {"error": "잠시 후 다시 시도하세요"})
            try:
                cid, count = passkey_auth_verify(json.dumps(j.get("credential")), pend["chal"], self.rp_id, self.origin,
                                                 self._passkeys())
            except Exception:                           # noqa: BLE001
                self.lockout.fail(ip, count_global=False)
                self._log(ip, "reauth-fail")
                return self._json(401, {"error": "패스키 확인 실패"})
            self.lockout.ok(ip)
            self._bump(cid, count)
            self.sessions.mark_reauth(tok)
            self._log(ip, "reauth-ok")
            ok_next = ({"/", "/accounts", "/details", "/orders"} | {f"/details?p={quote(str(c.get('profile', '')))}" for c in self.profiles()}
                       | {f"/plans?p={quote(str(c.get('profile', '')))}" for c in self.profiles() if c.get("strategy") == "plan_trader"})
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
            if self.lockout.is_locked(ip, include_global=False):
                return self._json(429, {"error": "잠시 후 다시 시도하세요"})
            stored = self._passkeys()
            try:
                cid, count = passkey_auth_verify(json.dumps(j.get("credential")), pend["chal"], self.rp_id, self.origin, stored)
            except Exception:                           # noqa: BLE001
                self.lockout.fail(ip, count_global=False)
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
