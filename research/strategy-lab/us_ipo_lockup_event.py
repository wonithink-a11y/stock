"""미국 IPO 보호예수 해제(명목 180일) 전후 이벤트 연구 — E 레인.
사전등록: findings/us-ipo-lockup-preregistration-2026-11.md (표본·창·귀무·셀 동결).

  python research/strategy-lab/us_ipo_lockup_event.py [--out findings/us-ipo-lockup-results-2026-11.md]
  python research/strategy-lab/us_ipo_lockup_event.py --judge     # forward(SPCX 12/8·ANT) 는 날짜 전 거부, 건수만

시각: 일봉 날짜 = 미국 거래일. 장 마감(16:00 ET)의 KST 시각을 표에 같이 적는다.
자료: 야후 공개 차트(us_daily_yahoo.fetch), 조정종가 · 거래량.
"""
import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import us_daily_yahoo as Y

SAMPLE = ["META", "BABA", "UBER", "LYFT", "ABNB", "SNOW", "RIVN", "ARM", "PINS", "ZM", "SNAP",
          "DASH", "DDOG", "HOOD", "RDDT", "CART", "CRWV", "CRCL", "V"]
WIN = {"A[-10,-1]": (-10, -1), "B[0,+4]": (0, 4), "C[+5,+20]": (5, 20)}
NULL_N, BOOT_N, SEED = 1000, 2000, 20261126
ET, KST = ZoneInfo("America/New_York"), ZoneInfo("Asia/Seoul")

# 예정(공식 미확인·출처 간 차이): 날짜 전에는 판정 거부
FORWARD = {"SPCX": ["2026-12-08"], "ANT": ["2026-12-15", "2027-01-05", "2027-01-19", "2027-02-02"]}


def kst_close(d):
    t = datetime(d.year, d.month, d.day, 16, 0, tzinfo=ET).astimezone(KST)
    return t.strftime("%m-%d %H:%M")


def load_px(sym):
    p = Path("/tmp/claude-0/px") / f"{sym}.csv"
    if p.exists():
        return pd.read_csv(p, index_col=0, parse_dates=True)
    return Y.fetch(sym)


def event_index(idx):
    """첫 거래일 + 180달력일 이후 첫 거래일의 위치."""
    tgt = pd.Timestamp(idx[0]) + pd.Timedelta(days=180)
    pos = idx.searchsorted(tgt)
    return pos if pos < len(idx) else None


def win_sum(arr, pos, lo, hi):
    return float(np.nansum(arr[pos + lo: pos + hi + 1]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--judge", action="store_true")
    a = ap.parse_args()
    if a.judge:
        today = date.today()
        for k, ds in FORWARD.items():
            left = [d for d in ds if date.fromisoformat(d) > today]
            print(f"{k}: forward 예정 {len(ds)}건 · 아직 안 지난 것 {len(left)}건 → 판정 거부(새 사전등록 전 판정 없음)")
        return

    rng = np.random.default_rng(SEED)
    ndx = load_px("^NDX")["adjclose"]
    rows, prof, flags, ev = [], {}, [], []
    data = {}
    for s in SAMPLE:
        px = load_px(s)
        df = pd.DataFrame({"c": px["adjclose"], "v": px["volume"]}).join(ndx.rename("n"), how="inner").dropna(subset=["c", "n"])
        df["rs"], df["rn"] = np.log(df.c).diff(), np.log(df.n).diff()
        df["ex"] = df.rs - df.rn
        pos = event_index(df.index)
        if pos is None or pos + 20 >= len(df) or pos < 121:
            print("제외(자료 부족):", s)
            continue
        data[s] = (df, pos)
        ev.append(s)
    n = len(ev)
    print("사건", n, "건:", ev)

    def stat(df, pos, kind):
        arr = (df.ex if kind == "ex" else df.rn).to_numpy()
        return [win_sum(arr, pos, lo, hi) for (lo, hi) in WIN.values()]

    obs = {k: np.array([stat(*data[s], k) for s in ev]) for k in ("ex", "rn")}   # n × 3

    # 귀무
    nulls = {k: np.zeros((NULL_N, 3)) for k in obs}
    for b in range(NULL_N):
        acc = {k: [] for k in obs}
        for s in ev:
            df, pos = data[s]
            lo_ok = 30
            cand = [p for p in range(lo_ok, len(df) - 25) if abs(p - pos) > 25]
            p0 = cand[rng.integers(len(cand))]
            for k in acc:
                acc[k].append(stat(df, p0, k))
        for k in obs:
            nulls[k][b] = np.mean(acc[k], axis=0)

    names = list(WIN)
    cells = []
    for k, label in (("ex", "종목 초과(−NDX)"), ("rn", "NDX 원수익")):
        for j, w in enumerate(names):
            x = obs[k][:, j]
            m = x.mean()
            bs = np.array([rng.choice(x, n).mean() for _ in range(BOOT_N)])
            nl = nulls[k][:, j]
            p = (np.sum(np.abs(nl - nl.mean()) >= abs(m - nl.mean())) + 1) / (NULL_N + 1)
            cells.append(dict(kind=label, k=k, w=w, mean=m, lo=np.percentile(bs, 2.5), hi=np.percentile(bs, 97.5),
                              med=float(np.median(x)), win=float((x < 0).mean()), nmean=nl.mean(),
                              p1=np.percentile(nl, 1), p99=np.percentile(nl, 99), p=p, j=j))
    # BH(누적 K) — 이 실행의 6칸 + 장부 누적 K 는 호출자가 trials.py 로 확인
    try:
        import trials as T
        K = T.count("us-ipo-lockup") + len(cells)
    except Exception:
        K = len(cells)
    order = sorted(range(len(cells)), key=lambda i: cells[i]["p"])
    passed = set()
    for rank, i in enumerate(order, 1):
        if cells[i]["p"] <= 0.10 * rank / K:
            passed = set(order[:rank])
    for i, c in enumerate(cells):
        out = c["mean"] < c["p1"] or c["mean"] > c["p99"]
        c["verdict"] = "INFORMATION" if (out and i in passed and n >= 5) else "NONE"

    # 시기·진단
    def sub(mask_fn, k):
        xs = np.array([obs[k][i] for i, s in enumerate(ev) if mask_fn(s)])
        return xs.mean(axis=0) if len(xs) else None, len(xs)
    e0year = {s: data[s][0].index[data[s][1]].year for s in ev}
    per = {"≤2023": lambda s: e0year[s] <= 2023, "2024": lambda s: e0year[s] == 2024, "2025~": lambda s: e0year[s] >= 2025,
           "ARM 제외": lambda s: s != "ARM", "V 제외": lambda s: s != "V"}

    # 이벤트 프로필·특별 사건
    offs = list(range(-20, 21))
    prof_ex = np.array([[data[s][0].ex.iloc[data[s][1] + o] for o in offs] for s in ev])
    prof_rn = np.array([[data[s][0].rn.iloc[data[s][1] + o] for o in offs] for s in ev])
    for s in ev:
        df, pos = data[s]
        base = df.iloc[pos - 120: pos - 30]
        sd, vm = base.ex.std(), base.v.median()
        for o in range(-10, 21):
            r = df.iloc[pos + o]
            z = r.ex / sd if sd else 0
            vr = r.v / vm if vm else np.nan
            if abs(z) >= 3 or vr >= 3:
                flags.append((s, o, df.index[pos + o].date(), z, vr, r.ex * 100))

    L = []
    L.append("---\ntrack: us\nfactor: ipo-lockup-event-window\ndate: 2026-11-26\n")
    any_info = any(c["verdict"] == "INFORMATION" for c in cells)
    L.append(f"verdict: {'INFORMATION' if any_info else 'NONE'}\nlane: E\ncriteria_version: RP-2.0\n")
    L.append('conditions: ["명목 180일 사건일 19건(자료 부족 제외 후 %d)", "창 A[-10,-1] B[0,+4] C[+5,+20]", "귀무 1,000회 1·99백분위 + BH 10%% 누적 K=%d"]\n' % (n, K))
    L.append(f"reason: >-\n  신호: {'일부 있음' if any_info else '없음'} · 경제성: 미측정(이벤트 연구). 스크립트 판정, 사전등록 동결.\n---\n")
    L.append("# 미국 대형 IPO 보호예수 해제 전후 — 결과 (E 레인)\n")
    L.append(f"사전등록 `us-ipo-lockup-preregistration-2026-11.md` (커밋 b8182a7). 사건 {n}건. 일봉 날짜는 미국 거래일, 장 마감 16:00 ET = 한국 다음날 05:00/06:00.\n")
    L.append("## 1. 표 (로그수익 합, %)\n")
    L.append("| 칸 | 평균 [부트 95%] | 중앙 | 음(−) 비율 | 귀무 평균 · 1/99백분위 | 경험 p | 판정 |\n|---|---|---:|---:|---|---:|---|")
    for c in cells:
        L.append(f"| {c['kind']} {c['w']} | {c['mean']*100:+.2f}% [{c['lo']*100:+.2f}%, {c['hi']*100:+.2f}%] | {c['med']*100:+.2f}% | {c['win']*100:.0f}% | {c['nmean']*100:+.2f}% · {c['p1']*100:+.2f}%/{c['p99']*100:+.2f}% | {c['p']:.3f} | **{c['verdict']}** |")
    L.append("\n## 2. 시기·진단 (기록 전용)\n")
    L.append("| 구간 | 건수 | 종목 초과 A | B | C | NDX A | B | C |\n|---|---:|---:|---:|---:|---:|---:|---:|")
    for nm, fn in per.items():
        e, cnt = sub(fn, "ex")
        r_, _ = sub(fn, "rn")
        if e is None:
            continue
        L.append(f"| {nm} | {cnt} | " + " | ".join(f"{v*100:+.2f}%" for v in e) + " | " + " | ".join(f"{v*100:+.2f}%" for v in r_) + " |")
    L.append("\n## 3. 사건별 (E0 = 미국 날짜 · 마감 KST)\n")
    L.append("| 종목 | E0(US) | 마감 KST | A 초과 | B 초과 | C 초과 | NDX A | B | C |\n|---|---|---|---:|---:|---:|---:|---:|---:|")
    for i, s in enumerate(ev):
        d0 = data[s][0].index[data[s][1]].date()
        L.append(f"| {s} | {d0} | {kst_close(d0)} | " + " | ".join(f"{v*100:+.1f}%" for v in obs['ex'][i]) + " | " + " | ".join(f"{v*100:+.1f}%" for v in obs['rn'][i]) + " |")
    L.append("\n## 4. 사건 시간 프로필 — 평균 누적 (오프셋 거래일, 기록)\n")
    L.append("| 오프셋 | -20 | -10 | -5 | -1 | 0 | +1 | +2 | +4 | +10 | +20 |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for nm, pf in (("종목 초과 누적(−20 기준)", prof_ex), ("NDX 누적(−20 기준)", prof_rn)):
        cum = np.cumsum(pf.mean(axis=0))
        pick = [-20, -10, -5, -1, 0, 1, 2, 4, 10, 20]
        L.append(f"| {nm} | " + " | ".join(f"{cum[offs.index(o)]*100:+.2f}%" for o in pick) + " |")
    L.append("\n## 5. 특별 사건 후보 (창 -10~+20, |초과| ≥ 3σ 또는 거래량 ≥ 3× — 원인 미확인, 사후 관찰)\n")
    L.append("| 종목 | 오프셋 | 미국 날짜 | z | 거래량배수 | 초과 |\n|---|---:|---|---:|---:|---:|")
    for s, o, d, z, vr, ex in flags:
        L.append(f"| {s} | {o:+d} | {d} | {z:+.1f} | {vr:.1f}× | {ex:+.1f}% |")
    L.append(f"\n(후보 {len(flags)}건. 실적·증자·지수 편입 등 원인은 아래 별도 조사.)\n")
    txt = "\n".join(L)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
        print("wrote", a.out)
    print(txt)


if __name__ == "__main__":
    main()
