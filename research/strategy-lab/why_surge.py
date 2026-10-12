#!/usr/bin/env python3
"""급등 원인 빠른 점검 — 분봉으로 '언제·혼자인가 무리인가·거래가 어떻게 들어왔나'를 본다(판정·예측 아님).

    python research/strategy-lab/why_surge.py 005930 20261008      # 한 건
    python research/strategy-lab/why_surge.py --batch               # .cache/surge_causes.csv(diag_daily_rotation_2026) 전부 → 분포

분류(먼저 맞는 것):
  시초 갭형      09:00 시가에서 이미 전체 상승의 70% 이상 — 밤사이·장 전 재료(전날 공시·미국·뉴스)
  장중 무리형    점화 시각 ±10분 안에 같은 테마 소그룹·업종 종목 중 +2% 이상 동반 비율이 30% 이상 — 업종 단위 재료(정책·업황·해외)
  장중 단독+공시 혼자 올랐고 같은 날·전날 DART 공시가 있음
  장중 단독      혼자 올랐고 공시 없음 — 풍문·수급·장중 공시(목록 API 는 시각이 없다)·캐시 밖 뉴스
점화 시각 = 전일 종가 대비 상승이 그날 최종 상승의 절반을 처음 넘은 분.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MIN = HERE / ".cache" / "minute_raw"
DAILY = HERE / "data" / "krx-daily-ext"
GAP_SHARE, PEER_MOVE, PEER_SHARE, WIN = 0.7, 0.02, 0.3, 10


def peer_map():
    themes = json.load(open(REPO / "config" / "themeTree.json", encoding="utf-8"))["themes"]
    sub = {}
    for big, groups in themes.items():
        for gname, g in groups.items():
            for x in g:
                sub.setdefault(x["t"], set()).add(f"{big}/{gname}")
    import importlib.util
    spec = importlib.util.spec_from_file_location("bss", REPO / "scripts" / "build-sector-strength.py")
    bss = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bss)
    sec = bss.load_sector_by_ticker(bss.load_rollup())
    return sub, sec


def daily(date):
    e = pd.read_parquet(DAILY / f"{date[:4]}-{date[4:6]}.parquet")
    e = e[e.BAS_DD == date].set_index("ISU_CD")
    r = pd.to_numeric(e.FLUC_RT, errors="coerce") / 100
    return (e.TDD_CLSPRC / (1 + r)).rename("prev"), r.rename("r"), e.ISU_NM


def minutes(date):
    d = MIN / f"date={date[:4]}-{date[4:6]}-{date[6:]}"
    if not d.exists():
        return None
    m = pd.concat([pd.read_parquet(p) for p in sorted(d.glob("*.parquet"))], ignore_index=True)
    m["hm"] = m.ts.str[11:16]
    return m


def titles(ticker, date, corp):
    p = HERE / "data" / "dart_event_titles" / f"{corp.get(ticker, '')}.json"
    if not p.exists():
        return None
    j = json.load(open(p, encoding="utf-8"))
    prev = (pd.to_datetime(date, format="%Y%m%d") - pd.Timedelta(days=4)).strftime("%Y%m%d")
    return [x["nm"].strip()[:40] for k in ("I", "B") for x in j.get(k, []) if prev <= x["d"] <= date]


def analyze(ticker, date, ctx):
    m, prev, rday, names = ctx["m"], ctx["prev"], ctx["r"], ctx["names"]
    s = m[m.ticker == ticker].sort_values("hm")
    if s.empty or ticker not in prev.index:
        return None
    p0 = prev[ticker]
    ret = s.close.to_numpy() / p0 - 1
    final = ret[-1]
    gap = s.open.iloc[0] / p0 - 1
    half = np.argmax(ret >= final / 2) if final > 0 else 0
    ign = s.hm.iloc[half]
    vol = s.volume.to_numpy()
    top10 = np.sort(vol)[-10:].sum() / max(vol.sum(), 1)        # 거래가 몇 분에 몰렸나
    # 동반: 같은 테마 소그룹 ∪ 같은 업종 종목의 점화 ±WIN분 수익
    peers = set()
    for g in ctx["sub"].get(ticker, ()):
        peers |= {t for t, gs in ctx["sub"].items() if g in gs}
    sec = ctx["sec"].get(ticker)
    if sec:
        peers |= {t for t, sc in ctx["sec"].items() if sc == sec}
    peers.discard(ticker)
    hms = sorted(m.hm.unique())
    i = hms.index(ign) if ign in hms else 0
    a, b = hms[max(0, i - WIN)], hms[min(len(hms) - 1, i + WIN)]
    w = ctx["piv"].loc[a:b, [t for t in peers if t in ctx["piv"].columns]]
    mv = (w.iloc[-1] / w.iloc[0] - 1).dropna() if len(w) > 1 else pd.Series(dtype=float)
    share = float((mv >= PEER_MOVE).mean()) if len(mv) >= 5 else float("nan")
    tl = titles(ticker, date, ctx["corp"])
    if final > 0 and gap >= GAP_SHARE * final:
        kind = "시초 갭형"
    elif np.isfinite(share) and share >= PEER_SHARE:
        kind = "장중 무리형"
    elif tl:
        kind = "장중 단독+공시"
    else:
        kind = "장중 단독" + ("" if tl is not None else "(공시 캐시 없음)")
    return dict(date=date, ticker=ticker, name=names.get(ticker, ""), r_day=float(rday.get(ticker, np.nan)), gap=float(gap), ignite=ign,
                vol_top10min=float(top10), peers=len(mv), peer_share=share, kind=kind, titles=" | ".join(tl or [])[:120])


def context(date):
    m = minutes(date)
    if m is None:
        return None
    prev, r, names = daily(date)
    piv = m.pivot_table(index="hm", columns="ticker", values="close")
    corp = {}
    for line in open(REPO / "data" / "backfill" / "dart" / "corpcode.jsonl", encoding="utf-8"):
        j = json.loads(line)
        if j.get("ticker"):
            corp[j["ticker"]] = j["corp"]
    return dict(m=m, prev=prev, r=r, names=names.to_dict(), piv=piv, corp=corp)


def main():
    sub, sec = peer_map()
    if len(sys.argv) > 1 and sys.argv[1] == "--batch":
        ev = pd.read_csv(HERE / ".cache" / "surge_causes.csv", dtype={"ticker": str, "date": str})
        rows = []
        for d, g in ev.groupby("date"):
            ctx = context(d)
            if ctx is None:
                continue
            ctx.update(sub=sub, sec=sec)
            rows += [x for t in g.ticker if (x := analyze(t, d, ctx))]
        df = pd.DataFrame(rows)
        df.to_csv(HERE / ".cache" / "why_surge_batch.csv", index=False, encoding="utf-8-sig")
        print(f"분봉 있는 급등 {len(df)}/{len(ev)}건")
        print(df.kind.value_counts().to_string())
        print("\n점화 시각 분포:", df[df.kind != "시초 갭형"].ignite.str[:2].value_counts().sort_index().to_dict())
        print("거래 몰림(상위 10분 비중) 중앙값:", df.groupby("kind").vol_top10min.median().round(2).to_dict())
        print("다음 날 확인은 별도. 예시:")
        print(df.sort_values("r_day", ascending=False).groupby("kind").head(3)[["date", "name", "r_day", "gap", "ignite", "peer_share", "kind", "titles"]].to_string())
        return
    t, d = sys.argv[1], sys.argv[2]
    ctx = context(d)
    if ctx is None:
        sys.exit(f"{d} 분봉 없음")
    ctx.update(sub=sub, sec=sec)
    print(json.dumps(analyze(t, d, ctx), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
