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
from .web_auth import (AuthStore, Lockout, Sessions, passkey_auth_options, passkey_auth_verify, passkey_available,
                       passkey_reg_options, passkey_reg_verify, totp_verify, verify_password)

KST = timezone(timedelta(hours=9))
COOKIE = "at_sess"
ACCOUNTS_URL = "http://127.0.0.1:8766/accounts"   # 같은 VM 의 실계좌 요약 API. 2026-09-22 부터 인터넷에는 닫고(nginx) 여기서만 보여 준다
LIVE_PHRASE = "실계좌주문"      # 실계좌 주문 켜기·실행 때 입력하는 확인 문구(실수 클릭 방지 — 보안은 인증앱 코드와 서버 한도가 맡는다)
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


def _money(m: str, x) -> str:
    if x is None:
        return "-"
    return f"${x:,.2f}" if m == "US" else f"{x:,.0f}원"


def _pnl_html(m: str, t: dict) -> str:
    if not t or t.get("pnl") is None:
        return '<span class="mut">현재가 없음</span>'
    cls = "ok" if t["pnl"] >= 0 else "bad"
    pct = f' ({t["pnlPct"]:+.2f}%)' if t.get("pnlPct") is not None else ""
    return f'<span class="{cls}">{"+" if t["pnl"] >= 0 else ""}{_money(m, t["pnl"])}{pct}</span>'


def render_money_rows(snap: Optional[dict]) -> str:
    out = []
    rz = (snap or {}).get("realized") or {}
    for m, d in ((snap or {}).get("markets") or {}).items():
        t = d.get("totals")
        if not t:
            continue
        out.append(f'<div class="row"><span>{E(m)} 투자금(원가) · 평가</span><span>{_money(m, t["cost"])} · {_money(m, t["value"])}</span></div>'
                   f'<div class="row"><span>{E(m)} 평가손익(보유분)</span>{_pnl_html(m, t)}</div>')
        if "realized" in (snap or {}):
            r = rz.get(m) or {"realized": 0.0, "incomplete": False}
            cls = "ok" if r["realized"] >= 0 else "bad"
            warn = ' <span class="warn">(원가 모르는 매도 있음)</span>' if r["incomplete"] else ""
            out.append(f'<div class="row"><span>{E(m)} 실현손익(수수료·세금 전)</span><span class="{cls}">'
                       f'{"+" if r["realized"] >= 0 else ""}{_money(m, r["realized"])}{warn}</span></div>')
    if (snap or {}).get("realizedError"):
        out.append(f'<div class="row"><span>실현손익</span><span class="warn">체결 조회 실패 — 다음 갱신에 다시</span></div>')
    return "".join(out)


def render_sells(snap: Optional[dict]) -> str:
    rows = []
    for m, r in ((snap or {}).get("realized") or {}).items():
        for x in reversed(r.get("sells", [])[-30:]):
            cls = "ok" if x["pnl"] >= 0 else "bad"
            rows.append(f'<tr><td>{E(str(x.get("day", "")))}</td><td>{E(x["symbol"])}</td><td>{E(str(x["qty"]))}</td>'
                        f'<td>{x["avg"]:,.2f} → {x["price"]:,.2f}</td><td class="{cls}">{_money(m, x["pnl"])}</td></tr>')
    if "realized" not in (snap or {}):
        return ""
    return ('<div class="card"><h2>실현손익 내역(매도 체결, 최근 30)</h2><table><tr><th>날짜</th><th>종목</th><th>수량</th>'
            '<th>평단 → 체결가</th><th>손익</th></tr>' + ("".join(rows) or "<tr><td colspan=5 class=mut>아직 매도 체결 없음</td></tr>")
            + "</table></div>")


def render_profiles(items: List[Tuple[dict, dict]], base: str = "") -> str:
    # 프로필(키 묶음+전략)마다 한 장. 금액·종목은 없다 — 상세 링크에서 본다.
    out = []
    for cfg, v in items:
        name = str(cfg.get("profile", ""))
        snap = v["snapshot"]
        if snap:
            age = (v["now"] - datetime.fromisoformat(snap["at"])).total_seconds()
            snap_txt = f'<span class="{"warn" if age > SNAPSHOT_STALE_SEC else "ok"}">{int(age // 60)}분 전</span>'
        else:
            snap_txt = '<span class="warn">없음</span>'
        t = v["todayRuns"]
        cnt = lambda k: sum(len(r.get(k) or []) for r in t)   # noqa: E731
        last = v["runs"][-1] if v["runs"] else None
        last_txt = (f'<span class="{"ok" if last.get("status") == "ok" else "bad"}">{E(str(last.get("at", ""))[5:16].replace("T", " "))}'
                    f' {E("주문" if last.get("execute") else "dry-run")} {E(str(last.get("status")))}</span>') if last else '<span class="mut">-</span>'
        auto = cfg.get("auto", "off")
        auto_cls = {"execute": "bad", "dry": "ok"}.get(auto, "mut")
        out.append(f'''<div class="card"><h2>{E(name)}</h2>
<span class="pill">{E(str(cfg.get("strategy")))}</span><span class="pill">{"실전" if cfg.get("mode") == "live" else "모의"}</span>
<span class="pill {auto_cls}">자동 {E({"off": "꺼짐", "dry": "dry-run", "execute": "주문"}.get(auto, auto))} {E(",".join(cfg.get("run_at") or []))}</span>
{'<span class="pill bad">킬 ON</span>' if v["kill"] else ""}
<div class="row"><span>상태 조회</span>{snap_txt}</div>
{render_money_rows(snap)}
<div class="row"><span>오늘 실행 · 접수 · 오류</span><span>{len(t)} · {cnt("placed")} · <span class="{"bad" if cnt("errors") else ""}">{cnt("errors")}</span></span></div>
<div class="row"><span>마지막 실행</span>{last_txt}</div>
<a href="{base}/details?p={quote(name)}">상세 보기</a></div>''')
    return ("<h1 style='margin-top:20px'>프로필</h1>" + "".join(out)) if out else ""


def render_dashboard(v: dict, csrf: str, base: str = "", strict: bool = False, extra: str = "") -> bytes:
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
<div class="card"><a href="{base}/accounts">실계좌 요약 (업비트·빗썸·KIS·RV20){" (인증앱 코드 재입력)" if strict else ""}</a></div>
<div class="card"><a href="{base}/passkey">🔑 패스키(지문) 관리</a></div>
{extra}
<form method="post" action="{base}/logout"><input type="hidden" name="csrf" value="{E(csrf)}"><button>로그아웃</button></form>'''
    return _page("autotrader", body, refresh=True)


def render_controls(cfg: dict, csrf: str, base: str, msg: str = "", has_pk: bool = False) -> str:
    """프로필 조작 폼. 킬 켜기만 코드 없이. 모의는 인증앱 코드, **실계좌의 주문 켜기·실행·킬 해제는 패스키로만**
    (2026-09-22 보안 검토 M2·M3·M4 — 피싱된 인증앱 코드로는 실계좌 주문에 닿지 않는다)."""
    name = str(cfg.get("profile", ""))
    live = cfg.get("mode") == "live"
    web_live = live and bool(cfg.get("web_live_allowed"))
    opts = [("auto-off", "자동 끄기"), ("auto-dry", "자동 dry-run (주문 없이 계획만)")]
    if not live:
        opts += [("auto-execute", "자동 주문 켜기 (모의투자)"), ("run", "지금 한 번 실행 (현재 자동 설정대로, 5분 안에)"),
                 ("resume", "킬 스위치 해제")]
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
    pk_form = ""
    if live and has_pk:
        pk_ops = ('<option value="auto-execute">⚠ 실계좌 자동 주문 켜기</option><option value="run">⚠ 실계좌 지금 한 번 실행</option>'
                  if web_live else "") + '<option value="resume">실계좌 킬 스위치 해제</option>'
        pk_form = f'''<form id="pk-action" data-base="{E(base)}" data-csrf="{E(csrf)}" data-profile="{E(name)}" style="margin-top:10px">
<h2>🔑 실계좌 (패스키)</h2><select name="op">{pk_ops}</select>
<input name="phrase" placeholder="확인 문구: {E(LIVE_PHRASE)}" autocomplete="off" required>
<button>패스키(지문)로 확인</button><div id="pk-action-msg"></div></form>
<script src="{E(base)}/static/passkey.js"></script>'''
    return f'''<div class="card"><h2>조작</h2>{m}
<div class="row"><span>지금 자동 설정</span><span>{E({"off": "꺼짐", "dry": "dry-run", "execute": "주문"}.get(cfg.get("auto"), str(cfg.get("auto"))))} {E(",".join(cfg.get("run_at") or []))}</span></div>
<form method="post" action="{base}/action"><input type="hidden" name="csrf" value="{E(csrf)}"><input type="hidden" name="p" value="{E(name)}">
<select name="op">{sel}</select>
<input name="code" placeholder="인증앱 6자리 코드(새 코드)" inputmode="numeric" autocomplete="one-time-code" maxlength="7" required>
<button>적용</button></form>{note}
<form method="post" action="{base}/action" style="margin-top:10px"><input type="hidden" name="csrf" value="{E(csrf)}"><input type="hidden" name="p" value="{E(name)}">
<input type="hidden" name="op" value="kill"><button style="background:var(--bad)">킬 스위치 켜기 (코드 없이 즉시 — 주문 중단)</button></form>{pk_form}</div>'''


def render_details(v: dict, csrf: str, base: str = "", strict: bool = False, title: str = "", controls: str = "") -> bytes:
    snap = v["snapshot"] or {}
    rows = []
    for m, d in (snap.get("markets") or {}).items():
        if d.get("error"):
            rows.append(f'<div class="card"><h2>{E(m)}</h2><span class="bad">{E(str(d["error"]))}</span></div>')
            continue
        def prow(p):
            px = p.get("price") or 0
            pnl = (px - p["avgPrice"]) * p["qty"] if px else None
            pc = (px / p["avgPrice"] - 1) * 100 if px and p["avgPrice"] else None
            cls = "" if pnl is None else ("ok" if pnl >= 0 else "bad")
            return (f'<tr><td>{E(str(p["symbol"]))}</td><td>{E(str(p["qty"]))}</td><td>{p["avgPrice"]:,.2f}</td>'
                    f'<td>{f"{px:,.2f}" if px else "-"}</td><td class="{cls}">{"-" if pnl is None else f"{pnl:+,.2f}"}'
                    f'{"" if pc is None else f" ({pc:+.1f}%)"}</td></tr>')
        pos = "".join(prow(p) for p in d.get("positions", []))
        oo = "".join(f'<tr><td>{E(str(o["symbol"]))}</td><td>{E(str(o["side"]))}</td><td>{E(str(o["remaining"]))}/{E(str(o["qty"]))}</td>'
                     f'<td>{o["price"]:,.2f}</td></tr>' for o in d.get("openOrders", []))
        cash = d.get("cash")
        rows.append(f'''<div class="card"><h2>{E(m)}</h2>
<div class="row"><span>주문가능 현금</span><span>{"-" if cash is None else _money(m, cash)}</span></div>
{render_money_rows({"markets": {m: d}, **({"realized": snap["realized"]} if "realized" in snap else {})})}
<h2 style="margin-top:10px">보유</h2><table><tr><th>종목</th><th>수량</th><th>평단</th><th>현재가</th><th>손익</th></tr>{pos or "<tr><td colspan=5 class=mut>없음</td></tr>"}</table>
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
    body = f'''<h1>상세{" · " + E(title) if title else ""}{" (재인증 후 5분간 열림)" if strict else ""}</h1>{controls}{"".join(rows) or '<div class="card mut">스냅샷이 없다</div>'}{render_sells(snap)}{lastblk}
<div class="card"><h2>주문 원장(최근 30)</h2><table><tr><th>시각</th><th>시장</th><th>종목</th><th>방향</th><th>수량</th><th>종류</th></tr>{led or "<tr><td colspan=6 class=mut>없음</td></tr>"}</table></div>
<div class="card"><a href="{base}/">← 요약으로</a></div>
<form method="post" action="{base}/logout"><input type="hidden" name="csrf" value="{E(csrf)}"><button>로그아웃</button></form>'''
    return _page("autotrader 상세", body, refresh=False)


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
    cards = []
    if err:
        cards.append(f'<div class="card"><span class="bad">실계좌 요약을 못 읽었다: {E(err)}</span></div>')
    real = (d or {}).get("real") or {}
    for key, label in (("upbit", "업비트"), ("bithumb", "빗썸")):
        a = real.get(key)
        if not a:
            continue
        pnl = a.get("totalPnlKrw")
        rows = "".join(
            f'<tr><td>{E(str(h.get("currency")))}</td><td>{E(str(h.get("balance")))}</td><td>{won(h.get("evalKrw"))}</td>'
            f'<td class="{"" if h.get("pnlKrw") is None else ("ok" if h["pnlKrw"] >= 0 else "bad")}">{won(h.get("pnlKrw"))}'
            f'{_pct(h.get("pnlPct"))}</td></tr>'
            for h in a.get("holdings") or [])
        cards.append(f'''<div class="card"><h2>{label} 실계좌</h2>
<div class="row"><span>평가 합계</span><span>{won(a.get("totalKrw"))}</span></div>
<div class="row"><span>매입 합계 · 평가손익</span><span>{won(a.get("totalCostKrw"))} · <span class="{"" if pnl is None else ("ok" if pnl >= 0 else "bad")}">{won(pnl)}</span></span></div>
<table><tr><th>자산</th><th>수량</th><th>평가</th><th>손익</th></tr>{rows or "<tr><td colspan=4 class=mut>없음</td></tr>"}</table>
<div class="mut">갱신 {E(str(a.get("generatedAtKST", "-")))}</div></div>''')
    k = real.get("kis")
    if k:
        acc = k.get("account") or {}
        cards.append(f'''<div class="card"><h2>KIS 실계좌</h2>
<div class="row"><span>총평가</span><span>{won(acc.get("totalValueKrw"))}</span></div>
<div class="row"><span>주식 평가 · 예수금</span><span>{won(acc.get("stockValueKrw"))} · {won(acc.get("cashKrw"))}</span></div>
<div class="row"><span>보유 종목 수</span><span>{len(k.get("holdings") or [])}</span></div>
<div class="mut">갱신 {E(str(k.get("generatedAtKST", "-")))}</div></div>''')
    rv = ((d or {}).get("paper") or {}).get("rv20")
    if rv:
        fm = rv.get("frontMonth") or {}
        cards.append(f'''<div class="card"><h2>RV20 선물 (모의)</h2>
<div class="row"><span>보유 계약</span><span>{E(str(rv.get("heldContracts")))}</span></div>
<div class="row"><span>근월물</span><span>{E(str(fm.get("name", "-")))} {E(str(fm.get("price", "")))}</span></div>
<div class="mut">갱신 {E(str(rv.get("generatedAtKST", "-")))}</div></div>''')
    body = (f'<h1>실계좌 요약</h1><div class="card mut">수집 {E(str((d or {}).get("fetchedAt", "-")))} · '
            f'업비트·빗썸·KIS 실계좌는 조회만 한다(autotrader 주문과 무관)</div>{"".join(cards)}'
            f'<div class="card"><a href="{base}/">← 요약으로</a></div>'
            f'<form method="post" action="{base}/logout"><input type="hidden" name="csrf" value="{E(csrf)}"><button>로그아웃</button></form>')
    return _page("실계좌 요약", body)


def render_passkey(n: int, enabled: str, csrf: str, ready: bool, base: str = "") -> bytes:
    # 패스키 관리 — 등록만 한다. **삭제는 서버에서만**(웹에서 지울 수 있으면 공격자가 지우고 인증앱 코드 방식으로 되돌린다).
    if enabled:
        inner = f'<div class="warn">{E(enabled)}</div>'
    elif ready:
        inner = (f'<button id="pk-register" data-base="{E(base)}" data-csrf="{E(csrf)}">이 기기로 패스키 등록(지문·화면잠금)</button>'
                 f'<div id="pk-msg" class="mut">5분 안에 누르세요.</div><script src="{E(base)}/static/passkey.js"></script>')
    else:
        inner = ('<div class="mut">등록 코드는 서버에서만 나온다(피싱된 인증앱 코드로 남의 패스키를 추가하지 못하게):<br>'
                 '<code>python3 -m autotrader --config ~/collector-venv/autotrader/autotrader.local.json passkey-enroll</code> (15분·1회용)</div>'
                 f'<form method="post" action="{base}/passkey/begin"><input type="hidden" name="csrf" value="{E(csrf)}">'
                 '<input name="code" placeholder="서버 등록 코드 (예: 3F2A-9C01-77BE)" autocomplete="off" maxlength="20" required>'
                 '<button>등록 시작</button></form>')
    body = (f'<h1>패스키(지문)</h1><div class="card"><div class="row"><span>등록된 패스키</span><span>{n}개</span></div>'
            '<div class="mut">패스키가 하나라도 있으면 <b>실계좌 주문 켜기·실행은 패스키로만</b> 된다(인증앱 코드는 안 받는다 — 피싱 방지). '
            '삭제는 서버에서만: <code>python3 -m autotrader passkey-reset</code></div></div>'
            f'<div class="card">{inner}</div><div class="card"><a href="{base}/">← 요약으로</a></div>')
    return _page("패스키", body)


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
        form = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True) if method == "POST" else {}
        field = lambda k: (form.get(k) or [""])[0]   # noqa: E731

        if method == "POST" and path == "/login":
            return self._login(field("password"), field("code"), ip)
        if method == "GET" and path in ("/", "/index.html"):
            if not sess:
                return 200, self._hdrs(), render_login(base=self.base)
            now = self._now()
            extra = render_profiles([(c, load_view(c, state_dir(c), now)) for c in self.profiles()], self.base)
            return 200, self._hdrs(), render_dashboard(load_view(self.cfg, self.sdir, now), sess["csrf"], self.base,
                                                       self.require_reauth, extra)
        if not sess:                                    # 로그인 전에는 나머지 경로가 존재하지 않는 것처럼
            return self._not_found()
        if method == "GET" and path == "/accounts":
            if self.require_reauth and not self.sessions.is_fresh(sess):
                return 200, self._hdrs(), render_reauth(sess["csrf"], base=self.base)
            try:
                d, err = self.fetch_accounts(), ""
            except Exception as e:                      # noqa: BLE001 — API 가 죽어도 화면은 뜬다
                d, err = None, type(e).__name__
            return 200, self._hdrs(), render_accounts(d, err, sess["csrf"], self.base)
        if method == "GET" and path == "/details":
            if self.require_reauth and not self.sessions.is_fresh(sess):
                return 200, self._hdrs(), render_reauth(sess["csrf"], base=self.base)
            want = (parse_qs(urlsplit(raw_path).query).get("p") or [""])[0]
            if not want:
                return 200, self._hdrs(), render_details(load_view(self.cfg, self.sdir, self._now()), sess["csrf"], self.base, self.require_reauth)
            match = [c for c in self.profiles() if c.get("profile") == want]     # 목록에 있는 이름만 — 경로로 쓰지 않는다
            if not match:
                return self._not_found()
            c = match[0]
            msg = (parse_qs(urlsplit(raw_path).query).get("m") or [""])[0]
            msg = msg if msg in self._msgs else ""
            has_pk = bool(self._passkeys()) and not self._pk_disabled()
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
        if path == "/passkey/action-options":
            match = [c for c in self.profiles() if c.get("profile") == j.get("p")]
            if not match or not is_live_order(match[0], j.get("op")) or not self._passkeys():
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
            def bump(r):
                for pk in r.get("passkeys") or []:
                    if pk["id"] == cid:
                        pk["count"] = max(int(pk.get("count") or 0), count)
            self.store.update(bump)
            c = [x for x in self.profiles() if x.get("profile") == pend["p"]][0]
            live = c.get("mode") == "live"
            if live and str(j.get("phrase", "")).strip() != LIVE_PHRASE:
                return self._json(400, {"error": f"확인 문구({LIVE_PHRASE})를 정확히 입력"})
            msg = self._execute(c, pend["p"], pend["op"], ip)
            return self._json(200, {"redirect": self.base + self._back_url(pend["p"], msg)})
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
    sessions = Sessions(idle_sec=int(w.get("idle_min", 30)) * 60, absolute_sec=int(w.get("session_hours", 8)) * 3600,
                        reauth_sec=int(w.get("reauth_min", 5)) * 60)
    app = WebApp(cfg, sdir, AuthStore(sdir / "web_auth.json"), sessions, Lockout(),
                 secure_cookie=secure_cookie, fail_delay=0.5, base=base,
                 require_reauth=bool(w.get("require_reauth_for_details", False)),
                 profiles=_profile_loader(cfg, config_path) if config_path else None,
                 rp_id=str(w.get("rp_id", "")), origin=str(w.get("origin", "")))
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"autotrader web — http://{host}:{port} (앞단 HTTPS 프록시 뒤에서만 쓴다)", flush=True)
    httpd.serve_forever()
