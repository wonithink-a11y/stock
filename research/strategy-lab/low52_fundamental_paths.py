#!/usr/bin/env python3
"""52주 저점 근처 × 실적 — 사건 정의·사건 수·현재 스냅샷.
사전등록: findings/low52-fundamental-paths-preregistration-2026-10.md. 정의 상수는 사전등록 §1~§3 과 같고 결과를 보고 바꾸지 않는다.

--counts·--snapshot 은 수익률을 보지 않는다. 경로·수익률·판정(--run)은 사용자 GO(2026-10-08) 뒤 추가했고 실행 전에 커밋했다.

    python research/strategy-lab/low52_fundamental_paths.py --collect-recent   # DART 2026 1분기·반기 주요계정(≈62콜) → data/quarterly-multi/recent-2026/
    python research/strategy-lab/low52_fundamental_paths.py --counts           # 월말 사건 수(그룹·상태·연도) — 사전등록 부록 A
    python research/strategy-lab/low52_fundamental_paths.py --snapshot         # 가격 마지막 날 목록 → reports/2026-10-low52-snapshot/ (관찰용, gitignore)
    python research/strategy-lab/low52_fundamental_paths.py --run              # 판정 J1~J4 + 기록 → findings/low52-fundamental-paths-results-2026-10.{md,json}
    python research/strategy-lab/low52_fundamental_paths.py --posthoc          # 사후 기록(결과 뒤 추가, 판정 불사용) — 결과 문서 §7 표
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
    return dict(O=P["open"], C=C, L=L, low250=low250, high250=high250, tv=tv, elig=elig, near=near)


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


# ───────────────────── 경로·수익률·판정 (사전등록 §4~§6, GO 뒤 추가·실행 전 커밋) ─────────────────────
OUT = HERE / "findings" / "low52-fundamental-paths-results-2026-10"
H_MAIN, HS = 60, (20, 60, 120)
BREAK_X, REBOUND_X = 0.90, 1.20
COST, COST_STRESS = 0.002354, 0.00335
SEED, N_NULL, N_BOOT, BLOCK = 20261009, 1000, 2000, 6
WINDOWS = {"TRAIN": (2016, 2020), "VALID": (2021, 2022), "TEST": (2023, 2025), "REC": (2026, 2026)}
JUDGE_WINS = ("TRAIN", "VALID", "TEST")
NM = (2025 - Y0 + 1) * 12          # TRAIN~TEST 달 수(2016-01 ~ 2025-12)
PATHS = ("추가 하락", "다지기", "반등", "끝남")
JUDGES = {   # 이름: (라벨 열, 그룹 1, 그룹 2, x 열, 가설 부호)
    "J1": ("grp", "G", "B", "brk", -1),
    "J2": ("grp", "G", "B", "x60", +1),
    "J3": ("state", "다지기", "경신 중", "brk", 0),
    "J4": ("sector", "개별", "동반", "brk", 0),
}


def win_of(y):
    return next((w for w, (a, b) in WINDOWS.items() if a <= y <= b), None)


def path_of(seg, low, E, ended):
    """진입일부터 60거래일 종가 seg 에서 먼저 닿는 쪽. ended = 그 안에 종목 데이터가 끝남(폐지·합병 등)."""
    for c in seg:
        if np.isnan(c):
            continue
        if c <= BREAK_X * low:
            return "추가 하락"
        if c >= REBOUND_X * E:
            return "반등"
    return "끝남" if ended else "다지기"


def build_events(A):
    F, dates, tick = A["F"], A["dates"], A["tick"]
    O, C = F["O"], F["C"]
    D = len(dates)
    Cff = pd.DataFrame(C).ffill().to_numpy()
    valid = ~np.isnan(C)
    lv = np.where(valid.any(0), D - 1 - np.argmax(valid[::-1], axis=0), -1)     # 종목별 마지막 유효 종가 행
    ev, bench, no_entry = [], {}, 0
    for r in month_end_rows(dates):
        e = r + 1
        if e >= D:
            continue
        d = dates[r].date()
        mi = (d.year - Y0) * 12 + d.month - 1
        E = O[e]
        ok = F["elig"][r] & np.isfinite(E)
        no_entry += int((F["near"][r] & ~np.isfinite(E)).sum())
        rets = {}
        for h in HS:
            if e + h <= D - 1:                     # h 거래일 뒤 시가(없으면 그때까지 마지막 종가)
                rets[h] = np.where(np.isfinite(O[e + h]), O[e + h], Cff[e + h]) / E - 1
                bench[(mi, h)] = float(np.nanmean(rets[h][ok]))
        pbr, _ = valuation_at(A["krx"], dates, C, A["ti"], r)
        med = np.nanmedian(np.where(ok, pbr, np.nan))
        share = sector_share(F["near"][r], F["elig"][r], tick, A["sector"])
        for j in np.flatnonzero(F["near"][r] & np.isfinite(E)):
            f = fundamentals(A["quarters"].get(tick[j], []), d)
            grp = group_of(f)
            st, a = state_at(F["L"], C, F["low250"], r, j)
            s = share(j)
            low = F["low250"][r, j]
            x = dict(mi=mi, year=d.year, win=win_of(d.year), date=str(d), ticker=tick[j], name=A["names"].get(tick[j], ""),
                     grp=grp, gv=bool(grp == "G" and np.isfinite(pbr[j]) and pbr[j] <= med), state=st, a=a,
                     sector=sector_label(s), share=s, dist=C[r, j] / low - 1, dd=C[r, j] / F["high250"][r, j] - 1,
                     qup=None if f is None else bool(f["q_op"] > f["q_op_prev"]), pbr=pbr[j], path=None)
            if e + H_MAIN <= D - 1:
                x["path"] = path_of(C[e:e + H_MAIN, j], low, E[j], lv[j] < e + H_MAIN - 1)
            for h in HS:
                x[f"r{h}"] = float(rets[h][j]) if h in rets else np.nan
                x[f"x{h}"] = x[f"r{h}"] - bench[(mi, h)] if h in rets else np.nan
            ev.append(x)
    df = pd.DataFrame(ev)
    df["brk"] = np.where(df["path"].isna(), np.nan, (df["path"] == "추가 하락").astype(float))
    df["brk_end"] = np.where(df["path"].isna(), np.nan, df["path"].isin(["추가 하락", "끝남"]).astype(float))
    return df, bench, no_entry


def by_month(df, mask1, mask2, xcol):
    """두 그룹이 각 MIN_GROUP 이상인 달 → {mi: (x 배열[그룹 1 먼저], n1)}."""
    out = {}
    d = df[(mask1 | mask2) & df[xcol].notna()]
    m1 = mask1[d.index]
    for mi, idx in d.groupby("mi").groups.items():
        g1, g2 = d.loc[idx][m1[idx]][xcol].to_numpy(float), d.loc[idx][~m1[idx]][xcol].to_numpy(float)
        if len(g1) >= MIN_GROUP and len(g2) >= MIN_GROUP:
            out[int(mi)] = (np.r_[g1, g2], len(g1))
    return out


def wstat(bm, months):
    """달별 (그룹 1 평균 − 그룹 2 평균) 의 표본 가중 평균, w = n1·n2/(n1+n2). months 에 중복이 있으면 그만큼 센다."""
    num = den = 0.0
    for m in months:
        if m in bm:
            v, n1 = bm[m]
            n2 = len(v) - n1
            w = n1 * n2 / (n1 + n2)
            num += w * (v[:n1].mean() - v[n1:].mean())
            den += w
    return num / den if den else np.nan


def win_months(w):
    a, b = WINDOWS[w]
    return list(range((a - Y0) * 12, (b - Y0 + 1) * 12))


def verdict_of(res, hyp):
    if any(res[w]["insufficient"] for w in JUDGE_WINS):
        return "INCONCLUSIVE(표본 부족)"
    t, v, s = (res[w]["value"] for w in JUDGE_WINS)
    ci = res["ALL"]["ci"]
    if not (abs(t) > res["floor"] and np.sign(v) == np.sign(t) == np.sign(s) and (ci[0] > 0 or ci[1] < 0)):
        return "INCONCLUSIVE"
    return "반대 방향 확정" if hyp and np.sign(t) != hyp else "CONFIRMED"


def judge(bm, hyp, rng):
    res = {}
    for w in WINDOWS:
        ms = win_months(w)
        used = [m for m in ms if m in bm]
        res[w] = dict(value=wstat(bm, used), months=len(used), of=len(ms), insufficient=len(used) * 2 < len(ms),
                      n1=int(sum(bm[m][1] for m in used)), n2=int(sum(len(bm[m][0]) - bm[m][1] for m in used)))
    train = [m for m in win_months("TRAIN") if m in bm]
    null = np.array([wstat({m: (rng.permutation(bm[m][0]), bm[m][1]) for m in train}, train) for _ in range(N_NULL)])
    res["floor"] = float(np.nanquantile(np.abs(null), 0.99)) if train else np.nan
    boot = np.array([wstat(bm, [s + k for s in rng.integers(0, NM - BLOCK + 1, NM // BLOCK) for k in range(BLOCK)])
                     for _ in range(N_BOOT)])
    res["ALL"] = dict(value=wstat(bm, range(NM)), ci=[float(np.nanquantile(boot, 0.025)), float(np.nanquantile(boot, 0.975))])
    res["verdict"] = verdict_of(res, hyp)
    return res


def window_values(bm):
    return {w: wstat(bm, win_months(w)) for w in WINDOWS} | {"ALL": wstat(bm, range(NM))}


def seg_table(d):
    """사건 단위 단순 집계: n, 경로 비율, 60일 초과 평균·중앙값, 20·120일 초과 평균, 60일 비용 후 절대 수익 > 0 비율."""
    m = d[d["path"].notna()]
    row = dict(n=len(m))
    for p in PATHS:
        row[p] = float((m["path"] == p).mean()) if len(m) else np.nan
    for h in HS:
        row[f"x{h}"] = float(d[f"x{h}"].mean())
    row["x60_med"] = float(m["x60"].median())
    row["win60"] = float((m["r60"] - COST > 0).mean()) if len(m) else np.nan
    return row


def economic(df, cost):
    """G 의 달별 평균(60일 비용 후 절대 수익·초과)을 구간별로 다시 평균."""
    g = df[(df["grp"] == "G") & df["x60"].notna()]
    mm = g.groupby(["win", "mi"]).agg(net=("r60", "mean"), ex=("x60", "mean")).reset_index()
    mm["net"] -= cost
    return {w: dict(net=float(mm.loc[mm["win"] == w, "net"].mean()), ex=float(mm.loc[mm["win"] == w, "ex"].mean()),
                    months=int((mm["win"] == w).sum())) for w in WINDOWS}


def run():
    A = load_all()
    df, bench, no_entry = build_events(A)
    rng = np.random.default_rng(SEED)
    J = {}
    for name, (col, a, b, xcol, hyp) in JUDGES.items():
        J[name] = judge(by_month(df, df[col] == a, df[col] == b, xcol), hyp, rng)
    econ = {"base": economic(df, COST), "stress": economic(df, COST_STRESS)}
    econ_ok = J["J2"]["verdict"] == "CONFIRMED" and all(econ["base"][w]["net"] > 0 and econ["base"][w]["ex"] > 0 for w in ("VALID", "TEST"))

    jt = df[df["win"].isin(JUDGE_WINS)]
    rec = {}
    # 1. 그룹별(G·GV·B·U) × 구간
    rec["groups"] = {w: {g: seg_table(df[(df["win"] == w) & m]) for g, m in
                         (("G", df["grp"] == "G"), ("GV", df["gv"]), ("B", df["grp"] == "B"), ("U", df["grp"] == "U"))}
                     for w in WINDOWS}
    # 2. G 안 세분(TRAIN~TEST 묶음)
    G = jt[jt["grp"] == "G"]
    sec3 = np.where(G["share"].isna(), "결측", np.where(G["share"] < 0.10, "개별(<10%)", np.where(G["share"] < 0.30, "10~30%", "≥30%")))
    pq, dq = G["pbr"].quantile([1 / 3, 2 / 3]).to_numpy(), G["dd"].quantile([1 / 3, 2 / 3]).to_numpy()
    segs = {
        "상태": G["state"].to_numpy(),
        "업종 동반": sec3,
        "저점 거리": np.where(G["dist"] < 0.02, "0~2%", "2~5%"),
        "PBR 3분위(G 안)": np.where(G["pbr"].isna(), "결측", np.where(G["pbr"] <= pq[0], "하", np.where(G["pbr"] <= pq[1], "중", "상"))),
        "52주 고점 대비 낙폭 3분위": np.where(G["dd"] <= dq[0], "깊음", np.where(G["dd"] <= dq[1], "중간", "얕음")),
        "최근 분기 영업이익 전년 대비": np.where(G["qup"] == True, "증가", "감소·같음"),
    }
    rec["g_segments"] = {k: {lab: seg_table(G[v == lab]) for lab in pd.unique(v)} for k, v in segs.items()}
    rec["g_segment_cuts"] = dict(pbr=pq.tolist(), dd=dq.tolist())
    # 3. GV vs B · G 안 J3·J4
    rec["gv_vs_b"] = {x: window_values(by_month(df, df["gv"], df["grp"] == "B", x)) for x in ("brk", "x60")}
    gm = df["grp"] == "G"
    rec["j3_in_g"] = window_values(by_month(df, gm & (df["state"] == "다지기"), gm & (df["state"] == "경신 중"), "brk"))
    rec["j4_in_g"] = window_values(by_month(df, gm & (df["sector"] == "개별"), gm & (df["sector"] == "동반"), "brk"))
    # 4. 끝남 = 추가 하락으로 본 J1
    rec["j1_end_as_break"] = window_values(by_month(df, df["grp"] == "G", df["grp"] == "B", "brk_end"))
    # 5. 시장 국면(그 달 적격 유니버스 60일 평균 수익 부호)
    up = {mi for (mi, h), v in bench.items() if h == 60 and v > 0 and mi < NM}
    down = {mi for (mi, h), v in bench.items() if h == 60 and v <= 0 and mi < NM}
    rec["regime"] = {}
    for x in ("brk", "x60"):
        bm = by_month(df, df["grp"] == "G", df["grp"] == "B", x)
        rec["regime"][x] = dict(up=wstat(bm, sorted(up)), down=wstat(bm, sorted(down)), up_months=len(up & set(bm)), down_months=len(down & set(bm)))
    # 6. G 상위·하위 20건(TRAIN~TEST, 60일 절대 수익)
    cols = ["date", "ticker", "name", "state", "r60", "x60", "path"]
    Gm = G[G["r60"].notna()].sort_values("r60")
    rec["g_top20"] = Gm.tail(20)[::-1][cols].to_dict("records")
    rec["g_bottom20"] = Gm.head(20)[cols].to_dict("records")
    # 7. 수
    rec["counts"] = dict(events=len(df), mature=int(df["path"].notna().sum()), no_entry=no_entry,
                         by_win={w: dict(df[df["win"] == w]["grp"].value_counts()) for w in WINDOWS})
    out = dict(judges=J, economic=econ, economic_ok=econ_ok, records=rec,
               params=dict(H=H_MAIN, BREAK_X=BREAK_X, REBOUND_X=REBOUND_X, COST=COST, SEED=SEED, N_NULL=N_NULL, N_BOOT=N_BOOT,
                           BLOCK=BLOCK, MIN_GROUP=MIN_GROUP, price_last=str(A["dates"][-1].date())))
    OUT.with_suffix(".json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=lambda o: None if o is None else (float(o) if np.isscalar(o) else str(o))), encoding="utf-8")
    OUT.with_suffix(".md").write_text(render(out), encoding="utf-8")
    for k, v in J.items():
        print(k, v["verdict"], {w: round(v[w]["value"], 4) for w in JUDGE_WINS}, "floor", round(v["floor"], 4), "ci", [round(c, 4) for c in v["ALL"]["ci"]])
    print("→", OUT.with_suffix(".md"))
    return 0


def posthoc():
    """사후 기록(결과를 본 뒤 추가, 판정 불사용): J3·J4 칸의 경로·수익과 사건 전 60일 변동성, 변동성 3분위 안 상태 비교."""
    A = load_all()
    df, _, _ = build_events(A)
    C, ti = A["F"]["C"], A["ti"]
    rows = {str(d.date()): i for i, d in enumerate(A["dates"])}
    lr = np.log(C[1:] / C[:-1])
    df["vol60"] = [np.nanstd(lr[max(rows[d] - 60, 0):rows[d], ti[t]]) * np.sqrt(250) for d, t in zip(df["date"], df["ticker"])]
    jt = df[df["win"].isin(JUDGE_WINS) & df["path"].notna()]
    q = jt["vol60"].quantile([1 / 3, 2 / 3]).to_numpy()
    jt = jt.assign(vq=np.where(jt["vol60"] <= q[0], "저", np.where(jt["vol60"] <= q[1], "중", "고")))
    print("| 칸 | 사건 | 추가 하락 | 다지기 | 반등 | 60일 초과 평균 | 60일 초과 중앙 | 사건 전 60일 변동성(연율, 중앙) |\n|---|---:|---:|---:|---:|---:|---:|---:|")
    for col, labs in (("state", ("경신 중", "중간", "접근", "다지기")), ("sector", ("개별", "동반"))):
        for lab in labs:
            s = jt[jt[col] == lab]
            print(f"| {lab} | {len(s)} | {(s.path == '추가 하락').mean():.0%} | {(s.path == '다지기').mean():.0%} | {(s.path == '반등').mean():.0%} | "
                  f"{pct(s.x60.mean())} | {pct(s.x60.median())} | {s.vol60.median():.0%} |")
    print(f"\n변동성 3분위 경계 {q[0]:.2f} · {q[1]:.2f}\n\n| 변동성 | 상태 | 사건 | 추가 하락 | 반등 | 60일 초과 평균 |\n|---|---|---:|---:|---:|---:|")
    for v in ("저", "중", "고"):
        for st in ("경신 중", "다지기"):
            t = jt[(jt.vq == v) & (jt.state == st)]
            print(f"| {v} | {st} | {len(t)} | {(t.path == '추가 하락').mean():.0%} | {(t.path == '반등').mean():.0%} | {pct(t.x60.mean())} |")
    return 0


def pct(x, d=1):
    return "" if x is None or not np.isfinite(x) else f"{x * 100:+.{d}f}%"


def pp(x, d=1):
    return "" if x is None or not np.isfinite(x) else f"{x * 100:+.{d}f}%p"


def render(o):
    J, rec, econ = o["judges"], o["records"], o["economic"]
    conf = [k for k, v in J.items() if v["verdict"] == "CONFIRMED"]
    rev = [k for k, v in J.items() if v["verdict"] == "반대 방향 확정"]
    overall = "CONFIRMED" if conf else ("REVERSE" if rev else "INCONCLUSIVE")
    sig = "있음(" + "·".join(conf + [f"{k} 반대" for k in rev]) + ")" if conf or rev else "없음"
    unit = {"J1": pp, "J2": pp, "J3": pp, "J4": pp}
    desc = {"J1": "추가 하락 확률 G − B", "J2": "60일 초과수익 G − B", "J3": "추가 하락 확률 다지기 − 경신 중", "J4": "추가 하락 확률 개별 − 동반"}
    L = ["---", "track: kr", "factor: low52-fundamental-paths", "date: 2026-10-08", f"verdict: {overall}",
         "criteria_version: research-only (low52-fundamental-paths-preregistration-2026-10)",
         'conditions: ["월말 52주 저점 +5% 이내 · 거래대금 10억 · 보통주", "G = TTM 영업이익 흑자·전년 대비 증가(PIT)", '
         '"경로 3갈래 60거래일(추가 하락 = 저점 × 0.90, 반등 = 진입가 × 1.20)", "같은 달 안 비교·표본 가중·월 안 순열 99백분위·6개월 블록 부트스트랩", '
         '"TRAIN 2016~2020 / VALID 2021~22 / TEST 2023~25", "비용 23.54bp"]',
         "reason: >-",
         f"  신호: {sig} · 경제성: {'통과' if o['economic_ok'] else '미달'}. "
         + " · ".join(f"{k} {v['verdict']}" for k, v in J.items()) + ". (스크립트가 계산한 판정, 정의는 사전등록 그대로)",
         "---", "", "# 52주 저점 근처 × 실적 — 이후 경로 3갈래 결과", "",
         "수치는 `low52_fundamental_paths.py --run` 이 계산해 그대로 옮긴 값이다. 정의·구간·판정은 사전등록(`low52-fundamental-paths-preregistration-2026-10`, 동결 876c905f) 그대로이며 결과를 보고 바꾸지 않았다.",
         f"가격 마지막 날 {o['params']['price_last']}. 사건 {rec['counts']['events']:,}건(60일 성숙 {rec['counts']['mature']:,}, 진입 시가 없어 제외 {rec['counts']['no_entry']}).", "",
         "## 1. 판정", "",
         "| 판정 | 값 | TRAIN | VALID | TEST | 전체(2016~2025) [블록 95%] | 바닥선(TRAIN 99백분위) | 쓴 달 TRAIN/VALID/TEST | 사건 그룹1/그룹2 (TRAIN) | 판정 |",
         "|---|---|---:|---:|---:|---|---:|---|---|---|"]
    for k, v in J.items():
        f = unit[k] if k != "J2" else pp
        L.append(f"| {k} | {desc[k]} | {f(v['TRAIN']['value'])} | {f(v['VALID']['value'])} | {f(v['TEST']['value'])} | "
                 f"{f(v['ALL']['value'])} [{f(v['ALL']['ci'][0])}, {f(v['ALL']['ci'][1])}] | {f(v['floor'])} | "
                 f"{v['TRAIN']['months']}/{v['VALID']['months']}/{v['TEST']['months']} | {v['TRAIN']['n1']}/{v['TRAIN']['n2']} | **{v['verdict']}** |")
    L += ["", f"2026 성숙분(기록): " + " · ".join(f"{k} {pp(v['REC']['value'])}({v['REC']['months']}달)" for k, v in J.items()), "",
          "## 2. 경제성 (G 의 60일 절대 수익·초과, 달별 평균의 구간 평균)", "",
          "| 구간 | 비용 23.54bp 후 절대 | 초과(유니버스 대비) | 스트레스 33.5bp 후 절대 | 달 수 |", "|---|---:|---:|---:|---:|"]
    for w in WINDOWS:
        b, s = econ["base"][w], econ["stress"][w]
        L.append(f"| {w} | {pct(b['net'])} | {pct(b['ex'])} | {pct(s['net'])} | {b['months']} |")
    L += ["", f"ECONOMIC 조건(J2 가설 방향 확정 ∧ VALID·TEST 절대·초과 모두 양): **{'통과' if o['economic_ok'] else '미달'}**.", "",
          "## 3. 기록 — 그룹별 경로·수익 (사건 단위 단순 집계)", "",
          "| 구간 | 그룹 | 사건(성숙) | 추가 하락 | 다지기 | 반등 | 끝남 | 20일 초과 | 60일 초과 평균 | 60일 초과 중앙 | 120일 초과 | 60일 비용 후 > 0 |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for w, gs in rec["groups"].items():
        for g, r in gs.items():
            L.append(f"| {w} | {g} | {r['n']} | {pct(r['추가 하락'], 0)} | {pct(r['다지기'], 0)} | {pct(r['반등'], 0)} | {pct(r['끝남'], 0)} | "
                     f"{pct(r['x20'])} | {pct(r['x60'])} | {pct(r['x60_med'])} | {pct(r['x120'])} | {pct(r['win60'], 0)} |")
    L += ["", "## 4. 기록 — G 안 세분 (TRAIN~TEST 묶음, 사건 단위)", "",
          f"PBR 3분위 경계 {', '.join(f'{x:.2f}' for x in rec['g_segment_cuts']['pbr'])} · 낙폭 3분위 경계 {', '.join(pct(x, 0) for x in rec['g_segment_cuts']['dd'])}.", "",
          "| 축 | 칸 | 사건(성숙) | 추가 하락 | 다지기 | 반등 | 끝남 | 60일 초과 평균 | 60일 초과 중앙 | 60일 비용 후 > 0 |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k, cells in rec["g_segments"].items():
        for lab, r in sorted(cells.items()):
            L.append(f"| {k} | {lab} | {r['n']} | {pct(r['추가 하락'], 0)} | {pct(r['다지기'], 0)} | {pct(r['반등'], 0)} | {pct(r['끝남'], 0)} | "
                     f"{pct(r['x60'])} | {pct(r['x60_med'])} | {pct(r['win60'], 0)} |")
    L += ["", "## 5. 기록 — 다른 대조 (같은 가중 방식, 판정 아님)", "", "| 대조 | TRAIN | VALID | TEST | REC 2026 | 전체 |", "|---|---:|---:|---:|---:|---:|"]
    for lab, wv in (("GV vs B 추가 하락", rec["gv_vs_b"]["brk"]), ("GV vs B 60일 초과", rec["gv_vs_b"]["x60"]),
                    ("J1, 끝남 = 추가 하락", rec["j1_end_as_break"]), ("J3 G 안에서", rec["j3_in_g"]), ("J4 G 안에서", rec["j4_in_g"])):
        L.append(f"| {lab} | {pp(wv['TRAIN'])} | {pp(wv['VALID'])} | {pp(wv['TEST'])} | {pp(wv['REC'])} | {pp(wv['ALL'])} |")
    rg = rec["regime"]
    L += ["", f"시장 국면(그 달 유니버스 60일 평균 수익): 상승 달 J1 {pp(rg['brk']['up'])} · J2 {pp(rg['x60']['up'])} ({rg['brk']['up_months']}달) / "
          f"하락 달 J1 {pp(rg['brk']['down'])} · J2 {pp(rg['x60']['down'])} ({rg['brk']['down_months']}달).", "",
          "## 6. 기록 — G 60일 절대 수익 상위·하위 20건 (TRAIN~TEST)", "", "| 순 | 신호일 | 종목 | 상태 | 60일 | 초과 | 경로 |", "|---|---|---|---|---:|---:|---|"]
    for tag, rows in (("상", rec["g_top20"]), ("하", rec["g_bottom20"])):
        for i, x in enumerate(rows, 1):
            L.append(f"| {tag}{i} | {x['date']} | {x['name']}({x['ticker']}) | {x['state']} | {pct(x['r60'], 0)} | {pct(x['x60'], 0)} | {x['path']} |")
    return "\n".join(L) + "\n"


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

    # 경로 3갈래: 저점 100, 진입 103 → 추가 하락 ≤ 90 · 반등 ≥ 123.6
    check("저점 −10% 를 먼저 깸 → 추가 하락", path_of(np.array([100, 95, 89, 130.0]), 100, 103, False) == "추가 하락")
    check("+20% 를 먼저 넘음 → 반등(결측일 건너뜀)", path_of(np.array([100, np.nan, 124, 80.0]), 100, 103, False) == "반등")
    check("둘 다 아님 → 다지기", path_of(np.array([95, 110, 120.0]), 100, 103, False) == "다지기")
    check("둘 다 아니고 데이터 끝남 → 끝남", path_of(np.array([95, np.nan, np.nan]), 100, 103, True) == "끝남")
    # 가중 평균: 달 0 은 G[1,1,1]·B[0,0,0] → 차 1, w 1.5 · 달 1 은 G[0]×3·B[0]×6 → 차 0, w 2
    bm = {0: (np.r_[np.ones(3), np.zeros(3)], 3), 1: (np.zeros(9), 3)}
    check("표본 가중 평균 = 1.5/3.5", abs(wstat(bm, [0, 1]) - 1.5 / 3.5) < 1e-12 and abs(wstat(bm, [0, 0, 1]) - 3 / 5) < 1e-12)
    # 판정 규칙: 합성 120달, 달마다 G·B 각 10건
    def synth(p1, p2, seed):
        r = np.random.default_rng(seed)
        rows = [dict(mi=m, grp=g, brk=float(r.random() < (p1 if g == "G" else p2))) for m in range(NM) for g in ("G", "B") for _ in range(10)]
        d = pd.DataFrame(rows)
        return by_month(d, d["grp"] == "G", d["grp"] == "B", "brk")
    check("G 추가 하락 10% vs B 40% → 가설(−) 확정", judge(synth(0.1, 0.4, 1), -1, np.random.default_rng(0))["verdict"] == "CONFIRMED")
    check("같은 효과를 가설(+)로 보면 반대 방향 확정", judge(synth(0.1, 0.4, 1), +1, np.random.default_rng(0))["verdict"] == "반대 방향 확정")
    check("차이 없음 → 확정 아님", judge(synth(0.3, 0.3, 2), -1, np.random.default_rng(0))["verdict"].startswith("INCONCLUSIVE"))
    sparse = {m: v for m, v in synth(0.1, 0.4, 1).items() if m % 3 == 0}
    check("쓸 수 있는 달이 절반 미만 → 표본 부족", judge(sparse, -1, np.random.default_rng(0))["verdict"] == "INCONCLUSIVE(표본 부족)")
    print("ALL PASS" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    for a in ("--collect-recent", "--counts", "--snapshot", "--run", "--posthoc", "--selftest"):
        g.add_argument(a, action="store_true")
    a = ap.parse_args()
    sys.exit(collect_recent() if a.collect_recent else counts() if a.counts else snapshot() if a.snapshot else run() if a.run else posthoc() if a.posthoc else selftest())
