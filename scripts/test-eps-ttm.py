#!/usr/bin/env python3
"""build-eps-ttm.py 회귀 — 5종목 시험(2026-09-30)에서 나온 실제 사례를 고정한다. 네트워크·데이터 파일 없음.
  python scripts/test-eps-ttm.py
"""
import importlib.util
import math
import sys
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("b", ROOT / "scripts" / "build-eps-ttm.py")
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

passed = failed = 0


def ok(msg, cond, detail=""):
    global passed, failed
    print(("  OK    " if cond else "  FAIL  ") + msg + ("" if cond else f"  [{detail}]"))
    passed += bool(cond)
    failed += not cond


def row(nm, q, add=None, sj="CIS"):
    return {"sj_div": sj, "account_nm": nm, "thstrm_amount": str(q), "thstrm_add_amount": "" if add is None else str(add)}


print("[parse_eps — 계정명이 제각각]")
p = b.parse_eps([row("기본주당이익(손실)", 737, 1929), row("희석주당이익(손실)", 737, 1929)])
ok("삼성 2025 반기: 기본 EPS 3개월 737 · 누적 1929 (희석 제외)", p[:3] == (737, 1929, "plain"), str(p))
p = b.parse_eps([row("계속영업 기본주당순이익", 1138, ""), row("중단영업 기본주당순이익", -20, ""), row("계속영업희석주당이익(손실) (원/주)", 1134, "")])
ok("카카오 FY2025: 총합 행이 없으면 계속영업+중단영업 = 1118, 계속영업만 = 1138", p[0] == 1118 and p[3] == 1138 and p[2] == "continuing+discontinued", str(p))
p = b.parse_eps([row("계속영업순이익", 1205, 2332), row("중단영업순이익", 0, 0), row("계속영업순이익", 1198, 2319)])
ok("NAVER 2022 반기(주당 행 이름이 '계속영업순이익'): 첫 쌍(기본) 1205·2332, 희석 1198 은 안 쓴다", p[0] == 1205 and p[1] == 2332 and p[2] == "fallback", str(p))
p = b.parse_eps([row("계송영업순이익", 1127, 1127), row("계속영업순이익", 1118, 1118)])
ok("NAVER 2022 1분기(오타 '계송영업순이익'): 기본 1127 을 집는다(희석 1118 아님)", p[0] == 1127, str(p))
ok("주당이익 행이 없으면 None(0 이 아니다)", b.parse_eps([row("영업이익", 336151055118, 1)]) is None)

print("\n[split_events — 분기 발행주식 수의 정수배 점프]")
sh = {date(2021, 3, 31): 88761861, date(2021, 6, 30): 444460230, date(2021, 9, 30): 445361320, date(2020, 12, 31): 88501998}
ev = b.split_events(sh)
ok("카카오: 2021-03-31→06-30 5배(5.008) 하나만 잡는다 — 소폭 증자(+0.6%)는 분할이 아니다", ev == [(date(2021, 3, 31), date(2021, 6, 30), 5)], str(ev))
ok("정수배가 아닌 점프(증자 ×1.4)는 분할이 아니다", b.split_events({date(2020, 3, 31): 100, date(2020, 6, 30): 140}) == [])

print("\n[resolve_basis — 카카오 2021 실사례: 5월 공시(1분기)가 분할 효력(4월) 뒤인데 분할 전 기준]")
E = (date(2021, 3, 31), date(2021, 6, 30), 5)
def fil(y, rc, f, q, cum):
    m, d = b.PE[rc]
    return {"y": y, "rc": rc, "f": date(*f), "pe": date(y, m, d), "q": q, "cum": cum, "qc": q, "cumc": cum}
F = {(2020, "11014"): fil(2020, "11014", (2020, 11, 13), 1500, 4400),
     (2021, "11013"): fil(2021, "11013", (2021, 5, 17), 2605, 2605),       # 분할 전 기준(5배)
     (2021, "11012"): fil(2021, "11012", (2021, 8, 17), 722, 1243)}         # 분할 후 기준, 누적 1243 − 722 = 521 = 2605/5
fac, notes = b.resolve_basis(F, [E])
ok("1분기 공시는 분할 전 기준(계수 5) — 누적 항등식(반기누적−반기 = 521 ≈ 2605/5)으로 확정", fac[(2021, "11013")] == 5.0 and any("누적 사슬" in n for n in notes), str((fac, notes)))
ok("반기 공시(효력 뒤)는 분할 후 기준(계수 1), 분할 전 3분기 공시는 5", fac[(2021, "11012")] == 1.0 and fac[(2020, "11014")] == 5.0)

print("\n[build_quarters·ttm_at — 4분기 파생·연속 4분기·정정 재공시 결측]")
def year(y, qs, fy, f_fy=None, late=False):
    """분기 EPS(3개월) 3개 + 사업보고서 EPS. f_fy 를 늦추면 정정 재공시(원본 없음)."""
    out = {}
    for i, (rc, e) in enumerate(zip(("11013", "11012", "11014"), qs)):
        m, d = b.PE[rc]
        cum = sum(qs[:i + 1])
        out[(y, rc)] = {"y": y, "rc": rc, "f": date(y, m + (1 if m < 12 else 0), 14), "pe": date(y, m, d), "q": e, "cum": cum, "qc": e, "cumc": cum, "rule": "plain"}
    out[(y, "11011")] = {"y": y, "rc": "11011", "f": f_fy or date(y + 1, 3, 15), "pe": date(y, 12, 31), "q": fy, "cum": fy, "qc": fy, "cumc": fy, "rule": "plain"}
    return out
F = {**year(2024, (100, 110, 120), 460), **year(2025, (130, 140, 150), 600)}
fac, _ = b.resolve_basis(F, [])
Q, QC, ann = b.build_quarters(F, fac)
ok("4분기 = 연간 − 3분기 누적: 2024Q4 = 460 − 330 = 130, 2025Q4 = 600 − 420 = 180", Q[(2024, 4)][0] == 130 and Q[(2025, 4)][0] == 180)
t = b.ttm_at(date(2026, 3, 20), Q)
ok("TTM(2026-03-20) = 2025Q1~Q4 = 130+140+150+180 = 600 (=연간)", t[0] == "ok" and t[1] == 600, str(t))
t = b.ttm_at(date(2025, 12, 1), Q)
ok("TTM(2025-12-01): 4분기(2025Q4)는 아직 공시 전 → 2024Q4~2025Q3 = 130+130+140+150 = 550", t[0] == "ok" and t[1] == 550, str(t))
ok("공시 이전이면 None", b.ttm_at(date(2024, 1, 1), Q) is None)
F2 = {**year(2024, (100, 110, 120), 460, f_fy=date(2028, 3, 20)), **year(2025, (130, 140, 150), 600)}
fac2, _ = b.resolve_basis(F2, [])
Q2, _, _ = b.build_quarters(F2, fac2)
ok("정정 재공시(접수일 4년 뒤)는 late 로 표시된다", Q2[(2024, 4)][2] is True)
ok("그 4분기가 창 안에 걸리는 구간(2025-06-01: 2024Q2~2025Q1)은 TTM 결측('gap') — 0 으로 채우지 않는다", b.ttm_at(date(2025, 6, 1), Q2) == ("gap",))
ok("창이 그 분기를 지나면(2026-03-20: 2025Q1~Q4) 다시 계산된다", b.ttm_at(date(2026, 3, 20), Q2)[0] == "ok")

print("\n[attribution — ln P = ln EPS + ln PER]")
a = {"price": 100, "ttmEps": 5, "per": 20}
c = {"price": 130, "ttmEps": 8, "per": 16.25}
at = b.attribution(a, c)
ok("항등식 잔차 ≈ 0 (PER = 가격÷EPS 로 정의했으니 자명 — 검증 대상은 입력)", abs(at["lnEps"] + at["lnPer"] - at["lnP"]) < 1e-12)
ok("EPS ≤ 0 이면 귀인을 내지 않는다", b.attribution({**a, "ttmEps": -1}, c) is None and b.attribution(a, {**c, "ttmEps": 0}) is None)

print("\n[summarize — 항목 조립]")
F3 = {**year(2023, (90, 100, 110), 400), **F}          # 2024 연말 TTM 이 정의되려면 2023 이 있어야 한다
it = b.summarize(F3, [], {2024: ("20241230", 1000.0), 2025: ("20251230", 1500.0)}, date(2026, 3, 20))
ok("최신 TTM 600 · 연간 600 · 나이 5일(3/15 공시)", it["ttm"]["eps"] == 600 and it["annual"]["eps"] == 600 and it["ttm"]["ageDays"] == 5, str(it["ttm"]))
y25 = it["yearly"][-1]
ok("연말표: 2025 말 TTM 550 → PER 1500/550, 연간 EPS(FY2024=460) 기준 PER 은 다르다", abs(y25["per"] - 1500 / 550) < 0.01 and y25["annEps"] == 460)
ok("연말 귀인이 들어간다(2024→2025)", y25["attr"] is not None)
it2 = b.summarize(F2, [], {}, date(2026, 3, 20))
ok("정정 재공시가 낀 종목은 restated 플래그", "restated" in it2["flags"])
it3 = b.summarize({k: v for k, v in F.items() if k[0] == 2025 and k[1] != "11011"}, [], {}, date(2026, 3, 20))
ok("최근 4분기가 안 모이면 ttm=None · 이유 quarter_gap(공시는 있다)", it3["ttm"] is None and it3["ttmReason"] == "quarter_gap", str(it3.get("ttmReason")))
ok("공시가 하나도 없으면 항목 없음(None)", b.summarize({}, [], {}, date(2026, 3, 20)) is None)

print("\n[plan_tasks — 증분·예산 순서]")
today = date(2026, 9, 30)
cache = {"AAA": {f"2026|11013": {"f": "20260515", "q": 1, "cum": 1, "qc": 1, "cumc": 1, "rule": "plain"}}}
tasks = b.plan_tasks(cache, ["AAA", "BBB"], today)
ok("최신 기간부터: 첫 작업이 2026 반기(BBB)·(AAA)", tasks[0][0] == date(2026, 6, 30) and {t[1] for t in tasks[:2]} == {"AAA", "BBB"})
ok("받은 건(AAA 2026 1분기)은 다시 안 부른다", not any(t[1] == "AAA" and t[2] == 2026 and t[3] == "11013" for t in tasks))
ok("기간말+30일이 안 지난 것(2026 3분기 9/30, 사업보고서 12/31)은 계획에 없다", not any(t[2] == 2026 and t[3] in ("11014", "11011") for t in tasks))
cache["BBB"] = {"2026|11012": {"none": "20260929"}, "2015|11013": {"none": "20200101"}, "2025|11011": {"none": "20260101"}}
tasks = b.plan_tasks(cache, ["BBB"], today)
ok("최근 기간의 '없음'은 6일 안엔 재조회 안 함(20260929 조회)", not any(t[2] == 2026 and t[3] == "11012" for t in tasks))
cache["BBB"]["2026|11012"] = {"none": "20260901"}
ok("6일 넘으면 다시 묻는다", any(t[2] == 2026 and t[3] == "11012" for t in b.plan_tasks(cache, ["BBB"], today)))
ok("오래된 기간(2016 이전 아님, 240일 초과)의 '없음'은 확정 — 다시 안 묻는다", not any(t[2] == 2025 and t[3] == "11011" for t in b.plan_tasks(cache, ["BBB"], today)))

print("\n[run_fetch — 병렬 수집: 예산·한도(020)·연속 실패·동시성]")
import threading
import time as _time


def fake_factory(cost=1, fail_at=None, none_all=False, delay=0.01):
    lock, state = threading.Lock(), {"cur": 0, "max": 0, "n": 0}

    def fake(key, corp, y, rc):
        with lock:
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
            state["n"] += 1
            n = state["n"]
        _time.sleep(delay)
        with lock:
            state["cur"] -= 1
        if fail_at and n >= fail_at:
            raise RuntimeError("DART 020 일일 한도 초과")
        if none_all:
            return None, 1
        return {"f": "20260515", "div": "CFS", "q": 1, "cum": 1, "qc": 1, "cumc": 1, "rule": "plain"}, cost
    return fake, state


tasks = [(date(2026, 3, 31), f"T{i:03d}", 2026, "11013") for i in range(40)]
corp = {f"T{i:03d}": f"C{i}" for i in range(40)}
orig = b.fetch_entry
try:
    fake, st = fake_factory()
    b.fetch_entry = fake
    cache = {}
    f_, c_, e_ = b.run_fetch(tasks, cache, "k", corp, 1000, 5, 4, lambda: None)
    ok("예산이 넉넉하면 40건 전부 받아 캐시에 넣는다", f_ == 40 and c_ == 40 and sum(len(v) for v in cache.values()) == 40)
    ok("스레드 4개가 실제로 동시에 돈다(최대 동시 4)", st["max"] == 4, str(st))
    fake, st = fake_factory()
    b.fetch_entry = fake
    f_, c_, _ = b.run_fetch(tasks, {}, "k", corp, 10, 5, 4, lambda: None)
    ok("예산 10콜이면 초과하지 않는다(제출 시점에 지킨다)", 0 < c_ <= 10, str(c_))
    fake, st = fake_factory(cost=2)
    b.fetch_entry = fake
    f_, c_, _ = b.run_fetch(tasks, {}, "k", corp, 10, 5, 4, lambda: None)
    ok("작업당 2콜(OFS 재조회)이어도 예산 10 을 넘지 않는다", c_ <= 10, str(c_))
    fake, st = fake_factory(fail_at=6)
    b.fetch_entry = fake
    f_, c_, _ = b.run_fetch(tasks, {}, "k", corp, 1000, 5, 4, lambda: None)
    ok("020 이면 새 제출을 멈춘다 — 40건을 다 시도하지 않는다", f_ < 40 and st["n"] < 20, f"{f_} {st}")
    fake, st = fake_factory(none_all=True)
    b.fetch_entry = fake
    saved = []
    try:
        b.run_fetch(tasks, {}, "k", corp, 1000, 5, 4, lambda: saved.append(1))
        raised = False
    except SystemExit:
        raised = True
    ok("연속 30건 비정상이면 저장하고 SystemExit(붉어진다)", raised and saved and st["n"] < 40, f"{raised} {saved} {st}")
    fake, st = fake_factory()
    b.fetch_entry = fake
    f_, c_, _ = b.run_fetch(tasks, {}, "k", corp, 1000, 0, 4, lambda: None)
    ok("시간 상한(0분)이면 거의 시작 못 한다 — 무한히 안 돈다", f_ <= 5, str(f_))
finally:
    b.fetch_entry = orig

print(f"\n통과 {passed} · 실패 {failed}")
sys.exit(1 if failed else 0)
