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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="autotrader")
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--execute", action="store_true", help="실제 주문을 낸다. 없으면 dry-run")
    for name in ("check-config", "status", "kill", "resume"):
        sub.add_parser(name)
    args = ap.parse_args(argv)
    fn = {"run": cmd_run, "check-config": cmd_check, "status": cmd_status,
          "kill": cmd_kill, "resume": cmd_resume}[args.cmd]
    try:
        return fn(args)
    except ConfigError as e:
        print(f"설정 오류: {e}", file=sys.stderr)
        return 2
