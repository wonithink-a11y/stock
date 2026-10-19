#!/usr/bin/env python3
"""연간 전체 재무제표 원문 수집 — DART fnlttSinglAcntAll, **모든 행**(당기 열만).

왜: A3e 패널(build_extended_financials_panel.py)은 필요 계정만 골라 저장해 계약부채·선수금·매출채권·계약자산이 없다.
같은 API 를 다시 부르면서 이번엔 행을 거르지 않는다 — 다음에 다른 계정이 필요해도 재수집하지 않게(교훈75).
연구 전용(data/backfill/ 아님). 격자는 A3(종목·회계연도). PIT·키·한도 처리는 A3e 수집기 그대로 재사용한다.
A3e 가 이미 확인한 연결/별도 구분을 먼저 부르므로 corp-year 당 거의 1콜(없으면 CFS → OFS).

  python research/strategy-lab/collect_full_financials.py --selftest
  python research/strategy-lab/collect_full_financials.py --limit 20     # 시험
  python research/strategy-lab/collect_full_financials.py                # 이어서 계속(state 로 재개 안전)
"""
import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_extended_financials_panel as EXT  # noqa: E402

OUT_DIR = HERE / "data" / "fundamentals-full"
OUT = OUT_DIR / "annual-full.jsonl"
STATE = OUT_DIR / "_state.json"


def compact_all(rows):
    out = []
    for r in rows:
        amt = r.get("thstrm_amount")
        try:
            amt = float(str(amt).replace(",", "")) if amt not in ("", None, "-") else None
        except ValueError:
            amt = None
        out.append([r.get("sj_div"), r.get("account_id"), r.get("account_nm"), amt])
    return out


def known_fs():
    p = EXT.OUT_PANEL
    if not p.exists():
        return {}
    return {f"{d['ticker']}|{d['fiscalYear']}": d["fsDiv"] for d in map(json.loads, open(p, encoding="utf-8"))}


def fetch(call, hint):
    """hint(CFS/OFS) 먼저, 없으면 나머지. 반환 (rec|None, 호출수, 오류)."""
    order = [hint, "OFS" if hint == "CFS" else "CFS"] if hint else ["CFS", "OFS"]
    n = 0
    for fs in order:
        rows, err = call(fs)
        n += 1
        if err and err != "013":
            return None, n, err
        if rows:
            rn = rows[0].get("rcept_no") or ""
            return {"fsDiv": fs, "rceptNo": rn, "availableFrom": rn[:8], "rows": compact_all(rows)}, n, None
    return None, n, "013"


def load_state():
    if STATE.exists():
        st = json.loads(STATE.read_text(encoding="utf-8"))
    else:
        st = {"date": EXT.today_kst(), "callsUsedToday": 0, "doneKeys": [], "noDataKeys": []}
    if st["date"] != EXT.today_kst():
        st["date"], st["callsUsedToday"] = EXT.today_kst(), 0
    st["doneKeys"], st["noDataKeys"] = set(st["doneKeys"]), set(st["noDataKeys"])
    return st


def save_state(st):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({**st, "doneKeys": sorted(st["doneKeys"]), "noDataKeys": sorted(st["noDataKeys"])}), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--daily-budget", type=int, default=30_000)
    ap.add_argument("--sleep", type=float, default=0.15)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-consecutive-empty", type=int, default=30)
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    key = EXT.load_env()
    if not key:
        sys.exit("DART_API_KEY 없음")
    import requests
    session = requests.Session()
    grid, hints, st = EXT.load_grid(), known_fs(), load_state()
    print(f"격자 {len(grid)} · 완료 {len(st['doneKeys'])} · 자료없음 {len(st['noDataKeys'])} · 구분 힌트 {len(hints)} · 오늘 사용 {st['callsUsedToday']}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = open(OUT, "a", encoding="utf-8")
    n_done = n_rec = n_calls = empty_run = 0
    fails = Counter()
    for row in grid:
        k = f"{row['ticker']}|{row['fiscalYear']}"
        if k in st["doneKeys"] or k in st["noDataKeys"]:
            continue
        if a.limit and n_done >= a.limit:
            break
        if st["callsUsedToday"] + 2 > a.daily_budget:
            print(f"일일 예산 도달({st['callsUsedToday']}/{a.daily_budget}) — 내일 이어서")
            break
        rec, n, err = fetch(lambda fs: (time.sleep(a.sleep) or EXT.dart_call(session, key, row["corp"], row["fiscalYear"], fs)), hints.get(k))
        st["callsUsedToday"] += n
        n_calls += n
        if err == "020":
            print("한도 초과(020) — 중단, 내일 이어서")
            break
        if err == "013":
            st["noDataKeys"].add(k)
            empty_run += 1
        elif err:
            fails[err] += 1
            empty_run += 1
        else:
            out.write(json.dumps({"ticker": row["ticker"], "corp": row["corp"], "fiscalYear": row["fiscalYear"], **rec}, ensure_ascii=False) + "\n")
            st["doneKeys"].add(k)
            n_rec += 1
            empty_run = 0
        n_done += 1
        if empty_run >= a.max_consecutive_empty:
            print(f"서킷브레이커: {empty_run}건 연속 레코드 없음(오류 {fails.most_common(3)}) — 중단")
            break
        if n_done % 500 == 0:
            out.flush()
            save_state(st)
            print(f"  {n_done} 처리 · 레코드 {n_rec} · 호출 {n_calls}", flush=True)
    out.close()
    save_state(st)
    print(f"이번 실행: 처리 {n_done} · 레코드 {n_rec} · 호출 {n_calls} · 오류 {dict(fails)} | 누적 완료 {len(st['doneKeys'])}/{len(grid)}")


def selftest():
    rows = [{"sj_div": "BS", "account_id": "ifrs-full_ContractLiabilities", "account_nm": "계약부채", "thstrm_amount": "1,200", "rcept_no": "20240320000111"},
            {"sj_div": "BS", "account_id": "-표준계정코드 미사용-", "account_nm": "선수금", "thstrm_amount": "-"}]
    c = compact_all(rows)
    assert c == [["BS", "ifrs-full_ContractLiabilities", "계약부채", 1200.0], ["BS", "-표준계정코드 미사용-", "선수금", None]]
    calls = []

    def call(fs):
        calls.append(fs)
        return (rows, None) if fs == "OFS" else (None, "013")
    rec, n, err = fetch(call, "OFS")
    assert (n, err, rec["fsDiv"], rec["availableFrom"], calls) == (1, None, "OFS", "20240320", ["OFS"])     # 힌트 맞으면 1콜
    calls.clear()
    rec, n, err = fetch(call, None)
    assert (n, calls) == (2, ["CFS", "OFS"])                                                             # 힌트 없으면 CFS → OFS
    assert fetch(lambda fs: (None, "020"), "CFS")[2] == "020"                                            # 한도는 바로 멈춤
    print("selftest OK")


if __name__ == "__main__":
    main()
