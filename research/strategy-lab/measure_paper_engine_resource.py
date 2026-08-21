#!/usr/bin/env python
"""Paper Trading Engine 배포 타당성 조사 — 실제 하루 1회 크론 호출 패턴
(run_once, 캐시 미사용·전체 이력 스캔) 하나를 서브프로세스로 띄우고 psutil로
peak RSS/실행시간을 잰다. VM 배포 여부(1GB Oracle VM 그대로 vs 증설/별도
서버)를 사용자가 판단할 근거만 만든다 - 실행 인프라 자체는 안 만든다.

  python measure_paper_engine_resource.py --universe small   (5종목, 현재 더미 전략)
  python measure_paper_engine_resource.py --universe full    (2,558종목, 상한 스트레스)
"""
import argparse
import json
import os
import subprocess
import sys
import time

import psutil

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _worker_script(universe_mode, repo_root):
    strategy_lab = os.path.join(repo_root, "research", "strategy-lab")
    universe_expr = (
        '["005930","000660","035420","051910","005380"]' if universe_mode == "small"
        else 'sorted({e.ticker for e in UniverseProvider(repo_root=REPO_ROOT).entries})'
    )
    return f"""
import sys, os, time
REPO_ROOT = {repo_root!r}
sys.path.insert(0, {strategy_lab!r})
from engine.data.calendar import TradingCalendar
from engine.data.universeProvider import UniverseProvider
from engine.live.paperEngine import run_once

class _Rule:
    PARAMS = {{
        "strategyId": "resource_probe",
        "testUniverse": {universe_expr},
        "risk": {{"stopPct": 0.05, "targetPct": 0.10, "maxHoldingSessions": 20}},
        "position": {{"notionalPerPosition": 10000000, "maxPositions": 3}},
    }}
    def compute_features(self, bars):
        return bars
    def signal_fires(self, features, as_of):
        return False  # 순수 자원 측정 - 신호/체결 로직은 이미 검증됨(tests/test_paper_engine.py)

cal = TradingCalendar(repo_root=REPO_ROOT)
as_of = cal.days[-1]
t0 = time.time()
run_once(REPO_ROOT, _Rule(), as_of, log=lambda *a: None)
print(f"ELAPSED={{time.time()-t0:.1f}}")
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", choices=["small", "full"], default="small")
    args = ap.parse_args()

    script = _worker_script(args.universe, REPO_ROOT)
    proc = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    p = psutil.Process(proc.pid)

    peak_rss = 0
    t0 = time.time()
    while proc.poll() is None:
        try:
            rss = p.memory_info().rss
            for child in p.children(recursive=True):
                rss += child.memory_info().rss
            peak_rss = max(peak_rss, rss)
        except psutil.NoSuchProcess:
            break
        time.sleep(0.1)
    wall = time.time() - t0
    out, err = proc.communicate()

    result = {
        "universe": args.universe,
        "tickerCount": 5 if args.universe == "small" else None,
        "peakRssMB": round(peak_rss / (1024 * 1024), 1),
        "wallSeconds": round(wall, 1),
        "exitCode": proc.returncode,
        "stdout": out.strip(),
        "stderr": err.strip()[-2000:] if err else "",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
