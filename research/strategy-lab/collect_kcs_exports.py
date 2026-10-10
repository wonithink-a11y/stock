#!/usr/bin/env python3
"""관세청 품목별 수출(HS 10단위 월별) 수집 — 사전등록 findings/kcs-export-sector-preregistration-2026-10.md §2.

HS 2단위(류)로 1년씩 조회하면 그 아래 10단위 품목이 월별로 온다(API 조회기간 1년 제한). 연구에 필요한 앞자리 행만 저장한다.

    python research/strategy-lab/collect_kcs_exports.py            # 수집(연·류 단위 이어받기) + 무결성 점검
    python research/strategy-lab/collect_kcs_exports.py --check    # 점검만

출력: data/kcs-exports/exports.jsonl (gitignore). 한 줄 = {ym, hs, exp} (ym='YYYY-MM', exp = expDlr USD).
무결성: ① 품목별 월 합 == 그 품목의 '총계' 행  ② 류 조회에서 모은 8542 == 8542 직접 조회(2024년).
DATA_GO_KR_API_KEY 는 이미 URL 인코딩된 값이라 urlencode 에 넣지 않는다(semiconductor_cycle_kcs_export_price.py 와 같다).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from semiconductor_cycle_kcs_export_price import BASE, _load_key  # noqa: E402

OUT = HERE / "data" / "kcs-exports" / "exports.jsonl"
STATE = OUT.parent / "_done.json"
PREFIXES = ["8542", "8703", "8708", "89", "2710", "72", "73", "74", "76", "79", "29", "39", "3304", "8507", "8517",
            "3002", "3004", "9018", "8504", "8535", "8537", "8544", "84", "88", "93", "8710", "19", "20", "21", "22",
            "8529", "8532", "8534", "9013", "8524"]
CHAPTERS = sorted({p[:2] for p in PREFIXES})
YEARS = range(2014, date.today().year + 1)
FIELD = re.compile(r"<(\w+)>([^<]*)</\1>")


def fetch(hs, y):
    q = {"strtYymm": f"{y}01", "endYymm": f"{y}12", "hsSgn": hs, "imexTp": "1", "type": "json", "numOfRows": "50", "pageNo": "1"}
    url = f"{BASE}?serviceKey={_load_key()}&" + urllib.parse.urlencode(q)
    for i in range(4):
        try:
            raw = urllib.request.urlopen(url, timeout=180).read().decode("utf-8")
            code = re.search(r"<resultCode>(\w+)</resultCode>", raw)
            if code and code.group(1) == "00":
                return [dict(FIELD.findall(it)) for it in re.findall(r"<item>(.*?)</item>", raw, re.S)]
            err = code.group(1) if code else raw[:80]
        except Exception as e:  # noqa: BLE001
            err = type(e).__name__
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"{hs} {y}: {err}")


def keep(hs):
    return any(hs.startswith(p) for p in PREFIXES)


def parse(items):
    """→ (월 행 [(ym, hs, exp)], 총계 {hs: exp}, 무결성 위반 수)."""
    rows, total = [], {}
    for it in items:
        hs, y, e = it.get("hsCode", ""), it.get("year", ""), it.get("expDlr", "0")
        if not keep(hs):
            continue
        v = float(e) if e not in ("", "-") else 0.0
        if y == "총계":
            total[hs] = total.get(hs, 0.0) + v
        elif re.fullmatch(r"\d{4}\.\d{2}", y):
            rows.append((y.replace(".", "-"), hs, v))
    s = defaultdict(float)
    for _, hs, v in rows:
        s[hs] += v
    bad = sum(1 for hs, v in total.items() if abs(s.get(hs, 0.0) - v) > max(1.0, 1e-6 * v))
    return rows, total, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = set(json.loads(STATE.read_text()) if STATE.exists() else [])
    this_year = date.today().year
    if not a.check:
        with open(OUT, "a", encoding="utf-8") as f:
            for y in YEARS:
                for ch in CHAPTERS:
                    tag = f"{y}:{ch}"
                    if tag in done and y < this_year:
                        continue
                    rows, total, bad = parse(fetch(ch, y))
                    if bad:
                        sys.exit(f"{tag}: 월 합 != 총계 {bad}건 — 저장 안 함")
                    for ym, hs, v in rows:
                        f.write(json.dumps({"ym": ym, "hs": hs, "exp": v}) + "\n")
                    f.flush()
                    done.add(tag)
                    STATE.write_text(json.dumps(sorted(done)))
                    print(tag, len(rows))
                    time.sleep(0.3)
    # 점검 ②: 류 조회 vs 4단위 직접 조회
    got = defaultdict(float)
    seen = {}
    for line in open(OUT, encoding="utf-8"):
        d = json.loads(line)
        seen[(d["ym"], d["hs"])] = d["exp"]            # 올해 재수집분은 마지막 값
    for (ym, hs), v in seen.items():
        if hs.startswith("8542") and ym.startswith("2024"):
            got[ym] += v
    direct, _, _ = parse(fetch("8542", 2024))
    dsum = defaultdict(float)
    for ym, hs, v in direct:
        dsum[ym] += v
    diff = max(abs(got[m] - dsum[m]) for m in dsum)
    print(f"점검: 8542 2024 류 조회 vs 직접 조회 최대 차이 {diff:.0f} USD (월 합 {sum(dsum.values()) / 1e9:.1f}B)")
    if diff > 1:
        sys.exit("불일치")


if __name__ == "__main__":
    main()
