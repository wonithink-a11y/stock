"""VIX · 공탐 · RSI 극단 규칙 — 섹터·배당·주도섹터 ETF 와 한국 시장 적용. 사전등록 vix-fng-rsi-sector-kr-preregistration-2026-11.md 를 그대로 실행.

    python research/strategy-lab/vix_fng_rsi_sector_kr.py

판정 = 묶음 평균 ΔSharpe(묶음×규칙 18셀, α 0.05/40). 대상별 표·진단은 기록 전용. 체결·비용·창은 vix_fng_rsi_timing 의 함수를 그대로 쓴다.
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import vix_fng_rsi_timing as m  # noqa: E402

warnings.filterwarnings("ignore")
m.BOOT, m.ALPHA = 4000, 0.05 / 40
OUT_JSON = ROOT / "findings/vix-fng-rsi-sector-kr-results.json"
US_SEC = {"XLK": "기술", "XLF": "금융", "XLE": "에너지", "XLV": "헬스", "XLY": "경기소비", "XLP": "필수소비", "XLI": "산업", "XLB": "소재", "XLU": "유틸"}
US_DIV = {"VYM": "배당", "DVY": "배당2"}
KR_IDX = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}
KR_SEC = {"091160.KS": "반도체", "091180.KS": "자동차", "091170.KS": "은행", "117680.KS": "철강", "117460.KS": "에너지화학", "117700.KS": "건설", "102970.KS": "증권"}
RECORD = {"SCHD": ("US", "배당성장"), "161510.KS": ("KR", "ARIRANG고배당주"), "210780.KS": ("KR", "TIGER코스피고배당"),
          "279530.KS": ("KR", "KODEX고배당"), "266410.KS": ("KR", "필수소비"), "266420.KS": ("KR", "헬스케어")}
GROUPS = {"US 경기민감": ["XLK", "XLY", "XLI", "XLB", "XLF"], "US 방어": ["XLV", "XLP", "XLU"], "US 에너지": ["XLE"], "US 배당": ["VYM", "DVY"],
          "KR 경기": ["091160.KS", "091180.KS", "117680.KS", "117460.KS", "117700.KS"], "KR 금융": ["091170.KS", "102970.KS"]}
RULES = m.RULES
PPY = {"D": 252, "W": 52}
BLK = {"D": 21, "W": 4}
LB, TOPK = 126, 3


def get(t):
    x = yf.download(t, start="2010-06-01", end="2026-03-12", auto_adjust=True, progress=False)
    x.columns = x.columns.get_level_values(0)
    return x[["Open", "Close"]].dropna().rename(columns={"Open": "O", "Close": "C"})


def attach(d, us):
    """대상 일봉에 미국 VIX·공탐(같은 달력일 값, 없으면 직전)과 자기 RSI14 를 붙인다."""
    s = us[["vix", "fg"]]
    sig = s.reindex(s.index.union(d.index)).ffill().reindex(d.index)
    out = d.join(sig)
    out["rsi"] = m.rsi14(out["C"])
    return out


def weekly(d):
    g = d.groupby(pd.Grouper(freq="W-FRI"))
    w = pd.DataFrame({"O": g["O"].first(), "C": g["C"].last(), "vix": g["vix"].last(), "fg": g["fg"].last()}).dropna(subset=["C"])
    w = w[w.index <= pd.Timestamp(m.END)]
    w["rsi"] = m.rsi14(w["C"])
    return w


def basket(comps):
    names = list(comps)
    C = np.column_stack([comps[n]["C"] for n in names])
    O = np.column_stack([comps[n]["O"] for n in names])
    idx = comps[names[0]].index
    n = len(C)
    gon = np.zeros_like(C)
    gon[1:] = O[1:] / C[:-1] - 1
    gid = C / O - 1
    W = np.zeros_like(C)
    cur = np.full(len(names), 1 / len(names))
    for t in range(n):
        W[t] = cur
        last = t == n - 1 or idx[t].month != idx[t + 1].month
        if last and t >= LB:
            top = np.argsort(-(C[t] / C[t - LB] - 1))[:TOPK]
            cur = np.zeros(len(names))
            cur[top] = 1 / TOPK
    gb_on, gb_id = (W * gon).sum(1), (W * gid).sum(1)
    Cb = 100 * np.cumprod((1 + gb_on) * (1 + gb_id))
    Ob = np.r_[100.0, Cb[:-1]] * (1 + gb_on)
    return pd.DataFrame({"O": Ob, "C": Cb}, index=idx)


def win(df):
    i0 = max(df.index.searchsorted(pd.Timestamp(m.START)), 1)
    return df.iloc[i0 - 1:df.index.searchsorted(pd.Timestamp(m.END), side="right")]


def build_panels(us):
    P = {}
    def load(group):
        raw = {t: get(t) for t in group}
        base = raw[next(iter(raw))].index
        return {t: x.reindex(base).ffill().dropna() for t, x in raw.items()}
    us_sec = load(US_SEC)
    kr_sec = load(KR_SEC)
    P["US 섹터"] = ({**{t: attach(x, us) for t, x in us_sec.items()}}, US_SEC)
    P["US 배당"] = ({t: attach(x, us) for t, x in load(US_DIV).items()}, US_DIV)
    P["US 주도섹터"] = ({"주도3": attach(basket(us_sec), us)}, {"주도3": "주도섹터 상위3"})
    P["KR 지수"] = ({t: attach(x, us) for t, x in load(KR_IDX).items()}, KR_IDX)
    P["KR 업종"] = ({t: attach(x, us) for t, x in kr_sec.items()}, KR_SEC)
    P["KR 주도업종"] = ({"주도3": attach(basket(kr_sec), us)}, {"주도3": "주도업종 상위3"})
    return P


def sharpe(r, ppy):
    return r.mean() / r.std(ddof=1) * np.sqrt(ppy)


def panel_cell(frames, rule, tf, ppy, blk, rng):
    col, sell, buy = RULES[rule]
    names = list(frames)
    F = {k: win(v if tf == "D" else weekly(v)) for k, v in frames.items()}
    ref = F[names[0]].index
    n = len(ref) - 1
    arr = {k: (F[k]["O"].to_numpy(), F[k]["C"].to_numpy(), m.state(F[k][col].to_numpy(), sell, buy)) for k in names}
    R, B, T1, inm = {}, {}, {}, {}
    for k, (O, C, T) in arr.items():
        R[k], T1[k] = m.returns(O, C, T)
        B[k] = C[1:] / C[:-1] - 1
    idx = ref[1:]
    yrs = (idx[-1] - idx[0]).days / 365.25
    Rm, Bm = np.column_stack([R[k] for k in names]), np.column_stack([B[k] for k in names])
    shr, shb = np.array([sharpe(Rm[:, i], ppy) for i in range(len(names))]), np.array([sharpe(Bm[:, i], ppy) for i in range(len(names))])
    mr = {k: m.metrics(R[k], idx, ppy) for k in names}
    mb = {k: m.metrics(B[k], idx, ppy) for k in names}
    nb = int(np.ceil(n / blk))
    bt = np.empty(m.BOOT)
    for b in range(m.BOOT):
        ix = ((rng.integers(0, n, nb)[:, None] + np.arange(blk)) % n).ravel()[:n]
        a, c = Rm[ix], Bm[ix]
        bt[b] = (a.mean(0) / a.std(0, ddof=1) - c.mean(0) / c.std(0, ddof=1)).mean() * np.sqrt(ppy)
    nsh, ncg = np.empty((m.BOOT, len(names))), np.empty((m.BOOT, len(names)))
    for b in range(m.BOOT):
        kk = int(rng.integers(21, n - 21))
        for i, k in enumerate(names):
            O, C, T = arr[k]
            rr, _ = m.returns(O, C, np.r_[1.0, np.roll(T[1:], kk)])
            nsh[b, i], ncg[b, i] = sharpe(rr, ppy), np.prod(1 + rr) ** (1 / yrs) - 1
    pm = (int((nsh.mean(1) >= shr.mean()).sum()) + 1) / (m.BOOT + 1)
    pi = {k: (int((nsh[:, i] >= shr[i]).sum()) + 1) / (m.BOOT + 1) for i, k in enumerate(names)}
    dsh = float((shr - shb).mean())
    lo, hi = float(np.quantile(bt, m.ALPHA / 2)), float(np.quantile(bt, 1 - m.ALPHA / 2))
    cag_r, cag_b = np.mean([mr[k]["cagr"] for k in names]), np.mean([mb[k]["cagr"] for k in names])
    ver = m.verdict(pm, lo, dsh, cag_r, cag_b)
    inst = {}
    for i, k in enumerate(names):
        t1, bb = T1[k], B[k]
        cash = t1 == 0
        ep = []
        j = 0
        while j < len(cash):
            if cash[j]:
                e = j
                while e + 1 < len(cash) and cash[e + 1]:
                    e += 1
                ep.append(float(np.prod(1 + bb[j:e + 1]) - 1))
                j = e + 1
            else:
                j += 1
        inst[k] = dict(rule=mr[k], hold=mb[k], dsharpe=float(shr[i] - shb[i]), p=pi[k], inmkt=float(t1.mean()), trades=int(np.abs(np.diff(arr[k][2])).sum()),
                       in_ann=float(bb[t1 == 1].mean() * ppy) if (t1 == 1).any() else None, cash_ann=float(bb[cash].mean() * ppy) if cash.any() else None,
                       ep_n=len(ep), ep_mean=float(np.mean(ep)) if ep else None, avoided=float(-sum(e for e in ep if e < 0)), missed=float(sum(e for e in ep if e > 0)),
                       null_cagr=float(ncg[:, i].mean()))
    ys = {}  # 연도·시기는 대상별 (규칙−보유) 수익의 평균
    for y in sorted(set(idx.year)):
        mk = idx.year == y
        ys[int(y)] = float(np.mean([(np.prod(1 + R[k][mk]) - 1) - (np.prod(1 + B[k][mk]) - 1) for k in names]))
    eras = {}
    for nm, a, z in m.ERAS:
        mk = (idx.year >= a) & (idx.year <= z)
        eras[nm] = float(np.mean([(np.prod(1 + R[k][mk]) - 1) - (np.prod(1 + B[k][mk]) - 1) for k in names]))
    return dict(verdict=ver, dsharpe=dsh, ci=[lo, hi], p=pm, cagr_rule=float(cag_r), cagr_hold=float(cag_b),
                sharpe_rule=float(shr.mean()), sharpe_hold=float(shb.mean()), n_inst=len(names), inst=inst, years=ys, eras=eras)


def record_only(us):
    out = {}
    for t, (mk, nm) in RECORD.items():
        d = attach(get(t), us)
        for tf in "D":
            for rule, (col, sell, buy) in RULES.items():
                f = win(d)
                O, C = f["O"].to_numpy(), f["C"].to_numpy()
                T = m.state(f[col].to_numpy(), sell, buy)
                r, T1 = m.returns(O, C, T)
                rb = C[1:] / C[:-1] - 1
                idx = f.index[1:]
                out[f"{nm}|{rule}"] = dict(start=str(idx[0].date()), rule=m.metrics(r, idx, 252), hold=m.metrics(rb, idx, 252), inmkt=float(T1.mean()), trades=int(np.abs(np.diff(T)).sum()))
    return out


def main():
    us = m.build_frames()["D"]
    P = build_panels(us)
    rng = np.random.default_rng(m.SEED)
    res, rec = {}, None
    for tf in "DW":
        for pn, (frames, _) in P.items():
            for rule in RULES:
                res[f"{pn}|{rule}|{tf}"] = panel_cell(frames, rule, tf, PPY[tf], BLK[tf], rng)
    rec = record_only(us)
    OUT_JSON.write_text(json.dumps(dict(cells=res, record=rec), ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    pc = lambda x: "-" if x is None else f"{x * 100:+.1f}%"
    print("## 판정 묶음 평균 (일봉 판정 18셀, 주봉은 기록 전용)  α 0.05/40 = 0.00125")
    print("| 묶음 | 규칙 | 봉 | 판정 | 평균 CAGR 규칙/보유 | 평균 샤프 규칙/보유 | 평균 ΔSharpe [99.875% CI] | 타이밍 p |")
    print("|---|---|---|---|---|---|---|---|")
    for k, v in res.items():
        pn, rule, tf = k.split("|")
        tag = v["verdict"] if tf == "D" else f"({v['verdict']})"
        print(f"| {pn} | {rule} | {tf} | **{tag}** | {pc(v['cagr_rule'])}/{pc(v['cagr_hold'])} | {v['sharpe_rule']:.2f}/{v['sharpe_hold']:.2f} | {v['dsharpe']:+.2f} [{v['ci'][0]:+.2f}, {v['ci'][1]:+.2f}] | {v['p']:.4f} |")
    print("\n## 대상별 (일봉, 기록 전용): CAGR 규칙/보유 · 샤프 규칙/보유 · MDD · 체류 · 전환 · p(참고)")
    names = {**US_SEC, **US_DIV, **KR_IDX, **KR_SEC, "주도3": "주도 상위3"}
    for rule in RULES:
        print(f"\n### {rule}")
        print("| 묶음 | 대상 | CAGR 규칙/보유 | 샤프 규칙/보유 | MDD 규칙/보유 | 체류 | 전환 | p |\n|---|---|---|---|---|---|---|---|")
        for pn in P:
            for t, v in res[f"{pn}|{rule}|D"]["inst"].items():
                print(f"| {pn} | {names.get(t, t)} | {pc(v['rule']['cagr'])}/{pc(v['hold']['cagr'])} | {v['rule']['sharpe']:.2f}/{v['hold']['sharpe']:.2f} | {pc(v['rule']['mdd'])}/{pc(v['hold']['mdd'])} | {v['inmkt']*100:.0f}% | {v['trades']} | {v['p']:.2f} |")
    print("\n## 성격별 평균 (일봉, 기록 전용): CAGR 규칙−보유 %p / ΔSharpe")
    print("| 성격 | " + " | ".join(RULES) + " |\n|---|" + "---|" * len(RULES))
    allinst = {}
    for pn in P:
        for rule in RULES:
            for t, v in res[f"{pn}|{rule}|D"]["inst"].items():
                allinst[(t, rule)] = v
    for g, ts in GROUPS.items():
        cells = []
        for rule in RULES:
            vs = [allinst[(t, rule)] for t in ts if (t, rule) in allinst]
            cells.append(f"{np.mean([v['rule']['cagr'] - v['hold']['cagr'] for v in vs]) * 100:+.1f}%p / {np.mean([v['dsharpe'] for v in vs]):+.2f}")
        print(f"| {g} | " + " | ".join(cells) + " |")
    print("\n## 진단 (일봉, 묶음 평균): 시장 연수익 체류봉/현금봉 · 피한 손실 vs 놓친 이익(대상 합) · 무작위 타이밍 CAGR")
    print("| 묶음 | 규칙 | 체류봉 / 현금봉 | 피한 vs 놓친 (%p 합) | 무작위 타이밍 CAGR | 규칙 CAGR |\n|---|---|---|---|---|---|")
    for pn in P:
        for rule in RULES:
            v = res[f"{pn}|{rule}|D"]
            I = list(v["inst"].values())
            ia = np.mean([i["in_ann"] for i in I if i["in_ann"] is not None])
            ca = [i["cash_ann"] for i in I if i["cash_ann"] is not None]
            print(f"| {pn} | {rule} | {pc(ia)} / {pc(np.mean(ca)) if ca else '-'} | {sum(i['avoided'] for i in I)*100:.0f} vs {sum(i['missed'] for i in I)*100:.0f} | {pc(np.mean([i['null_cagr'] for i in I]))} | {pc(v['cagr_rule'])} |")
    print("\n## 시기별 평균 초과(규칙−보유, %p, 일봉)")
    print("| 묶음 | 규칙 | " + " | ".join(n for n, _, _ in m.ERAS) + " |\n|---|---|" + "---|" * len(m.ERAS))
    for pn in P:
        for rule in RULES:
            v = res[f"{pn}|{rule}|D"]
            print(f"| {pn} | {rule} | " + " | ".join(f"{v['eras'][n]*100:+.0f}" for n, _, _ in m.ERAS) + " |")
    print("\n## 연도별 평균 초과(규칙−보유, %p, 일봉)")
    ys = list(next(iter(res.values()))["years"])
    print("| 묶음 | 규칙 | " + " | ".join(str(y) for y in ys) + " |\n|---|---|" + "---|" * len(ys))
    for pn in P:
        for rule in RULES:
            v = res[f"{pn}|{rule}|D"]
            print(f"| {pn} | {rule} | " + " | ".join(f"{v['years'][y]*100:+.0f}" for y in ys) + " |")
    print("\n## 기록 전용 (자기 상장일부터, 일봉): CAGR 규칙/보유 · 샤프 · 체류 · 전환")
    print("| 대상|규칙 | 시작 | CAGR 규칙/보유 | 샤프 규칙/보유 | MDD 규칙/보유 | 체류 | 전환 |\n|---|---|---|---|---|---|---|")
    for k, v in rec.items():
        print(f"| {k} | {v['start']} | {pc(v['rule']['cagr'])}/{pc(v['hold']['cagr'])} | {v['rule']['sharpe']:.2f}/{v['hold']['sharpe']:.2f} | {pc(v['rule']['mdd'])}/{pc(v['hold']['mdd'])} | {v['inmkt']*100:.0f}% | {v['trades']} |")


if __name__ == "__main__":
    sys.exit(main())
