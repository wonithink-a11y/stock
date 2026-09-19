"""명령행 — run · status · kill · resume · check-config.

    python -m autotrader check-config --config autotrader/autotrader.local.json
    python -m autotrader run --config autotrader/autotrader.local.json             # dry-run (기본, 주문 없음)
    python -m autotrader run --config autotrader/autotrader.local.json --execute   # 주문 (게이트 통과 시)
    python -m autotrader kill   /  python -m autotrader resume                     # 킬 스위치
    python -m autotrader status
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .config import (ConfigError, GateError, REPO_ROOT, gate_problems, kill_file, load_config, load_env, state_dir)
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
    return load_config(args.config)


def cmd_run(args) -> int:
    cfg = _cfg(args)
    env = load_env()
    try:
        strategy = load_strategy(cfg["strategy"])
        problems = gate_problems(cfg, env, args.execute)
        if problems:
            raise GateError(problems)
        broker = make_broker(cfg, env, args.execute)
        report = run_once(cfg, broker, strategy, execute=args.execute, env=env)
    except GateError as e:
        print("실행 거부 — 아래 조건이 안 맞는다:", file=sys.stderr)
        for p in e.problems:
            print(f"  - {p}", file=sys.stderr)
        return 2
    _print_report(report)
    return 0 if report["status"] == "ok" else 1


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
    snap = build_snapshot(cfg, make_broker(cfg, env, False), env, datetime.now(KST))
    p = write_snapshot(cfg, snap)
    errs = [f"{m}: {d['error']}" for m, d in snap["markets"].items() if d.get("error")]
    print(f"스냅샷 저장 {p}" + (" · 오류 " + "; ".join(errs) if errs else ""))
    return 1 if errs else 0


def cmd_serve(args) -> int:
    from .web import serve
    serve(_cfg(args), host=args.host, port=args.port, secure_cookie=not args.insecure_cookie, base=args.base_path)
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
    store.save({"password": hash_password(pw), "totpSecret": secret})
    print("\n설정 완료. 인증앱(Google Authenticator·Microsoft Authenticator 등)에 아래 키를 '직접 입력'으로 등록하세요.")
    print(f"  계정 이름: autotrader   키(공백 없이): {secret}")
    print("  (이 키는 지금 한 번만 보여 줍니다. 화면을 닫기 전에 등록하세요. 다른 사람에게 보여주지 마세요.)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="autotrader")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--execute", action="store_true", help="실제 주문을 낸다. 없으면 dry-run")
    for name in ("check-config", "status", "kill", "resume", "snapshot"):
        sub.add_parser(name)
    sv = sub.add_parser("serve")
    sv.add_argument("--host", default="127.0.0.1", help="기본 127.0.0.1 — 앞단 HTTPS 프록시 뒤에서만 쓴다")
    sv.add_argument("--port", type=int, default=8787)
    sv.add_argument("--base-path", default="", help="앞단 프록시가 이 경로 아래로 넘겨줄 때(예: /autotrader). 비우면 루트")
    sv.add_argument("--insecure-cookie", action="store_true", help="HTTPS 없이 로컬 시험할 때만")
    ws = sub.add_parser("web-setup")
    ws.add_argument("--reset", action="store_true")
    args = ap.parse_args(argv)
    fn = {"run": cmd_run, "check-config": cmd_check, "status": cmd_status,
          "kill": cmd_kill, "resume": cmd_resume, "snapshot": cmd_snapshot,
          "serve": cmd_serve, "web-setup": cmd_web_setup}[args.cmd]
    try:
        return fn(args)
    except ConfigError as e:
        print(f"설정 오류: {e}", file=sys.stderr)
        return 2
