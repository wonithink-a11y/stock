"""테마 대장주 장중 매매 — 사전등록 findings/theme-leader-intraday-preregistration-2026-10.md (83b9893e) 그대로.

09:15 선별(누적 거래대금 상위 300 ∩ +3% ∩ 1천~20만원, 30종목 미만 쉼) → 최다 업종(3종목 미만 쉼) → 거래대금 1위(상한가 근처 제외)
셀 1 즉시 매수 · 셀 2 눌림(고가 −2%) 뒤 5분 묶음 반등 매수 → 당일 마지막 봉 종가 청산. 비용 33.5bp. 대조 = 선별 목록 전체.
네트워크 없음. 실행: python research/strategy-lab/theme_leader_intraday.py [--selftest]
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(LAB))
MIN_DIR = os.path.join(LAB, ".cache", "minute_raw")
OUT = os.path.join(LAB, "findings", "theme-leader-intraday-results-2026-10")
COST, TOPV, UP, MIN_LIST, MIN_THEME, LIMIT_UP, DIP, TRAIL = 0.00335, 300, 0.03, 30, 3, 0.295, 0.02, 0.03


def load_day(d):
    df = pd.concat(pd.read_parquet(f, columns=["ticker", "ts", "open", "high", "low", "close", "volume"])
                   for f in sorted(glob.glob(os.path.join(MIN_DIR, f"date={d}", "*.parquet"))))
    df["hm"] = df.ts.str[11:16]
    df["tradingValue"] = df.close * df.volume  # 옛 분봉(2025-08~)엔 거래대금 열이 없다 — 모든 날을 같은 근사로 맞춘다
    return df.sort_values(["ticker", "hm"])


def pullback_entry(g):
    """g: 한 종목의 그날 1분봉(시각순). 셀 2 진입 (시각, 가격) 또는 None."""
    g = g.reset_index(drop=True)
    hi = g.high.cummax()
    after = g.hm >= "09:15"
    dipped_idx = g.index[after & (g.close <= hi * (1 - DIP))]
    if len(dipped_idx) == 0:
        return None
    start = dipped_idx[0]
    mins = g.hm.str[:2].astype(int) * 60 + g.hm.str[3:].astype(int)
    bucket = (mins - 540) // 5
    b = g.assign(bucket=bucket).groupby("bucket").agg(high=("high", "max"), close=("close", "last"), last=("hm", "last"),
                                                      lastidx=("hm", lambda s: s.index[-1]))
    for k in range(1, len(b)):
        cur, prev = b.iloc[k], b.iloc[k - 1]
        if cur.lastidx <= start or cur["last"] >= "14:00":
            continue
        if cur.close > prev.high:
            nxt = cur.lastidx + 1
            if nxt < len(g):
                return g.hm[nxt], float(g.open[nxt])
            return None
    return None


def trade(g, entry_hm, entry_px):
    """당일 마지막 봉 종가 청산 수익과 트레일링(−3%) 기록 수익."""
    post = g[g.hm >= entry_hm]
    close = float(g.close.iloc[-1])
    peak, trail = entry_px, None
    for c in post.close:
        peak = max(peak, c)
        if c <= peak * (1 - TRAIL):
            trail = c / entry_px - 1
            break
    return close / entry_px - 1, (trail if trail is not None else close / entry_px - 1)


def run():
    uni = {json.loads(l)["ticker"]: json.loads(l) for l in open(os.path.join(REPO, "data/backfill/universe/a1a/current.jsonl"), encoding="utf-8")}
    ok = {t for t, u in uni.items() if t.endswith("0") and u.get("sector") and not any(k in u.get("name", "") for k in ("스팩", "기업인수목적"))}
    days = sorted(d.split("=", 1)[1] for d in os.listdir(MIN_DIR) if d.startswith("date="))
    rows, prev_close = [], None
    for d in days:
        df = load_day(d)
        df = df[df.ticker.isin(ok)]
        last_close = df.groupby("ticker").close.last()
        if prev_close is None:
            prev_close = last_close
            continue
        early = df[df.hm < "09:15"]
        rec = {"date": d, "status": None}
        if early.empty:
            rec["status"] = "no_early_bars"
        else:
            s = early.groupby("ticker").agg(val=("tradingValue", "sum"), px=("close", "last"))
            s["pc"] = prev_close.reindex(s.index)
            s = s.dropna()
            s = s.nlargest(TOPV, "val")
            s["ret"] = s.px / s.pc - 1
            s = s[(s.ret >= UP) & (s.pc >= 1000) & (s.pc <= 200000)]
            s["sector"] = [uni[t]["sector"] for t in s.index]
            rec["n_list"] = len(s)
            if len(s) < MIN_LIST:
                rec["status"] = "list_lt_30"
            else:
                agg = s.groupby("sector").agg(n=("val", "size"), v=("val", "sum")).sort_values(["n", "v"], ascending=False)
                theme, n_theme = agg.index[0], int(agg.n.iloc[0])
                rec.update(theme=theme, n_theme=n_theme)
                if n_theme < MIN_THEME:
                    rec["status"] = "theme_lt_3"
                else:
                    cand = s[(s.sector == theme) & (s.ret < LIMIT_UP)].sort_values("val", ascending=False)
                    if cand.empty:
                        rec["status"] = "all_limit_up"
                    else:
                        rec["status"] = "trade"
                        leader = cand.index[0]
                        byt = {t: g.reset_index(drop=True) for t, g in df[df.ticker.isin(s.index)].groupby("ticker")}

                        def cell1(t):
                            g = byt[t]
                            e = g[g.hm >= "09:15"]
                            return trade(g, e.hm.iloc[0], float(e.open.iloc[0])) if len(e) else None

                        def cell2(t):
                            g = byt[t]
                            p = pullback_entry(g)
                            return trade(g, *p) if p else None

                        rec.update(leader=leader, leader_name=uni[leader]["name"], leader_ret0915=float(s.ret[leader]))
                        r1, r2 = cell1(leader), cell2(leader)
                        rec["c1"], rec["c1_trail"] = (r1 if r1 else (None, None))
                        rec["c2"], rec["c2_trail"] = (r2 if r2 else (None, None))
                        c1s = [x[0] for x in map(cell1, s.index) if x]
                        c2s = [x[0] for x in map(cell2, s.index) if x]
                        rec["ctrl1"] = float(np.mean(c1s)) if c1s else None
                        rec["ctrl2"] = float(np.mean(c2s)) if c2s else None
        rows.append(rec)
        prev_close = last_close
    return pd.DataFrame(rows)


def boot_ci(x, n=5000, seed=0):
    x = np.asarray(x, dtype=float)
    rng = np.random.default_rng(seed)
    m = rng.choice(x, size=(n, len(x)), replace=True).mean(1)
    return float(np.percentile(m, 5)), float(np.percentile(m, 95))


def judge(gross, ctrl):
    if len(gross) < 100:
        return "판정 불가"
    net = gross - COST
    lo_g, _ = boot_ci(gross)
    lo_n, _ = boot_ci(net)
    if net.mean() > 0 and lo_n > 0 and gross.mean() > np.nanmean(ctrl):
        return "ECONOMIC"
    if lo_g > 0:
        return "INFORMATION"
    if gross.mean() <= 0:
        return "REJECT"
    return "INCONCLUSIVE"


def write(df):
    t = df[df.status == "trade"]
    res = {}
    for c, ctrl in (("c1", "ctrl1"), ("c2", "ctrl2")):
        x = t.dropna(subset=[c])
        g = x[c].to_numpy(float)
        res[c] = {"n": len(g), "gross": g.mean() if len(g) else None, "ci": boot_ci(g) if len(g) else (None, None),
                  "net": g.mean() - COST if len(g) else None, "ctrl": float(np.nanmean(x[ctrl])) if len(x) else None,
                  "trail": float(x[c + "_trail"].mean()) if len(x) else None, "win": float((g > COST).mean()) if len(g) else None,
                  "verdict": judge(g, x[ctrl].to_numpy(float))}
    bp = lambda v: "" if v is None else f"{v * 1e4:+.1f}bp"
    sig = lambda r: "있음" if r["ci"][0] is not None and r["ci"][0] > 0 else "없음"
    eco = lambda r: "통과" if r["verdict"] == "ECONOMIC" else "미달"
    reason = (f"셀1 신호: {sig(res['c1'])} · 경제성: {eco(res['c1'])} ({res['c1']['verdict']}, 비용 전 {bp(res['c1']['gross'])}) / "
              f"셀2 신호: {sig(res['c2'])} · 경제성: {eco(res['c2'])} ({res['c2']['verdict']}, 비용 전 {bp(res['c2']['gross'])}). 비용 33.5bp. (스크립트 판정)")
    order = ["ECONOMIC", "INFORMATION", "INCONCLUSIVE", "판정 불가", "REJECT"]  # 두 셀 중 더 나은 판정을 머리말에
    verdict = min((res["c1"]["verdict"], res["c2"]["verdict"]), key=order.index)
    st = df.status.value_counts().to_dict()
    L = ["---", "track: kr", "factor: theme-leader-intraday", "date: 2026-10-10", f"verdict: {verdict}",
         "criteria_version: research-only (theme-leader-intraday-preregistration-2026-10)", "reason: >-", f"  {reason}", "---", "",
         "# 테마 대장주 장중 매매 — 결과", "",
         f"사전등록 83b9893e 그대로. 분봉 {df.date.min()} ~ {df.date.max()} · {len(df)}일 · 상태 {st}.", "",
         "| 셀 | 매매일 | 비용 전 평균 (90%) | 비용 후 | 손익분기 비용 | 대조(선별 전체) | 비용 후 이긴 날 | 트레일링 −3%(기록) | 판정 |",
         "|---|---:|---|---:|---:|---:|---:|---:|---|"]
    for c, name in (("c1", "셀 1 즉시 매수"), ("c2", "셀 2 눌림 반등")):
        r = res[c]
        L.append(f"| {name} | {r['n']} | {bp(r['gross'])} [{bp(r['ci'][0])}, {bp(r['ci'][1])}] | {bp(r['net'])} | {bp(r['gross'])} | "
                 f"{bp(r['ctrl'])} | {r['win'] * 100:.0f}% | {bp(r['trail'])} | **{r['verdict']}** |")
    L += ["", "## 기록 (판정 불사용)", "", "| 월 | 매매일 | 셀1 평균 | 셀2 평균(신호일) | 대조1 |", "|---|---:|---:|---:|---:|"]
    for m, g in t.groupby(t.date.str[:7]):
        L.append(f"| {m} | {len(g)} | {bp(g.c1.mean())} | {bp(g.c2.mean()) if g.c2.notna().any() else ''} | {bp(g.ctrl1.mean())} |")
    L += ["", "| 테마(업종) | 선정일 | 셀1 평균 |", "|---|---:|---:|"]
    for th, g in t.groupby("theme").c1.agg(["size", "mean"]).sort_values("size", ascending=False).head(12).iterrows():
        L.append(f"| {th} | {int(g['size'])} | {bp(g['mean'])} |")
    L += ["", "대장주 예시(최근 10일):", ""]
    for r in t.tail(10).itertuples():
        L.append(f"- {r.date} {r.theme}({r.n_theme}) → {r.leader_name} 09:15 {r.leader_ret0915 * 100:+.1f}% · 셀1 {bp(r.c1)} · 셀2 {bp(r.c2) if r.c2 == r.c2 and r.c2 is not None else '신호 없음'}")
    L += ["", "구현: 분 거래대금 = 분 종가 × 거래량(옛 분봉에 거래대금 열이 없어 모든 날 같은 근사). 한계: 280일 전부 2025~26 한 장세(시기 분리 칸 없음) · 테마 = KSIC 세분류(LLM 대신) · 업종은 현재 분류 · 체결강도 조건 없음 · 분봉은 현재 상장 종목만."]
    open(OUT + ".md", "w", encoding="utf-8").write("\n".join(L) + "\n")
    df.to_json(OUT + ".json", orient="records", force_ascii=False, indent=1)
    return res, verdict


def selftest():
    hm = [f"09:{m:02d}" for m in range(0, 60)] + [f"10:{m:02d}" for m in range(0, 30)]
    px = [100 + i for i in range(20)] + [119 - (i + 1) * 0.5 for i in range(10)] + [114 + i for i in range(60)]
    g = pd.DataFrame({"hm": hm, "open": px, "high": [p + 0.2 for p in px], "low": [p - 0.2 for p in px], "close": px})
    e = pullback_entry(g)
    assert e is not None and e[0] > "09:29", e     # 09:20~09:29 눌림(고가 119.2 → 114, −2% 넘음) 뒤 반등 묶음 다음 봉
    r, tr = trade(g, e[0], e[1])
    assert abs(r - (g.close.iloc[-1] / e[1] - 1)) < 1e-12
    flat = g.assign(close=100.0, high=100.2, low=99.8, open=100.0)
    assert pullback_entry(flat) is None             # 눌림이 없으면 진입 없음
    print("selftest ok")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        df = run()
        res, v = write(df)
        print(v, {c: (r["n"], r["gross"], r["verdict"]) for c, r in res.items()})
