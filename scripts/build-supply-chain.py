#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""공급망 지도 -> docs/data/supply-chain.json

config/supplyChain.json(손으로 고른 연결 + 공시 근거)을 검사하고, 노드마다
docs/data/sector-strength.json 의 수익률(1d·1w·1m·3m)을 붙인다 - 새 수집 없음.

★ 맥락 표시 전용이다. 점수·매매·등급에 연결하지 않는다(절대 규칙 1).
   공급사 주가가 올랐으니 고객사를 사라는 근거로 쓰지 않는다(테마 선행관계 REJECT).
★ 근거(공시 접수번호·원문 인용)가 없는 연결은 검사에서 거부한다. 비율은 공시된 것만.

  python scripts/build-supply-chain.py
  python scripts/build-supply-chain.py --selftest
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "supplyChain.json")
SECTOR = os.path.join(ROOT, "docs", "data", "sector-strength.json")
OUT = os.path.join(ROOT, "docs", "data", "supply-chain.json")
CONF = ("명시", "이름만", "간접")


def validate(cfg):
    """문제 목록 - 비어 있어야 통과."""
    bad, nodes = [], cfg["nodes"]
    for i, e in enumerate(cfg["edges"]):
        tag = f"edge[{i}] {e.get('from')}->{e.get('to')}"
        for k in ("from", "to"):
            if e.get(k) not in nodes:
                bad.append(f"{tag}: 노드 없음 {e.get(k)}")
        if e.get("conf") not in CONF:
            bad.append(f"{tag}: conf {e.get('conf')}")
        if not e.get("src"):
            bad.append(f"{tag}: 근거 없음")
        for s in e.get("src", []):
            if not re.fullmatch(r"\d{14}|\d{10}-\d{2}-\d{6}", s.get("rcept", "")) or not s.get("quote"):   # DART 접수번호 14자리 · SEC accession
                bad.append(f"{tag}: 근거 접수번호·인용 누락")
        for k in ("itemShare", "supplierShare"):
            sh = e.get(k)
            if sh is not None and not (isinstance(sh.get("pct"), (int, float)) and 0 <= sh["pct"] <= 100 and sh.get("basis")):
                bad.append(f"{tag}: {k} pct/basis 이상")
        if e["conf"] == "이름만" and (e.get("itemShare") or e.get("supplierShare")):
            bad.append(f"{tag}: 이름만인데 비율이 있다")
    for m in cfg.get("itemMix", []):
        tot = sum(x["pct"] for x in m["items"])
        if abs(tot - 100) > 2:
            bad.append(f"itemMix {m['company']}: 합 {tot}")
    return bad


def build():
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    bad = validate(cfg)
    if bad:
        raise SystemExit("공급망 검사 실패:\n  " + "\n  ".join(bad))
    sec = json.load(open(SECTOR, encoding="utf-8"))
    have = {s["t"] for s in sec["stocks"]}
    out = {"asOf": cfg["asOf"], "note": cfg["note"], "nodes": cfg["nodes"],
           "edges": cfg["edges"], "itemMix": cfg["itemMix"], "undisclosed": cfg["undisclosed"]}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    miss = [k for k, v in cfg["nodes"].items() if v.get("listed") and k not in have]
    print(f"노드 {len(cfg['nodes'])} · 연결 {len(cfg['edges'])} · 주가 유니버스에 없는 상장 노드 {miss}")   # 수익률은 화면이 sector-strength 에서 붙인다


def selftest():
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    assert validate(cfg) == [], validate(cfg)
    import copy
    c = copy.deepcopy(cfg); c["edges"][0]["src"] = []
    assert any("근거 없음" in b for b in validate(c))
    c = copy.deepcopy(cfg); c["edges"][0]["to"] = "999999"
    assert any("노드 없음" in b for b in validate(c))
    c = copy.deepcopy(cfg)
    e = next(x for x in c["edges"] if x["conf"] == "이름만"); e["supplierShare"] = {"pct": 10, "basis": "x"}
    assert any("이름만인데" in b for b in validate(c))
    c = copy.deepcopy(cfg); c["edges"][4]["supplierShare"]["pct"] = 120
    assert any("pct" in b for b in validate(c))
    print("selftest OK")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else build()
