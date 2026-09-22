"""명령행 — run · status · kill · resume · check-config.

    python -m autotrader check-config --config autotrader/autotrader.local.json
    python -m autotrader run --config autotrader/autotrader.local.json             # dry-run (기본, 주문 없음)
    python -m autotrader run --config autotrader/autotrader.local.json --execute   # 주문 (게이트 통과 시)
    python -m autotrader kill   /  python -m autotrader resume                     # 킬 스위치
    python -m autotrader status

프로필(키 묶음 + 전략 + 한도 + 일정을 이름 하나로) — README §8:
    python -m autotrader profiles                                   # 목록·키 유무·마지막 예약 실행
    python -m autotrader new-profile 이름 --strategy target_weights --key-prefix KIS_VTS
    python -m autotrader --profile 이름 run                         # 모든 명령에 --profile 을 붙일 수 있다
    python -m autotrader run-due [--execute]                         # 타이머가 5분마다 부른다 — 예약 시각이 된 프로필만 실행
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import (ConfigError, GateError, REPO_ROOT, due_slots, gate_problems, key_names, kill_file,
                     list_profiles, load_config, load_env, load_profile, profiles_dir, state_dir, take_run_request)
from .engine import KST, Ledger, run_once
from .kis import make_broker
from .strategy import load_strategy

DEFAULT_CONFIG = REPO_ROOT / "autotrader" / "autotrader.local.json"


def _print_report(r: dict) -> None:
    tag = "주문 실행" if r["execute"] else "dry-run(주문 없음)"
    print(f"[{r['runId']}] {r['mode']} · {r['strategy']} · {tag} · 상태 {r['status']}")
    for k, label in (("planned", "계획"), ("placed", "접수"), ("rejected", "위험 검사 거부"),
                     ("skipped", "건너뜀"), ("cancelled", "취소"), ("errors", "오류")):
        items = r.get(k) or []
        if not items:
            continue
        print(f"  {label} {len(items)}건")
        for x in items:
            if isinstance(x, str):
                print(f"    - {x}")
            else:
                print("    - " + " ".join(f"{a}={b}" for a, b in x.items() if b not in (None, "")))


def _cfg(args):
    if getattr(args, "profile", None):
        return load_profile(args.config, args.profile)
    return load_config(args.config)


def _run(cfg: dict, env: dict, execute: bool):
    """한 설정(프로필)을 한 번 돌린다 → (종료코드, 리포트 또는 None=게이트 거부)."""
    try:
        strategy = load_strategy(cfg["strategy"])
        problems = gate_problems(cfg, env, execute)
        if problems:
            raise GateError(problems)
        broker = make_broker(cfg, env, execute)
        report = run_once(cfg, broker, strategy, execute=execute, env=env)
    except GateError as e:
        print("실행 거부 — 아래 조건이 안 맞는다:", file=sys.stderr)
        for p in e.problems:
            print(f"  - {p}", file=sys.stderr)
        return 2, None
    _print_report(report)
    return (0 if report["status"] == "ok" else 1), report


def cmd_run(args) -> int:
    return _run(_cfg(args), load_env(), args.execute)[0]


def run_summary(name: str, r: Optional[dict]) -> str:
    """텔레그램용 한 덩어리 요약. 계좌번호·금액 한도 같은 건 넣지 않는다."""
    if r is None:
        return f"[autotrader] {name}: 실행 거부(조건 미충족) — autotrader.log 확인"
    lines = [f"[autotrader] {name} · {r.get('strategy')} · {'모의' if r.get('mode') == 'paper' else '실전'}"
             f" · {'주문' if r.get('execute') else 'dry-run'} · {r.get('status')}"]
    for x in r.get("placed") or []:
        lines.append(f"접수 {x.get('market')} {x.get('symbol')} {x.get('side')} {x.get('qty')}")
    lines += [f"오류 {e}"[:200] for e in r.get("errors") or []]
    return "\n".join(lines)


def cmd_run_due(args) -> int:
    """예약 시각이 된 프로필을 돈다. 주문은 `--execute` **와** 프로필 auto=execute 가 둘 다 있어야 나간다.
    회차는 성공·실패와 무관하게 한 번만 돈다(재시도로 중복 주문을 내지 않는다). 주문 접수·오류·거부는 텔레그램으로 알린다."""
    import json
    from .notify import send_telegram
    main_cfg = load_config(args.config)
    env = load_env()
    now = datetime.now(KST)
    worst = 0
    for name in list_profiles(args.config):
        try:
            cfg = load_profile(args.config, name, main_cfg)
        except (ConfigError, ValueError) as e:
            # 5분마다 불리므로 종료코드로 알리면 장애 알림이 하루 288통이 된다 — 프로필당 하루 한 번만 텔레그램.
            print(f"[{name}] 프로필 오류: {e}", file=sys.stderr)
            flag = state_dir(main_cfg) / f"profile_error_{name}.txt"
            day = now.strftime("%Y-%m-%d")
            if not (flag.exists() and flag.read_text(encoding="utf-8") == day) and env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
                try:
                    send_telegram(env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"], f"[autotrader] 프로필 {name} 설정 오류 — 실행 안 함: {e}"[:300])
                    flag.parent.mkdir(parents=True, exist_ok=True)
                    flag.write_text(day, encoding="utf-8")
                except Exception as te:                 # noqa: BLE001
                    print(f"[{name}] 텔레그램 실패: {te}", file=sys.stderr)
            continue
        sfile = state_dir(cfg) / "schedule.json"
        done = json.loads(sfile.read_text(encoding="utf-8")) if sfile.exists() else []
        slots = due_slots(cfg, now, done)
        asked = take_run_request(cfg, now)              # 웹의 "지금 실행" — 소비하고 나서 돈다
        if not slots and not asked:
            continue
        if slots:
            sfile.parent.mkdir(parents=True, exist_ok=True)
            sfile.write_text(json.dumps((done + slots)[-50:]), encoding="utf-8")    # 실행 전에 기록 — 도중에 죽어도 같은 회차를 다시 안 돈다
        execute = args.execute and cfg["auto"] == "execute"
        why = f"예약 {slots[-1]}" if slots else f"웹 요청 {asked[11:16]}"
        print(f"[{name}] {now.isoformat()[:19]} {why} · {'주문' if execute else 'dry-run'}", flush=True)
        try:
            code, rep = _run(cfg, env, execute)
        except Exception as e:                          # noqa: BLE001 — 한 프로필의 실패가 다른 프로필을 막지 않는다
            print(f"[{name}] 실행 오류: {type(e).__name__}: {e}", file=sys.stderr)
            code, rep = 1, {"strategy": cfg["strategy"], "mode": cfg["mode"], "execute": execute,
                            "status": "crash", "errors": [f"{type(e).__name__}: {e}"]}
        worst = max(worst, code)
        if (rep is None or rep.get("placed") or rep.get("errors") or asked) and env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
            try:
                send_telegram(env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"], run_summary(name, rep))
            except Exception as e:                      # noqa: BLE001 — 알림 실패가 실행 결과를 바꾸지 않는다
                print(f"[{name}] 텔레그램 실패: {e}", file=sys.stderr)
    return worst


def cmd_profiles(args) -> int:
    import json
    main_cfg = load_config(args.config)
    env = load_env()
    print(f"프로필 폴더: {profiles_dir(args.config)}")
    sdir = Path(__file__).resolve().parent / "strategies"
    print("쓸 수 있는 전략:", ", ".join(sorted(p.stem for p in sdir.glob("*.py") if not p.stem.startswith("_"))))
    names = list_profiles(args.config)
    if not names:
        print("프로필이 없다 — new-profile 로 만든다")
    for n in names:
        try:
            c = load_profile(args.config, n, main_cfg)
        except (ConfigError, ValueError) as e:
            print(f"- {n}: 설정 오류 — {e}")
            continue
        keys = key_names(c)
        miss = [k for k in keys if not env.get(k)]
        sfile = state_dir(c) / "schedule.json"
        last = ((json.loads(sfile.read_text(encoding="utf-8")) or ["-"])[-1]) if sfile.exists() else "-"
        print(f"- {n}: 전략 {c['strategy']} · {c['mode']} · 키 {keys[0][:-len('_APP_KEY')]}"
              f"({'있음' if not miss else '없음: ' + ', '.join(miss)}) · 자동 {c['auto']} {','.join(c['run_at']) or '-'}"
              f" {c['days']} · 킬 {'ON' if kill_file(c).exists() else 'OFF'} · 마지막 예약 실행 {last}")
    return 0


def cmd_new_profile(args) -> int:
    """프로필 파일을 만든다. 자동 실행은 꺼진(auto=off) 상태, 허용 종목은 빈 상태로 — 채우는 건 사용자."""
    import json
    from .config import _PROFILE
    if not _PROFILE.match(args.name):
        print("프로필 이름은 소문자·숫자·-·_ 만(32자 이내)", file=sys.stderr)
        return 2
    try:
        load_strategy(args.strategy)                    # 없는 전략이면 여기서 멈춘다
    except (ImportError, ValueError) as e:
        print(f"전략을 불러올 수 없다({args.strategy}): {e} — `profiles` 로 쓸 수 있는 전략을 본다", file=sys.stderr)
        return 2
    d = profiles_dir(args.config)
    p = d / f"{args.name}.json"
    if p.exists():
        print(f"이미 있다: {p}", file=sys.stderr)
        return 2
    ex = json.loads((Path(__file__).resolve().parent / "config.example.json").read_text(encoding="utf-8"))
    markets = args.markets.split(",")
    prof = {"strategy": args.strategy, "params": ex["params"] if args.strategy == ex["strategy"] else {},
            "mode": args.mode, "key_prefix": args.key_prefix, "markets": markets, "symbol_allowlist": [],
            "risk": {m: ex["risk"][m] for m in markets if m in ex["risk"]},
            "auto": "off", "run_at": ["09:10"], "days": "weekdays", "live": ex["live"]}
    from .config import normalize_config
    normalize_config({**prof, "state_dir": "x"})         # 쓰기 전에 형식 검증(틀리면 설정 오류로 멈춘다)
    d.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(prof, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"만들었다: {p}")
    print("다음: 파일을 열어 symbol_allowlist·params·run_at 을 채우고, 먼저 auto 를 \"dry\" 로 둔다")
    return 0


def cmd_check(args) -> int:
    cfg = _cfg(args)
    env = load_env()
    print(f"설정 OK — 전략 {cfg['strategy']} · mode {cfg['mode']} · 시장 {cfg['markets']}")
    for label, ex in (("dry-run", False), ("--execute", True)):
        p = gate_problems(cfg, env, ex)
        print(f"{label}: " + ("통과" if not p else "막힘"))
        for x in p:
            print(f"  - {x}")
    return 0


def cmd_status(args) -> int:
    cfg = _cfg(args)
    kf = kill_file(cfg)
    print("킬 스위치:", "켜져 있음 (" + kf.read_text(encoding="utf-8").strip() + ")" if kf.exists() else "꺼져 있음")
    rows = Ledger(state_dir(cfg)).rows()
    print(f"원장 {len(rows)}건. 최근 10건:")
    for r in rows[-10:]:
        print("  ", r.get("ts", "")[:19], r.get("kind"), r.get("market"), r.get("symbol"), r.get("side"),
              r.get("qty"), r.get("orderNo") or r.get("error", ""))
    return 0


def cmd_kill(args) -> int:
    cfg = _cfg(args)
    kf = kill_file(cfg)
    kf.parent.mkdir(parents=True, exist_ok=True)
    kf.write_text(datetime.now(KST).isoformat(), encoding="utf-8")
    print(f"킬 스위치 ON — {kf}. 이후 --execute 는 주문 직전에 중단한다. 해제: python -m autotrader resume")
    return 0


def cmd_resume(args) -> int:
    kf = kill_file(_cfg(args))
    if kf.exists():
        kf.unlink()
    print("킬 스위치 OFF")
    return 0


def cmd_snapshot(args) -> int:
    """브로커를 읽기 전용으로 조회해 state/snapshot.json 을 갱신한다(웹 화면이 읽는다). 주문은 절대 안 낸다."""
    from .snapshot import build_snapshot, write_snapshot
    cfg = _cfg(args)
    env = load_env()
    problems = gate_problems(cfg, env, False)
    if problems:
        print("스냅샷 거부 — 키가 없다:", "; ".join(problems), file=sys.stderr)
        return 2
    worst = 0
    targets = [cfg]
    if not getattr(args, "profile", None):              # 기본 설정 + 모든 프로필(웹 화면이 전부 보여 준다)
        for n in list_profiles(args.config):
            try:
                targets.append(load_profile(args.config, n, cfg))
            except (ConfigError, ValueError) as e:
                print(f"[{n}] 프로필 오류: {e}", file=sys.stderr)
                worst = 1
    for c in targets:
        tag = c.get("profile", "기본")
        if c is not cfg and gate_problems(c, env, False):
            print(f"[{tag}] 키 없음 — 건너뜀", file=sys.stderr)
            continue
        try:
            broker, now = make_broker(c, env, False), datetime.now(KST)
            snap = build_snapshot(c, broker, env, now)
        except Exception as e:                          # noqa: BLE001 — 한 프로필의 실패가 다른 프로필을 막지 않는다
            print(f"[{tag}] 스냅샷 실패: {type(e).__name__}: {e}", file=sys.stderr)
            worst = 1
            continue
        if c is not cfg:                                # 프로필만 실현손익(우리 주문번호의 체결 → fills.json)
            from .pnl import realized, sync_fills
            try:
                snap["realized"] = realized(sync_fills(c, broker, snap, now))
            except Exception as e:                      # noqa: BLE001 — 체결 조회 실패가 보유 화면을 막지 않는다
                snap["realizedError"] = f"{type(e).__name__}: {e}"[:200]
                print(f"[{tag}] 체결 조회 실패: {snap['realizedError']}", file=sys.stderr)
        p = write_snapshot(c, snap)
        errs = [f"{m}: {d['error']}" for m, d in snap["markets"].items() if d.get("error")]
        print(f"[{tag}] 스냅샷 저장 {p}" + (" · 오류 " + "; ".join(errs) if errs else ""))
        worst = max(worst, 1 if errs else 0)
    return worst


def cmd_serve(args) -> int:
    from .web import serve
    serve(_cfg(args), host=args.host, port=args.port, secure_cookie=not args.insecure_cookie, base=args.base_path,
          config_path=args.config)
    return 0


def cmd_web_setup(args) -> int:
    """웹 화면의 비밀번호와 인증앱(TOTP)을 처음 설정한다. 비밀번호는 화면에 안 보이게 입력받는다(getpass)."""
    import getpass
    from .web_auth import AuthStore, hash_password, new_totp_secret, otpauth_uri
    cfg = _cfg(args)
    store = AuthStore(state_dir(cfg) / "web_auth.json")
    if store.exists() and not args.reset:
        print("이미 설정돼 있다. 다시 하려면 --reset", file=sys.stderr)
        return 2
    pw = getpass.getpass("새 비밀번호(12자 이상): ")
    if len(pw) < 12:
        print("12자 이상이어야 한다", file=sys.stderr)
        return 2
    if getpass.getpass("한 번 더: ") != pw:
        print("두 번이 다르다", file=sys.stderr)
        return 2
    secret = new_totp_secret()
    gen = max(store.session_gen(), 0) + 1 if store.exists() else 0     # 재설정이면 그 전의 모든 로그인을 끊는다(N3)
    store.save({"password": hash_password(pw), "totpSecret": secret, "sessGen": gen})
    print("\n설정 완료. 인증앱(Google Authenticator·Microsoft Authenticator 등)에 아래 키를 '직접 입력'으로 등록하세요.")
    print(f"  계정 이름: autotrader   키(공백 없이): {secret}")
    print("  (이 키는 지금 한 번만 보여 줍니다. 화면을 닫기 전에 등록하세요. 다른 사람에게 보여주지 마세요.)")
    return 0


def cmd_passkey_enroll(args) -> int:
    """패스키 등록 코드(1회용·15분)를 발급한다 — **서버에서만**. 웹의 '패스키 관리'에 이 코드를 넣어야 등록이 시작된다."""
    import time as _t
    from .web_auth import AuthStore
    store = AuthStore(state_dir(_cfg(args)) / "web_auth.json")
    if not store.exists():
        print("웹 인증 설정이 없다(web-setup 먼저)", file=sys.stderr)
        return 2
    print(f"패스키 등록 코드: {store.issue_enroll_code(_t.time())}   (15분 안에 한 번만 쓸 수 있다)")
    return 0


def cmd_passkey_reset(args) -> int:
    """등록된 패스키를 전부 지운다 — **서버에서만**(웹에는 삭제 기능이 없다: 지울 수 있으면 공격자가 지우고 코드 방식으로 되돌린다)."""
    from .web_auth import AuthStore
    store = AuthStore(state_dir(_cfg(args)) / "web_auth.json")
    if not store.exists():
        print("웹 인증 설정이 없다", file=sys.stderr)
        return 2
    n = [0]

    def fn(r):
        n[0] = len(r.pop("passkeys", None) or [])
        r["sessGen"] = int(r.get("sessGen") or 0) + 1          # 모든 로그인도 끊는다(N3)
    store.update(fn)
    print(f"패스키 {n[0]}개를 지우고 모든 기기를 로그아웃시켰다. 웹 서비스 재시작은 필요 없다. 웹 '패스키 관리'가 0개인지 확인.")
    return 0


def cmd_logout_all(args) -> int:
    """모든 기기의 웹 로그인을 끊는다 — **서버에서만**. 재시작 필요 없음(웹이 요청마다 세대를 확인한다)."""
    from .web_auth import AuthStore
    store = AuthStore(state_dir(_cfg(args)) / "web_auth.json")
    if not store.exists():
        print("웹 인증 설정이 없다", file=sys.stderr)
        return 2
    store.bump_session_gen()
    print("모든 기기를 로그아웃시켰다. 다시 로그인하려면 비밀번호 + 인증앱 코드.")
    return 0


def cmd_notify(args) -> int:
    """로그인 기록을 텔레그램으로 알린다. 토큰은 이 프로세스만 가진다(웹 프로세스는 없다)."""
    from .notify import LoginNotifier, run_loop, send_telegram
    cfg = _cfg(args)
    env = load_env()
    tok, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("환경변수 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 없다(값은 출력하지 않는다)", file=sys.stderr)
        return 2
    send = lambda text: send_telegram(tok, chat, text)   # noqa: E731
    if args.test:
        send("🔔 autotrader 텔레그램 알림 테스트 — 이 메시지가 보이면 연결이 정상입니다.")
        print("테스트 메시지를 보냈다")
        return 0
    sdir = state_dir(cfg)
    n = LoginNotifier(sdir / "web_login.log", sdir / "notify_offset.txt", send)
    if args.once:
        print(f"보낸 알림 {n.poll()}통")
        return 0
    run_loop(n)
    return 0


def cmd_chat_id(args) -> int:
    """내 텔레그램 채팅 번호 찾기 — 봇에게 아무 말이나 보낸 뒤 실행한다. 필요한 값은 TELEGRAM_BOT_TOKEN 하나뿐."""
    from .notify import find_chat_ids
    env = load_env()
    tok = env.get("TELEGRAM_BOT_TOKEN")
    if not tok:
        print("환경변수 TELEGRAM_BOT_TOKEN 이 없다(값은 출력하지 않는다)", file=sys.stderr)
        return 2
    from .notify import bot_username
    print(f"이 토큰의 봇: {bot_username(tok)}   ← 텔레그램에서 **이 봇**에게 말을 걸어야 한다")
    found = find_chat_ids(tok)
    if not found:
        print("찾은 대화가 없다. 텔레그램에서 위의 봇에게 아무 말이나(예: 안녕) 보낸 뒤 다시 실행한다.")
        return 1
    for c in found:
        print(f"채팅 번호: {c['id']}   (종류: {c['type']}, 이름: {c['name']})")
    print("1:1 대화(private)의 번호를 TELEGRAM_CHAT_ID= 에 넣는다.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="autotrader")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--profile", help="기본 설정 대신 profiles/<이름>.json 으로 실행")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--execute", action="store_true", help="실제 주문을 낸다. 없으면 dry-run")
    rd = sub.add_parser("run-due")
    rd.add_argument("--execute", action="store_true", help="auto=execute 프로필만 주문. 없으면 전부 dry-run")
    sub.add_parser("profiles")
    npf = sub.add_parser("new-profile")
    npf.add_argument("name")
    npf.add_argument("--strategy", required=True)
    npf.add_argument("--key-prefix", default="KIS_VTS", help="키 이름 앞부분(예: KIS_VTS → KIS_VTS_APP_KEY ...)")
    npf.add_argument("--mode", choices=("paper", "live"), default="paper")
    npf.add_argument("--markets", default="KR", help="KR 또는 US 또는 KR,US")
    for name in ("check-config", "status", "kill", "resume", "snapshot"):
        sub.add_parser(name)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1", help="기본 127.0.0.1 — 앞단 HTTPS 프록시 뒤에서만 쓴다")
    sv.add_argument("--port", type=int, default=8787)
    sv.add_argument("--base-path", default="", help="앞단 프록시가 이 경로 아래로 넘겨줄 때(예: /autotrader). 비우면 루트")
    sv.add_argument("--insecure-cookie", action="store_true", help="HTTPS 없이 로컬 시험할 때만")
    nt = sub.add_parser("notify-logins")
    nt.add_argument("--test", action="store_true", help="테스트 메시지 한 통만 보내고 끝낸다")
    nt.add_argument("--once", action="store_true", help="한 번만 확인하고 끝낸다(기본은 계속 감시)")
    sub.add_parser("telegram-chat-id")
    sub.add_parser("passkey-reset")
    sub.add_parser("logout-all")
    sub.add_parser("passkey-enroll")
    ws = sub.add_parser("web-setup")
    ws.add_argument("--reset", action="store_true")
    args = ap.parse_args(argv)
    fn = {"run": cmd_run, "check-config": cmd_check, "status": cmd_status,
          "kill": cmd_kill, "resume": cmd_resume, "snapshot": cmd_snapshot,
          "serve": cmd_serve, "web-setup": cmd_web_setup, "run-due": cmd_run_due,
          "profiles": cmd_profiles, "new-profile": cmd_new_profile, "notify-logins": cmd_notify, "telegram-chat-id": cmd_chat_id,
          "passkey-reset": cmd_passkey_reset, "passkey-enroll": cmd_passkey_enroll, "logout-all": cmd_logout_all}[args.cmd]
    try:
        return fn(args)
    except ConfigError as e:
        print(f"설정 오류: {e}", file=sys.stderr)
        return 2
