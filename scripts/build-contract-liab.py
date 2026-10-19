#!/usr/bin/env python3
"""build-contract-liab.py — 종목별 계약부채 증가(매출 가시성) → docs/data/contract-liab.json (2026-10-19)

  python scripts/build-contract-liab.py [--only 005930,000500] [--budget 3000] [--cache PATH] [--out PATH] [--no-fetch]

정의는 연구 1단계(research/strategy-lab/contract_liab_revenue.py, CONFIRMED)와 같다 — 계약부채 행 고르기는 그 파일의 `cl_amount` 를 그대로 부른다.
  CL_t  = 사업보고서 재무상태표의 계약부채·선수금·선수수익·초과청구공사 합(상위 합계 행 제외). 행이 없으면 결측(0 이 아니다).
  dCL_t = (CL_t − CL_{t−1}) / 매출_{t−1}  (매출 = A3 revenue). 금융업(KSIC 64~66)·매출 10억 미만은 내지 않는다.
  t     = 공시된 가장 최근 사업연도. 관심종목 KR 12월 결산만(사업연도 라벨이 달력 연도를 가정한다).
  위치  = 같은 t 의 관심종목 중 dCL 백분위·5분위(5 = 가장 많이 늘었다).
DART fnlttSinglAcntAll(사업보고서 11011, CFS 없으면 OFS) — 받은 값은 data/contract-liab/cache.json 에 캐시해 다음 실행은 새 사업연도만 부른다.
★ 관찰용 — 점수·매매에 쓰지 않는다. 연구 결과: 다음 해 매출은 맞혔고(순위상관 +0.19~+0.22) 공시 뒤 주가는 REJECT.
  docs/data · data/contract-liab 는 Actions(contract-liab.yml)만 쓴다.
"""
import argparse
import gzip
import glob
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "contract-liab.json"
CACHE = ROOT / "data" / "contract-liab" / "cache.json"
KST = timezone(timedelta(hours=9))
RECHECK_DAYS = 7          # '보고서 없음'을 최신 사업연도에 한해 다시 묻는 간격
MIN_REV = 1e9
FIN = ("64", "65", "66")

sys.path.insert(0, str(ROOT / "research" / "strategy-lab"))
from contract_liab_revenue import cl_amount  # noqa: E402  — 연구와 같은 정의를 한 곳에서


def _eps_mod():
    spec = importlib.util.spec_from_file_location("build_eps_ttm", ROOT / "scripts" / "build-eps-ttm.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


EPS = _eps_mod()                                   # dart_fnltt · load_fy_month · load_env 재사용


def latest_fy(today: date) -> int:
    """사업보고서는 결산 뒤 3월 말까지 — 4월부터 직전 연도를 최신으로 본다."""
    return today.year - 1 if today >= date(today.year, 4, 1) else today.year - 2


def rows_of(lst):
    """DART list → cl_amount 가 읽는 [sj_div, account_id, account_nm, 금액] 행."""
    out = []
    for r in lst:
        a = r.get("thstrm_amount")
        try:
            a = float(str(a).replace(",", "")) if a not in ("", None, "-") else None
        except ValueError:
            a = None
        out.append([r.get("sj_div"), r.get("account_id"), r.get("account_nm"), a])
    return out


def fetch_year(key, corp, y):
    """→ (entry, 호출 수). entry = {f, div, cl} | {none: 조회일} | None(오류 — 캐시 안 함)."""
    calls = 0
    for div in ("CFS", "OFS"):
        d = EPS.dart_fnltt(key, corp, y, "11011", div)
        calls += 1
        st = d.get("status")
        if st == "020":
            raise RuntimeError("DART 020 일일 한도 초과")
        lst = d.get("list") or []
        if st == "000" and lst:
            return {"f": str(lst[0].get("rcept_no") or "")[:8], "div": div, "cl": cl_amount(rows_of(lst))}, calls
        if st != "013":
            return None, calls
    return {"none": datetime.now(KST).strftime("%Y%m%d")}, calls


def plan_tasks(cache, targets, y0, today):
    """(종목, 연도) — 최신 사업연도 y0 와 y0−1. y0 가 없으면(미공시) y0−2 도 받아 한 해 앞 쌍으로 낸다."""
    tasks = []
    for t in targets:
        c = cache.get(t, {})
        need = [y0, y0 - 1] + ([y0 - 2] if "none" in c.get(str(y0), {}) else [])
        for y in need:
            e = c.get(str(y))
            if e is None:
                tasks.append((t, y))
            elif "none" in e and y == y0 and (today - datetime.strptime(e["none"], "%Y%m%d").date()).days >= RECHECK_DAYS:
                tasks.append((t, y))
    return tasks


def load_a3(tickers):
    """{(종목, 연도): 매출} · {종목: KSIC} — A3."""
    rev, sic = {}, {}
    for p in glob.glob(str(ROOT / "data/backfill/fundamentals/a3/20*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                i = line.find('"ticker": "')
                if i < 0 or line[i + 11:i + 17] not in tickers:
                    continue
                r = json.loads(line)
                rev[(r["ticker"], r["fiscalYear"])] = r.get("revenue")
                if r.get("sicCode"):
                    sic[r["ticker"]] = str(r["sicCode"])
    return rev, sic


def item_for(t, c, rev, sic, y0):
    """한 종목 → {fy, dcl, ...} 또는 {reason}. 모르는 값은 None — 0 으로 채우지 않는다."""
    if sic.get(t, "")[:2] in FIN:
        return {"reason": "financial"}
    y = y0 if "f" in c.get(str(y0), {}) else y0 - 1
    cur, prev = c.get(str(y)), c.get(str(y - 1))
    if cur is None or prev is None:
        return {"reason": "pending"}
    if "f" not in cur or "f" not in prev:
        return {"reason": "no_report"}
    if cur["cl"] is None or prev["cl"] is None:
        return {"reason": "no_cl_row"}
    r0 = rev.get((t, y - 1))
    if not r0 or r0 < MIN_REV:
        return {"reason": "small_revenue" if r0 else "no_revenue"}
    return {"fy": y, "cl": cur["cl"], "clPrev": prev["cl"], "revPrev": r0, "dcl": (cur["cl"] - prev["cl"]) / r0, "f": cur["f"]}


def rank_items(items):
    """같은 사업연도끼리 dCL 백분위(0~100, 큰 쪽이 많이 늘었다)·5분위."""
    by = {}
    for t, it in items.items():
        if it.get("dcl") is not None:
            by.setdefault(it["fy"], []).append(t)
    for fy, ts in by.items():
        ts.sort(key=lambda t: items[t]["dcl"])
        n = len(ts)
        for i, t in enumerate(ts):
            pct = 100.0 * i / (n - 1) if n > 1 else 50.0
            items[t].update({"pct": round(pct, 1), "q": min(5, int(pct // 20) + 1), "peers": n})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--budget", type=int, default=3000, help="이번 실행의 DART 호출 상한(첫 실행 ≈ 관심종목 × 2.2)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    today = datetime.now(KST).date()
    y0 = latest_fy(today)
    wl = json.loads((ROOT / "config" / "watchlist.json").read_text(encoding="utf-8"))
    names = {t["code"]: t.get("name") for t in wl["tickers"] if (t.get("market") or "KR") == "KR"}
    if a.only:
        names = {t: names.get(t) for t in a.only.split(",")}
    corp = {}
    for line in (ROOT / "data" / "backfill" / "dart" / "corpcode.jsonl").read_text(encoding="utf-8").splitlines():
        j = json.loads(line)
        corp[j.get("ticker")] = j.get("corp")
    fy = EPS.load_fy_month(set(names))
    skipped = {t: ("no_corp" if not corp.get(t) else "fy_unknown" if t not in fy else "non_december_fy")
               for t in names if not corp.get(t) or fy.get(t) != 12}
    targets = [t for t in names if t not in skipped]
    cp = Path(a.cache)
    cache = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}

    tasks = plan_tasks(cache, targets, y0, today)
    print(f"최신 사업연도 {y0} · 대상 {len(targets)}종목 · 남은 조회 {len(tasks)}건 · 예산 {a.budget}콜")
    calls = 0
    if tasks and not a.no_fetch:
        key = EPS.load_env().get("DART_API_KEY")
        if not key:
            raise SystemExit("DART_API_KEY 가 필요하다")
        tasks = tasks[: a.budget // 2]                 # 작업당 최대 2콜(CFS → OFS)
        try:
            with ThreadPoolExecutor(max_workers=a.workers) as ex:
                for (t, y), (e, n) in zip(tasks, ex.map(lambda ty: fetch_year(key, corp[ty[0]], ty[1]), tasks)):
                    calls += n
                    if e is not None:
                        cache.setdefault(t, {})[str(y)] = e
        except RuntimeError as err:                    # 한도 — 받은 것까지 저장하고 정상 종료
            print(f"중단: {err}")
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")

    rev, sic = load_a3(set(targets))
    items = {t: dict(item_for(t, cache.get(t, {}), rev, sic, y0), name=names.get(t)) for t in targets}
    items.update({t: {"reason": why, "name": names.get(t)} for t, why in skipped.items()})
    rank_items(items)
    have = sum(1 for it in items.values() if it.get("dcl") is not None)
    left = len(plan_tasks(cache, targets, y0, today))
    out = {"updatedAt": datetime.now(KST).isoformat(timespec="seconds"), "latestFy": y0, "count": len(items), "withValue": have,
           "pending": left,
           "note": ("dCL = (계약부채_t − 계약부채_t−1) ÷ 매출_t−1, 사업보고서 재무상태표(계약부채·선수금·선수수익·초과청구공사). "
                    "pct·q = 같은 사업연도 관심종목 중 위치(q5 = 가장 많이 늘었다). 연구 1단계: 다음 해 매출 순위상관 +0.19~+0.22(9개 연도 전부 양) · "
                    "2단계 공시 뒤 주가 REJECT. 관찰용 — 점수·매매에 쓰지 않는다."),
           "items": items}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"saved: {a.out} · 종목 {len(items)} · 값 있음 {have} · 호출 {calls} · 남은 조회 {left}")


def selftest():
    assert latest_fy(date(2026, 3, 31)) == 2024 and latest_fy(date(2026, 4, 1)) == 2025
    lst = [{"sj_div": "BS", "account_id": "ifrs-full_ContractLiabilities", "account_nm": "계약부채", "thstrm_amount": "1,200"},
           {"sj_div": "BS", "account_id": "-표준계정코드 미사용-", "account_nm": "선수금", "thstrm_amount": "300"},
           {"sj_div": "BS", "account_id": "x", "account_nm": "확정계약부채", "thstrm_amount": "999"},
           {"sj_div": "IS", "account_id": "x", "account_nm": "선수수익", "thstrm_amount": "5"}]
    assert cl_amount(rows_of(lst)) == 1500.0                                  # BS·확정계약 제외 — 연구 정의 그대로
    assert cl_amount(rows_of([{"sj_div": "BS", "account_id": "a", "account_nm": "자본금", "thstrm_amount": "1"}])) is None
    today = date(2026, 10, 19)
    c = {"A": {"2025": {"f": "20260320", "cl": 300.0}, "2024": {"f": "20250320", "cl": 100.0}},
         "B": {"2025": {"none": "20261018"}, "2024": {"f": "20250320", "cl": 50.0}, "2023": {"f": "20240320", "cl": 80.0}},
         "C": {"2025": {"none": "20261001"}}}
    assert plan_tasks(c, ["A", "B", "C", "D"], 2025, today) == [("C", 2025), ("C", 2024), ("C", 2023), ("D", 2025), ("D", 2024)]
    rev = {("A", 2024): 2e9, ("B", 2023): 1e10, ("E", 2024): 5e8}
    a_ = item_for("A", c["A"], rev, {}, 2025)
    assert a_["fy"] == 2025 and abs(a_["dcl"] - 1e-7) < 1e-12 and a_["f"] == "20260320"
    b_ = item_for("B", c["B"], rev, {}, 2025)
    assert b_["fy"] == 2024 and b_["dcl"] == (50 - 80) / 1e10                 # 최신 연도 미공시면 한 해 앞 쌍
    assert item_for("A", c["A"], rev, {"A": "64191"}, 2025) == {"reason": "financial"}
    assert item_for("C", c["C"], rev, {}, 2025) == {"reason": "pending"}
    assert item_for("E", {"2025": {"f": "1", "cl": 1.0}, "2024": {"f": "1", "cl": 0.0}}, rev, {}, 2025) == {"reason": "small_revenue"}
    assert item_for("F", {"2025": {"f": "1", "cl": None}, "2024": {"f": "1", "cl": 0.0}}, rev, {}, 2025) == {"reason": "no_cl_row"}
    its = rank_items({"x": {"fy": 2025, "dcl": 0.1}, "y": {"fy": 2025, "dcl": -0.2}, "z": {"fy": 2025, "dcl": 0.0},
                      "w": {"fy": 2024, "dcl": 1.0}, "v": {"reason": "no_cl_row"}})
    assert (its["y"]["pct"], its["z"]["pct"], its["x"]["pct"]) == (0.0, 50.0, 100.0) and its["x"]["q"] == 5 and its["y"]["q"] == 1
    assert its["w"]["peers"] == 1 and "pct" not in its["v"]
    print("selftest 통과")


if __name__ == "__main__":
    sys.exit(main())
