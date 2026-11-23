"""RP-2.0 시도 장부 — 표본별 누적 시도 칸 수(누적 K)와 그것을 반영한 BH.

  python research/strategy-lab/trials.py count us
  python research/strategy-lab/trials.py log --sample us --lane E --cells 4 --what "진바닥 4칸" [--file findings/x.md]
  python research/strategy-lab/trials.py seed      # RP-1.0 결과 파일 수로 시작값(한 번만)
  python research/strategy-lab/trials.py --selftest

장부: research/strategy-lab/trial-log.jsonl (덧붙이기만, 고쳐 쓰지 않는다).
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
LOG = HERE / "trial-log.jsonl"
REG = HERE / "findings" / "_registry.jsonl"
KNOWN_GRIDS = {"global": 1194}       # 조건 격자 L2 K (condition-grid §2-1)


def _rows(path=LOG):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def count(sample, path=LOG):
    return sum(int(r["cells"]) for r in _rows(path) if r["sample"] == sample)


def log(sample, lane, cells, what, file=None, path=LOG):
    if lane not in ("S", "E", "C", "v1-seed"):
        raise SystemExit("lane 은 S·E·C 중 하나")
    row = {"at": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M KST"),
           "sample": sample, "lane": lane, "cells": int(cells), "what": what, "file": file}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def seed(path=LOG):
    if any(r["lane"] == "v1-seed" for r in _rows(path)):
        raise SystemExit("이미 시작값이 있다")
    c = Counter()
    for l in REG.read_text(encoding="utf-8").splitlines():
        d = json.loads(l)
        if d.get("verdict") != "PREREGISTERED":
            c[d.get("track") or "unknown"] += 1
    for k, n in sorted(c.items()):
        log(k, "v1-seed", n + KNOWN_GRIDS.get(k, 0),
            f"RP-1.0 결과 파일 {n}개(하한)" + (f" + 알려진 격자 K {KNOWN_GRIDS[k]}" if k in KNOWN_GRIDS else ""), path=path)
    return c


def bh_with_prior(pvals, sample=None, q=0.10, prior=None, path=LOG):
    """누적 칸을 p=1 시험으로 채운 BH. 반환: (조정 p 리스트, 통과 여부 리스트, 가족 크기 m)."""
    prior = count(sample, path) if prior is None else prior
    m = len(pvals) + prior
    order = sorted(range(len(pvals)), key=lambda i: pvals[i])
    adj = [1.0] * len(pvals)
    run = 1.0
    for rank in range(len(pvals), 0, -1):          # 채운 p=1 들은 순위가 뒤라 앞 순위 값에 영향 없음
        i = order[rank - 1]
        run = min(run, pvals[i] * m / rank)
        adj[i] = min(run, 1.0)
    return adj, [a <= q for a in adj], m


def selftest():
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / "t.jsonl"
    log("us", "E", 4, "a", path=tmp); log("us", "S", 10, "b", path=tmp); log("kr", "E", 3, "c", path=tmp)
    assert count("us", tmp) == 14 and count("kr", tmp) == 3 and count("x", tmp) == 0
    adj, ok, m = bh_with_prior([0.001, 0.02, 0.5, 0.04], prior=0)
    assert m == 4 and ok == [True, True, False, True] and abs(adj[0] - 0.004) < 1e-12
    adj, ok, m = bh_with_prior([0.001, 0.02, 0.5, 0.04], prior=96)
    assert m == 100 and ok == [True, False, False, False] and abs(adj[0] - 0.1) < 1e-12
    try:
        log("us", "X", 1, "bad", path=tmp); raise AssertionError
    except SystemExit:
        pass
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["count", "log", "seed"])
    ap.add_argument("sample_pos", nargs="?")
    ap.add_argument("--sample"); ap.add_argument("--lane"); ap.add_argument("--cells", type=int)
    ap.add_argument("--what"); ap.add_argument("--file")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.cmd == "count":
        print(count(a.sample_pos or a.sample))
    elif a.cmd == "log":
        print(log(a.sample, a.lane, a.cells, a.what, a.file))
    elif a.cmd == "seed":
        print(dict(seed()))
    else:
        ap.print_help(); sys.exit(1)
