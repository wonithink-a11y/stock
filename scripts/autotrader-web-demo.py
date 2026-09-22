"""autotrader 웹 로컬 미리보기(디자인 작업용) — 가짜 상태·가짜 계좌. 키·네트워크·주문 없음.

    python scripts/autotrader-web-demo.py   → http://127.0.0.1:8799 , 브라우저 쿠키 at_sess=demo 로 로그인된 상태

로컬 미리보기용 — 가짜 상태로 autotrader 웹을 띄운다. 세션 토큰 'demo' 가 미리 로그인돼 있다(쿠키 at_sess=demo)."""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from autotrader import web, web_auth as A  # noqa: E402
from autotrader.config import normalize_config  # noqa: E402

KST = timezone(timedelta(hours=9))
now = datetime.now(KST)
td = Path(tempfile.mkdtemp())
main_p = td / "autotrader.local.json"
BASE = {"strategy": "target_weights", "mode": "paper", "markets": ["KR"], "symbol_allowlist": ["005930"]}
main_p.write_text(json.dumps({**BASE, "state_dir": str(td / "state")}), encoding="utf-8")
(td / "profiles").mkdir()
(td / "profiles" / "infbuy.json").write_text(json.dumps({"strategy": "infinite_buying", "mode": "paper", "markets": ["US"],
    "symbol_allowlist": ["TQQQ", "SOXL"], "auto": "dry", "run_at": ["21:30"], "params": {}}), encoding="utf-8")
(td / "profiles" / "pbr.json").write_text(json.dumps({**BASE, "symbol_allowlist": ["005930", "000660", "035420", "0218L0"],
    "auto": "off", "run_at": ["09:10"]}), encoding="utf-8")
sd = td / "state"
(sd / "profiles" / "infbuy" / "runs").mkdir(parents=True)
(sd / "profiles" / "pbr").mkdir(parents=True)
(sd / "runs").mkdir(parents=True)

snap_main = {"at": now.isoformat(), "mode": "paper", "markets": {"KR": {"cash": 98451853.0, "openOrders": [],
    "positions": [{"symbol": "005930", "name": "", "qty": 1, "avgPrice": 274000, "price": 276500},
                  {"symbol": "000660", "name": "", "qty": 12, "avgPrice": 231000, "price": 224500}],
    "totals": {"cost": 3046000, "value": 2970500, "pnl": -75500, "pnlPct": -2.48}}}, "gates": {"execute": []}}
(sd / "snapshot.json").write_text(json.dumps(snap_main), encoding="utf-8")
snap_ib = {"at": (now - timedelta(minutes=3)).isoformat(), "mode": "paper", "markets": {"US": {"cash": 97935.94,
    "openOrders": [{"orderNo": "1", "symbol": "TQQQ", "side": "BUY", "qty": 7, "remaining": 7, "price": 81.66}],
    "positions": [{"symbol": "SOXL", "name": "DIREXION DAILY SEMICONDUCTOR BULL 3X", "qty": 8, "avgPrice": 123.58, "price": 139.78},
                  {"symbol": "TQQQ", "name": "PROSHARES ULTRAPRO QQQ", "qty": 15, "avgPrice": 71.419, "price": 77.53}],
    "totals": {"cost": 2059.92, "value": 2281.19, "pnl": 221.27, "pnlPct": 10.74}}},
    "realized": {"US": {"realized": 51.25, "incomplete": False, "sells": [{"day": "20260922", "symbol": "TQQQ", "qty": 5,
                                                                          "price": 81.67, "avg": 71.42, "pnl": 51.25}]}}}
(sd / "profiles" / "infbuy" / "snapshot.json").write_text(json.dumps(snap_ib), encoding="utf-8")
(sd / "profiles" / "infbuy" / "runs" / "20260922-213000.json").write_text(json.dumps({
    "at": now.isoformat(), "execute": False, "status": "ok", "placed": [], "rejected": [], "skipped": [], "errors": [],
    "planned": [{"symbol": "TQQQ", "side": "SELL", "qty": 3, "reason": "무한매수 LOC T 0.86"},
                {"symbol": "SOXL", "side": "BUY", "qty": 4, "reason": "무한매수 LOC T 0.79"}]}), encoding="utf-8")
snap_pbr = {"at": (now - timedelta(minutes=41)).isoformat(), "mode": "paper", "markets": {"KR": {"cash": 1000000, "openOrders": [],
    "positions": [{"symbol": "035420", "name": "", "qty": 3, "avgPrice": 180000, "price": 186300},
                  {"symbol": "0218L0", "name": "", "qty": 10, "avgPrice": 10000, "price": 9700}],
    "totals": {"cost": 640000, "value": 655900, "pnl": 15900, "pnlPct": 2.48}}}, "realized": {}}
(sd / "profiles" / "pbr" / "snapshot.json").write_text(json.dumps(snap_pbr), encoding="utf-8")

(sd / "channels.json").write_text(json.dumps({"updatedAt": "2026-09-22T21:00:00+09:00", "errors": {}, "posts": [   # 가짜 글(실제 채널 글은 저장소에 넣지 않는다)
    {"id": "mk_giant/1", "channel": "mk_giant", "at": "2026-09-22T11:28:00+00:00", "text": "✅ 예시전기 : +6.0% 상승 중\n\n현재주가 : 1,000,000원\n- 데모 문장입니다."},
    {"id": "wcforumxyz/2", "channel": "wcforumxyz", "at": "2026-09-22T09:10:00+00:00", "text": "비트코인 데모 소식 " + "긴 본문 " * 60},
    {"id": "mkglobalinvest/3", "channel": "mkglobalinvest", "at": "2026-09-22T06:00:00+00:00", "text": ""}]}), encoding="utf-8")

store = A.AuthStore(sd / "web_auth.json")
store.save({"password": A.hash_password("pw-long-enough-1"), "totpSecret": A.new_totp_secret()})
cfg = normalize_config({**BASE, "state_dir": str(sd)})
sessions = A.Sessions(idle_sec=86400)
sessions._s[A.Sessions._h("demo")] = {"created": 9e18, "seen": 9e18, "reauth": 0.0, "csrf": "c", "gen": 0}   # 세션은 토큰 해시로 찾는다
sessions._s[A.Sessions._h("demo")].update(created=__import__("time").time(), seen=__import__("time").time())
app = web.WebApp(cfg, sd, store, sessions, A.Lockout(), secure_cookie=False, profiles=web._profile_loader(cfg, main_p),
                 rp_id="localhost", origin="http://localhost:8799",
                 accounts_fetch=lambda: {"fetchedAt": now.isoformat()[:19], "real": {"upbit": {"totalKrw": 1523000.0, "totalCostKrw": 1600000.0,
                     "totalPnlKrw": -77000.0, "generatedAtKST": now.isoformat()[:16], "holdings": [
                         {"currency": "BTC", "balance": 0.0071, "evalKrw": 1020000.0, "pnlKrw": -30000.0, "pnlPct": -2.9},
                         {"currency": "ETH", "balance": 0.12, "evalKrw": 503000.0, "pnlKrw": -47000.0, "pnlPct": -8.5}]},
                     "kis": {"account": {"totalValueKrw": 5120000, "stockValueKrw": 0, "cashKrw": 5120000}, "holdings": []}},
                     "paper": {"rv20": {"heldContracts": 1, "frontMonth": {"name": "F 202612", "price": 431.2}}}})
httpd = ThreadingHTTPServer(("127.0.0.1", 8799), web.make_handler(app))
print("demo on http://127.0.0.1:8799  (cookie at_sess=demo)", flush=True)
httpd.serve_forever()
