#!/usr/bin/env python3
"""autotrader 프로필 회귀 — 키 묶음 교체·프로필 격리·예약 실행(run-due). 키·네트워크 없이 돈다.

핀하는 것: 시세용 KIS 키는 고를 수 없다 · 프로필 상태 폴더가 안 섞인다 · 주문은 --execute 와 auto=execute 가
둘 다 있어야 나간다 · 같은 회차는 두 번 안 돈다 · 늦게 깬 타이머가 몰아서 주문하지 않는다.

    python scripts/test-autotrader-profiles.py
"""
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from autotrader import cli, web                                               # noqa: E402
from autotrader import web_auth as A                                          # noqa: E402
from autotrader.broker import FakeBroker                                      # noqa: E402
from autotrader.config import (ConfigError, due_slots, gate_problems, key_names, load_env,   # noqa: E402
                               load_profile, normalize_config)
from autotrader.engine import KST                                             # noqa: E402

FAILS, COUNT = [], [0]


def ck(name, cond):
    COUNT[0] += 1
    if not cond:
        FAILS.append(name)
    print(("ok   " if cond else "FAIL ") + name)


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return True
    except Exception:                                   # noqa: BLE001
        return False
    return False


BASE = {"strategy": "target_weights", "mode": "paper", "markets": ["KR"], "symbol_allowlist": ["005930"]}


def setup(td, profiles):
    td = Path(td)
    main = td / "autotrader.local.json"
    main.write_text(json.dumps({**BASE, "state_dir": str(td / "state")}), encoding="utf-8")
    (td / "profiles").mkdir()
    for n, body in profiles.items():
        (td / "profiles" / f"{n}.json").write_text(json.dumps(body), encoding="utf-8")
    return main


def main():
    # ---- 키 묶음
    ck("기본 키 이름(모의)", key_names(normalize_config({**BASE, "state_dir": "x"}))[0] == "KIS_VTS_APP_KEY")
    c2 = normalize_config({**BASE, "state_dir": "x", "key_prefix": "KIS_VTS2"})
    ck("접두사로 키 교체", key_names(c2) == ("KIS_VTS2_APP_KEY", "KIS_VTS2_APP_SECRET", "KIS_VTS2_ACCOUNT_NO"))
    ck("시세용 KIS 키(접두사 KIS)는 못 고른다", raises(ConfigError, normalize_config, {**BASE, "state_dir": "x", "key_prefix": "KIS"}))
    ck("소문자 접두사 거부", raises(ConfigError, normalize_config, {**BASE, "state_dir": "x", "key_prefix": "kis_vts"}))
    env = load_env(Path(tempfile.gettempdir()) / "없는폴더", {"KIS_VTS2_APP_KEY": "a", "KIS_APP_KEY": "q", "OTHER": "z"})
    ck("load_env 가 새 키 묶음은 읽는다", env.get("KIS_VTS2_APP_KEY") == "a")
    ck("load_env 가 시세용 KIS_APP_KEY·무관한 값은 안 읽는다", "KIS_APP_KEY" not in env and "OTHER" not in env)
    ck("게이트가 설정한 키 묶음을 본다",
       any("KIS_VTS2_APP_SECRET" in p for p in gate_problems(c2, {"KIS_VTS2_APP_KEY": "a"}, False)))
    ck("auto 값 검증", raises(ConfigError, normalize_config, {**BASE, "state_dir": "x", "auto": "yes"}))
    ck("run_at 형식 검증", raises(ConfigError, normalize_config, {**BASE, "state_dir": "x", "run_at": ["9:10"]}))

    # ---- 예약 판정
    mon = datetime(2026, 9, 21, 9, 12, tzinfo=KST)
    pc = normalize_config({**BASE, "state_dir": "x", "auto": "dry", "run_at": ["09:10", "15:00"]})
    ck("예약 시각 직후 → 실행", due_slots(pc, mon, []) == ["2026-09-21 09:10"])
    ck("이미 돈 회차는 다시 안 돈다", due_slots(pc, mon, ["2026-09-21 09:10"]) == [])
    ck("유예(20분) 지나면 몰아서 안 돈다", due_slots(pc, mon.replace(hour=9, minute=31), []) == [])
    ck("예약 전엔 안 돈다", due_slots(pc, mon.replace(hour=9, minute=9), []) == [])
    ck("주말(weekdays) 안 돈다", due_slots(pc, datetime(2026, 9, 20, 9, 12, tzinfo=KST), []) == [])
    ck("daily 면 주말에도 돈다",
       due_slots({**pc, "days": "daily"}, datetime(2026, 9, 20, 9, 12, tzinfo=KST), []) == ["2026-09-20 09:10"])
    ck("auto=off 는 안 돈다", due_slots({**pc, "auto": "off"}, mon, []) == [])

    with tempfile.TemporaryDirectory() as td:
        prof = {**BASE, "params": {"targets_file": str(Path(td) / "t.json")}, "auto": "execute", "run_at": ["09:10"]}
        (Path(td) / "t.json").write_text(json.dumps({"KR": {"005930": 0.2}}), encoding="utf-8")
        main_p = setup(td, {"a": prof, "b": {**prof, "auto": "dry"}, "bad": {**prof, "state_dir": "/tmp/x"}})

        # ---- 프로필 격리
        a = load_profile(main_p, "a")
        ck("프로필 상태 폴더 강제", Path(a["state_dir"]) == Path(td) / "state" / "profiles" / "a")
        ck("프로필이 state_dir 를 쓰면 거부", raises(ConfigError, load_profile, main_p, "bad"))
        ck("경로 조작 이름 거부", raises(ConfigError, load_profile, main_p, "../a"))
        (Path(td) / "profiles" / "bad.json").unlink()

        # ---- run-due (가짜 브로커·고정 시각)
        brokers = {}

        def fake_make(cfg, env, execute):
            b = FakeBroker(cash={"KR": 1_000_000}, quotes={"005930": 70_000})
            brokers[cfg["profile"]] = b
            return b

        class FixedDT(datetime):
            @classmethod
            def now(cls, tz=None):
                return mon

        cli.make_broker, cli.datetime = fake_make, FixedDT
        cli.load_env = lambda: dict(PAPER)               # noqa: E731
        sent = []
        import autotrader.notify as N
        N.send_telegram = lambda tok, chat, text: sent.append(text)   # noqa: E731

        args = lambda ex: type("A", (), {"config": main_p, "execute": ex})()   # noqa: E731
        cli.cmd_run_due(args(False))
        ck("--execute 없으면 auto=execute 여도 주문 없음", brokers["a"].placed == [] and brokers["b"].placed == [])
        brokers.clear()
        cli.cmd_run_due(args(True))
        ck("같은 회차 두 번째 호출은 아무것도 안 돈다", brokers == {})

        for n in ("a", "b"):
            (Path(td) / "state" / "profiles" / n / "schedule.json").unlink()
        cli.cmd_run_due(args(True))
        ck("--execute + auto=execute 만 주문", len(brokers["a"].placed) == 1 and brokers["b"].placed == [])
        ck("주문 접수는 텔레그램 요약", any("접수 KR 005930 BUY" in t for t in sent) and all("12345678" not in t for t in sent))
        ck("원장이 프로필마다 따로", (Path(td) / "state" / "profiles" / "a" / "ledger.jsonl").exists()
           and not (Path(td) / "state" / "profiles" / "b" / "ledger.jsonl").exists())

        (Path(td) / "profiles" / "broken.json").write_text('{"mode": "x"}', encoding="utf-8")
        codes = [cli.cmd_run_due(args(True)), cli.cmd_run_due(args(True))]
        ck("깨진 프로필은 하루 한 번만 알림·종료코드 0(5분마다 장애 알림 폭주 방지)",
           sum("broken" in t for t in sent) == 1 and codes == [0, 0])
        (Path(td) / "profiles" / "broken.json").unlink()

        # ---- 웹: 프로필 카드·상세
        sdir = Path(td) / "state"
        store = A.AuthStore(sdir / "web_auth.json")
        store.save({"password": A.hash_password("pw-long-enough-1"), "totpSecret": A.new_totp_secret()})
        app = web.WebApp(normalize_config({**BASE, "state_dir": str(sdir)}), sdir, store, A.Sessions(), A.Lockout(),
                         secure_cookie=False, profiles=web._profile_loader(load_profile(main_p, "a"), main_p))
        tok = app.sessions.create()
        h = {"Cookie": f"at_sess={tok}"}
        st, _, body = app.handle("GET", "/", h, b"", "1.1.1.1")
        page = body.decode()
        ck("대시보드에 프로필 카드", st == 200 and "<h2>a</h2>" in page and "<h2>b</h2>" in page and "자동 주문" in page)
        st, _, body = app.handle("GET", "/details?p=a", h, b"", "1.1.1.1")
        ck("프로필 상세 200", st == 200 and "상세 · a" in body.decode())
        ck("없는 프로필 상세 404", app.handle("GET", "/details?p=zz", h, b"", "1.1.1.1")[0] == 404)
        ck("로그인 없이 프로필 상세 404", app.handle("GET", "/details?p=a", {}, b"", "1.1.1.1")[0] == 404)

    print(f"\ntest-autotrader-profiles {COUNT[0] - len(FAILS)}/{COUNT[0]}")
    return 1 if FAILS else 0


PAPER = {"KIS_VTS_APP_KEY": "k", "KIS_VTS_APP_SECRET": "s", "KIS_VTS_ACCOUNT_NO": "12345678-01",
         "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}

if __name__ == "__main__":
    sys.exit(main())
