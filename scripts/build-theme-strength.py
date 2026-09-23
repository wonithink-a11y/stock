#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""투자 테마 트리 강도 스냅샷 -> docs/data/theme-strength.json

config/themeTree.json(손으로 고른 대테마 > 소테마 > 종목)을 build-sector-strength.py 의
build() 로 그대로 계산한다 - 가중(EW/TV/CAP)·창·주식수 가드가 업종 탭과 같다.

★ 관찰용이다. 업종 주도권 신호는 Step 0 에서 REJECT 됐고
  (findings/sector-leadership-step0-2026-09.md), 테마 소속은 사후에 붙은 이름이라
  과거 검증에도 못 쓴다. "지금 무엇이 움직이는가"만 보여준다.

prices.json 은 config/watchlist.json(점수·추천 범위) 종목만 담는다. 테마 소형주를 거기
넣으면 추천 범위가 조용히 바뀌므로 넣지 않고, **빠진 종목만** 같은 출처(네이버 일봉,
collect.js 의 fetchDailyCandlesKR 과 같은 주소)로 받아 이 계산에만 쓴다. 받은 봉은
prices.json 의 기준일까지 자른다 - 안 자르면 종목마다 끝 날짜가 달라 창이 어긋난다.

벤치마크 = 가격이 있는 KR 전 종목(워치리스트 + 테마 보충분)의 중앙값/가중.
업종 탭 벤치마크와 보충분만큼 다르다(asOf 같음).

  python scripts/build-theme-strength.py
  python scripts/build-theme-strength.py --selftest     # 네트워크 없음
"""
import argparse
import importlib.util
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TREE = os.path.join(ROOT, "config", "themeTree.json")
OUT = os.path.join(ROOT, "docs", "data", "theme-strength.json")
MIN_THEME_MEMBERS = 2    # 손으로 고른 묶음이라 업종(5)보다 작다. n 은 화면에 같이 낸다
BARS = 250

_spec = importlib.util.spec_from_file_location("sector", os.path.join(ROOT, "scripts", "build-sector-strength.py"))
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)


def load_tree(path=TREE):
    return json.load(open(path, encoding="utf-8"))


def check_tree(tree, known):
    """문제 목록(비면 정상). 종목코드가 A1a 에 없거나 주 테마가 1개가 아니면 실패."""
    prim, probs = {}, []
    for big, subs in tree["themes"].items():
        for sub, ms in subs.items():
            for m in ms:
                if m["t"] not in known:
                    probs.append(f"{big}/{sub}: {m['t']} {m.get('name')} - A1a 현재 상장 목록에 없음")
                prim[m["t"]] = prim.get(m["t"], 0) + (m.get("primary", True) is not False)
    probs += [f"{t}: 주 테마 {n}개(1개여야 함)" for t, n in prim.items() if n != 1]
    return probs


def memberships(tree):
    """ticker -> 그룹 키 목록. 대테마 키와 '대테마 · 소테마' 키 둘 다에 넣는다."""
    out = {}
    for big, subs in tree["themes"].items():
        for sub, ms in subs.items():
            for m in ms:
                ks = out.setdefault(m["t"], [])
                for k in (big, f"{big} · {sub}"):
                    if k not in ks:
                        ks.append(k)
    return out


def fetch_naver(ticker, count=BARS):
    url = f"https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count={count}&requestType=0"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    xml = urllib.request.urlopen(req, timeout=15).read().decode("euc-kr", "replace")
    rows = [x.split("|") for x in re.findall(r'<item data="([^"]+)"', xml)]
    if not rows:
        raise ValueError("빈 응답")
    return {"d": [r[0] for r in rows], "o": [float(r[1]) for r in rows], "h": [float(r[2]) for r in rows],
            "l": [float(r[3]) for r in rows], "c": [float(r[4]) for r in rows], "v": [float(r[5]) for r in rows]}


def clip(rec, as_of):
    """as_of 이후 봉을 버린다 - 모든 종목의 마지막 날짜를 prices.json 에 맞춘다."""
    k = sum(1 for d in rec["d"] if d <= as_of)
    return {f: rec[f][:k] for f in ("d", "o", "h", "l", "c", "v")}


def leader(members):
    """현재 시총 1위(주식수 × 마지막 종가). build() 의 capTop 은 창 **시작** 시점 비중이라
    '지금의 대장주'와 다르다 - 실측 09-22 메모리: 3개월 전엔 SK하이닉스 1,866조 > 삼성전자
    1,812조, 지금은 삼성전자 1,622조 > 1,345조. 표시용이지 가중치가 아니다.
    ★ 주 테마 종목 중에서 고른다 - 부 테마까지 보면 '친환경 에너지' 대장주가 현대차
    (수소 부 테마)가 된다. 주 테마 종목에 시총이 하나도 없을 때만 부 테마까지 본다."""
    cands = ([m for m in members if m.get("capNow") and m["primary"]]
             or [m for m in members if m.get("capNow")])
    if not cands:
        return None
    m = max(cands, key=lambda x: x["capNow"])
    return {"t": m["t"], "name": m["name"], "primary": m["primary"]}


def tree_view(tree, out, prices, member_of, shares=None):
    """build() 결과를 트리 모양으로 다시 엮는다. 종목별 수익률·현재 시총도 같이 낸다."""
    gi = {g["group"]: g for g in out["groups"]}
    shares = shares or {}
    def mem(m):
        rec = prices["byTicker"].get(m["t"])
        c = (rec or {}).get("c") or []
        sh = shares.get(m["t"]) or {}
        ok = sh.get("shares") and not sh.get("unverified") and c
        return {"t": m["t"], "name": m.get("name"), "primary": m.get("primary", True) is not False,
                "hasPrice": bool(c), "capNow": round(sh["shares"] * c[-1]) if ok else None,
                "ret": {k: S.r4(S.ret(c, n)) for k, n in S.WINDOWS.items()} if c else None}
    view = []
    for big, subs in tree["themes"].items():
        kids = []
        for sub, ms in subs.items():
            members = [mem(m) for m in ms]
            kids.append({"theme": sub, "key": f"{big} · {sub}", "stats": gi.get(f"{big} · {sub}"),
                         "total": len(ms), "priced": sum(x["hasPrice"] for x in members),
                         "leader": leader(members), "members": members})
        uniq = {m["t"]: m for k in kids for m in k["members"]}
        view.append({"theme": big, "key": big, "stats": gi.get(big),
                     "total": sum(1 for t, ks in member_of.items() if big in ks),
                     "leader": leader(list(uniq.values())), "subs": kids})
    return view


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    tree = load_tree()
    known = {json.loads(l)["ticker"] for l in open(S.A1A, encoding="utf-8")}
    probs = check_tree(tree, known)
    if probs:
        sys.exit("themeTree.json 검사 실패:\n  " + "\n  ".join(probs))
    member_of = memberships(tree)

    prices = json.load(open(S.PRICES, encoding="utf-8"))
    by = prices["byTicker"]
    as_of = max((r["d"][-1] for r in by.values() if r.get("market") == "KR" and r.get("d")), default=None)
    names = {m["t"]: m.get("name") for subs in tree["themes"].values() for ms in subs.values() for m in ms}
    fetched, failed = [], []
    for t in sorted(member_of):
        if t in by:
            continue
        try:
            by[t] = {"name": names.get(t), "market": "KR", **clip(fetch_naver(t), as_of)}
            fetched.append(t)
        except Exception as e:                  # fail-soft: 그 종목만 '가격 없음'으로 남는다
            failed.append({"t": t, "name": names.get(t), "error": str(e)[:120]})
        time.sleep(0.2)

    mapping = {t: member_of.get(t, []) for t, r in by.items() if r.get("market") == "KR"}
    kr = list(mapping)
    closes = {t: dict(zip(by[t].get("d") or [], by[t].get("c") or [])) for t in kr}
    shares = S.resolve_shares(kr, S.load_snapshot(), S.load_shares(as_of),
                              S.load_a8_price_ratio(as_of, kr, closes), as_of)
    out = S.build(prices, mapping, shares_by_ticker=shares, min_members=MIN_THEME_MEMBERS)

    result = {
        "updatedAt": out["updatedAt"], "asOf": out["asOf"], "treeVersion": tree.get("version"),
        "treeAsOf": tree.get("asOf"), "universeCount": out["universeCount"],
        "benchmark": out["benchmark"], "tvBenchmark": out["tvBenchmark"], "capBenchmark": out["capBenchmark"],
        "benchmarkNote": "가격이 있는 KR 전 종목(워치리스트 + 테마 보충 %d종목)" % len(fetched),
        "supplemented": fetched, "fetchFailed": failed, "minMembers": MIN_THEME_MEMBERS,
        "aggregation": out["aggregation"], "weightingNote": out["weightingNote"],
        "disclaimer": "관찰용이다. 테마 소속은 현재 기준으로 손으로 고른 것이라 과거 검증에 쓰지 않는다. "
                      "부 테마(primary=false) 종목은 두 테마에 모두 들어가므로 두 테마가 같이 움직여 보일 수 있다.",
        "tree": tree_view(tree, out, prices, member_of, shares),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
    pc = lambda v: "   -  " if v is None else "{:+6.1%}".format(v)
    print(f"asOf {result['asOf']} · 보충 {len(fetched)} · 실패 {len(failed)} · 벤치 1d {pc(out['benchmark']['1d'])}")
    for b in result["tree"]:
        st = b["stats"] or {"ret": {}}
        print(f"  {b['theme']:<14} 1d {pc(st['ret'].get('1d'))}  1m {pc(st['ret'].get('1m'))}")
        for k in b["subs"]:
            st = k["stats"] or {"ret": {}}
            print(f"     {k['theme']:<16} {k['priced']}/{k['total']}  1d {pc(st['ret'].get('1d'))}  1m {pc(st['ret'].get('1m'))}")
    print("saved:", OUT)


def selftest():
    known = {"A00001", "A00002", "A00003"}
    ok = {"themes": {"X": {"x1": [{"t": "A00001"}, {"t": "A00002"}],
                           "x2": [{"t": "A00003"}, {"t": "A00001", "primary": False}]}}}
    assert check_tree(ok, known) == []
    dup = {"themes": {"X": {"x1": [{"t": "A00001"}], "x2": [{"t": "A00001"}]}}}
    assert any("주 테마 2개" in p for p in check_tree(dup, known))          # 주 테마 겹침 거부
    none = {"themes": {"X": {"x1": [{"t": "A00001", "primary": False}]}}}
    assert any("주 테마 0개" in p for p in check_tree(none, known))         # 주 테마 없음 거부
    assert any("A1a" in p for p in check_tree({"themes": {"X": {"x": [{"t": "ZZZZZZ"}]}}}, known))
    mo = memberships(ok)
    assert mo["A00001"] == ["X", "X · x1", "X · x2"]                     # 대테마 키는 한 번만
    assert clip({f: [1, 2, 3] for f in "ohlcv"} | {"d": ["20260921", "20260922", "20260923"]},
                "20260922")["c"] == [1, 2]

    # build() 다중 소속: 겹친 종목은 두 그룹에 들어가되 벤치마크에는 한 번만
    def rec(step):
        c = [100 * (1 + step) ** i for i in range(140)]
        return {"market": "KR", "name": "n", "d": [str(20260000 + i) for i in range(140)], "c": c, "v": [1.0] * 140}
    by = {"A00001": rec(0.01), "A00002": rec(0.0), "A00003": rec(-0.01), "B00001": rec(0.0)}
    mp = {"A00001": ["g1", "g2"], "A00002": ["g1"], "A00003": ["g2"], "B00001": []}
    o = S.build({"byTicker": by}, mp, min_members=2)
    g = {x["group"]: x for x in o["groups"]}
    assert g["g1"]["n"] == 2 and g["g2"]["n"] == 2 and o["universeCount"] == 4
    assert o["benchmark"]["1d"] == 0.0                                   # 중앙값 (+1%, 0, 0, -1%)
    assert abs(g["g1"]["ret"]["1d"] - 0.005) < 1e-9                      # 중앙값(+1%, 0)
    assert o["unmappedTickers"] == 0                                     # [] 는 미매핑이 아니다
    L = leader([{"t": "a", "name": "a", "primary": True, "capNow": 5},
                {"t": "b", "name": "b", "primary": False, "capNow": 9},
                {"t": "c", "name": "c", "primary": True, "capNow": None}])
    assert L == {"t": "a", "name": "a", "primary": True}                # 주 테마 우선(부 테마 b 가 더 커도)
    assert leader([{"t": "b", "name": "b", "primary": False, "capNow": 9},
                   {"t": "c", "name": "c", "primary": True, "capNow": None}])["t"] == "b"   # 주 테마 시총 없으면 부 테마
    assert leader([{"t": "c", "name": "c", "primary": True, "capNow": None}]) is None
    print("selftest ok")


if __name__ == "__main__":
    main()
