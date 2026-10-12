#!/usr/bin/env python3
"""결산배당 기준일 명단 — 회계연도마다 결산배당 기준일을 그해 12월에 두었는지(DEC) 다음 해로 옮겼는지(MOVED).
docs/control/연말배당랠리-실행조사-2026-10-11.md §5 첫 항목. 판정·수익률 없음 — 실행 판단용 명단(기준일 필터 자체는 미검증 가설).

    python research/strategy-lab/dividend_record_dates.py             # 수집(본문 캐시 .cache/dividend_record_dates/) → 명단
    python research/strategy-lab/dividend_record_dates.py --selftest

대상 = KRX 단면 DIV ≥ 3% 보통주(스팩 제외)의 합집합 — 2023·2024·2025 11월 말 + 최신 월.
공시 = 회계연도 Y 에 대해 Y+1-01-01 ~ Y+1-04-30 에 접수된 '현금ㆍ현물배당결정'(자회사 공시 제외) 본문의 배당구분·배당기준일.
같은 해 결산배당 공시가 여럿이면(기재정정 포함) 접수번호가 가장 늦은 것. 기준일이 Y+1-04-30 뒤면 결산으로 보지 않는다. 정정 공시는 본문 끝의 정정 후 값(마지막 일치)을 읽는다.
분류: DEC(기준일 Y년) · MOVED(기준일 Y+1년) · NONE(창 안에 결산배당 공시 없음 — 무배당·12월 결산 아님) · FAIL(본문 해석 실패).
제목 목록: 공시 제목 캐시(data/dart_event_titles, A5 패널 1,724종목)에 있으면 그것, 없으면 DART list.json(I, 2024-01-01~2026-04-30)을 받아 캐시.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import collect_dart_event_titles as cdt  # noqa: E402
import dividend_capture as dc  # noqa: E402

YEARS = (2023, 2024, 2025)
SNAPS = ("2023-11", "2024-11", "2025-11")
CACHE = HERE / ".cache" / "dividend_record_dates"
TITLES = Path(cdt.CACHE)
OUT = HERE / "findings" / "dividend-record-dates-2026-10"
DECISION = "현금ㆍ현물배당결정"
RE_KIND = re.compile(r"배당구분\s*(\S+?배당)")
RE_DATE = re.compile(r"배당기준일\s*(\d{4})[-.](\d{2})[-.](\d{2})")
RE_DPS = re.compile(r"1주당\s*배당금\s*\(원\)\s*보통주식\s*([\d,]+)")


def parse_body(text: str) -> dict:
    """본문 텍스트 → {kind, record, dps}. 정정 공시는 정정 후 값이 마지막에 오므로 마지막 일치를 쓴다."""
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
    k, d, p = RE_KIND.findall(t), RE_DATE.findall(t), RE_DPS.findall(t)
    return {"kind": k[-1] if k else None, "record": "-".join(d[-1]) if d else None,
            "dps": int(p[-1].replace(",", "")) if p else None}


def classify(fy: int, record: str | None) -> str:
    if not record:
        return "FAIL"
    y = int(record[:4])
    return "DEC" if y == fy else ("MOVED" if y == fy + 1 else "FAIL")


def is_decision(nm: str) -> bool:
    s = nm.replace(" ", "")
    return DECISION in s and "자회사" not in s and "분기" not in s and "중간" not in s


def titles(key, corp, calls):
    p = TITLES / f"{corp}.json"
    if p.exists():
        return json.load(open(p, encoding="utf-8"))["I"]
    q = CACHE / "titles" / f"{corp}.json"
    if q.exists():
        return json.load(open(q, encoding="utf-8"))
    rows, page = [], 1
    while True:
        lst, total = cdt.dart_list_range(key, corp, "I", page, "20240101", "20260430")
        calls[0] += 1
        rows += [{"d": r["rcept_dt"], "nm": r["report_nm"], "no": r["rcept_no"]} for r in lst]
        if page >= total:
            break
        page += 1
    q.parent.mkdir(parents=True, exist_ok=True)
    json.dump(rows, open(q, "w", encoding="utf-8"), ensure_ascii=False)
    return rows


def body(key, no, calls):
    p = CACHE / "body" / f"{no}.json"
    if p.exists():
        return json.load(open(p, encoding="utf-8"))
    for attempt in range(3):
        try:
            r = requests.get("https://opendart.fss.or.kr/api/document.xml", params={"crtfc_key": key, "rcept_no": no}, timeout=60)
            break
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(5)
    calls[0] += 1
    if r.content[:2] != b"PK":
        if b"020" in r.content[:300]:
            raise cdt.LimitReached(r.text[:200])
        out = {"kind": None, "record": None, "dps": None, "error": r.text[:200]}
    else:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        raw = b" ".join(z.read(n) for n in z.namelist())
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp949", errors="replace")
        out = parse_body(text)
    p.parent.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    time.sleep(0.1)
    return out


def candidates():
    corp, name = {}, {}
    for line in open(REPO / "data" / "backfill" / "dart" / "corpcode.jsonl", encoding="utf-8"):
        j = json.loads(line)
        if j.get("ticker"):
            corp[j["ticker"]], name[j["ticker"]] = j["corp"], j.get("corpName", "")
    latest = sorted(p.stem for p in dc.PBR.glob("20*.parquet"))[-1]
    div = {}
    for m in SNAPS + (latest,):
        f = pd.read_parquet(dc.PBR / f"{m}.parquet").drop_duplicates("ticker").set_index("ticker")["DIV"]
        div[m] = f.to_dict()
    tk = sorted({t for m in div for t, v in div[m].items()
                 if v >= dc.DIV_MIN and t.endswith("0") and t in corp and not dc.SPAC.search(name.get(t, ""))})
    return tk, corp, name, div, latest


def run():
    key = cdt.load_env().get("DART_API_KEY")
    if not key:
        sys.exit("DART_API_KEY 없음(.env)")
    tk, corp, name, div, latest = candidates()
    print(f"대상 {len(tk)}종목 (단면 {', '.join(SNAPS)} · 최신 {latest})")
    calls, rows = [0], []
    try:
        for i, t in enumerate(tk, 1):
            lst = titles(key, corp[t], calls)
            for fy in YEARS:
                lo, hi = f"{fy + 1}0101", f"{fy + 1}0430"
                cand = sorted((r for r in lst if lo <= r["d"] <= hi and is_decision(r["nm"])), key=lambda r: r["no"], reverse=True)
                hit = None
                for r in cand:
                    b = body(key, r["no"], calls)
                    late = b["record"] and b["record"] > f"{fy + 1}-04-30"   # 정정 전 원본이 분기배당을 결산으로 잘못 적은 경우(현대차 2025-04)
                    if (b["kind"] == "결산배당" or (b["kind"] is None and b["record"])) and not late:
                        hit = (r, b)
                        break
                row = {"ticker": t, "name": name[t], "corp": corp[t], "fy": fy, "div_nov": div[f"{fy}-11"].get(t),
                       "div_latest": div[latest].get(t)}
                if hit:
                    r, b = hit
                    row.update({"class": classify(fy, b["record"]), "record_date": b["record"], "dps": b["dps"],
                                "filed": r["d"], "rcept_no": r["no"]})
                else:
                    row.update({"class": "NONE"})
                rows.append(row)
            if i % 50 == 0:
                print(f"  {i}/{len(tk)} 호출 {calls[0]}", flush=True)
    except cdt.LimitReached as e:
        sys.exit(f"DART 한도 도달 — 캐시 보존, 다시 실행하면 이어서: {e}")
    df = pd.DataFrame(rows)
    df.to_csv(OUT.with_suffix(".csv"), index=False, encoding="utf-8-sig")
    write_md(df, latest)
    print(f"완료 · 호출 {calls[0]} → {OUT.name}.csv/.md")


def write_md(df, latest):
    L = ["---", "track: kr", "factor: dividend-record-dates", "date: 2026-10-12", "verdict: EXPLORATORY", "reason: >-",
         "  기술 명단(판정 없음). 고배당 후보의 회계연도별 결산배당 기준일(12월 유지 vs 다음 해 이동) — DART '현금ㆍ현물배당결정' 본문 기준.", "---", "",
         "# 결산배당 기준일 명단 (2023~2025 회계연도)", "",
         "`dividend_record_dates.py` 가 DART 본문의 배당구분·배당기준일을 읽어 만든 명단이다. 전체 표는 같은 이름의 `.csv`.",
         "**기준일 필터(12월 유지 회사만 사기)는 검증되지 않은 가설이다** — 쓰려면 새 사전등록(연말배당랠리-실행조사 §5 둘째 항목).", "",
         "## 1. 해마다 그해 11월 말 DIV ≥ 3% 후보의 분류", "",
         "| 회계연도 | 후보 | DEC(12월) | MOVED(다음 해) | NONE | FAIL | MOVED 비중(DEC+MOVED 중) |", "|---|---:|---:|---:|---:|---:|---:|"]
    for fy in YEARS:
        s = df[(df.fy == fy) & (df.div_nov >= dc.DIV_MIN)]
        c = s["class"].value_counts()
        dm = c.get("DEC", 0) + c.get("MOVED", 0)
        L.append(f"| {fy} | {len(s)} | {c.get('DEC', 0)} | {c.get('MOVED', 0)} | {c.get('NONE', 0)} | {c.get('FAIL', 0)} | "
                 f"{c.get('MOVED', 0) / dm:.0%} |" if dm else f"| {fy} | {len(s)} | 0 | 0 | {c.get('NONE', 0)} | {c.get('FAIL', 0)} | — |")
    cur = df[(df.fy == 2025) & (df.div_latest >= dc.DIV_MIN)].sort_values("div_latest", ascending=False)
    c = cur["class"].value_counts()
    L += ["", f"## 2. 2026 후보 근사 — {latest} DIV ≥ 3% {len(cur)}종목의 2025 결산 기준일", "",
          f"DEC {c.get('DEC', 0)} · MOVED {c.get('MOVED', 0)} · NONE {c.get('NONE', 0)} · FAIL {c.get('FAIL', 0)}. "
          "11월 말 단면이 나오면 후보가 바뀐다 — 그때 다시 실행한다(본문 캐시로 호출 거의 없음).", "",
          "**2025 결산을 다음 해로 옮긴 회사(MOVED)** — 12월 랠리·배당락 대상이 아닐 가능성이 높다:", ""]
    mv = cur[cur["class"] == "MOVED"]
    L.append(" · ".join(f"{r.name}({r.ticker}, {r.record_date})" for r in mv.itertuples()) or "(없음)")
    L += ["", "**옮겼다가 되돌린 회사**(2024 MOVED → 2025 DEC)와 그 반대는 csv 에서 연도별로 본다.", "",
          "## 3. 한계", "",
          "- 2025 결산이 12월이었다고 2026 결산도 12월이라는 보장은 없다. 12월 중순 '주주명부폐쇄기간또는기준일설정'·'배당기준일 안내' 공시를 한 번 더 본다.",
          "- NONE 은 무배당·12월 결산 아님·공시 제목 누락을 구분하지 않는다.",
          "- 공시 창은 다음 해 1~4월이다. 그 밖에 낸 결산배당 결정은 놓친다."]
    OUT.with_suffix(".md").write_text("\n".join(L) + "\n", encoding="utf-8")


def selftest():
    s = ("현금ㆍ현물배당 결정 1. 배당구분 결산배당 2. 배당종류 현금배당 3. 1주당 배당금(원) 보통주식 2,500 종류주식 2,600 "
         "6. 배당기준일 2026-02-28 7. 배당금지급")
    assert parse_body(s) == {"kind": "결산배당", "record": "2026-02-28", "dps": 2500}
    corr = "정정사항 6. 배당기준일 2025-12-31 2026-02-27 ... 1. 배당구분 결산배당 1주당 배당금(원) 보통주식 300 6. 배당기준일 2026-02-27"
    assert parse_body(corr)["record"] == "2026-02-27"
    assert classify(2025, "2025-12-31") == "DEC" and classify(2025, "2026-02-28") == "MOVED" and classify(2025, None) == "FAIL"
    assert is_decision("현금ㆍ현물배당결정              ") and not is_decision("현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정")
    assert not is_decision("현금ㆍ현물배당결정(자회사의 주요경영사항)") and not is_decision("현금ㆍ현물배당결정 (분기배당)")
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    selftest() if ap.parse_args().selftest else run()
