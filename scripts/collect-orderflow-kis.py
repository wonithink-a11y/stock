#!/usr/bin/env python3
"""호가·체결강도 장중 기록 (설계 docs/control/호가체결강도-기록-설계-2026-10-13.md). 조회 전용 — 주문 경로 없음.

1층 rank  : 1분마다 시장 순위 6콜 — 체결강도 상위(코스피·코스닥) · 순매수잔량 상위(코스피·코스닥) · 거래량 급증 · 등락률 상위.
2층 panel : 3분마다 전일 거래대금 상위 200(전날 분봉으로 장 전에 고정)의 10단계 호가·예상체결 + 최근 체결(체결강도).
저장: $ORDERFLOW_RAW_ROOT/date=YYYY-MM-DD/{rank,panel}.parquet · universe.json · _summary.json (저장소 밖, 커밋 안 함).
장중엔 같은 폴더 *.jsonl 에 한 줄씩 덧붙이고(죽어도 남는다) 끝나면 parquet 으로 바꾼다. 실패·빈 응답도 status 칸으로 남긴다(교훈75).

    python scripts/collect-orderflow-kis.py              # 평일 08:49 타이머가 띄운다 — 15:31 까지 돈다
    python scripts/collect-orderflow-kis.py --probe      # 각 조회 1회, 행 수·상태만 출력(쓰기 없음)
    python scripts/collect-orderflow-kis.py --finalize   # 남은 jsonl → parquet (자동으로도 한다)
    python scripts/collect-orderflow-kis.py --selftest

환경: collector.env(KIS_ENV_PATH·KIS_TOKEN_CACHE·MINUTE_RAW_ROOT). 토큰은 분봉 수집기의 캐시를 같이 쓴다 — 새로 발급하지 않는 게 기본.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
RATE = 4.0                                   # 초당 상한 — 실전 키 20/s 를 분봉·A2b·autotrader 와 나눠 쓴다
N_PANEL, PANEL_EVERY, PANEL_START, END = 200, 3, "08:51", "15:31"
MIN_VOL = "100000"                           # 순위의 거래량 하한 — 없으면 1위가 206주짜리 종목이다(10-13 프로브)
EXCL = "0010011101"                          # 제외: 정리매매·거래정지·ETF·ETN·스팩 (투자위험/관리/불성실/우선주/신용불가는 둔다)
OUT = Path(os.environ.get("ORDERFLOW_RAW_ROOT") or "~/orderflow-raw").expanduser()
MINUTE = Path(os.environ.get("MINUTE_RAW_ROOT") or "~/minute-raw").expanduser()

RANKS = [  # (kind, url, tr_id, params) — 파라미터는 KIS 공식 예제(open-trading-api examples_llm) 그대로, 값만 고정
    ("power_kospi", "/uapi/domestic-stock/v1/ranking/volume-power", "FHPST01680000",
     dict(fid_trgt_exls_cls_code="0", fid_cond_mrkt_div_code="J", fid_cond_scr_div_code="20168", fid_input_iscd="0001",
          fid_div_cls_code="1", fid_input_price_1="", fid_input_price_2="", fid_vol_cnt=MIN_VOL, fid_trgt_cls_code="0")),
    ("power_kosdaq", "/uapi/domestic-stock/v1/ranking/volume-power", "FHPST01680000",
     dict(fid_trgt_exls_cls_code="0", fid_cond_mrkt_div_code="J", fid_cond_scr_div_code="20168", fid_input_iscd="1001",
          fid_div_cls_code="1", fid_input_price_1="", fid_input_price_2="", fid_vol_cnt=MIN_VOL, fid_trgt_cls_code="0")),
    ("bidrsqn_kospi", "/uapi/domestic-stock/v1/ranking/quote-balance", "FHPST01720000",
     dict(fid_vol_cnt=MIN_VOL, fid_cond_mrkt_div_code="J", fid_cond_scr_div_code="20172", fid_input_iscd="0001", fid_rank_sort_cls_code="0",
          fid_div_cls_code="1", fid_trgt_cls_code="0", fid_trgt_exls_cls_code="0", fid_input_price_1="", fid_input_price_2="")),
    ("bidrsqn_kosdaq", "/uapi/domestic-stock/v1/ranking/quote-balance", "FHPST01720000",
     dict(fid_vol_cnt=MIN_VOL, fid_cond_mrkt_div_code="J", fid_cond_scr_div_code="20172", fid_input_iscd="1001", fid_rank_sort_cls_code="0",
          fid_div_cls_code="1", fid_trgt_cls_code="0", fid_trgt_exls_cls_code="0", fid_input_price_1="", fid_input_price_2="")),
    ("volsurge", "/uapi/domestic-stock/v1/quotations/volume-rank", "FHPST01710000",
     dict(FID_COND_MRKT_DIV_CODE="J", FID_COND_SCR_DIV_CODE="20171", FID_INPUT_ISCD="0000", FID_DIV_CLS_CODE="1", FID_BLNG_CLS_CODE="1",
          FID_TRGT_CLS_CODE="111111111", FID_TRGT_EXLS_CLS_CODE=EXCL, FID_INPUT_PRICE_1="", FID_INPUT_PRICE_2="", FID_VOL_CNT=MIN_VOL,
          FID_INPUT_DATE_1="")),
    ("gainers", "/uapi/domestic-stock/v1/ranking/fluctuation", "FHPST01700000",
     dict(fid_rsfl_rate2="", fid_cond_mrkt_div_code="J", fid_cond_scr_div_code="20170", fid_input_iscd="0000", fid_rank_sort_cls_code="0",
          fid_input_cnt_1="0", fid_prc_cls_code="0", fid_input_price_1="", fid_input_price_2="", fid_vol_cnt=MIN_VOL,
          fid_trgt_cls_code="0", fid_trgt_exls_cls_code=EXCL, fid_div_cls_code="1", fid_rsfl_rate1="")),
]
ASK = ("/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn", "FHKST01010200")
CCNL = ("/uapi/domestic-stock/v1/quotations/inquire-ccnl", "FHKST01010300")


def now():
    return datetime.now(KST)


def hm(t=None):
    return (t or now()).strftime("%H:%M")


def cmk():
    """분봉 수집기의 키·토큰 캐시 함수를 그대로 쓴다(토큰을 따로 발급하면 같은 앱키의 배치가 흔들린다)."""
    spec = importlib.util.spec_from_file_location("cmk", HERE / "collect-minute-kis.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Kis:
    def __init__(self):
        import requests
        self.m, self.s = cmk(), requests.Session()
        self.key, self.sec = self.m.credentials()
        self.tok = self.m.get_token(self.key, self.sec)[0]
        self.last, self.calls, self.limited = 0.0, 0, 0

    def get(self, url, tr, params):
        """반환 (status, body). status: OK · HTTP_nnn · RT_코드 · EXC_이름. 초과(EGW00201)·토큰 만료는 1회 재시도."""
        for attempt in (0, 1):
            wait = self.last + 1 / RATE - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.calls += 1
            try:
                r = self.s.get(self.m.BASE + url, params=params, timeout=10,
                               headers={"authorization": "Bearer " + self.tok, "appkey": self.key, "appsecret": self.sec,
                                        "tr_id": tr, "custtype": "P", "content-type": "application/json; charset=utf-8"})
                b = r.json()
            except Exception as e:                                  # noqa: BLE001 — 한 콜 실패가 하루를 멈추지 않는다
                return f"EXC_{type(e).__name__}", {}
            code = b.get("msg_cd", "")
            if b.get("rt_cd") == "0":
                return "OK", b
            if attempt == 0 and code == "EGW00201":
                self.limited += 1
                time.sleep(1.0)
                continue
            if attempt == 0 and code in ("EGW00123", "EGW00121"):  # 토큰 만료·무효 → 캐시 다시 읽기(다른 수집기가 갱신했을 수 있다)
                self.tok = self.m.get_token(self.key, self.sec)[0]
                continue
            return (f"HTTP_{r.status_code}" if r.status_code != 200 else f"RT_{code or b.get('rt_cd')}"), b
        return "RT_EGW00201", {}


def rank_rows(kind, status, body, ts):
    rows = body.get("output") or []
    if status != "OK" or not rows:
        return [dict(ts=ts, kind=kind, status=status if status != "OK" else "EMPTY")]
    out = []
    for r in rows:
        t = r.get("stck_shrn_iscd") or r.get("mksc_shrn_iscd") or ""
        out.append(dict(ts=ts, kind=kind, status="OK", ticker=t, **{k: v for k, v in r.items() if k not in ("stck_shrn_iscd", "mksc_shrn_iscd")}))
    return out


def panel_row(ticker, ts, ask, ccnl):
    """한 종목 한 회차 = 한 행. 호가 응답 output2 의 종목코드가 요청과 다르면 MISMATCH(교훈81 — 성공 코드 ≠ 내 질문의 답)."""
    (sa, ba), (sc, bc) = ask, ccnl
    row = dict(ts=ts, ticker=ticker, ask_status=sa, ccnl_status=sc)
    if sa == "OK":
        o1, o2 = ba.get("output1") or {}, ba.get("output2") or {}
        if o2.get("stck_shrn_iscd") and o2["stck_shrn_iscd"] != ticker:
            row["ask_status"] = "MISMATCH"
        elif not o1:
            row["ask_status"] = "EMPTY"
        else:
            row.update({k: v for k, v in o1.items()})
            row.update({f"x_{k}": v for k, v in o2.items() if k != "stck_shrn_iscd"})
    if sc == "OK":
        tr = bc.get("output") or []
        if not tr:
            row["ccnl_status"] = "EMPTY"
        else:
            row.update(c_hour=tr[0].get("stck_cntg_hour"), c_price=tr[0].get("stck_prpr"), c_rltv=tr[0].get("tday_rltv"),
                       c_ctrt=tr[0].get("prdy_ctrt"), c_n=len(tr), c_first_hour=tr[-1].get("stck_cntg_hour"),
                       c_vol=sum(int(x.get("cntg_vol") or 0) for x in tr))
    return row


def pick_universe(m, n=N_PANEL):
    """전날 분봉 → 거래대금 상위 n(보통주 = 코드 끝 0). tradingValue 칸이 없는 옛 형식은 거래량 × 종가."""
    m = m[m.ticker.str.endswith("0")]
    tv = m["tradingValue"] if "tradingValue" in m and m["tradingValue"].notna().any() else m.volume * m.close
    s = tv.groupby(m.ticker).sum().sort_values(ascending=False, kind="stable")
    return list(s.index[:n]), {t: float(v) for t, v in s.head(n).items()}


def prev_minute_day(today):
    days = sorted(p.name[5:] for p in MINUTE.glob("date=*") if p.name[5:] < today)
    return days[-1] if days else None


def load_universe(day_dir, today):
    p = day_dir / "universe.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))["tickers"]
    import pandas as pd
    src = prev_minute_day(today)
    if not src:
        raise SystemExit("전날 분봉이 없다 — 2층 종목을 못 고른다")
    m = pd.concat([pd.read_parquet(f) for f in sorted((MINUTE / f"date={src}").glob("*.parquet"))], ignore_index=True)
    tickers, tv = pick_universe(m)
    day_dir.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dict(date=today, source_minute_day=src, n=len(tickers), tickers=tickers, trading_value=tv),
                            ensure_ascii=False, indent=1), encoding="utf-8")
    return tickers


def append(path, rows):
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def finalize(day_dir):
    """jsonl → parquet(전 칸 문자열 — KIS 가 문자열로 준다, 해석은 연구 쪽에서). parquet 이 있으면 덧붙여 합친다."""
    import pandas as pd
    for name in ("rank", "panel"):
        j, pq = day_dir / f"{name}.jsonl", day_dir / f"{name}.parquet"
        if not j.exists():
            continue
        df = pd.read_json(j, lines=True, dtype=False).astype("string")
        if pq.exists():
            df = pd.concat([pd.read_parquet(pq), df], ignore_index=True)
        df.to_parquet(pq.with_suffix(".tmp"), index=False)
        os.replace(pq.with_suffix(".tmp"), pq)
        j.unlink()


def is_open_day(k):
    """휴장일엔 KIS 가 직전 영업일 체결을 정상 코드로 준다(교훈81). 09:03 이후 삼성전자 최근 체결 시각이 오늘 장중인지 본다."""
    st, b = k.get(*CCNL, dict(FID_COND_MRKT_DIV_CODE="J", FID_INPUT_ISCD="005930"))
    h = ((b.get("output") or [{}])[0]).get("stck_cntg_hour", "")
    return st == "OK" and "090000" <= h <= hm().replace(":", "") + "59", h


class Holiday(Exception):
    pass


def run():
    today = now().strftime("%Y-%m-%d")
    day = OUT / f"date={today}"
    for old in OUT.glob("date=*"):
        if old != day and any(old.glob("*.jsonl")):
            finalize(old)                                           # 어제 죽은 실행의 남은 줄
    tickers = load_universe(day, today)
    k = Kis()
    st = dict(checked=False, rank_min=None, n_rank=0, n_panel=0)

    def tick():
        """분이 바뀌었으면 순위 6콜. 패널 회차(약 100초) 도중에도 불러 순위가 1분 간격을 지키게 한다."""
        t = now()
        if not st["checked"] and hm(t) >= "09:03":
            ok, h = is_open_day(k)
            if not ok:
                raise Holiday(h)
            st["checked"] = True
        if "09:00" <= hm(t) < "15:31" and hm(t) != st["rank_min"]:
            st["rank_min"] = hm(t)
            ts = t.isoformat(timespec="seconds")
            rows = [r for kind, url, tr, p in RANKS for r in rank_rows(kind, *k.get(url, tr, p), ts)]
            append(day / "rank.jsonl", rows)
            st["n_rank"] += len(rows)

    print(f"[{hm()}] 시작 · 2층 {len(tickers)}종목 · 초당 {RATE}")
    panel_last = None
    try:
        while hm() < END:
            tick()
            t = now()
            slot = (t.hour * 60 + t.minute) // PANEL_EVERY
            if hm(t) >= PANEL_START and slot != panel_last:
                panel_last = slot
                for tk in tickers:                                  # 회차 중 END 를 넘겨도 회차는 끝낸다(15:30 종가 회차)
                    tick()
                    ts = now().isoformat(timespec="seconds")
                    append(day / "panel.jsonl", [panel_row(tk, ts, k.get(*ASK, dict(FID_COND_MRKT_DIV_CODE="J", FID_INPUT_ISCD=tk)),
                                                           k.get(*CCNL, dict(FID_COND_MRKT_DIV_CODE="J", FID_INPUT_ISCD=tk)))])
                    st["n_panel"] += 1
            nxt = now().replace(second=0, microsecond=0) + timedelta(seconds=61)
            time.sleep(max(0.0, (nxt - now()).total_seconds()))
    except Holiday as e:
        print(f"휴장일로 본다(삼성전자 최근 체결 {e.args[0]!r}) — 오늘 기록 지움")
        for f in day.glob("*"):
            f.unlink()
        day.rmdir()
        return
    finalize(day)
    summary(day, k, st["n_rank"], st["n_panel"])


def summary(day, k, n_rank, n_panel):
    import pandas as pd
    s = dict(finished_at=now().isoformat(timespec="seconds"), calls=k.calls, egw00201_retried=k.limited, rank_rows=n_rank, panel_rows=n_panel)
    p = day / "panel.parquet"
    if p.exists():
        d = pd.read_parquet(p, columns=["ask_status", "ccnl_status"])
        s["ask_status"] = d.ask_status.value_counts().to_dict()
        s["ccnl_status"] = d.ccnl_status.value_counts().to_dict()
    (day / "_summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(s, ensure_ascii=False))


def probe():
    k = Kis()
    ts = now().isoformat(timespec="seconds")
    for kind, url, tr, p in RANKS:
        rows = rank_rows(kind, *k.get(url, tr, p), ts)
        top = [(r.get("ticker"), r.get("hts_kor_isnm"), r.get("acml_vol")) for r in rows[:3]]
        print(f"{kind:15s} {rows[0]['status']:12s} {len(rows)}행 {top}")
    r = panel_row("005930", ts, k.get(*ASK, dict(FID_COND_MRKT_DIV_CODE="J", FID_INPUT_ISCD="005930")),
                  k.get(*CCNL, dict(FID_COND_MRKT_DIV_CODE="J", FID_INPUT_ISCD="005930")))
    print("panel 005930", r["ask_status"], r["ccnl_status"], len(r), "칸 · 체결강도", r.get("c_rltv"), "· 총잔량", r.get("total_askp_rsqn"), r.get("total_bidp_rsqn"))
    print("휴장일 검사", is_open_day(k), "· 호출", k.calls)


def selftest():
    import pandas as pd
    m = pd.DataFrame({"ticker": ["000010", "000010", "000020", "000025", "000030"], "volume": [10, 10, 5, 999, 1],
                      "close": [100.0, 100, 100, 100, 100], "tradingValue": [None] * 5})
    t, tv = pick_universe(m, 2)
    assert t == ["000010", "000020"] and tv["000010"] == 2000            # 우선주(끝 5) 제외 · 거래량×종가 대체
    r = rank_rows("power_kospi", "OK", {"output": [{"stck_shrn_iscd": "005930", "tday_rltv": "120.5"}]}, "T")
    assert r == [dict(ts="T", kind="power_kospi", status="OK", ticker="005930", tday_rltv="120.5")]
    assert rank_rows("gainers", "RT_OPSQ2002", {}, "T")[0]["status"] == "RT_OPSQ2002"
    assert rank_rows("gainers", "OK", {"output": []}, "T")[0]["status"] == "EMPTY"
    ask = ("OK", {"output1": {"askp1": "100", "total_askp_rsqn": "5"}, "output2": {"stck_shrn_iscd": "005930", "antc_cnpr": "99"}})
    cc = ("OK", {"output": [{"stck_cntg_hour": "100002", "stck_prpr": "100", "tday_rltv": "110.0", "cntg_vol": "3"},
                            {"stck_cntg_hour": "100000", "cntg_vol": "2"}]})
    p = panel_row("005930", "T", ask, cc)
    assert p["ask_status"] == "OK" and p["x_antc_cnpr"] == "99" and p["c_rltv"] == "110.0" and p["c_vol"] == 5 and p["c_first_hour"] == "100000"
    assert panel_row("000660", "T", ask, cc)["ask_status"] == "MISMATCH"
    assert panel_row("005930", "T", ("HTTP_500", {}), ("EXC_Timeout", {})) == dict(ts="T", ticker="005930", ask_status="HTTP_500", ccnl_status="EXC_Timeout")
    print("selftest 통과")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    for a in ("probe", "finalize", "selftest"):
        g.add_argument(f"--{a}", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    elif a.probe:
        probe()
    elif a.finalize:
        for d in OUT.glob("date=*"):
            finalize(d)
    else:
        run()
