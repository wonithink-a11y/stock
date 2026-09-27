#!/usr/bin/env python3
"""autotrader 직접매매 계획 카드(plan_trader) 회귀 — 키·네트워크 없이 돈다.

핀하는 것: 입력 검증(허용 종목·순서·한도·자본 없음) · 수량 = 자본×위험% ÷ (진입 상단−손절) · 상태 전이(진입은 하루 한 번,
당일물 미체결은 다음 날 대기로, 다른 전략 몫 수량은 안 센다, 청산 시도 하루 3번) · 엔진을 거쳐 시장가 주문 + 원장에 계획 id ·
실계좌면 주문 없음 · 장 밖이면 주문 없음 · 허용 종목 밖은 엔진이 거부 · 체결가로 R 배수(모르면 None) · 웹은 지문 재확인 뒤에만
보고·입력하고 plans.json 만 쓴다 · 웹 입력은 텔레그램 조작 알림으로 · run_at 범위 표기.

    python scripts/test-autotrader-plans.py
"""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autotrader import notify, web                                            # noqa: E402
from autotrader import web_auth as A                                          # noqa: E402
from autotrader.broker import FakeBroker                                      # noqa: E402
from autotrader.config import due_slots, expand_run_at, load_profile, normalize_config, validate_config   # noqa: E402
from autotrader.engine import KST, Ledger, run_once                           # noqa: E402
from autotrader.models import Position                                        # noqa: E402
from autotrader.plans import (MAX_EXIT_TRIES, build_plan, fills_by_plan, load_plans, outcome, save_plans,   # noqa: E402
                              size_qty, step, summarize)
from autotrader.strategy import load_strategy                                 # noqa: E402

FAILS, COUNT = [], [0]


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


PAPER = {"KIS_VTS_APP_KEY": "k", "KIS_VTS_APP_SECRET": "s", "KIS_VTS_ACCOUNT_NO": "12345678-01"}
PROF = {"strategy": "plan_trader", "mode": "paper", "markets": ["KR"], "symbol_allowlist": ["005930", "000660"],
        "params": {"capital": 10_000_000}, "risk": {"KR": {"max_order_value": 5_000_000, "max_position_value": 5_000_000,
                                                          "max_daily_value": 20_000_000}},
        "auto": "execute", "run_at": ["09:05-15:15/5"]}
FORM = {"symbol": "005930", "entryLow": "70000", "entryHigh": "71000", "stop": "68000", "target": "78000", "riskPct": "1",
        "validDays": "14", "invalidation": "20일선 이탈", "thesis": "t", "tag": "눌림"}


def main():
    now = datetime(2026, 9, 28, 10, 0, tzinfo=KST)
    cfg = normalize_config({**PROF, "state_dir": "x"})

    # ---- 입력 검증·수량
    p, err = build_plan(FORM, cfg, now, 0)
    ck("수량 = 자본×1% ÷ (진입 상단 − 손절) = 100,000 ÷ 3,000 = 33주", p and p["qty"] == 33 and size_qty(1e7, 1, 71000, 68000) == 33)
    ck("만료일 = 오늘 + 14일", p and p["validUntil"] == "2026-10-12")
    ck("자본 없으면 거부", build_plan(FORM, {**cfg, "params": {}}, now, 0)[0] is None)
    ck("허용 종목 밖이면 거부", "허용 종목" in build_plan({**FORM, "symbol": "035720"}, cfg, now, 0)[1])
    ck("손절 ≥ 진입이면 거부", build_plan({**FORM, "stop": "70500"}, cfg, now, 0)[0] is None)
    ck("목표 ≤ 진입이면 거부", build_plan({**FORM, "target": "70500"}, cfg, now, 0)[0] is None)
    ck("위험 비율 5% 초과 거부", build_plan({**FORM, "riskPct": "6"}, cfg, now, 0)[0] is None)
    ck("주문당 한도 초과면 입력 단계에서 거부", "주문당 한도" in build_plan({**FORM, "riskPct": "5"}, cfg, now, 0)[1])
    ck("수량 0 이면 거부", build_plan({**FORM, "riskPct": "0.01", "stop": "10000"}, cfg, now, 0)[0] is None)
    ck("숫자가 아니면 거부", build_plan({**FORM, "stop": "abc"}, cfg, now, 0)[0] is None)
    ck("살아 있는 계획 20개면 거부", build_plan(FORM, cfg, now, 20)[0] is None)
    ck("진입 상단 비우면 하단과 같게", build_plan({**FORM, "entryHigh": ""}, cfg, now, 0)[0]["entryHigh"] == 70000)

    # ---- run_at 범위
    ex = expand_run_at(["09:05-15:15/5"])
    ck("09:05-15:15/5 → 75회", len(ex) == 75 and ex[0] == "09:05" and ex[-1] == "15:15")
    ck("단일 시각과 섞어 쓸 수 있다", expand_run_at(["08:00", "09:00-09:10/5"]) == ["08:00", "09:00", "09:05", "09:10"])
    ck("5분 미만 간격은 설정 오류", validate_config({**PROF, "run_at": ["09:05-15:15/3"]}) != [])
    ck("범위 표기는 설정 통과", validate_config(PROF) == [])
    ck("범위 안 예약이 돈다", due_slots({**cfg, "auto": "execute"}, now, []) and "2026-09-28 10:00" in due_slots({**cfg, "auto": "execute"}, now, []))

    # ---- 상태 전이
    d0, d1 = "2026-09-28", "2026-09-29"
    s = {"status": "wait"}
    ck("구간 밖이면 아무것도 안 함", step(p, s, 0, 72000, d0) is None and s["status"] == "wait")
    ck("구간 안이면 진입 매수", step(p, s, 0, 70500, d0) == ("BUY", 33, "진입") and s["status"] == "entering")
    ck("체결 전에는 기다린다", step(p, s, 0, 70500, d0) is None and s["status"] == "entering")
    ck("당일물 미체결은 다음 날 대기로", step(p, s, 0, 72000, d1) is None and s["status"] == "wait")
    s2 = {"status": "wait"}
    step(p, s2, 0, 70500, d0)
    step(p, s2, 0, 72000, d0)
    ck("진입 시도는 하루 한 번", s2["status"] == "entering")
    s3 = {"status": "wait"}
    step(p, s3, 10, 70500, d0)                                  # 계좌에 다른 전략 몫 10주가 이미 있다
    ck("다른 전략 몫은 안 센다(10주 → 43주 = 33주 체결)", step(p, s3, 43, 70500, d0) is None and s3["heldQty"] == 33)
    ck("손절가 아래면 계획 몫만 매도", step(p, s3, 43, 67900, d0) == ("SELL", 33, "손절") and s3["status"] == "exiting")
    ck("매도 체결되면 종료", step(p, s3, 10, 67000, d0) is None and s3["status"] == "done")
    s4 = {"status": "held", "heldQty": 33}
    ck("목표가 이상이면 매도", step(p, s4, 33, 78100, d0) == ("SELL", 33, "목표"))
    s5 = {"status": "held", "heldQty": 33}
    tries = 0
    for _ in range(MAX_EXIT_TRIES + 2):
        r = step(p, s5, 33, 67000, d0)                          # 매도가 안 맞는 상황(휴장일 등)
        tries += 1 if r else 0
    ck(f"청산 시도는 하루 {MAX_EXIT_TRIES}번까지", tries == MAX_EXIT_TRIES)
    ck("다음 날 다시 청산 시도", step(p, s5, 33, 67000, d1) == ("SELL", 33, "손절"))
    ck("손절·목표 사이면 보유 유지", step(p, {"status": "held", "heldQty": 33}, 33, 72000, d0) is None)
    ck("지금 청산 요청이면 매도", step({**p, "closeReq": True}, {"status": "held", "heldQty": 33}, 33, 72000, d0)[2] == "지금 청산 요청")
    s6 = {"status": "held", "heldQty": 33}
    ck("계좌에서 사라지면 종료(수동 매도)", step(p, s6, 0, 72000, d0) is None and s6["status"] == "done")
    s7 = {"status": "wait"}
    ck("만료일 지나면 만료", step(p, s7, 0, 70500, "2026-10-13") is None and s7["status"] == "expired")
    s8 = {"status": "wait"}
    ck("취소 요청이면 취소", step({**p, "cancel": True}, s8, 0, 70500, d0) is None and s8["status"] == "cancelled")
    s9 = {"status": "exiting", "heldQty": 33, "preExitQty": 33, "sellQty": 33}
    ck("일부만 팔렸으면 남은 수량으로 다시 판단", step(p, s9, 13, 67000, d0) == ("SELL", 13, "손절"))

    # ---- R 배수
    rows = [{"kind": "order", "executed": True, "orderNo": "1", "side": "BUY", "reason": f"plan:{p['id']} 진입"},
            {"kind": "order", "executed": True, "orderNo": "2", "side": "SELL", "reason": f"plan:{p['id']} 손절"},
            {"kind": "order", "executed": True, "orderNo": "3", "side": "BUY", "reason": "다른 전략"}]
    book = {"fills": {"1": {"qty": 33, "price": 70500}, "2": {"qty": 33, "price": 67000}, "3": {"qty": 1, "price": 1}}}
    fb = fills_by_plan(rows, book)
    o = outcome(p, fb[p["id"]])
    ck("R = (67,000 − 70,500) ÷ (70,500 − 68,000) = −1.40", abs(o["R"] + 1.4) < 1e-9 and len(fb) == 1)
    ck("청산 체결을 모르면 R 은 None(0 아님)", outcome(p, {"BUY": fb[p["id"]]["BUY"]})["R"] is None)
    sm = summarize([1.0, -1.0, 2.0, -1.4])
    ck("통계: 기대값·−1R 초과 손실·표본 부족", abs(sm["expectancy"] - 0.15) < 1e-9 and sm["worseThan1R"] == 1 and not sm["enough"])

    # ---- 엔진을 거친 실제 흐름(가짜 브로커)
    strat = load_strategy("plan_trader")
    with tempfile.TemporaryDirectory() as td:
        sdir = Path(td) / "st"
        c = normalize_config({**PROF, "state_dir": str(sdir)})
        save_plans(sdir, [p])
        fb = FakeBroker(cash={"KR": 50_000_000}, quotes={"005930": 70500})
        rep = run_once(c, fb, strat, execute=True, env=PAPER, now=now)
        ck("진입 구간이면 시장가 매수 접수", len(fb.placed) == 1 and fb.placed[0]["side"] == "BUY" and fb.placed[0]["qty"] == 33
           and rep["placed"][0]["orderType"] == "market")
        ck("원장에 계획 id 가 남는다", Ledger(sdir).rows()[-1]["reason"] == f"plan:{p['id']} 진입")
        fb2 = FakeBroker(positions={"KR": [Position("005930", "KR", 33, 70500.0, 67000.0)]}, cash={"KR": 1e7}, quotes={"005930": 67000})
        run_once(c, fb2, strat, execute=True, env=PAPER, now=now.replace(minute=5))
        ck("다음 점검: 보유 확인 → 손절가 아래라 매도", [x["side"] for x in fb2.placed] == ["SELL"] and fb2.placed[0]["qty"] == 33)
        fb3 = FakeBroker(cash={"KR": 1e7}, quotes={"005930": 70500})
        save_plans(sdir, [{**p, "id": "x2"}])
        run_once(c, fb3, strat, execute=True, env=PAPER, now=now.replace(hour=15, minute=20))
        ck("장 마감 무렵(15:15 이후)엔 주문 없음", fb3.placed == [])
        run_once(c, fb3, strat, execute=True, env=PAPER, now=now.replace(hour=9, minute=0))
        ck("개장 직후(09:05 전)엔 주문 없음", fb3.placed == [])
        save_plans(sdir, [{**p, "id": "x3", "symbol": "035720"}])          # 웹을 거치지 않고 파일을 고친 경우
        fb4 = FakeBroker(cash={"KR": 1e7}, quotes={"035720": 70500})
        rep4 = run_once(c, fb4, strat, execute=True, env=PAPER, now=now)
        ck("허용 종목 밖은 엔진이 거부(파일을 고쳐도 주문 안 나감)", fb4.placed == [] and rep4["rejected"])
        lv = normalize_config({**PROF, "mode": "live", "state_dir": str(sdir), "live": {"enabled": True, "tr_ids_reviewed": True}})
        save_plans(sdir, [{**p, "id": "x4"}])
        fb5 = FakeBroker(cash={"KR": 1e7}, quotes={"005930": 70500})
        fb5.mode = "live"                                   # 실제 KIS 브로커의 mode 는 설정 mode 에서 온다(kis.make_broker)
        rep5 = run_once(lv, fb5, strat, execute=True, env={"KIS_LIVE_APP_KEY": "k", "KIS_LIVE_APP_SECRET": "s",
                                                           "KIS_LIVE_ACCOUNT_NO": "1", "AUTOTRADER_ALLOW_LIVE": "I-ACCEPT-REAL-TRADES"}, now=now)
        ck("실계좌 모드면 전략이 거부 — 주문 없음", fb5.placed == [] and rep5["status"] == "strategy-error")

    # ---- 웹
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        main_p = td / "autotrader.local.json"
        base = {"strategy": "target_weights", "mode": "paper", "markets": ["KR"], "symbol_allowlist": ["005930"]}
        main_p.write_text(json.dumps({**base, "state_dir": str(td / "state")}), encoding="utf-8")
        (td / "profiles").mkdir()
        (td / "profiles" / "pl.json").write_text(json.dumps(PROF), encoding="utf-8")
        (td / "profiles" / "tw.json").write_text(json.dumps({**base, "auto": "off"}), encoding="utf-8")
        sdir = td / "state"
        store = A.AuthStore(sdir / "web_auth.json")
        store.save({"password": A.hash_password("pw-long-enough-1"), "totpSecret": A.new_totp_secret()})
        clk = [now.timestamp()]
        mc = normalize_config({**base, "state_dir": str(sdir)})
        app = web.WebApp(mc, sdir, store, A.Sessions(clock=lambda: clk[0]), A.Lockout(clock=lambda: clk[0]),
                         clock=lambda: clk[0], secure_cookie=False, require_reauth=True, profiles=web._profile_loader(mc, main_p))
        tok = app.sessions.create()
        csrf = app.sessions.get(tok)["csrf"]
        h = {"Cookie": f"at_sess={tok}"}
        get = lambda q: app.handle("GET", "/plans" + q, h, b"", "1.1.1.1")                         # noqa: E731
        post = lambda b: app.handle("POST", "/plans", h, b.encode(), "1.1.1.1")                    # noqa: E731
        form = "&".join(f"{k}={v}" for k, v in FORM.items())
        ck("로그인 없이 404", app.handle("GET", "/plans?p=pl", {}, b"", "1.1.1.1")[0] == 404)
        ck("계획 전략이 아닌 프로필은 404", get("?p=tw")[0] == 404)
        ck("재확인 전에는 재인증 화면", "한 번 더 확인" in get("?p=pl")[2].decode())
        post(f"csrf={csrf}&p=pl&op=new&{form}")
        pl = load_profile(main_p, "pl")
        ck("재확인 전 입력은 저장 안 됨", load_plans(Path(pl["state_dir"])) == [])
        app.sessions.mark_reauth(tok)
        page = get("?p=pl")[2].decode()
        ck("재확인 뒤 계획 화면", "새 계획" in page and "10,000,000원" in page)
        ck("CSRF 없으면 403", post(f"p=pl&op=new&{form}")[0] == 403)
        st, hd, _ = post(f"csrf={csrf}&p=pl&op=new&{form}")
        saved = load_plans(Path(pl["state_dir"]))
        ck("입력 → plans.json 에 저장·수량 계산", st == 303 and len(saved) == 1 and saved[0]["qty"] == 33)
        ck("안내 문구는 서버가 낸 것만", "33" in get("?p=pl&m=" + hd["Location"].split("m=")[1])[2].decode()
           and "가짜" not in get("?p=pl&m=%EA%B0%80%EC%A7%9C")[2].decode())
        post(f"csrf={csrf}&p=pl&op=new&{form.replace('005930', '035720')}")
        ck("허용 종목 밖 입력은 저장 안 됨", len(load_plans(Path(pl["state_dir"]))) == 1)
        post(f"csrf={csrf}&p=pl&op=cancel&id={saved[0]['id']}")
        ck("취소 요청은 플래그만(전략이 처리)", load_plans(Path(pl["state_dir"]))[0].get("cancel") is True)
        ck("없는 계획 id 는 404", post(f"csrf={csrf}&p=pl&op=cancel&id=nope")[0] == 404)
        ck("모르는 조작은 404", post(f"csrf={csrf}&p=pl&op=place")[0] == 404)
        log = (sdir / "web_login.log").read_text(encoding="utf-8").splitlines()
        msgs = notify.build_messages(log)
        ck("웹 입력은 텔레그램 조작 알림으로", any("매매 계획 추가" in m for m in msgs) and any("매매 계획 취소" in m for m in msgs))
        home = app.handle("GET", "/", h, b"", "1.1.1.1")[2].decode()
        ck("요약 화면에 계획 링크(계획 프로필만)", home.count("/plans?p=") == 1)

    print(f"\n{COUNT[0] - len(FAILS)}/{COUNT[0]} 통과")
    if FAILS:
        print("실패:", *FAILS, sep="\n  ")
        sys.exit(1)


if __name__ == "__main__":
    main()
