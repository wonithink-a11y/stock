#!/usr/bin/env python3
"""대회 우승자·고전 단기 기법 4종 — 국내 주식형 ETF. 사전등록 findings/champion-shortterm-kretf-preregistration-2026-10.md 그대로.

    python scripts/research-data.py get etf-ohlc                            # (저장소 루트) 원본이 없으면
    python research/strategy-lab/champion_shortterm_kretf.py --selftest     # 유니버스 정규식·행렬 대조(원본 불필요)
    python research/strategy-lab/champion_shortterm_kretf.py --count        # 유니버스·신호·체결 건수만(수익률 없음)
    python research/strategy-lab/champion_shortterm_kretf.py                # → findings/champion-shortterm-kretf-results-2026-10.{md,json}

사전등록에 없는 구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다):
- 셀 신호·적격·상한가 근처·이상값·청산 대체는 champion_shortterm_kr.trades 를 그대로 호출한다(같은 정의를 두 번 쓰지 않는다).
- 원본 줄 중 '_day' 키가 있는 줄(수집 메타)은 건너뛴다. 같은 (날짜, 코드)가 두 번이면 뒤의 것.
- 날짜 행 = 원본에 나온 날짜의 합집합(유니버스 ETF 가 하나라도 있는 날).
- 연도·구간은 거래일(t = i+1) 기준. 바닥선 rng = SEED, 블록 부트스트랩 rng = SEED+1. NW·부트스트랩·바닥선은 day_trader_scan_kr 함수.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import champion_shortterm_kr as kr  # noqa: E402
import day_trader_scan_kr as dts  # noqa: E402

PREREG = HERE / "findings" / "champion-shortterm-kretf-preregistration-2026-10.md"
OUT = HERE / "findings" / "champion-shortterm-kretf-results-2026-10"
SRC = HERE / "data" / "etf-ohlc"
UNIV = HERE / "findings" / "etf-cross-section-universe-2026-09.csv"
STAMPS = REPO / ".cache" / "research-data-stamps.json"
KNOWN_BUILT = {"ef09b6479ef5": "2026-10-30T23:29:11+09:00"}   # get 출력에서 옮겨 적은 builtAt(sha256 앞 12자리로 대조)
BROAD = re.compile(r"^(코스피( 200| 100| 50)?( TR| 동일가중지수)?|KRX (100|300)( TR)?|MSCI Korea( TR)?( Index)?|코스피 200 TR)$")
CELLS = kr.CELLS
COST, STRESS, COST_LO = 0.0005, 0.0010, 0.000354
WIN = {"TRAIN": (2010, 2020), "VALID": (2021, 2022), "TEST": (2023, 2026)}
ERAS = {"2016~23": (2016, 2023), "2024": (2024, 2024), "2025~": (2025, 2100)}
SEED = 20261031


def universe(rows):
    """CSV 행 → (포함 코드 목록, 대표 지수 제외 수, 반도체 코드 집합)."""
    dom = [r for r in rows if r["class"] == "국내주식형"]
    broad = [r for r in dom if any(BROAD.match(n.strip()) for n in r["index_names"].split("|"))]
    bset = {r["code"] for r in broad}
    keep = [r for r in dom if r["code"] not in bset]
    semi = {r["code"] for r in keep if "반도체" in r["names"] + r["index_names"]}
    return [r["code"] for r in keep], len(broad), semi


def build(lines, codes):
    """원본 jsonl 줄들 → (날짜, 코드, O/H/L/C/V 행렬)."""
    cset = set(codes)
    recs = {}
    for ln in lines:
        d = json.loads(ln)
        if "_day" in d or d.get("ISU_CD") not in cset:
            continue
        recs[(d["BAS_DD"], d["ISU_CD"])] = d
    dates = sorted({k[0] for k in recs})
    di = {d: i for i, d in enumerate(dates)}
    ci = {c: j for j, c in enumerate(codes)}
    M = {k: np.full((len(dates), len(codes)), np.nan) for k in ("o", "h", "l", "c", "v")}
    for (dd, cd), d in recs.items():
        i, j = di[dd], ci[cd]
        for k, f in (("o", "TDD_OPNPRC"), ("h", "TDD_HGPRC"), ("l", "TDD_LWPRC"), ("c", "TDD_CLSPRC"), ("v", "ACC_TRDVOL")):
            try:
                x = float(str(d.get(f, "")).replace(",", ""))
            except ValueError:
                x = np.nan
            M[k][i, j] = x if x > 0 else np.nan
    return pd.to_datetime(dates, format="%Y%m%d"), M


def load():
    rows = list(csv.DictReader(open(UNIV, encoding="utf-8")))
    codes, nbroad, semi = universe(rows)
    files = sorted(SRC.glob("*.jsonl"))
    if not files:
        sys.exit("원본 없음 — 저장소 루트에서 python scripts/research-data.py get etf-ohlc")

    def gen():
        for p in files:
            with open(p, encoding="utf-8") as fh:
                for ln in fh:
                    if ln.strip():
                        yield ln
    dates, M = build(gen(), codes)
    meta = {"files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, "first": str(dates.min().date()),
            "last": str(dates.max().date()), "days": int(len(dates)), "etfs": len(codes), "broad_excluded": nbroad,
            "semi_etfs": len(semi), "etfs_with_data": int((~np.isnan(M["c"])).any(axis=0).sum())}
    if STAMPS.exists():
        sha = json.loads(STAMPS.read_text(encoding="utf-8")).get("etf-ohlc")
        meta["bundle"] = {"sha256": sha, "builtAt": KNOWN_BUILT.get(str(sha)[:12], "—(알 수 없음)")}
    tdate = pd.DatetimeIndex(list(dates[1:]) + [dates[-1] + pd.Timedelta(days=1)])
    semi_mask = np.array([c in semi for c in codes])
    return dates, tdate.year.to_numpy(), M, semi_mask, meta


def stats(mean, exc, years, rng):
    out = {}
    for w, (a, b) in {**WIN, **ERAS}.items():
        m = (years >= a) & (years <= b) & ~np.isnan(exc)
        x, e = mean[m], exc[m]
        nb = lambda cost: float((x.mean() - cost) * 1e4) if len(x) else float("nan")
        out[w] = dict(days=int(m.sum()), gross_bp=float(x.mean() * 1e4) if len(x) else float("nan"),
                      exc_bp=float(e.mean() * 1e4) if len(e) else float("nan"), t_exc=dts.nw_t(e) if len(e) else float("nan"),
                      net_bp=nb(COST), net_stress_bp=nb(STRESS), net_lo_bp=nb(COST_LO))
    mt = (years >= WIN["TRAIN"][0]) & (years <= WIN["TRAIN"][1]) & ~np.isnan(exc)
    out["TRAIN"]["boot_lo5_bp"] = dts.block_boot_lo(exc[mt], rng) * 1e4 if mt.sum() else float("nan")
    return out


def verdict(R, X, fl):
    out = {}
    for c in CELLS:
        r = R[c]
        tr, va, te = r["TRAIN"], r["VALID"], r["TEST"]
        if tr["days"] < 100:
            out[c] = "판정 불가"
            continue
        info = tr["exc_bp"] > 0 and tr["t_exc"] >= fl and tr.get("boot_lo5_bp", -1) > 0
        econ = info and va["net_bp"] > 0 and te["net_bp"] > 0 and va["exc_bp"] > 0 and te["exc_bp"] > 0
        rob = econ and r["2024"]["net_bp"] > 0 and r["2025~"]["net_bp"] > 0 and te["net_stress_bp"] > 0 and X[c]["TEST"]["net_bp"] > 0
        out[c] = "ROBUST" if rob else "ECONOMIC" if econ else "INFORMATION" if info else "REJECT"
    return out


def cmd_count():
    dates, years, M, semi_mask, meta = load()
    print(json.dumps({k: v for k, v in meta.items() if k != "files"}, ensure_ascii=False))
    _, rec = kr.trades(M["o"], M["h"], M["l"], M["c"], M["v"], semi_mask)
    for c in CELLS:
        r = rec[c]
        print(c, "signals", int(r["signals"].sum()), "fills", int(r["fills"].sum()), "good", int(r["good"].sum()),
              "limit", int(r["limit"].sum()), "big", int(r["big"].sum()), "sub", int(r["sub"].sum()),
              "TRAIN good days", int((r["good"].any(axis=1) & (years <= 2020)).sum()))
    return 0


def run():
    for p in (PREREG, Path(__file__).resolve()):
        if not dts.committed_clean(p):
            sys.exit(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률을 계산하지 않는다")
    if not re.search(r"^verdict: PREREGISTERED", PREREG.read_text(encoding="utf-8"), re.M):
        sys.exit("사전등록이 PREREGISTERED 가 아니다")
    dates, years, M, semi_mask, meta = load()
    acc, rec = kr.trades(M["o"], M["h"], M["l"], M["c"], M["v"], semi_mask)
    brng = np.random.default_rng(SEED + 1)
    R, X, tr_series = {}, {}, []
    for v, tgt in (("all", R), ("ex", X)):
        for c in CELLS:
            mean, exc = kr.day_series(acc[v][c])
            tgt[c] = stats(mean, exc, years, brng)
            if v == "all":
                tr_series.append(exc[(years <= WIN["TRAIN"][1]) & ~np.isnan(exc)])
    fl = dts.floor95(tr_series, np.random.default_rng(SEED))
    V_ = verdict(R, X, fl)
    record = {}
    for c in CELLS:
        r = rec[c]
        g = r["good"]
        record[c] = dict(signals=int(r["signals"].sum()), fills=int(r["fills"].sum()), good=int(g.sum()),
                         fill_rate=float(r["fills"].sum() / max(1, r["signals"].sum())), limit_dropped=int(r["limit"].sum()),
                         outlier_dropped=int(r["big"].sum()), exit_substituted=int(r["sub"].sum()), etfs=int(g.any(axis=0).sum()),
                         prem_bp=float(np.nanmean(np.where(g, r["prem"], np.nan)) * 1e4),
                         intraday_bp=float(np.nanmean(np.where(g, r["intr"], np.nan)) * 1e4),
                         overnight_bp=float(np.nanmean(np.where(g, r["ovn"], np.nan)) * 1e4) if r["ovn"] is not None else None)
    res = dict(floor_t95=fl, verdict=V_, all=R, ex_semis=X, record=record, cells=CELLS, data=meta)
    Path(str(OUT) + ".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    write_md(res)
    print(json.dumps(V_, ensure_ascii=False), f"floor t95={fl:.2f}")
    return 0


fmt = dts.fmt


def write_md(res):
    V_, R, X, fl, meta = res["verdict"], res["all"], res["ex_semis"], res["floor_t95"], res["data"]
    info = [c for c in CELLS if V_[c] in ("ROBUST", "ECONOMIC", "INFORMATION")]
    head = "있음" if info else "없음"
    econ = "통과" if any(V_[c] in ("ROBUST", "ECONOMIC") for c in CELLS) else "미달"
    top = next((v for v in ("ROBUST", "ECONOMIC", "INFORMATION") if v in V_.values()), "REJECT" if "REJECT" in V_.values() else "INCONCLUSIVE")
    b = meta.get("bundle") or {}
    L = ["---", "track: kr", "factor: champion-shortterm-kretf", "date: 2026-10-31", f"verdict: {top}", "criteria_version: research-only",
         "reason: >-", f"  신호: {head} · 경제성: {econ}. 셀 판정 {json.dumps(V_, ensure_ascii=False)}. TRAIN 난수 바닥선 |t| {fl:.2f}(7셀 가족 95%), 비용 5bp(국내 주식형 ETF).", "---", "",
         "# 대회 우승자·고전 단기 기법 4종 — 국내 주식형 ETF 결과 (사전등록 그대로)", "",
         "사전등록: findings/champion-shortterm-kretf-preregistration-2026-10.md. 셀·적격은 국내 판 champion_shortterm_kr.trades 를 그대로 호출. "
         "대조 = 같은 날 적격 ETF 등가중 '시가 → 같은 청산 시점'.", "",
         f"자료: KRX ETF 일봉 {meta['first']} ~ {meta['last']} · {meta['days']}일 · 유니버스 {meta['etfs']}종(대표 지수 {meta['broad_excluded']}종 제외, 자료 있는 것 {meta['etfs_with_data']}) · "
         f"반도체 ETF {meta['semi_etfs']}종 · 묶음 etf-ohlc builtAt {b.get('builtAt', '—')} · sha256 `{str(b.get('sha256', '—'))[:16]}…` (파일별 sha256 은 json `data.files`).", "",
         "## 1. 셀별 (bp, 거래일 관측 단위)", "",
         "| 셀 | 판정 | TRAIN 일수 | TRAIN gross | TRAIN 초과 | t(NW5) | boot 하단 | VALID net | TEST net | VALID 초과 | TEST 초과 | 손익분기(TEST gross) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {V_[c]} | {r['TRAIN']['days']} | {fmt(r['TRAIN']['gross_bp'])} | {fmt(r['TRAIN']['exc_bp'])} | {fmt(r['TRAIN']['t_exc'], 2)} | "
                 f"{fmt(r['TRAIN'].get('boot_lo5_bp'))} | {fmt(r['VALID']['net_bp'])} | {fmt(r['TEST']['net_bp'])} | {fmt(r['VALID']['exc_bp'])} | {fmt(r['TEST']['exc_bp'])} | {fmt(r['TEST']['gross_bp'])} |")
    L += ["", f"바닥선: |t| ≥ {fl:.2f} (TRAIN 부호반전 500회, 7셀 최댓값 95%). net = 셀 평균 gross − 5bp.", "",
          "## 2. 시기 세 칸 · 비용 · 반도체 제외 (bp)", "",
          "| 셀 | 2016~23 net | 2024 net | 2025~ net | 2016~23 초과 | 2024 초과 | 2025~ 초과 | TEST net @10bp | TEST net @3.54bp | 반도체 제외 TEST net | 반도체 제외 TEST 초과 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r, x = R[c], X[c]
        L.append(f"| {c} | {fmt(r['2016~23']['net_bp'])} | {fmt(r['2024']['net_bp'])} | {fmt(r['2025~']['net_bp'])} | {fmt(r['2016~23']['exc_bp'])} | "
                 f"{fmt(r['2024']['exc_bp'])} | {fmt(r['2025~']['exc_bp'])} | {fmt(r['TEST']['net_stress_bp'])} | {fmt(r['TEST']['net_lo_bp'])} | "
                 f"{fmt(x['TEST']['net_bp'])} | {fmt(x['TEST']['exc_bp'])} |")
    L += ["", "## 3. 기록 전용 (판정 불사용, 전 기간)", "",
          "| 셀 | 신호 | 체결 | 체결률 | 거래 | ETF 수 | 상한가 근처 제외 | 이상값 제외 | 청산 대체 | 체결가−시가 | 체결가→당일 종가 | 당일 종가→다음 시가 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = res["record"][c]
        L.append(f"| {c} | {r['signals']} | {r['fills']} | {r['fill_rate']:.1%} | {r['good']} | {r['etfs']} | {r['limit_dropped']} | {r['outlier_dropped']} | "
                 f"{r['exit_substituted']} | {fmt(r['prem_bp'])} | {fmt(r['intraday_bp'])} | {fmt(r['overnight_bp'])} |")
    L += ["", "TRAIN 에서 음(−)으로 유의한 셀이 있어도 '뒤집어 숏'은 사후 가설이라 판정하지 않는다(새 사전등록으로만).", "",
          "같은 표본 재절단·유니버스·셀·비용 변경 금지.", ""]
    Path(str(OUT) + ".md").write_text("\n".join(L), encoding="utf-8")


def selftest():
    rows = [dict(code="A", class_="", names="KODEX 200", index_names="코스피 200"),
            dict(code="B", names="TIGER 200 IT", index_names="코스피 200 정보기술"),
            dict(code="C", names="KODEX 반도체", index_names="KRX 반도체"),
            dict(code="D", names="X 동일가중", index_names="코스피 100 동일가중지수"),
            dict(code="E", names="Y 이중", index_names="코스피 200 경기방어소비재 | 코스피"),
            dict(code="F", names="Z 해외", index_names="S&P 500")]
    for r in rows:
        r["class"] = "제외" if r["code"] == "F" else "국내주식형"
    codes, nb, semi = universe(rows)
    assert codes == ["B", "C"] and nb == 3 and semi == {"C"}, (codes, nb, semi)
    lines = [json.dumps(dict(BAS_DD="20200102", ISU_CD="B", TDD_OPNPRC="100", TDD_HGPRC="101", TDD_LWPRC="99", TDD_CLSPRC="100", ACC_TRDVOL="10")),
             json.dumps(dict(BAS_DD="20200103", ISU_CD="C", TDD_OPNPRC="0", TDD_HGPRC="1", TDD_LWPRC="1", TDD_CLSPRC="1", ACC_TRDVOL="1")),
             json.dumps(dict(BAS_DD="20200103", ISU_CD="A", TDD_OPNPRC="5", TDD_HGPRC="5", TDD_LWPRC="5", TDD_CLSPRC="5", ACC_TRDVOL="1")),
             json.dumps({"_day": "2020-01-03", "n": 3})]
    dates, M = build(lines, codes)
    assert list(dates.strftime("%Y%m%d")) == ["20200102", "20200103"] and M["o"][0, 0] == 100 and np.isnan(M["o"][1, 1]) and M["c"][1, 1] == 1
    assert np.isnan(M["o"][1, 0])                                                   # B 는 둘째 날 없음
    print("selftest OK")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--count", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else cmd_count() if a.count else run())
