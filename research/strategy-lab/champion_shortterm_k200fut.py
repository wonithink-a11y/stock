#!/usr/bin/env python3
"""대회 우승자·고전 단기 기법 4종 — KOSPI200 선물. 사전등록 findings/champion-shortterm-k200fut-preregistration-2026-10.md 그대로.

    python scripts/research-data.py get cache-small                          # (저장소 루트) 캐시가 없으면
    python research/strategy-lab/champion_shortterm_k200fut.py --selftest   # 롤 조정·거래 계산 대조(데이터 불필요)
    python research/strategy-lab/champion_shortterm_k200fut.py --count      # 신호·체결·롤 제외 건수만(수익률 없음)
    python research/strategy-lab/champion_shortterm_k200fut.py              # → findings/champion-shortterm-k200fut-results-2026-10.{md,json}

사전등록에 없는 구현 세부(실행 전 커밋, 충돌하면 사전등록이 이긴다):
- 셀 신호·청산·이상값은 champion_shortterm_kr 의 signals / exit_price / big_rows 를 그대로 import 한다(단일 열 행렬 D×1).
- 롤 비율의 '교체 전날'은 최근월 계열의 직전 행 날짜. 그 날 새·옛 계약 종가가 없으면 즉시 중단한다(조용히 넘기지 않는다).
- 롤 걸침 판정 = 행 t(=i+1) 부터 청산 행(i+k)까지 계약 코드가 모두 같음. VB(O,2)는 t..t+1, TS1(C,1)은 t 하나.
- 비용의 실제 계약 가격 = 조정 E ÷ 그 행의 누적 비율.
- 구간·시기 칸은 거래일(t) 의 연도. 대조 평균은 그 칸 안의 적격 대조일 평균. 초과·NW t·부트스트랩은 '거래일의 r − 칸 대조 평균'.
- 바닥선 rng = SEED, 블록 부트스트랩 rng = SEED+1. NW·부트스트랩·바닥선은 day_trader_scan_kr 함수.
"""
from __future__ import annotations

import argparse
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

PREREG = HERE / "findings" / "champion-shortterm-k200fut-preregistration-2026-10.md"
OUT = HERE / "findings" / "champion-shortterm-k200fut-results-2026-10"
SRC = HERE / ".cache" / "kospi200_daily"
STAMPS = REPO / ".cache" / "research-data-stamps.json"      # get 이 남긴 묶음 sha256(builtAt 은 안 남긴다)
KNOWN_BUILT = {"d6a8b8577514": "2026-10-30T23:27:18+09:00"}   # get 출력에서 옮겨 적은 builtAt(sha256 앞 12자리로 대조)
CELLS, EXIT = kr.CELLS, kr.EXIT
JUDGED = ["TS1", "TS3", "NR1", "NR5", "HG5"]
COST_KRW, MULT = 26_000.0, 250_000.0
WIN = {"TRAIN": (2010, 2018), "VALID": (2019, 2021), "TEST": (2022, 2026)}
ERAS = {"2016~23": (2016, 2023), "2024": (2024, 2024), "2025~": (2025, 2100)}
SEED, W = 20261031, 63


def front_adjusted(df: pd.DataFrame):
    """원시 KRX 행 → (날짜, 조정 O/H/L/C (D,), 계약 코드, 누적 비율, 롤 수)."""
    df = df[df["ISU_NM"].str.contains("주간", na=False)].copy()
    for f in ["TDD_CLSPRC", "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "ACC_TRDVOL"]:
        df[f] = pd.to_numeric(df[f], errors="coerce")
    df["date"] = pd.to_datetime(df["BAS_DD"], format="%Y%m%d")
    fr = df.sort_values("ACC_TRDVOL", ascending=False).groupby("date").first().sort_index()
    fr = fr[(fr["ACC_TRDVOL"] > 0) & (fr["TDD_OPNPRC"] > 0)]
    piv = df.pivot_table(index="date", columns="ISU_CD", values="TDD_CLSPRC", aggfunc="first")
    code = fr["ISU_CD"].to_numpy()
    dates = fr.index
    n = len(fr)
    step = np.ones(n)                       # step[k] = 행 k 에서 계약이 바뀔 때의 비율(그 이전 행에 곱한다)
    rolls = 0
    for k in range(1, n):
        if code[k] != code[k - 1]:
            d0 = dates[k - 1]
            new, old = piv.at[d0, code[k]] if code[k] in piv.columns else np.nan, piv.at[d0, code[k - 1]]
            if not (new > 0 and old > 0):
                sys.exit(f"롤 비율 계산 불가 {d0.date()} {code[k-1]}→{code[k]}")
            step[k] = new / old
            rolls += 1
    F = np.ones(n)                          # F[j] = j 보다 뒤 롤 비율의 곱
    for k in range(n - 1, 0, -1):
        F[k - 1] = F[k] * step[k]
    px = {k: fr[c].to_numpy(float) * F for k, c in (("o", "TDD_OPNPRC"), ("h", "TDD_HGPRC"), ("l", "TDD_LWPRC"), ("c", "TDD_CLSPRC"))}
    return dates, px, code, F, rolls


def load():
    files = sorted(SRC.glob("kospi200_*.parquet"))
    if not files:
        sys.exit("캐시 없음 — 저장소 루트에서 python scripts/research-data.py get cache-small")
    df = pd.concat([pd.read_parquet(p) for p in files])
    dates, px, code, F, rolls = front_adjusted(df)
    meta = {"files": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
            "first": str(dates.min().date()), "last": str(dates.max().date()), "rows": int(len(dates)), "rolls": rolls}
    if STAMPS.exists():
        sha = json.loads(STAMPS.read_text(encoding="utf-8")).get("cache-small")
        meta["bundle"] = {"sha256": sha, "builtAt": KNOWN_BUILT.get(str(sha)[:12], "—(알 수 없음)")}
    tdate = pd.DatetimeIndex(list(dates[1:]) + [dates[-1] + pd.Timedelta(days=1)])
    return dates, tdate.year.to_numpy(), px, code, F, meta


def same_contract(code, k):
    """행 i 의 거래(t=i+1 ~ i+k)가 한 계약 안에 있는가."""
    n = len(code)
    ok = np.zeros(n, bool)
    for i in range(n - k):
        seg = code[i + 1:i + k + 1]
        ok[i] = bool((seg == seg[0]).all())
    return ok


def trades(O, H, L, C, code, F):
    """O..C: (D,1) 조정 가격. 셀별 일 배열(거래 r·비용·대조 rc)과 기록."""
    sh = kr.sh
    base = kr.roll(~np.isnan(C) * 1.0, W, "sum") == W
    sig = kr.signals(O, H, L, C, None)
    big = kr.big_rows(O, C)
    O1, H1, C1 = sh(O, 1), sh(H, 1), sh(C, 1)
    F1 = sh(F[:, None], 1)
    trad = base & ~np.isnan(O1) & ~np.isnan(H1) & ~np.isnan(C1)
    acc, rec = {}, {}
    for c in CELLS:
        kind, k = EXIT[c]
        X, sub = kr.exit_price(O, C, kind, k)
        anybig = np.zeros(C.shape, bool)
        for j in range(1, k + 1):
            anybig |= sh(big * 1.0, j) > 0
        sc = same_contract(code, k)[:, None]
        ctrl = trad & ~anybig & ~np.isnan(X) & sc
        m, P, strict = sig[c]
        cand = trad & m & ~np.isnan(P)
        fill = cand & ((H1 > P) if strict else (H1 >= P))
        E = np.fmax(O1, P)
        good = fill & ~anybig & ~np.isnan(X) & sc
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.where(good, X / E - 1, np.nan)
            cost = np.where(good, COST_KRW / (E / F1 * MULT), np.nan)
            rc = np.where(ctrl, X / O1 - 1, np.nan)
            prem = np.where(good, E / O1 - 1, np.nan)
            intr = np.where(good, C1 / E - 1, np.nan)
            ovn = np.where(good, X / C1 - 1, np.nan) if kind == "O" else None
        acc[c] = dict(r=r[:, 0], cost=cost[:, 0], rc=rc[:, 0])
        rec[c] = dict(signals=int(cand.sum()), fills=int(fill.sum()), good=int(good.sum()),
                      roll_dropped=int((fill & ~anybig & ~np.isnan(X) & ~sc).sum()), big=int((fill & anybig).sum()),
                      sub=int((good & sub).sum()), prem=prem, intr=intr, ovn=ovn, cost=cost)
    return acc, rec


def stats(A, years, rng):
    r, cost, rc = A["r"], A["cost"], A["rc"]
    out = {}
    for w, (a, b) in {**WIN, **ERAS}.items():
        yr = (years >= a) & (years <= b)
        m = yr & ~np.isnan(r)
        cm = yr & ~np.isnan(rc)
        ctrl = rc[cm].mean() if cm.any() else np.nan
        x, cst = r[m], cost[m]
        e = x - ctrl
        f = lambda v: float(v * 1e4) if len(x) else float("nan")
        out[w] = dict(days=int(m.sum()), ctrl_days=int(cm.sum()), gross_bp=f(x.mean() if len(x) else 0), ctrl_bp=float(ctrl * 1e4),
                      exc_bp=f(e.mean() if len(x) else 0), t_exc=dts.nw_t(e) if len(x) else float("nan"),
                      cost_bp=f(cst.mean() if len(x) else 0), net_bp=f((x - cst).mean() if len(x) else 0),
                      net_stress_bp=f((x - 2 * cst).mean() if len(x) else 0))
        if w == "TRAIN":
            out[w]["boot_lo5_bp"] = dts.block_boot_lo(e, rng) * 1e4 if len(e) else float("nan")
            out[w]["_exc"] = e
    return out


def verdict(R, fl):
    out = {}
    for c in CELLS:
        if c not in JUDGED:
            out[c] = "기록 전용"
            continue
        r = R[c]
        tr, va, te = r["TRAIN"], r["VALID"], r["TEST"]
        if tr["days"] < 100:
            out[c] = "판정 불가"
            continue
        info = tr["exc_bp"] > 0 and tr["t_exc"] >= fl and tr.get("boot_lo5_bp", -1) > 0
        econ = info and va["net_bp"] > 0 and te["net_bp"] > 0 and va["exc_bp"] > 0 and te["exc_bp"] > 0
        rob = econ and r["2024"]["net_bp"] > 0 and r["2025~"]["net_bp"] > 0 and te["net_stress_bp"] > 0
        out[c] = "ROBUST" if rob else "ECONOMIC" if econ else "INFORMATION" if info else "REJECT"
    return out


def mats(px):
    return [px[k][:, None] for k in ("o", "h", "l", "c")]


def cmd_count():
    dates, years, px, code, F, meta = load()
    print(json.dumps({k: v for k, v in meta.items() if k != "files"}, ensure_ascii=False))
    _, rec = trades(*mats(px), code, F)
    for c in CELLS:
        r = rec[c]
        print(c, {k: r[k] for k in ("signals", "fills", "good", "roll_dropped", "big", "sub")})
    return 0


def run():
    for p in (PREREG, Path(__file__).resolve()):
        if not dts.committed_clean(p):
            sys.exit(f"{p.name} 가 커밋되지 않았거나 수정 중 — 수익률을 계산하지 않는다")
    if not re.search(r"^verdict: PREREGISTERED", PREREG.read_text(encoding="utf-8"), re.M):
        sys.exit("사전등록이 PREREGISTERED 가 아니다")
    dates, years, px, code, F, meta = load()
    acc, rec = trades(*mats(px), code, F)
    brng = np.random.default_rng(SEED + 1)
    R = {c: stats(acc[c], years, brng) for c in CELLS}
    fl = dts.floor95([R[c]["TRAIN"].pop("_exc") for c in CELLS], np.random.default_rng(SEED))
    V_ = verdict(R, fl)
    record = {}
    for c in CELLS:
        r = rec[c]
        record[c] = {k: r[k] for k in ("signals", "fills", "good", "roll_dropped", "big", "sub")}
        record[c].update(fill_rate=r["fills"] / max(1, r["signals"]), prem_bp=float(np.nanmean(r["prem"]) * 1e4),
                         intraday_bp=float(np.nanmean(r["intr"]) * 1e4), cost_bp=float(np.nanmean(r["cost"]) * 1e4),
                         overnight_bp=float(np.nanmean(r["ovn"]) * 1e4) if r["ovn"] is not None else None)
    res = dict(floor_t95=fl, verdict=V_, all=R, record=record, cells=CELLS, judged=JUDGED, data=meta)
    Path(str(OUT) + ".json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    write_md(res)
    print(json.dumps(V_, ensure_ascii=False), f"floor t95={fl:.2f}")
    return 0


fmt = dts.fmt


def write_md(res):
    V_, R, fl, meta = res["verdict"], res["all"], res["floor_t95"], res["data"]
    jv = {c: V_[c] for c in JUDGED}
    info = [c for c in JUDGED if V_[c] in ("ROBUST", "ECONOMIC", "INFORMATION")]
    head = "있음" if info else "없음"
    econ = "통과" if any(V_[c] in ("ROBUST", "ECONOMIC") for c in JUDGED) else "미달"
    top = next((v for v in ("ROBUST", "ECONOMIC", "INFORMATION") if v in jv.values()), "REJECT" if "REJECT" in jv.values() else "INCONCLUSIVE")
    b = meta.get("bundle") or {}
    L = ["---", "track: kr", "factor: champion-shortterm-k200fut", "date: 2026-10-31", f"verdict: {top}", "criteria_version: research-only",
         "reason: >-", f"  신호: {head} · 경제성: {econ}. 판정 셀 {json.dumps(jv, ensure_ascii=False)} · VB·VBM 기록 전용. "
         f"TRAIN 난수 바닥선 |t| {fl:.2f}(7셀 가족 95%), 비용 26,000원/계약(평균 bp 는 표).", "---", "",
         "# 대회 우승자·고전 단기 기법 4종 — KOSPI200 선물 결과 (사전등록 그대로)", "",
         "사전등록: findings/champion-shortterm-k200fut-preregistration-2026-10.md. 셀 정의는 국내 판(champion-shortterm-kr) 함수를 그대로 import. "
         "대조 = 같은 칸 모든 적격일의 '시가 → 같은 청산 시점' 평균. 롤 = 비율 후방 조정, 계약이 바뀌는 거래는 제외.", "",
         f"자료: KRX KOSPI200 선물 주간 일봉 최근월 {meta['first']} ~ {meta['last']} · {meta['rows']}행 · 롤 {meta['rolls']}회 · "
         f"연구 캐시 cache-small builtAt {b.get('builtAt', '—')} · sha256 `{str(b.get('sha256', '—'))[:16]}…` (parquet 파일별 sha256 은 json `data.files`).", "",
         "## 1. 셀별 (bp, 거래일 관측 단위)", "",
         "| 셀 | 판정 | TRAIN 일수 | TRAIN gross | TRAIN 대조 | TRAIN 초과 | t(NW5) | boot 하단 | VALID net | TEST net | VALID 초과 | TEST 초과 | 손익분기(TEST gross) | TEST 비용 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {V_[c]} | {r['TRAIN']['days']} | {fmt(r['TRAIN']['gross_bp'])} | {fmt(r['TRAIN']['ctrl_bp'])} | {fmt(r['TRAIN']['exc_bp'])} | "
                 f"{fmt(r['TRAIN']['t_exc'], 2)} | {fmt(r['TRAIN'].get('boot_lo5_bp'))} | {fmt(r['VALID']['net_bp'])} | {fmt(r['TEST']['net_bp'])} | "
                 f"{fmt(r['VALID']['exc_bp'])} | {fmt(r['TEST']['exc_bp'])} | {fmt(r['TEST']['gross_bp'])} | {fmt(r['TEST']['cost_bp'], 2)} |")
    L += ["", f"바닥선: |t| ≥ {fl:.2f} (TRAIN 부호반전 500회, 7셀 최댓값 95%). net = 거래 gross − 그 거래의 비용(26,000원 ÷ 계약 명목).", "",
          "## 2. 시기 세 칸 · 스트레스 (bp)", "",
          "| 셀 | 2016~23 일수 | 2016~23 net | 2024 일수 | 2024 net | 2025~ 일수 | 2025~ net | 2016~23 초과 | 2024 초과 | 2025~ 초과 | TEST net @2배 비용 |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = R[c]
        L.append(f"| {c} | {r['2016~23']['days']} | {fmt(r['2016~23']['net_bp'])} | {r['2024']['days']} | {fmt(r['2024']['net_bp'])} | {r['2025~']['days']} | "
                 f"{fmt(r['2025~']['net_bp'])} | {fmt(r['2016~23']['exc_bp'])} | {fmt(r['2024']['exc_bp'])} | {fmt(r['2025~']['exc_bp'])} | {fmt(r['TEST']['net_stress_bp'])} |")
    L += ["", "반도체 제외 줄은 지수 선물이라 만들 수 없다(사전등록 §4) — 2025~ 칸은 반도체 쏠림 장세다.", "",
          "## 3. 기록 전용 (판정 불사용, 전 기간)", "",
          "| 셀 | 신호 | 체결 | 체결률 | 거래 | 롤 걸침 제외 | 체결가−시가 | 체결가→당일 종가 | 당일 종가→다음 시가 | 평균 비용 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for c in CELLS:
        r = res["record"][c]
        L.append(f"| {c} | {r['signals']} | {r['fills']} | {r['fill_rate']:.1%} | {r['good']} | {r['roll_dropped']} | {fmt(r['prem_bp'])} | "
                 f"{fmt(r['intraday_bp'])} | {fmt(r['overnight_bp'])} | {fmt(r['cost_bp'], 2)} |")
    L += ["", "VB·VBM 은 KODEX 200 변동성 돌파(2026-10-09, INFORMATION)와 같은 지수·기간이라 판정하지 않는다 — 숫자는 나란히 읽기만 한다.",
          "TRAIN 에서 음(−)으로 유의한 셀이 있어도 '뒤집어 숏'은 사후 가설이라 판정하지 않는다(새 사전등록으로만).", "",
          "같은 표본 재절단·셀·롤 처리·비용 변경 금지. 남은 길: 분봉(같은 시각·가격 대조로 역지정가 공정 비교)은 새 사전등록으로만.", ""]
    Path(str(OUT) + ".md").write_text("\n".join(L), encoding="utf-8")


def selftest():
    # 1) 롤 조정: 3일차에 계약 B 로 교체, 전날(2일차) B 종가 / A 종가 = 1.02
    rows = []
    for d, (a, b, va, vb) in zip(["20200102", "20200103", "20200106", "20200107"],
                                  [(100, 102, 10, 1), (101, 103, 10, 5), (None, 104, 0, 10), (None, 105, 0, 10)]):
        for cd, cl, v in (("A", a, va), ("B", b, vb)):
            if cl is None:
                continue
            rows.append(dict(BAS_DD=d, ISU_CD=cd, ISU_NM=f"코스피200 F {cd} (주간)", TDD_OPNPRC=str(cl), TDD_HGPRC=str(cl + 1),
                             TDD_LWPRC=str(cl - 1), TDD_CLSPRC=str(cl), ACC_TRDVOL=str(v)))
    rows.append(dict(BAS_DD="20200102", ISU_CD="A", ISU_NM="코스피200 F A (야간)", TDD_OPNPRC="1", TDD_HGPRC="1", TDD_LWPRC="1",
                     TDD_CLSPRC="1", ACC_TRDVOL="999"))
    dates, px, code, F, rolls = front_adjusted(pd.DataFrame(rows))
    assert rolls == 1 and list(code) == ["A", "A", "B", "B"], code
    ratio = 103 / 101
    assert np.allclose(F, [ratio, ratio, 1, 1]) and np.allclose(px["c"], [100 * ratio, 101 * ratio, 104, 105])
    assert list(same_contract(code, 1)) == [True, True, True, False]
    assert list(same_contract(code, 2)) == [False, True, False, False]  # 행 0 의 t..t+1 = 행 1·2 = A·B → 걸침
    # 2) VB 한 건: 상승 계열, 행 71 고가만 돌파, 비용 = 26,000 / (E × 250,000)
    D = 120
    C = (300.0 + np.arange(D) * 0.5)[:, None]
    O, H, L = C.copy(), C + 1.0, C - 1.0
    H[71] = O[71] + 1.2
    code2 = np.array(["X"] * D)
    acc, rec = trades(O, H, L, C, code2, np.ones(D))
    E = O[71, 0] + 1.0
    assert abs(acc["VB"]["r"][70] - (O[72, 0] / E - 1)) < 1e-12
    assert abs(acc["VB"]["cost"][70] - COST_KRW / (E * MULT)) < 1e-15
    assert abs(acc["VB"]["rc"][70] - (O[72, 0] / O[71, 0] - 1)) < 1e-12
    # 3) 롤 걸침 제외: 행 71 에서 계약이 바뀌면 행 70 의 VB(t=71..72)는 같은 계약이라 남고, 행 69(t=70..71)는 빠진다
    code3 = np.array(["X"] * 71 + ["Y"] * (D - 71))
    acc3, rec3 = trades(O, H, L, C, code3, np.ones(D))
    assert not np.isnan(acc3["VB"]["r"][70]) and np.isnan(acc3["VB"]["rc"][69])
    print("selftest OK")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--count", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else cmd_count() if a.count else run())
