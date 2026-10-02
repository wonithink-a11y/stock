#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""급등 군집 관찰 기록 - docs/data/market-movers.json 의 새 거래일을 clusters.jsonl 에 추가한다(추가 전용).

사전등록: research/strategy-lab/findings/market-cluster-shadow-preregistration-2026-10.md (이 문서가 이 코드보다 우선).
기록만 한다 - 수익률을 읽거나 계산하지 않고, 점수·추천·정책에 연결하지 않는다.

  - 동결 정의 파일(cluster-definition.v1.json)의 sha256 이 이 파일의 상수와 다르면 거부한다.
  - 동결일(freezeAsOf) 이전 거래일은 기록하지 않는다(이미 본 날짜는 판정에서 제외).
  - 이미 있는 날짜는 건너뛰고 기존 줄은 건드리지 않는다. 기존 줄의 정의 해시가 다르면 중단한다.
  - eventRaw = 임계값 충족 여부만(5거래일 중복 제거는 성과 계산 때 한다). 4분면은 기록만 한다.

  python scripts/append-cluster-shadow.py            # 정식: 새 거래일 추가
  python scripts/append-cluster-shadow.py --selftest
"""
import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHADOW = os.path.join(ROOT, "research", "strategy-lab", "reports", "2026-10-cluster-shadow")
DEF_PATH = os.path.join(SHADOW, "cluster-definition.v1.json")
OUT_PATH = os.path.join(SHADOW, "clusters.jsonl")
MOVERS = os.path.join(ROOT, "docs", "data", "market-movers.json")
SECTOR = os.path.join(ROOT, "docs", "data", "sector-strength.json")

EXPECTED_DEF_SHA256 = "b667cb5b8b5d3969408846857cfe7fc519178cb19f27605c38e7c5d79d5cf5f8"


def sha256_lf(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()


def load_definition():
    got = sha256_lf(DEF_PATH)
    if got != EXPECTED_DEF_SHA256:
        raise SystemExit(f"정의 파일 sha256 이 동결값과 다르다 - 기록 거부\n  기대 {EXPECTED_DEF_SHA256}\n  실제 {got}")
    with open(DEF_PATH, encoding="utf-8") as f:
        return json.load(f)


def existing_dates(path, def_sha):
    if not os.path.exists(path):
        return set()
    out = set()
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("defSha256") != def_sha:
                raise SystemExit(f"기존 {ln}번째 줄의 정의 해시가 현재와 다르다 - 중단")
            out.add(r["asOf"])
    return out


def build_line(movers, definition, def_sha, quad_by_group, quad_as_of):
    """순수 함수. movers = market-movers.json (MM-1.1)."""
    ev = definition["event"]
    groups = []
    for g in movers["groups"]:
        n, up = g["n"], g["up"]
        raw = n >= ev["minMembers"] and up >= ev["minUp"] and (up / n) >= ev["minShare"]
        groups.append({"group": g["group"], "n": n, "up": up, "dn": g["dn"], "eventRaw": bool(raw),
                       "quad": quad_by_group.get(g["group"]), "top": g.get("top", []), "members": g["members"]})
    u = movers["universe"]
    return {"asOf": movers["asOf"], "defSha256": def_sha, "schema": movers.get("schemaVersion"), "quadAsOf": quad_as_of,
            "market": {"eligible": u["eligible"], "up": u["up"], "down": u["down"]}, "groups": groups}


def append_line(path, rec):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n")


def selftest():
    import tempfile

    def ok(c, m):
        if not c:
            print("selftest 실패:", m); sys.exit(1)
    d = {"event": {"minMembers": 10, "minShare": 0.30, "minUp": 5}}
    mv = {"asOf": "20261005", "schemaVersion": "MM-1.1", "universe": {"eligible": 40, "up": 12, "down": 1},
          "groups": [{"group": "A", "n": 10, "up": 3, "dn": 0, "top": [], "members": ["1"] * 10},     # 비율 30% 이지만 급등 3 < 5
                     {"group": "B", "n": 10, "up": 5, "dn": 1, "top": [], "members": ["2"] * 10},     # 경계값 충족
                     {"group": "C", "n": 9, "up": 9, "dn": 0, "top": [], "members": ["3"] * 9},       # 종목 9 < 10
                     {"group": "D", "n": 20, "up": 5, "dn": 0, "top": [], "members": ["4"] * 20}]}    # 25% < 30%
    line = build_line(mv, d, "h", {"B": "부상"}, "20261002")
    flags = {g["group"]: g["eventRaw"] for g in line["groups"]}
    ok(flags == {"A": False, "B": True, "C": False, "D": False}, f"임계값 판정 {flags}")
    ok(line["groups"][1]["quad"] == "부상" and line["groups"][0]["quad"] is None, "4분면은 기록만")
    ok("fwd" not in json.dumps(line) and "ret" not in json.dumps(line).replace("returns", ""), "수익률 필드가 없다")
    ok(json.dumps(build_line(mv, d, "h", {"B": "부상"}, "20261002")) == json.dumps(line), "결정적")
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "c.jsonl")
        append_line(p, {"asOf": "20261005", "defSha256": "h"})
        before = open(p, "rb").read()
        append_line(p, {"asOf": "20261006", "defSha256": "h"})
        ok(open(p, "rb").read().startswith(before), "기존 바이트가 바뀌었다")
        ok(existing_dates(p, "h") == {"20261005", "20261006"}, "기존 날짜")
        try:
            existing_dates(p, "x"); ok(False, "해시 불일치 거부")
        except SystemExit:
            pass
        a, b = os.path.join(td, "a"), os.path.join(td, "b")
        open(a, "wb").write(b"{}\n"); open(b, "wb").write(b"{}\r\n")
        ok(sha256_lf(a) == sha256_lf(b), "CRLF 정규화")
    ok(sha256_lf(DEF_PATH) == EXPECTED_DEF_SHA256, "정의 파일이 동결 해시와 다르다")
    print("selftest OK - append-cluster-shadow")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--out", default=OUT_PATH)
    ap.add_argument("--allow-pre-freeze", action="store_true", help="기계 점검용 - 반드시 --out 을 저장소 밖으로")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    definition = load_definition()
    if a.allow_pre_freeze and os.path.abspath(a.out).startswith(os.path.abspath(SHADOW)):
        raise SystemExit("--allow-pre-freeze 는 스냅샷 폴더에 쓰지 않는다")
    with open(MOVERS, encoding="utf-8") as f:
        mv = json.load(f)
    if mv.get("schemaVersion") != "MM-1.1":
        print(f"market-movers 스키마 {mv.get('schemaVersion')} - MM-1.1(members 포함)이 필요하다"); return 1
    asof = mv["asOf"]
    if asof < definition["freezeAsOf"] and not a.allow_pre_freeze:
        print(f"{asof}: 동결일({definition['freezeAsOf']}) 이전 - 기록하지 않는다"); return 0
    if asof in existing_dates(a.out, EXPECTED_DEF_SHA256):
        print(f"{asof}: 이미 기록됨"); return 0
    quads, qas = {}, None
    if os.path.exists(SECTOR):
        with open(SECTOR, encoding="utf-8") as f:
            sd = json.load(f)
        quads = {g["group"]: g.get("quadrant") for g in sd.get("groups", [])}
        qas = sd.get("asOf")
    rec = build_line(mv, definition, EXPECTED_DEF_SHA256, quads, qas)
    append_line(a.out, rec)
    ev = [g["group"] for g in rec["groups"] if g["eventRaw"]]
    print(f"{asof}: 기록 · 임계값 충족 그룹 {len(ev)}개 {ev}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
