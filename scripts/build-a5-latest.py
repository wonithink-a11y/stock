#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""A5 백필 점수의 최신 주차만 -> docs/data/a5-latest.json (스코어링 화면 '전 종목' 서브탭용)

data/backfill/scores/<최신 연도>.jsonl.gz 에서 가장 늦은 기준일(d)의 행만 뽑고,
종목명·시장·업종은 data/backfill/universe/a1a/current.jsonl 에서 붙인다.
라이브 스코어(docs/data/latest.json, 관심종목만)와 **다른 점수**다 — 같은 KR 기준이지만
A5 는 공시 시점(PIT) 재무·주가로, 라이브는 현재 시세 기준 PER·PBR 로 매긴다. 섞지 않는다.

  python scripts/build-a5-latest.py
  python scripts/build-a5-latest.py --selftest
"""
import ast, glob, gzip, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCORES = os.path.join(ROOT, "data", "backfill", "scores")
UNIVERSE = os.path.join(ROOT, "data", "backfill", "universe", "a1a", "current.jsonl")
OUT = os.path.join(ROOT, "docs", "data", "a5-latest.json")
AXES = ("fundamental", "valuation", "technical", "supplyDemand")
MIN_COV = 60.0   # KR-2.4 minimumDataCoverage 0.6 과 같은 값


def _num(v):
    if v in (None, "None", ""):
        return None
    return float(v)


def _obj(v):
    """A5 행은 dict/list 를 파이썬 repr 문자열로 담기도 한다('{...}', "['A']")."""
    if isinstance(v, (dict, list)) or v is None:
        return v
    if v == "None":
        return None
    return ast.literal_eval(v)


def latest_rows(path):
    best, rows = "", []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            d = r.get("d")
            if not d:
                continue
            if d > best:
                best, rows = d, [r]
            elif d == best:
                rows.append(r)
    return best, rows


def build(rows, names):
    """행 -> 화면용 레코드. 총점 결측은 순위에서 빼고 null 로 둔다(0 으로 채우지 않는다 - 교훈57)."""
    out = []
    for r in rows:
        t = r["t"]
        u = names.get(t, {})
        c = _obj(r.get("c")) or {}
        out.append({"t": t, "n": u.get("name"), "m": u.get("market"), "s": u.get("sector"),
                    "f": _num(r.get("fin")), "c": [None if c.get(k) is None else round(float(c[k]), 1) for k in AXES],
                    "cov": _num(r.get("cov")), "fl": _obj(r.get("flags")) or []})
    # 커버리지 60% 미만은 등급 '유보'(절대 규칙 1) — 점수는 보여도 순위에는 넣지 않는다
    ok = lambda x: x["f"] is not None and x["cov"] is not None and x["cov"] >= MIN_COV
    scored = sorted((x["f"] for x in out if ok(x)), reverse=True)
    n = len(scored)
    for x in out:   # 상위 몇 % — 동점은 같은 값
        x["p"] = round(100 * sum(1 for v in scored if v > x["f"]) / n, 1) if ok(x) and n else None
    out.sort(key=lambda x: (not ok(x), -(x["f"] or 0)))
    for i, x in enumerate(out):   # 순위(정렬 순서 그대로) — 유보는 None
        x["r"] = i + 1 if ok(x) else None
    return out


def main():
    years = sorted(glob.glob(os.path.join(SCORES, "[0-9][0-9][0-9][0-9].jsonl.gz")))
    if not years:
        sys.exit("A5 산출물이 없다: data/backfill/scores/YYYY.jsonl.gz")
    as_of, rows = latest_rows(years[-1])
    names = {}
    with open(UNIVERSE, encoding="utf-8") as f:
        for line in f:
            u = json.loads(line)
            names[u["ticker"]] = u
    items = build(rows, names)
    doc = {"asOf": as_of,   # 생성 시각은 넣지 않는다 - 같은 데이터면 바이트 동일해서 커밋이 안 생긴다
           "criteria": "KR-2.4 (A5 PIT 백필)", "axes": list(AXES),
           "note": "주 1회 시점 점수 · 공시 시점 재무·주가 기준 · 라이브 스코어(관심종목)와 값이 다를 수 있다 · 예측력 미검증",
           "count": len(items), "items": items}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(f"A5 최신 {as_of} · {len(items)}종목 · 총점 있는 종목 {sum(1 for x in items if x['f'] is not None)} -> {OUT}")


def selftest():
    rows = [{"d": "2026-09-03", "t": "000001", "fin": "80.0", "c": "{'fundamental': 30.0, 'valuation': 50.0, 'technical': None, 'supplyDemand': 0}", "cov": "70", "flags": "[]"},
            {"d": "2026-09-03", "t": "000002", "fin": "None", "c": "{}", "cov": "20", "flags": "['VERY_LOW_CONFIDENCE']"},
            {"d": "2026-09-03", "t": "000003", "fin": "40.0", "c": {"fundamental": 40.0}, "cov": "65", "flags": []},
            {"d": "2026-09-03", "t": "000004", "fin": "95.0", "c": {"technical": 19.0}, "cov": "31.6", "flags": []}]
    out = build(rows, {"000001": {"name": "가", "market": "KOSPI", "sector": "x"}})
    assert [x["t"] for x in out] == ["000001", "000003", "000004", "000002"], out
    assert out[2]["p"] is None and out[2]["r"] is None, "커버리지 60% 미만은 순위 밖(유보)"
    assert [x["r"] for x in out[:2]] == [1, 2]
    assert out[0]["c"] == [30.0, 50.0, None, 0.0] and out[0]["n"] == "가" and out[0]["p"] == 0.0
    assert out[1]["p"] == 50.0, out[1]
    assert out[3]["f"] is None and out[3]["p"] is None and out[3]["fl"] == ["VERY_LOW_CONFIDENCE"]
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
