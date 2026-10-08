#!/usr/bin/env python3
"""52주 저점 근처 × 실적 — 사건 정의·사건 수·현재 스냅샷.
사전등록: findings/low52-fundamental-paths-preregistration-2026-10.md. 정의 상수는 사전등록 §1~§3 과 같고 결과를 보고 바꾸지 않는다.

지금 이 파일은 **수익률을 보지 않는다**(사건 수·현재 목록만). 경로·수익률·판정 계산은 사용자 GO 뒤에 추가한다.

    python research/strategy-lab/low52_fundamental_paths.py --collect-recent   # DART 2026 1분기·반기 주요계정(≈62콜) → data/quarterly-multi/recent-2026/
    python research/strategy-lab/low52_fundamental_paths.py --counts           # 월말 사건 수(그룹·상태·연도) — 사전등록 부록 A
    python research/strategy-lab/low52_fundamental_paths.py --snapshot         # 가격 마지막 날 목록 → reports/2026-10-low52-snapshot/ (관찰용, gitignore)
    python research/strategy-lab/low52_fundamental_paths.py --selftest
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "futures"))

PANELS = sorted(glob.glob(str(HERE / "data" / "quarterly-multi" / "quarterly-multi-panel-*.jsonl")))
RECENT_DIR = HERE / "data" / "quarterly-multi" / "recent-2026"      # 하위 폴더라 기존 연구의 glob 에 안 걸린다
RECENT = RECENT_DIR / "panel-recent.jsonl"
KRX_PBR = HERE / "data" / "krx-pbr-history" / "pbr"
UNIV_A = ROOT / "data" / "backfill" / "universe" / "a1a" / "current.jsonl"
UNIV_B = ROOT / "data" / "backfill" / "universe" / "a1b" / "delisted.jsonl"
SNAP_DIR = HERE / "reports" / "2026-10-low52-snapshot"

# ── 동결 상수(사전등록 §1~§3) ──
WIN_LOW, MIN_HIST = 250, 240      # 52주 = 250거래일(당일 포함), 유효 저가 240일 이상
NEAR = 0.05                        # 종가 ≤ 52주 최저 저가 × 1.05
LIQ_MIN = 1e9                      # 직전 20일 평균 거래대금(당일 제외, 15일 이상) ≥ 10억 원
HALT_LOOKBACK = 20                 # [t−20, t] 에 정지일(시가 0 ∧ 거래량 0)이 있으면 제외
MAKING_MAX, BASING_MIN, ZONE = 4, 20, 0.10   # 52주 최저가 형성 후 거래일 a: ≤4 경신 중 · 5~19 중간 ·
                                             # ≥20 이면서 최근 20일 종가가 모두 저점 × 1.10 이하 다지기, 아니면 접근(위에서 내려옴)
FRESH_DAYS = 200                   # 최신 분기 기간말이 사건일보다 200일 넘게 앞서면 실적 결측
SECTOR_MIN_PEERS = 5
SOLO_MAX = 0.10                    # 업종 동반 비율 < 10% 개별 · 그 밖 동반(≥ 30% 세분은 기록 전용)
MIN_GROUP = 3                      # 판정 대조에 쓰는 달 = 두 그룹이 각 3건 이상
SPAC = re.compile(r"스팩|기업인수목적")
Y0 = 2016


# ───────────────────── 가격 ─────────────────────
def low250_of(L):
    """저가 행렬(D×N, 결측 NaN) → 52주 최저 저가(당일 포함 250거래일, 유효 240일 이상)."""
    return pd.DataFrame(L).rolling(WIN_LOW, min_periods=MIN_HIST).min().to_numpy()


def state_at(L, C, low250, t, j):
    """사건 (t, j) → (상태, a). a = 창 안 52주 최저 저가가 찍힌 가장 최근 날로부터 거래일."""
    w = L[max(t - WIN_LOW + 1, 0): t + 1, j]
    with np.errstate(invalid="ignore"):
        a = int(len(w) - 1 - np.flatnonzero(w <= low250[t, j])[-1])
    if a <= MAKING_MAX:
        return "경신 중", a
    if a < BASING_MIN:
        return "중간", a
    zone = np.nanmax(C[t - BASING_MIN + 1: t + 1, j]) <= (1 + ZONE) * low250[t, j]
    return ("다지기" if zone else "접근"), a


def load_prices():
    import surge_day_continuation as s
    dates, tick, raw = s.load_raw()
    pos = {k: np.where(raw[k] > 0, raw[k], np.nan) for k in ("open", "high", "low", "close", "volume")}
    halt0 = (raw["open"] == 0) & (raw["volume"] == 0)
    return dates, tick, pos, halt0


def features(dates, tick, P, halt0, names):
    C, V, L, H = P["close"], P["volume"], P["low"], P["high"]
    low250 = low250_of(L)
    high250 = pd.DataFrame(H).rolling(WIN_LOW, min_periods=MIN_HIST).max().to_numpy()
    tv = pd.DataFrame(C * V).shift(1).rolling(20, min_periods=15).mean().to_numpy()
    halt = pd.DataFrame(halt0.astype(float)).rolling(HALT_LOOKBACK + 1, min_periods=1).sum().to_numpy() > 0
    col_ok = np.array([t[-1] == "0" and not SPAC.search(names.get(t, "")) for t in tick])   # 보통주 · 스팩 제외
    with np.errstate(invalid="ignore"):
        elig = (tv >= LIQ_MIN) & ~halt & ~np.isnan(C) & ~np.isnan(low250) & col_ok[None, :]
        near = elig & (C <= (1 + NEAR) * low250)
    return dict(C=C, L=L, low250=low250, high250=high250, tv=tv, elig=elig, near=near)


# ───────────────────── 실적(PIT) ─────────────────────
def collect_recent(year=2026, codes=("11013", "11012")):
    import collect_quarterly_multi as cq
    key = cq.key()
    if not key:
        print("DART_API_KEY 없음")
        return 1
    corp2tk = cq.corp_list()
    corps = sorted(corp2tk)
    RECENT_DIR.mkdir(parents=True, exist_ok=True)
    state = RECENT_DIR / "_state.json"
    done = set(json.load(open(state, encoding="utf-8"))["done"]) if state.exists() else set()
    calls = 0
    for code in codes:
        for i in range(0, len(corps), cq.BATCH):
            tag = f"{year}:{code}:{i // cq.BATCH}"
            if tag in done:
                continue
            rows, err = cq.call(key, corps[i:i + cq.BATCH], year, code)
            calls += 1
            if err:
                print("중단:", tag, err)
                return 1
            with open(RECENT, "a", encoding="utf-8") as f:
                for rec in cq.parse(rows, corp2tk):
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done.add(tag)
            json.dump({"done": sorted(done)}, open(state, "w", encoding="utf-8"))
            time.sleep(0.3)
    print(f"DART 콜 {calls}회 → {RECENT}")
    return 0


def load_quarters():
    """{ticker: [(t, rec)] 정렬}, t = year*4+q. 분기 구성·PIT 지연 제외는 분기 실적 연구(build_quarters)와 같다."""
    import quarterly_growth_sector_event as qg
    by = qg.load_records(PANELS + ([str(RECENT)] if RECENT.exists() else []))
    qs, _ = qg.build_quarters(by)
    per = defaultdict(dict)
    for (_, t), r in qs.items():
        if r.get("ticker"):
            per[r["ticker"]][t] = r
    return {tk: sorted(v.items()) for tk, v in per.items()}


def quarter_end(t):
    y, q = (t - 1) // 4, (t - 1) % 4 + 1
    return date(y, q * 3, 31 if q in (1, 4) else 30)


def fundamentals(series, d):
    """d(date) 에 이미 공시된 분기만으로 TTM 영업이익·매출. 연속 4분기·전년 동기·신선도 중 하나라도 없으면 None."""
    ds = d.strftime("%Y%m%d")
    have = {t: r for t, r in series if r["date"] <= ds}
    if not have:
        return None
    tmax = max(have)
    qs = [have.get(t) for t in range(tmax - 3, tmax + 1)]
    if any(r is None or r["op_prev"] is None for r in qs) or (d - quarter_end(tmax)).days > FRESH_DAYS:
        return None
    rev_prev = None if any(r["rev_prev"] is None for r in qs) else sum(r["rev_prev"] for r in qs)
    return dict(q=tmax, ttm_op=sum(r["op"] for r in qs), ttm_op_prev=sum(r["op_prev"] for r in qs),
                q_op=qs[-1]["op"], q_op_prev=qs[-1]["op_prev"], ttm_rev=sum(r["rev"] for r in qs), ttm_rev_prev=rev_prev)


def group_of(f):
    """G = TTM 영업이익 흑자 ∧ 전년 TTM 보다 큼 · B = 그 밖(적자이거나 감소) · U = 실적 결측."""
    if f is None:
        return "U"
    return "G" if f["ttm_op"] > 0 and f["ttm_op"] > f["ttm_op_prev"] else "B"


# ───────────────────── 가치(KRX 월말 단면) ─────────────────────
def load_krx():
    out = {}
    for p in sorted(KRX_PBR.glob("*.parquet")):
        df = pd.read_parquet(p)
        if len(df):
            out[pd.Timestamp(df["date"].iloc[0])] = df.set_index("ticker")[["PBR", "PER", "EPS", "BPS"]]
    return out


def valuation_at(krx, dates, C, ti, row):
    """row 시점 PBR·PER = 가장 최근 월말(≤ row) KRX 값 × (수정 종가 비율). 반환 (PBR 벡터, PER 벡터) — 적자·자본잠식은 NaN."""
    d = dates[row]
    me = max((m for m in krx if m <= d), default=None)
    N = C.shape[1]
    pbr, per = np.full(N, np.nan), np.full(N, np.nan)
    if me is None:
        return pbr, per
    mrow = int(np.searchsorted(dates, me, side="right")) - 1
    df = krx[me]
    ratio = C[row] / C[mrow]
    for tk, r in df.iterrows():
        j = ti.get(tk)
        if j is None:
            continue
        if r["PBR"] > 0:
            pbr[j] = r["PBR"] * ratio[j]
        if r["EPS"] > 0 and r["PER"] > 0:
            per[j] = r["PER"] * ratio[j]
    return pbr, per


# ───────────────────── 공통 ─────────────────────
def universe_meta():
    names, sector, market = {}, {}, {}
    for line in open(UNIV_A, encoding="utf-8"):
        r = json.loads(line)
        names[r["ticker"]], sector[r["ticker"]], market[r["ticker"]] = r.get("name", ""), r.get("sector"), r.get("market")
    for line in open(UNIV_B, encoding="utf-8"):
        r = json.loads(line)
        names.setdefault(r["ticker"], r.get("corpName", ""))
    return names, sector, market


def sector_share(row_near, row_elig, tick, sector):
    """업종별 (적격 수, 저점 근처 수). 종목별 동반 비율은 자기 자신을 빼고 계산한다."""
    tot, nr = Counter(), Counter()
    for j in np.flatnonzero(row_elig):
        s = sector.get(tick[j])
        if s:
            tot[s] += 1
            nr[s] += int(row_near[j])
    def share(j):
        s = sector.get(tick[j])
        if not s or tot[s] - 1 < SECTOR_MIN_PEERS:
            return np.nan
        return (nr[s] - int(row_near[j])) / (tot[s] - 1)
    return share


def sector_label(s):
    if s is None or not np.isfinite(s):
        return None
    return "개별" if s < SOLO_MAX else "동반"


def month_end_rows(dates):
    per = pd.Series(np.arange(len(dates))).groupby(pd.Series(dates).dt.to_period("M").values).max()
    return [int(r) for p, r in per.items() if p.year >= Y0]


def load_all():
    names, sector, market = universe_meta()
    dates, tick, P, halt0 = load_prices()
    F = features(dates, tick, P, halt0, names)
    return dict(names=names, sector=sector, market=market, dates=dates, tick=tick, F=F,
                ti={t: j for j, t in enumerate(tick)}, quarters=load_quarters(), krx=load_krx())


# ───────────────────── 사건 수(수익률 없음) ─────────────────────
def counts():
    A = load_all()
    F, dates, tick = A["F"], A["dates"], A["tick"]
    rows = month_end_rows(dates)
    by_year = defaultdict(Counter)
    elig_n, near_n = [], []
    pairs = {"J1·J2": ("G", "B"), "J3": ("다지기", "경신 중"), "J4": ("개별", "동반")}
    for r in rows:
        d = dates[r].date()
        js = np.flatnonzero(F["near"][r])
        elig_n.append(int(F["elig"][r].sum()))
        near_n.append(len(js))
        share = sector_share(F["near"][r], F["elig"][r], tick, A["sector"])
        g = Counter()
        for j in js:
            labs = (group_of(fundamentals(A["quarters"].get(tick[j], []), d)), state_at(F["L"], F["C"], F["low250"], r, j)[0], sector_label(share(j)))
            g.update(labs)
            by_year[d.year].update(labs + ("전체",))
        for name, (a, b) in pairs.items():
            if g[a] >= MIN_GROUP and g[b] >= MIN_GROUP:
                by_year[d.year]["달:" + name] += 1
    print(f"월말 {len(rows)}개({dates[rows[0]].date()} ~ {dates[rows[-1]].date()}) · 적격 평균 {np.mean(elig_n):.0f} · 저점 근처 평균 {np.mean(near_n):.0f}"
          f"(최소 {min(near_n)} · 최대 {max(near_n)})")
    cols = ["전체", "G", "B", "U", "경신 중", "중간", "다지기", "접근", "개별", "동반", None] + ["달:" + k for k in pairs]
    print("연도 | " + " | ".join("업종 결측" if c is None else c for c in cols))
    for y in sorted(by_year):
        print(f"{y} | " + " | ".join(str(by_year[y][c]) for c in cols))
    return 0


# ───────────────────── 현재 스냅샷(관찰용) ─────────────────────
def fmt_pct(x):
    return "" if x is None or not np.isfinite(x) else f"{x * 100:+.0f}%"


def growth_txt(cur, prev):
    if prev is None:
        return ""
    if prev <= 0:
        return "흑자전환" if cur > 0 else "적자 지속"
    return fmt_pct(cur / prev - 1)


def snapshot():
    A = load_all()
    F, dates, tick, ti = A["F"], A["dates"], A["tick"], A["ti"]
    r = len(dates) - 1
    d = dates[r].date()
    pbr, per = valuation_at(A["krx"], dates, F["C"], ti, r)
    med_pbr = float(np.nanmedian(np.where(F["elig"][r], pbr, np.nan)))
    share = sector_share(F["near"][r], F["elig"][r], tick, A["sector"])
    out = []
    for j in np.flatnonzero(F["near"][r]):
        tk = tick[j]
        f = fundamentals(A["quarters"].get(tk, []), d)
        st, a = state_at(F["L"], F["C"], F["low250"], r, j)
        out.append(dict(
            종목코드=tk, 종목명=A["names"].get(tk, ""), 시장=A["market"].get(tk, ""), 업종=A["sector"].get(tk) or "",
            그룹=group_of(f), 상태=st, 저점후일=a,
            종가=F["C"][r, j], 저점대비=F["C"][r, j] / F["low250"][r, j] - 1, 고점대비=F["C"][r, j] / F["high250"][r, j] - 1,
            TTM영업이익억=None if f is None else f["ttm_op"] / 1e8,
            TTM영업이익증감=None if f is None else growth_txt(f["ttm_op"], f["ttm_op_prev"]),
            최근분기영업이익증감=None if f is None else growth_txt(f["q_op"], f["q_op_prev"]),
            최근분기=None if f is None else f"{(f['q'] - 1) // 4}Q{(f['q'] - 1) % 4 + 1}",
            PBR=pbr[j], PER=per[j], 저PBR=bool(pbr[j] <= med_pbr) if np.isfinite(pbr[j]) else None,
            업종동반=share(j), 거래대금억=F["tv"][r, j] / 1e8))
    df = pd.DataFrame(out)
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(SNAP_DIR / f"snapshot-{d}.csv", index=False, encoding="utf-8-sig")
    order = {"다지기": 0, "중간": 1, "접근": 2, "경신 중": 3}
    g = df[df["그룹"] == "G"].assign(_o=df["상태"].map(order)).sort_values(["_o", "저점대비"])
    lines = [f"# 52주 저점 근처 종목 스냅샷 — {d} (관찰용, 판정·매매 연결 없음)", "",
             f"적격 {int(F['elig'][r].sum())}종목 중 저점 근처(종가 ≤ 52주 최저 저가 × 1.05) **{len(df)}종목** — "
             f"G(실적 양호) {int((df['그룹'] == 'G').sum())} · B(적자·감소) {int((df['그룹'] == 'B').sum())} · U(실적 결측) {int((df['그룹'] == 'U').sum())}. "
             f"적격 유니버스 PBR 중앙값 {med_pbr:.2f}.", "",
             "정의는 사전등록 §1~§3. 상태: 다지기 = 52주 최저가가 20거래일 넘게 전에 찍혔고 그 뒤 20일 종가가 모두 저점 +10% 이내 · "
             "접근 = 최저가는 오래전인데 최근 20일 안에 저점 +10% 위에 있다가 내려옴 · 경신 중 = 최근 5거래일 안에 새 최저가 · 중간 = 5~19일.", "",
             "PBR·PER 은 KRX 2026-08 월말 값 × 그 뒤 주가 변화(9월 KRX 단면 미수집). 업종은 현재 분류. "
             "외화로 보고하는 회사(예: 두산밥캣 USD)는 TTM 영업이익 금액 단위가 다르다 — 그룹 분류는 비율이라 영향 없음.", "",
             "| 상태 | 종목 | 업종 | 저점 대비 | 저점 후(일) | 52주 고점 대비 | TTM 영업이익(억) | 전년 대비 | 최근 분기 | 분기 전년 대비 | PBR | PER | 업종 동반 | 거래대금(억) |",
             "|---|---|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|"]
    for _, x in g.iterrows():
        lines.append(f"| {x['상태']} | {x['종목명']}({x['종목코드']}) | {x['업종'][:14]} | {fmt_pct(x['저점대비'])} | "
                     f"{int(x['저점후일'])} | {fmt_pct(x['고점대비'])} | "
                     f"{x['TTM영업이익억']:,.0f} | {x['TTM영업이익증감']} | {x['최근분기']} | {x['최근분기영업이익증감']} | "
                     f"{'' if not np.isfinite(x['PBR']) else f'{x['PBR']:.2f}'} | {'' if not np.isfinite(x['PER']) else f'{x['PER']:.1f}'} | "
                     f"{'' if not np.isfinite(x['업종동반']) else f'{x['업종동반'] * 100:.0f}%'} | {x['거래대금억']:,.0f} |")
    (SNAP_DIR / f"snapshot-{d}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{d}: 저점 근처 {len(df)} (G {int((df['그룹'] == 'G').sum())}) → {SNAP_DIR}")
    return 0


# ───────────────────── 자체 점검 ─────────────────────
def selftest():
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    # 경로 1: 300일 하락 후 30일 횡보(저점 위) — 종가 = 저가로 둔다
    L = np.r_[np.linspace(200, 100, 300), np.full(30, 103.0)][:, None]
    low250 = low250_of(L)
    check("하락 마지막 날 a=0 경신 중", state_at(L, L, low250, 299, 0) == ("경신 중", 0))
    check("횡보 30일째 a=30 다지기", state_at(L, L, low250, 329, 0) == ("다지기", 30))
    check("횡보 10일째 중간", state_at(L, L, low250, 309, 0)[0] == "중간")
    check("239일까지 52주 저점 없음", np.isnan(low250[238, 0]) and not np.isnan(low250[239, 0]))
    # 경로 2: 오래전 저점(100) → 200 까지 상승 → 104 로 되밀림: 최저가는 210일 전, 최근 20일은 저점 +10% 위에서 내려옴
    L2 = np.r_[np.full(50, 120.0), [100.0], np.linspace(120, 200, 150), np.linspace(200, 104, 60)][:, None]
    low2 = low250_of(L2)
    check("되밀림은 다지기가 아니라 접근", state_at(L2, L2, low2, 260, 0) == ("접근", 210))

    def q(t, op, op_prev, dt, rev=10.0, rev_prev=9.0):
        return (t, {"op": op, "op_prev": op_prev, "rev": rev, "rev_prev": rev_prev, "date": dt})
    s = [q(2025 * 4 + 3, 5, 4, "20251114"), q(2025 * 4 + 4, 5, 4, "20260310"), q(2026 * 4 + 1, 5, 4, "20260515"), q(2026 * 4 + 2, 5, 4, "20260814")]
    check("8/1 에는 최신 분기가 1분기라 연속 4분기(2025Q2 없음)가 안 됨 → U", group_of(fundamentals(s, date(2026, 8, 1))) == "U")
    check("반기 공시 뒤(10/2) 흑자·증가 → G", group_of(fundamentals(s, date(2026, 10, 2))) == "G")
    s2 = [q(t, 5, 6, r["date"]) for t, r in s]
    check("TTM 감소 → B", group_of(fundamentals(s2, date(2026, 10, 2))) == "B")
    check("신선도 200일 초과 → U", fundamentals(s, date(2027, 3, 1)) is None)
    check("분기 말일: 2026Q2 = 6/30", quarter_end(2026 * 4 + 2) == date(2026, 6, 30) and quarter_end(2025 * 4 + 4) == date(2025, 12, 31))
    check("증감 문구", growth_txt(5, -1) == "흑자전환" and growth_txt(-1, -2) == "적자 지속" and growth_txt(12, 10) == "+20%")
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    for a in ("--collect-recent", "--counts", "--snapshot", "--selftest"):
        g.add_argument(a, action="store_true")
    a = ap.parse_args()
    sys.exit(collect_recent() if a.collect_recent else counts() if a.counts else snapshot() if a.snapshot else selftest())
