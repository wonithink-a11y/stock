#!/usr/bin/env python
"""조합 스윕 결과 -> 대시보드 HTML.

sweep_combos.py 가 낸 JSON(전수 또는 빔) 하나를 읽어
dashboard/sweep-template.html 의 `/*__DATA__*/` 자리에 데이터를 끼워 넣는다.
새 스윕을 돌릴 때마다 이 스크립트만 다시 돌리면 화면이 갱신된다.

  python build_sweep_dashboard.py                       # 최신 스윕 JSON 자동 선택
  python build_sweep_dashboard.py --src <경로>.json
  python build_sweep_dashboard.py --selftest
"""
import argparse
import glob
import json
import os
import sys

LAB = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(LAB, "dashboard", "sweep-template.html")
OUT = os.path.join(LAB, "dashboard", "sweep-dashboard.html")
MANIFEST = os.path.join(LAB, "data", "factor-panel", "_manifest_kr_monthly.json")

# 표에 싣는 필드. 없는 값(옛 스윕 결과)은 None 으로 남겨 화면에서 "—" 로 뜬다.
FIELDS = ["t", "cagr", "sharpe", "mdd", "hitRate", "totalReturn", "benchTotalReturn",
          "calmar", "profitFactor", "maxSingleYearPct", "turnover", "avgNames",
          "avgHeld", "nMonths", "meanMonthlyExcess", "meanMonthlyBench", "excessHitRate"]


def normalize(doc):
    """전수 결과(results)와 빔 결과(steps)를 같은 모양의 행 목록으로 만든다."""
    rows, chain = [], []
    if "results" in doc:
        raw = doc["results"]
    else:                                    # 빔: 모든 단계의 beam 을 펼친다
        raw = [c for s in doc.get("steps", []) for c in s["beam"]]
    seen = set()
    for r in raw:
        names = r.get("factorNames") or r.get("factors") or []
        key = "|".join(sorted(names))
        if key in seen:
            continue
        seen.add(key)
        row = {"key": key, "factors": names}
        for f in FIELDS:
            v = r.get(f)
            row[f] = None if v is None else (round(v, 6) if isinstance(v, float) else v)
        rows.append(row)

    if "steps" in doc and doc.get("bestChain"):
        best = doc["bestChain"]
        for k in range(1, len(best) + 1):
            want = best[:k]
            node = next((c for c in doc["steps"][k - 1]["beam"]
                         if (c.get("chainNames") or []) == want), None)
            if node:
                chain.append({"k": k, "added": want[-1], "t": node["t"],
                              "deltaT": node.get("deltaT"),
                              "excess": node.get("meanMonthlyExcess")})
    return rows, chain


def build(src_path, out_path=OUT):
    doc = json.load(open(src_path, encoding="utf-8"))
    rows, chain = normalize(doc)
    rows.sort(key=lambda r: (r["t"] is None, -(r["t"] or 0)))

    liq = []
    if os.path.exists(MANIFEST):
        cat = json.load(open(MANIFEST, encoding="utf-8"))["factors"]
        liq = [f for f, v in cat.items() if v["family"] == "Liquidity"]

    g = doc["gates"]
    tested = g.get("nEvaluations") or g.get("nCombosTested")
    bar95 = g["nullBar95"]
    n_pass = sum(1 for r in rows if (r["t"] or -9) > bar95)
    is_beam = "steps" in doc
    best = rows[0] if rows else None

    headline = (
        f"{doc['period']} 구간에서 {tested:,}개 조합을 "
        f"{'빔서치로 ' if is_beam else '전수 '}평가했다. "
        f"난수 바닥선 t={bar95:.2f} 를 넘은 조합은 {n_pass}개"
        + (f", 최고는 {' + '.join(best['factors'])} (t={best['t']:.2f})." if best and n_pass else ".")
    )

    footnotes = [
        doc.get("warning", ""),
        f"규약 — 월 첫 세션 리밸런스, 익영업일 종가 진입, 익월 첫 세션 종가 청산. "
        f"상위 {int(g['topQuantile'] * 100)}% 동일가중, 왕복비용 {g['roundTripBps']:.0f}bp. "
        f"유동성 게이트 dv20≥1억원(절대임계값). 월별 최소 {g['minNames']}종목 · "
        f"최소 {g['minMonths']}개월을 못 채운 조합은 통계를 내지 않는다.",
        "초과 t 는 <b>같은 적격집합 동일가중(EW) 대비</b> 초과수익의 t 다. 절대수익으로 재면 "
        "모든 조합이 시장 베타를 공유해 난수를 섞어도 t 가 같은 값으로 수렴한다(바닥선이 죽는다). "
        "초과수익은 전략과 벤치마크의 비용이 상쇄되므로, 회전율 차이의 실제 비용은 "
        "여기 반영돼 있지 않다 — 실제 엔진 검증 단계에서 계산한다.",
        "이 화면은 후보를 <b>고르는</b> 도구이지 채택하는 도구가 아니다. 바닥선 통과는 "
        "'운이 아닐 수 있다'는 뜻일 뿐이며, 채택하려면 rule_discovery_criteria.json 의 나머지 "
        "게이트(VALID·TEST 부호 일관성, 연도집중도, 절대임계값 재확인, 실제 포트폴리오 엔진 "
        "검증)를 통과해야 한다. 이 프로젝트는 사전점검이 실제 엔진에서 40~50%로 줄어든 사례를 "
        "여러 번 겪었다(PBR +7.06%→+2.95%, LOWMOM60 +13.90%→+5.09%).",
        f"출처: {os.path.basename(src_path)} · 패널 {doc['panelVersion']}",
    ]

    payload = {
        "period": doc["period"],
        "panelVersion": doc["panelVersion"],
        "method": "BEAM" if is_beam else f"전수 k≤{max(len(r['factors']) for r in rows) if rows else 0}",
        "gates": g,
        "headline": headline,
        "footnotes": [f for f in footnotes if f],
        "liquidityFactors": liq,
        "chain": chain,
        "results": rows,
    }

    html = open(TEMPLATE, encoding="utf-8").read()
    if "/*__DATA__*/" not in html:
        raise SystemExit("템플릿에 /*__DATA__*/ 자리표시자가 없다")
    html = html.replace("/*__DATA__*/", json.dumps(payload, ensure_ascii=False,
                                                   separators=(",", ":")))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path, payload


def latest_src():
    pats = sorted(glob.glob(os.path.join(LAB, "reports", "*-combo-sweep", "*.json")),
                  key=os.path.getmtime, reverse=True)
    if not pats:
        raise SystemExit("스윕 결과 JSON 을 못 찾았다 - sweep_combos.py 를 먼저 돌릴 것")
    return pats[0]


def selftest():
    doc = {"period": "TRAIN", "panelVersion": "v1",
           "gates": {"nCombosTested": 3, "nullBar95": 2.0, "nullReps": 5,
                     "nullMaxT": [1.0, 2.0], "topQuantile": 0.9, "roundTripBps": 30.0,
                     "minNames": 30, "minMonths": 24},
           "results": [{"factors": ["a"], "t": 3.0, "cagr": 0.1},
                       {"factors": ["b"], "t": 1.0, "cagr": 0.05},
                       {"factors": ["a"], "t": 3.0, "cagr": 0.1}]}   # 중복
    rows, chain = normalize(doc)
    assert len(rows) == 2, "중복 조합이 안 걸러졌다"
    assert rows[0]["key"] == "a" and chain == []
    assert rows[0]["sharpe"] is None, "없는 필드는 None 이어야 한다"

    beam = {"period": "TRAIN", "panelVersion": "v1",
            "gates": doc["gates"], "bestChain": ["x", "y"],
            "steps": [{"k": 1, "beam": [{"factorNames": ["x"], "chainNames": ["x"],
                                         "t": 2.0, "deltaT": None, "meanMonthlyExcess": 0.01}]},
                      {"k": 2, "beam": [{"factorNames": ["x", "y"], "chainNames": ["x", "y"],
                                         "t": 3.0, "deltaT": 1.0, "meanMonthlyExcess": 0.02}]}]}
    rows2, chain2 = normalize(beam)
    assert len(rows2) == 2 and len(chain2) == 2, (len(rows2), len(chain2))
    assert chain2[1]["added"] == "y" and chain2[1]["deltaT"] == 1.0
    assert "/*__DATA__*/" in open(TEMPLATE, encoding="utf-8").read(), "템플릿 자리표시자 없음"
    print("selftest OK (중복제거·결측필드·빔체인·템플릿 4건)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=None)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
        return 0
    selftest()
    src = a.src or latest_src()
    out, payload = build(src, a.out)
    print(f"입력: {src}")
    print(f"저장: {out}  ({os.path.getsize(out) / 1024:.0f}KB)")
    print(f"  조합 {len(payload['results']):,}건 · 난수 바닥선 "
          f"{payload['gates']['nullBar95']:.2f} · "
          f"통과 {sum(1 for r in payload['results'] if (r['t'] or -9) > payload['gates']['nullBar95'])}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
