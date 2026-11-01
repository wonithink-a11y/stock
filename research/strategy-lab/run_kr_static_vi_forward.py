#!/usr/bin/env python3
"""정적 VI 근사 VU forward 기록. 사전등록 findings/kr-static-vi-forward-preregistration-2026-11.md.

    python3 research/strategy-lab/run_kr_static_vi_forward.py record     # VM(타이머 vi-forward): ~/minute-raw → ~/collector-venv/vi-forward/daily.jsonl + _status 복사
    python3 research/strategy-lab/run_kr_static_vi_forward.py sync       # 클라우드·PC(월간 점검): /research-data/_status/vi-forward.jsonl → reports/ 원장(처음 본 값 고정)
    python3 research/strategy-lab/run_kr_static_vi_forward.py --judge    # 관측일 100 ∧ 2027-05-03 전에는 건수만
    python3 research/strategy-lab/run_kr_static_vi_forward.py --selftest

사건·진입·청산·하위 표본 컷은 kr_static_vi_proxy.day_events · kr_static_vi_liquid.turnover 그대로. 기록 전용 — 매매·알림 없음.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import shutil
import sys
import warnings
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

START = "2026-11-02"
TOP = 200
COST = 33.5
STAGES = [("first", "2027-05-03", 100), ("final", "2027-11-01", 200)]
VM_DIR = Path(os.path.expanduser("~/collector-venv/vi-forward"))
STATUS = Path(os.environ.get("VI_FORWARD_STATUS", "/srv/stock-data/bundles/_status/vi-forward.jsonl"))
REPORT = ROOT / "reports" / "2026-11-kr-static-vi-forward"
KST = dt.timezone(dt.timedelta(hours=9))


def read_jsonl(p: Path) -> list:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def summarize(day: str, events: list, top: set | None) -> dict:
    row = {"day": day, "skipped": sum(1 for e in events if e["cell"] == "VU" and "skip" in e)}
    vu = [e for e in events if e["cell"] == "VU" and "ret_close" in e]
    for name, sub in (("VU", vu), ("VU_L", [e for e in vu if top is not None and e["ticker"] in top]),
                      ("VU_S", [e for e in vu if top is not None and e["ticker"] not in top])):
        r = [e["ret_close"] for e in sub]
        r19 = [e["ret_1519"] for e in sub if "ret_1519" in e]
        row[name] = {"n": len(r), "mean_bp": round(float(np.mean(r)), 2) if r else None,
                     "mean_1519_bp": round(float(np.mean(r19)), 2) if r19 else None}
    if top is None:
        row["VU_L"] = row["VU_S"] = None                 # 전날 분봉이 없으면 컷을 모른다(교훈57)
    return row


def cmd_record(minute_dir: str) -> int:
    import kr_static_vi_proxy as vp
    import kr_static_vi_liquid as vl
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    VM_DIR.mkdir(parents=True, exist_ok=True)
    led = VM_DIR / "daily.jsonl"
    done = {r["day"] for r in read_jsonl(led)}
    days = sorted(p.split("date=", 1)[1] for p in glob.glob(os.path.join(minute_dir, "date=*")))
    passed = {Path(p).stem for p in glob.glob(os.path.join(minute_dir, "_manifest", "*.json"))}
    new = []
    for i, d in enumerate(days):
        if d < START or d in done or d not in passed:
            continue
        prev = days[i - 1] if i else None
        top = set(vl.turnover(os.path.join(minute_dir, f"date={prev}")).nlargest(TOP).index) if prev else None
        new.append(summarize(d, vp.day_events(vp.read_day(os.path.join(minute_dir, f"date={d}")), d), top))
    with led.open("a", encoding="utf-8") as f:
        for r in new:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(led, STATUS)
    print(f"{dt.datetime.now(KST):%Y-%m-%d %H:%M} 새 날 {len(new)} {[r['day'] for r in new]} · 누계 {len(done) + len(new)} → {STATUS}")
    return 0


def cmd_sync() -> int:
    import importlib.util
    spec = importlib.util.spec_from_file_location("rd", ROOT / "scripts" / "research-data.py")
    rd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rd)
    with rd.http_get("_status/vi-forward.jsonl", rd.data_key()) as r:
        remote = [json.loads(x) for x in r.read().decode("utf-8").splitlines() if x.strip()]
    REPORT.mkdir(parents=True, exist_ok=True)
    led, drift = REPORT / "daily.jsonl", REPORT / "drift.jsonl"
    have = {r["day"]: r for r in read_jsonl(led)}
    add, dr = [], []
    for r in remote:
        if r["day"] not in have:
            add.append(r)
        elif r != have[r["day"]]:
            dr.append({"day": r["day"], "seen": have[r["day"]], "now": r})
    with led.open("a", encoding="utf-8") as f:
        for r in sorted(add, key=lambda x: x["day"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if dr:
        with drift.open("a", encoding="utf-8") as f:
            for r in dr:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"원격 {len(remote)}일 · 새로 {len(add)} · 달라진 날 {len(dr)} → {led.relative_to(ROOT)}")
    return 0


def tstat(x) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 2 and x.std(ddof=1) > 0 else float("nan")


def judge(rows: list, today: str) -> dict:
    obs = {c: [-r[c]["mean_bp"] for r in rows if r.get(c) and r[c]["mean_bp"] is not None] for c in ("VU", "VU_L", "VU_S")}
    n = len(obs["VU"])
    stage = next(((nm, d, k) for nm, d, k in STAGES if not (today >= d and n >= k)), None)
    due = [(nm, d, k) for nm, d, k in STAGES if today >= d and n >= k]
    if not due:
        return {"due": False, "n": n, "next": stage}
    out = {"due": True, "stage": due[-1][0], "n": n, "cells": {}}
    for c, x in obs.items():
        x = np.asarray(x, float)
        net = x - COST
        v = "CONFIRMED" if len(x) and net.mean() > 0 and tstat(net) >= 2 else "FADED" if len(x) and x.mean() <= 0 else "INCONCLUSIVE"
        out["cells"][c] = {"verdict": v, "days": int(len(x)), "short_gross_bp": round(float(x.mean()), 1) if len(x) else None,
                           "short_net_bp": round(float(net.mean()), 1) if len(x) else None, "t_net": round(tstat(net), 2)}
    out["verdict"] = out["cells"]["VU"]["verdict"]
    return out


def cmd_judge() -> int:
    rows = read_jsonl(REPORT / "daily.jsonl")
    res = judge(rows, dt.datetime.now(KST).date().isoformat())
    if not res["due"]:
        print(f"거부: 판정 전 — VU 관측일 {res['n']}, 다음 단계 {res['next']} (중간 숫자는 보지 않는다)")
        return 0
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


def selftest() -> int:
    ev = [{"cell": "VU", "ticker": "A", "ret_close": -100.0, "ret_1519": -80.0}, {"cell": "VU", "ticker": "B", "ret_close": -300.0},
          {"cell": "VU", "ticker": "C", "skip": "locked"}, {"cell": "VD", "ticker": "D", "ret_close": 50.0}]
    r = summarize("2026-11-02", ev, {"A"})
    assert r["VU"] == {"n": 2, "mean_bp": -200.0, "mean_1519_bp": -80.0} and r["skipped"] == 1
    assert r["VU_L"]["n"] == 1 and r["VU_L"]["mean_bp"] == -100.0 and r["VU_S"]["mean_bp"] == -300.0
    assert summarize("2026-11-02", ev, None)["VU_L"] is None
    rows = [{"day": f"d{i}", "VU": {"mean_bp": -200.0 - (i % 7) * 10}, "VU_L": None, "VU_S": None} for i in range(120)]
    assert judge(rows, "2027-05-02")["due"] is False and judge(rows[:99], "2027-06-01")["due"] is False   # 날짜·건수 둘 다
    j = judge(rows, "2027-05-03")
    assert j["due"] and j["stage"] == "first" and j["verdict"] == "CONFIRMED", j
    flat = [{"day": "x", "VU": {"mean_bp": 5.0 + (i % 3)}} for i in range(120)]
    assert judge(flat, "2027-05-03")["verdict"] == "FADED"
    print("selftest ok")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["record", "sync"])
    ap.add_argument("--minute-dir", default=os.path.expanduser("~/minute-raw"))
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else cmd_judge() if a.judge else cmd_record(a.minute_dir) if a.cmd == "record"
             else cmd_sync() if a.cmd == "sync" else ap.error("record / sync / --judge / --selftest"))
