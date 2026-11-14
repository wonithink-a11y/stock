#!/usr/bin/env python3
"""OKX 신규 상장 7일 — BL7 재현. 사전등록 findings/okx-listing-bl7-replication-preregistration-2026-11.md (cd0faaf9).

OKX 현물 USDT 중 바이낸스보다 먼저(또는 바이낸스에 없이) 상장된 코인의 상장 다음 날부터 7일 BTC 대비 수익을 재고 BL7 이 재현되는지 라벨을 단다. 기록 전용.

    python research/strategy-lab/futures/okx_listing_bl7.py --collect   # OKX 일봉(전 이력) → data/crypto/okx_listing/
    python research/strategy-lab/futures/okx_listing_bl7.py             # 판정 → futures/okx-listing-bl7.json, findings/okx-listing-bl7-replication-results-2026-11.md
    python research/strategy-lab/futures/okx_listing_bl7.py --selftest
"""
from __future__ import annotations

import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import binance_listing as bl  # noqa: E402
import coinbase_premium as cp  # noqa: E402
from short_horizon_study import tstat  # noqa: E402

DATA = HERE.parent / "data" / "crypto" / "okx_listing"
OUT_JSON = HERE / "okx-listing-bl7.json"
OUT_MD = HERE.parent / "findings" / "okx-listing-bl7-replication-results-2026-11.md"
API = "https://www.okx.com/api/v5"
D = pd.Timedelta(days=1)
H = 7
END = pd.Timestamp("2026-10-01", tz="UTC")
START = pd.Timestamp("2018-01-01", tz="UTC")
GATE, T_REP, BOOT, SEED = 40, -1.65, 10_000, 20261114
_lock, _last = threading.Lock(), [0.0]


def _get(path: str, **params) -> dict:
    for k in range(8):
        with _lock:                                      # 약 6 요청/초
            wait = _last[0] + 0.16 - time.time()
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            import requests
            j = requests.get(f"{API}/{path}", params=params, timeout=30).json()
            if j.get("code") == "0":
                return j
        except Exception:
            pass
        time.sleep(1.5 * (k + 1))
    raise RuntimeError(path + str(params))


def candles(inst: str) -> pd.Series:
    """1Dutc 일봉 시가, 가장 오래된 봉까지 페이지를 거슬러 올라간다(요청 한 번 100개, 최신순)."""
    rows, after = [], str(int(time.time() * 1000) + 86_400_000)
    while True:
        d = _get("market/history-candles", instId=inst, bar="1Dutc", after=after, limit="100")["data"]
        if not d:
            break
        rows += [(int(r[0]), float(r[1])) for r in d]
        if len(d) < 100:
            break
        after = d[-1][0]
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(t, unit="ms", tz="UTC"): o for t, o in rows}).sort_index()
    return s


def collect():
    DATA.mkdir(parents=True, exist_ok=True)
    ins = [x for x in _get("public/instruments", instType="SPOT")["data"] if x["quoteCcy"] == "USDT"]
    (DATA / "instruments.json").write_text(json.dumps([{"inst": x["instId"], "base": x["baseCcy"], "listTime": x["listTime"]} for x in ins], ensure_ascii=False), encoding="utf-8")

    def one(x):
        f = DATA / f"{x['instId']}.parquet"
        if f.exists():
            return 0
        candles(x["instId"]).rename("open").to_frame().to_parquet(f)
        return 1
    with ThreadPoolExecutor(4) as ex:
        n = sum(ex.map(one, ins + [{"instId": "BTC-USDT"}]))
    print("수집", n, "/", len(ins) + 1)


def binance_first_months() -> dict[str, str]:
    months = json.loads((bl.DATA / "months.json").read_text(encoding="utf-8"))
    first: dict[str, str] = {}
    for s, ms in months.items():
        sp = bl.split_symbol(s)
        if sp and ms:
            first[sp[0]] = min(first.get(sp[0], "9999-99"), ms[0])
    return first


def build_events(opens: dict[str, pd.Series], btc: pd.Series, first_bn: dict[str, str]) -> tuple[list[dict], dict]:
    ev, why = [], {"후보": 0, "비적격": 0, "첫봉<2018": 0, "청산>END": 0, "바이낸스오염": 0, "자료부족": 0}
    for inst, s in opens.items():
        base = inst.split("-")[0]
        why["후보"] += 1
        if not bl.eligible(base):
            why["비적격"] += 1
            continue
        if not len(s) or s.index[0] < START:
            why["첫봉<2018"] += 1
            continue
        L = s.index[0]
        t0, t1 = L + D, L + (1 + H) * D
        if t1 > END:
            why["청산>END"] += 1
            continue
        fb = first_bn.get(base)
        if fb is not None and fb <= (t0 + 8 * D).strftime("%Y-%m"):
            why["바이낸스오염"] += 1
            continue
        p0, p1, b0, b1 = s.get(t0, np.nan), s.get(t1, np.nan), btc.get(t0, np.nan), btc.get(t1, np.nan)
        if not all(np.isfinite([p0, p1, b0, b1])):
            why["자료부족"] += 1
            continue
        path = [((s.get(t0 + k * D, np.nan) / p0 - 1) - (btc.get(t0 + k * D, np.nan) / b0 - 1)) * 1e4 for k in range(1, H + 1)]
        ev.append({"inst": inst, "L": L, "rel": ((p1 / p0 - 1) - (b1 / b0 - 1)) * 1e4, "grp": "B" if fb is None else "A", "maxUp": float(np.nanmax(path)) if np.isfinite(path).any() else np.nan})
    return ev, why


def label(day: pd.Series) -> str:
    sp = day.index.map(cp.split)
    oos, tr = day[sp != "TRAIN"], day[sp == "TRAIN"]
    if len(oos) < GATE:
        return "정보 부족"
    if oos.mean() >= 0:
        return "재현 실패"
    return "재현" if (tstat(oos.to_numpy()) <= T_REP and len(tr) and tr.mean() < 0) else "부분 재현"


def summ(x: pd.Series) -> dict:
    return {"days": int(len(x)), "mean": round(float(x.mean()), 1) if len(x) else None, "t": round(float(tstat(x.to_numpy())), 2) if len(x) > 1 else None}


def run() -> dict:
    ins = json.loads((DATA / "instruments.json").read_text(encoding="utf-8"))
    opens = {}
    for x in ins:
        f = DATA / f"{x['inst']}.parquet"
        if f.exists():
            d = pd.read_parquet(f)["open"]
            d.index = pd.to_datetime(d.index, utc=True)
            opens[x["inst"]] = d
    btc = pd.read_parquet(DATA / "BTC-USDT.parquet")["open"]
    btc.index = pd.to_datetime(btc.index, utc=True)
    ev, why = build_events(opens, btc, binance_first_months())
    df = pd.DataFrame(ev)
    day = df.groupby("L")["rel"].mean().sort_index()
    sp = day.index.map(cp.split)
    out = {"label": label(day), "exclusions": why, "events": len(df), "days": int(len(day)), "byGroup": {g: summ(x.groupby("L")["rel"].mean()) for g, x in df.groupby("grp")},
           "bySplit": {k: summ(day[sp == k]) for k in ("TRAIN", "VALID", "TEST")}, "oos": summ(day[sp != "TRAIN"]),
           "periods": {g: summ(day[day.index.map(cp.period) == g]) for g in ("~2023", "2024", "2025~")},
           "coinPercentiles": {str(p): round(float(np.quantile(df["rel"], p / 100)), 1) for p in (5, 25, 50, 75, 95)}, "maxUpBpP90": round(float(np.nanquantile(df["maxUp"], 0.9)), 1)}
    mon = df.assign(m=df["L"].dt.tz_convert(None).dt.to_period("M")).groupby("m")["rel"].apply(np.array)
    rng, keys, bm = np.random.default_rng(SEED), list(mon.index), []
    oosm = [k for k in keys if cp.split(k.to_timestamp()) != "TRAIN"]
    if oosm:
        for _ in range(BOOT):
            pick = rng.integers(0, len(oosm), len(oosm))
            bm.append(float(np.concatenate([mon[oosm[i]] for i in pick]).mean()))
        out["bootstrapOOSCoinMean95"] = [round(float(np.quantile(bm, 0.025)), 1), round(float(np.quantile(bm, 0.975)), 1)]
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def write_md(o: dict) -> None:
    f = lambda v: "-" if v is None else f"{v:+,.1f}"  # noqa: E731
    L = ["---", "track: crypto", "factor: okx-listing-bl7-replication", "date: 2026-11-14", f"verdict: {o['label']}",
         "criteria_version: research-only (okx-listing-bl7-replication-preregistration-2026-11, 사전등록 cd0faaf9)", "reason: >-",
         f"  신호: {'있음' if o['label'] == '재현' else '약함/없음' if o['label'] != '정보 부족' else '판정 불가'}({o['label']}) · 경제성: 판정 안 함. OOS 상장일 {o['oos']['days']} 평균 rel {f(o['oos']['mean'])}bp (t {o['oos']['t']}), "
         f"TRAIN {f(o['bySplit']['TRAIN']['mean'])}bp. OKX 신규 상장(바이낸스 오염 제외, 생존 상품만) 7일 BTC 대비. 기록 전용.", "---", "",
         "# OKX 신규 상장 7일 — BL7 재현 — 결과", "",
         f"사전등록 cd0faaf9 그대로. 사건 {o['events']} · 상장일 {o['days']}. 제외 내역 {o['exclusions']}.", "", f"**라벨: {o['label']}**", "",
         "## 1. 구간별 (상장일 평균 rel, bp)", "", "| 구간 | 상장일 | 평균 | t |", "|---|---|---|---|"]
    for k, v in {**o["bySplit"], "OOS(VALID+TEST)": o["oos"]}.items():
        L.append(f"| {k} | {v['days']} | {f(v['mean'])} | {v['t']} |")
    L += ["", "## 2. 기록 (판정 불사용)", "", "| 갈래 | 상장일 | 평균 | t |", "|---|---|---|---|"]
    for k, v in o["byGroup"].items():
        L.append(f"| {'A 바이낸스 나중 상장' if k == 'A' else 'B 바이낸스 없음'} | {v['days']} | {f(v['mean'])} | {v['t']} |")
    L += ["", "시기 세 칸: " + " · ".join(f"{k} {v['days']}일 {f(v['mean'])}bp(t {v['t']})" for k, v in o["periods"].items()),
          f"코인 단위 백분위(bp): {o['coinPercentiles']} · 7일 중 BTC 대비 최대 상승 90분위 {o['maxUpBpP90']}bp",
          f"OOS 코인 평균 군집 부트스트랩(상장 월 블록 10,000회) 95% 구간: {o.get('bootstrapOOSCoinMean95')}", "",
          "## 3. 읽는 법·한계", "",
          "- 새 표본의 방향 재현만 본다. 숏 실행·비용·크기는 판정하지 않았다. OKX `instruments` 는 현재 live 상품만 주므로 상장 후 폐지된 코인이 빠진다(보수적 생존편향).",
          "- 오염 제외는 월 단위(보수적)라 바이낸스 상장이 같은 달 늦게 있던 코인도 뺐다. 첫 일봉 일자 L 은 OKX 일봉 이력의 첫 봉이며 실제 상장 시각과 다를 수 있다.",
          "- 같은 표본 재절단·기준 변경 금지. 실계좌·모의 슬리브·정책 불변."]
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


def selftest():
    idx = pd.date_range("2024-03-01", periods=30, freq="D", tz="UTC")
    s = pd.Series(100.0, index=idx)
    s[idx[1 + 7]] = 80.0
    btc = pd.Series(50.0, index=idx)
    btc[idx[8]] = 55.0
    ev, why = build_events({"AAA-USDT": s, "BBB-USDT": s, "CCC-USDT": s}, btc, {"BBB": "2024-03", "CCC": "2025-01"})
    got = {e["inst"]: e for e in ev}
    assert "BBB-USDT" not in got and why["바이낸스오염"] == 1                          # 같은 달 바이낸스 상장 → 제외
    assert abs(got["AAA-USDT"]["rel"] - (-0.2 - 0.1) * 1e4) < 1e-6 and got["AAA-USDT"]["grp"] == "B" and got["CCC-USDT"]["grp"] == "A"
    day = pd.Series([-500.0] * 45 + [-300.0] * 50, index=list(pd.date_range("2022-01-01", periods=45, freq="D", tz="UTC")) + list(pd.date_range("2024-01-01", periods=50, freq="D", tz="UTC")))
    day.iloc[50::2] += 100.0
    assert label(day) in ("재현", "부분 재현")
    assert label(pd.Series([1.0] * 100, index=pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC"))) == "재현 실패"
    assert label(pd.Series([-1.0] * 5, index=pd.date_range("2024-01-01", periods=5, freq="D", tz="UTC"))) == "정보 부족"
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    elif "--collect" in sys.argv:
        collect()
    else:
        o = run()
        write_md(o)
        print(o["label"], o["oos"], o["bySplit"], o["exclusions"])
