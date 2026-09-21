#!/usr/bin/env python3
"""autotrader 웹 조작·손익 표시 회귀 — 키·네트워크 없이 돈다.

핀하는 것: 웹은 요청 파일만 쓴다 · 킬 켜기 말고는 매번 새 인증앱 코드(재사용 불가) · 실전 프로필은 웹에서 주문을 못 켠다 ·
실행 요청은 한 번만·15분 넘으면 버림 · 자동이 꺼진 프로필의 '지금 실행'은 --execute 여도 주문 없음 · 프로필 스냅샷은 자기 종목만 ·
현재가를 모르면 손익을 0 이 아니라 '모름'으로 · 주소창으로 가짜 안내 문구를 못 넣는다 · 웹 조작은 텔레그램으로 즉시 알린다.

    python scripts/test-autotrader-webctl.py
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autotrader import cli, notify, web                                       # noqa: E402
from autotrader import web_auth as A                                          # noqa: E402
from autotrader.broker import FakeBroker                                      # noqa: E402
from autotrader.config import (effective_auto, kill_file, load_profile, normalize_config,   # noqa: E402
                               read_control, take_run_request, web_request_run, web_set_auto)
from autotrader.engine import KST                                             # noqa: E402
from autotrader.models import Position                                        # noqa: E402
from autotrader.snapshot import build_snapshot, totals                        # noqa: E402
from autotrader.config import state_dir as state_dir_of                       # noqa: E402

FAILS, COUNT = [], [0]


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


BASE = {"strategy": "target_weights", "mode": "paper", "markets": ["KR"], "symbol_allowlist": ["005930"]}
PAPER = {"KIS_VTS_APP_KEY": "k", "KIS_VTS_APP_SECRET": "s", "KIS_VTS_ACCOUNT_NO": "12345678-01"}


def main():
    now = datetime(2026, 9, 22, 10, 0, tzinfo=KST)
    # ---- 손익 합계
    t = totals([{"qty": 2, "avgPrice": 100.0, "price": 110.0}, {"qty": 1, "avgPrice": 50.0, "price": 40.0}])
    ck("투자금·평가·손익", t["cost"] == 250 and t["value"] == 260 and t["pnl"] == 10 and abs(t["pnlPct"] - 4.0) < 1e-9)
    t2 = totals([{"qty": 2, "avgPrice": 100.0, "price": 0.0}])
    ck("현재가를 모르면 손익은 모름(0 아님)", t2["cost"] == 200 and t2["pnl"] is None and t2["value"] is None)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        main_p = td / "autotrader.local.json"
        main_p.write_text(json.dumps({**BASE, "state_dir": str(td / "state")}), encoding="utf-8")
        (td / "profiles").mkdir()
        (td / "profiles" / "pp.json").write_text(json.dumps({**BASE, "auto": "off", "run_at": ["09:10"]}), encoding="utf-8")
        (td / "profiles" / "lv.json").write_text(json.dumps({**BASE, "mode": "live", "auto": "dry"}), encoding="utf-8")
        pp, lv = load_profile(main_p, "pp"), load_profile(main_p, "lv")

        # ---- 프로필 스냅샷은 자기 종목만
        fb = FakeBroker(positions={"KR": [Position("005930", "KR", 3, 70000.0, 72000.0), Position("000660", "KR", 1, 1.0, 2.0)]},
                        cash={"KR": 1_000_000})
        snap = build_snapshot(pp, fb, PAPER, now)
        kr = snap["markets"]["KR"]
        ck("프로필 스냅샷은 허용 종목만(공유 계좌의 남의 종목 제외)", [p["symbol"] for p in kr["positions"]] == ["005930"])
        ck("스냅샷에 손익 합계", kr["totals"]["pnl"] == 6000)

        # ---- 자동 여부: 웹 값·실전 제한
        ck("모의: 웹 값이 파일 값을 이긴다", effective_auto({**pp, "auto": "off"}, "execute") == "execute")
        ck("실전: 웹이 파일 값보다 올리지 못한다", effective_auto({"mode": "live", "auto": "dry"}, "execute") == "dry")
        ck("실전: 웹이 내리는 건 된다", effective_auto({"mode": "live", "auto": "dry"}, "off") == "off")
        ck("실전 주문 켜기는 웹 쓰기 단계에서 거부", web_set_auto(lv, "execute", now) is not None and not read_control(lv))

        # ---- 실행 요청
        web_request_run(pp, now)
        ck("실행 요청은 한 번만 소비된다", take_run_request(pp, now + timedelta(minutes=1)) and take_run_request(pp, now) is None)
        web_request_run(pp, now)
        ck("15분 넘은 요청은 버린다", take_run_request(pp, now + timedelta(minutes=16)) is None)

        # ---- 웹 조작
        sdir = td / "state"
        store = A.AuthStore(sdir / "web_auth.json")
        secret = A.new_totp_secret()
        store.save({"password": A.hash_password("pw-long-enough-1"), "totpSecret": secret})
        clk = [now.timestamp()]
        app = web.WebApp(normalize_config({**BASE, "state_dir": str(sdir)}), sdir, store, A.Sessions(clock=lambda: clk[0]),
                         A.Lockout(clock=lambda: clk[0]), clock=lambda: clk[0], secure_cookie=False,
                         profiles=web._profile_loader(normalize_config({**BASE, "state_dir": str(sdir)}), main_p))
        tok = app.sessions.create()
        csrf = app.sessions.get(tok)["csrf"]
        h = {"Cookie": f"at_sess={tok}"}

        def post(body, headers=h):
            return app.handle("POST", "/action", headers, body.encode(), "1.1.1.1")

        code = A.totp_now(secret, clk[0])
        ck("로그인 없이 조작 404", post(f"csrf={csrf}&p=pp&op=auto-dry&code={code}", {})[0] == 404)
        ck("CSRF 없으면 403", post(f"p=pp&op=auto-dry&code={code}")[0] == 403)
        ck("없는 프로필 404", post(f"csrf={csrf}&p=zz&op=auto-dry&code={code}")[0] == 404)
        ck("모르는 조작 404", post(f"csrf={csrf}&p=pp&op=place&code={code}")[0] == 404)
        post(f"csrf={csrf}&p=pp&op=auto-execute&code=000000")
        ck("틀린 코드면 안 바뀐다", read_control(pp) == {})
        st, hd, _ = post(f"csrf={csrf}&p=pp&op=auto-execute&code={code}")
        ck("맞는 코드면 자동 주문(모의)으로", st == 303 and read_control(pp)["auto"] == "execute"
           and load_profile(main_p, "pp")["auto"] == "execute")
        post(f"csrf={csrf}&p=pp&op=auto-off&code={code}")
        ck("같은 코드 재사용은 거부", load_profile(main_p, "pp")["auto"] == "execute")
        clk[0] += 30
        post(f"csrf={csrf}&p=pp&op=auto-off&code={A.totp_now(secret, clk[0])}")
        ck("새 코드면 다시 바뀐다", load_profile(main_p, "pp")["auto"] == "off")
        clk[0] += 30
        post(f"csrf={csrf}&p=lv&op=auto-execute&code={A.totp_now(secret, clk[0])}")
        ck("실전 프로필은 웹에서 주문을 못 켠다", load_profile(main_p, "lv")["auto"] == "dry")
        # ---- 서버가 허락한 실전 프로필(web_live_allowed): 코드 + 확인 문구가 있어야 켜진다
        (td / "profiles" / "la.json").write_text(json.dumps({**BASE, "mode": "live", "auto": "off", "web_live_allowed": True}),
                                                 encoding="utf-8")
        ck("허락된 실전은 웹이 올릴 수 있다", effective_auto({"mode": "live", "auto": "off", "web_live_allowed": True}, "execute") == "execute")
        ck("허락 값은 true/false 만", web is not None and __import__("autotrader.config", fromlist=["x"]).validate_config(
            {**BASE, "web_live_allowed": "yes"}) != [])
        clk[0] += 30
        post(f"csrf={csrf}&p=la&op=auto-execute&code={A.totp_now(secret, clk[0])}&phrase={web.LIVE_PHRASE}")
        ck("허락된 실전이라도 인증앱 코드 + 문구로는 주문이 안 켜진다(패스키로만)", load_profile(main_p, "la")["auto"] == "off")
        la = load_profile(main_p, "la")
        kill_file(la).parent.mkdir(parents=True, exist_ok=True)
        kill_file(la).write_text("x", encoding="utf-8")
        clk[0] += 30
        post(f"csrf={csrf}&p=la&op=resume&code={A.totp_now(secret, clk[0])}")
        ck("실계좌 킬 해제도 인증앱 코드로는 안 된다(M2)", kill_file(la).exists())
        clk[0] += 30
        post(f"csrf={csrf}&p=la&op=auto-dry&code={A.totp_now(secret, clk[0])}")
        ck("실계좌를 dry-run 으로 내리는 건 코드로 된다", load_profile(main_p, "la")["auto"] == "dry")
        post(f"csrf={csrf}&p=la&op=kill")
        ck("실계좌 킬 켜기는 코드 없이", kill_file(la).exists())
        st, _, b = app.handle("GET", "/details?p=la", h, b"", "1.1.1.1")
        ck("패스키 없으면 실계좌 조작 안내만(주문 켜기 선택지 없음)", "패스키로만" in b.decode() and "auto-execute" not in b.decode())
        lg = (sdir / "web_login.log").read_text(encoding="utf-8").splitlines()
        ck("실계좌 조작은 텔레그램에 실계좌로 표시", any("실계좌 킬 스위치 켬" in m for m in notify.build_messages(lg)))
        (td / "profiles" / "la.json").unlink()

        # ---- 실계좌 요약(전엔 인터넷에 인증 없이 열려 있던 /accounts) — 로그인 뒤에서만
        fake = {"fetchedAt": "t", "real": {"upbit": {"totalKrw": 1000.0, "totalCostKrw": 900.0, "totalPnlKrw": 100.0,
                                                      "holdings": [{"currency": "BTC", "balance": 0.1, "evalKrw": 1000.0,
                                                                    "pnlKrw": 100.0, "pnlPct": 11.1}]},
                                            "kis": {"account": {"totalValueKrw": 5000}, "holdings": []}},
                "paper": {"rv20": {"heldContracts": 1, "frontMonth": {"name": "F 202612"}}}}
        app.fetch_accounts = lambda: fake
        ck("로그인 없이 실계좌 요약 404", app.handle("GET", "/accounts", {}, b"", "1.1.1.1")[0] == 404)
        st, _, body = app.handle("GET", "/accounts", h, b"", "1.1.1.1")
        pg = body.decode()
        ck("로그인하면 실계좌 요약", st == 200 and "업비트 실계좌" in pg and "BTC" in pg and "+11.1%" in pg
           and "5,000원" in pg and "F 202612" in pg)

        def boom():
            raise OSError("down")
        app.fetch_accounts = boom
        st, _, body = app.handle("GET", "/accounts", h, b"", "1.1.1.1")
        ck("요약 API 가 죽어도 화면은 뜬다", st == 200 and "못 읽었다" in body.decode())
        ck("주소는 127.0.0.1 고정", web.ACCOUNTS_URL.startswith("http://127.0.0.1:"))

        post(f"csrf={csrf}&p=pp&op=kill")
        ck("킬 켜기는 코드 없이 즉시", kill_file(pp).exists())
        post(f"csrf={csrf}&p=pp&op=resume")
        ck("킬 해제는 코드가 있어야", kill_file(pp).exists())
        clk[0] += 30
        post(f"csrf={csrf}&p=pp&op=resume&code={A.totp_now(secret, clk[0])}")
        ck("코드와 함께면 해제", not kill_file(pp).exists())

        st, _, body = app.handle("GET", "/details?p=pp&m=" + "계좌가 해킹됐습니다", h, b"", "1.1.1.1")
        ck("주소창으로 넣은 가짜 문구는 안 보인다", st == 200 and "해킹" not in body.decode())
        st, _, body = app.handle("GET", "/details?p=pp&m=" + "킬 스위치를 해제했습니다", h, b"", "1.1.1.1")
        ck("서버가 낸 문구는 보인다 + 조작 폼", "킬 스위치를 해제했습니다" in body.decode() and 'action="/action"' in body.decode())
        log = (sdir / "web_login.log").read_text(encoding="utf-8")
        ck("조작이 기록된다", "action:pp:auto-execute" in log and "action:pp:kill" in log)
        msgs = notify.build_messages(log.splitlines())
        ck("조작은 텔레그램 즉시 알림", any("웹 조작: pp" in m and "자동 주문 켬" in m for m in msgs))

        # ---- 자동 꺼짐 + 지금 실행 → --execute 여도 주문 없음
        (td / "profiles" / "lv.json").unlink()
        (td / "t.json").write_text(json.dumps({"KR": {"005930": 0.2}}), encoding="utf-8")
        (td / "profiles" / "pp.json").write_text(json.dumps({**BASE, "auto": "off", "run_at": [],
                                                              "params": {"targets_file": str(td / "t.json")}}), encoding="utf-8")
        pp = load_profile(main_p, "pp")
        brokers = []
        cli.make_broker = lambda c, e, x: brokers.append(FakeBroker(cash={"KR": 1_000_000}, quotes={"005930": 70000})) or brokers[-1]
        cli.load_env = lambda: dict(PAPER)
        web_request_run(pp, datetime.now(KST))
        cli.cmd_run_due(type("A", (), {"config": main_p, "execute": True})())
        ck("자동이 꺼진 프로필의 '지금 실행'은 dry-run(주문 없음)", len(brokers) == 1 and brokers[0].placed == [])
        cli.cmd_run_due(type("A", (), {"config": main_p, "execute": True})())
        ck("요청은 한 번만 실행", len(brokers) == 1)

    # ---- H2: 동시 요청으로 잠금을 한꺼번에 통과하지 못한다(검증이 끝나야 다음 요청이 잠금을 본다)
    import threading
    import time as _time
    with tempfile.TemporaryDirectory() as td2:
        sd = Path(td2)
        st2 = A.AuthStore(sd / "web_auth.json")
        st2.save({"password": A.hash_password("pw-long-enough-1"), "totpSecret": A.new_totp_secret()})
        app2 = web.WebApp(normalize_config({**BASE, "state_dir": str(sd)}), sd, st2, A.Sessions(), A.Lockout(), secure_cookie=False)
        codes = []
        th = [threading.Thread(target=lambda: codes.append(app2.handle("POST", "/login", {}, b"password=wrong&code=000000",
                                                                      "9.9.9.9")[0])) for _ in range(20)]
        [t.start() for t in th]
        [t.join() for t in th]
        ck("동시 20건 중 실제 검증은 잠금 한도(5)까지만, 나머지는 잠김", codes.count(401) == 5 and codes.count(429) == 15)
        code_txt = st2.issue_enroll_code(_time.time())
        ck("등록 코드 형식·대소문자 무관·1회용", len(code_txt) == 14 and st2.take_enroll_code(code_txt.lower(), _time.time())
           and not st2.take_enroll_code(code_txt, _time.time()))

    print(f"\ntest-autotrader-webctl {COUNT[0] - len(FAILS)}/{COUNT[0]}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
