#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""기업 해독 — 종목 코드만 넣으면 숫자(코드) · 원문 추출(OpenCode) · 판단(Claude)을 한 화면으로 묶는다.

역할 분리(docs/control/기업분석-시범-2026-10-06.md 시험 결과):
  ① prepare  코드   DART 원문·재무(fnlttSinglAcntAll)·패널·주가·A5/라이브 점수·공시·동종사 → data.json, business.txt, prompt.md
  ② OpenCode       원문 → 정해진 항목 + 원문 인용 → extract.json   (정해진 칸 13/14 정답, 판단 칸은 맡기지 않는다)
  ③ check    코드   인용 원문 대조 · 숫자-인용 대조 · 부문 비중 합계 → check.json
  ④ Claude         judgment.json (한 줄 요약 · 성장 동력 단계 · 추가 사실) — 사람이 읽고 쓴다
  ⑤ render   코드   data + extract + check + judgment → 한 화면 HTML(비공개 Artifact 로 게시)

사용:
  python scripts/company_decode/cli.py prepare 032820 071320 328130 411080
  opencode.cmd run -m opencode/big-pickle "<캐시>/<티커>/prompt.md 파일을 읽고 그대로 따르라 ..."   ★ 한 줄로(아래 OPENCODE_LINE)
  python scripts/company_decode/cli.py check 032820 ...
  python scripts/company_decode/cli.py render 032820 ... --out <html>
  python scripts/company_decode/cli.py --selftest

★ Windows opencode.cmd 는 여러 줄 지시문의 첫 줄만 넘긴다 — 지시는 prompt.md 로 두고 한 줄로 가리킨다.
★ 캐시(research/strategy-lab/.cache/company-decode/)는 gitignore — 원문·추출물은 저장소에 남지 않는다.
점수·매매 정책에 연결하지 않는다. 투자 판단 근거 아님.
"""
import argparse, glob, gzip, importlib.util, json, math, re, sys, urllib.parse, urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CACHE = ROOT / "research" / "strategy-lab" / ".cache" / "company-decode"
sys.path.insert(0, str(ROOT / "research" / "strategy-lab"))

OPENCODE_LINE = ('{prompt} 파일을 먼저 읽고 그 지시를 그대로 따르라. 읽어도 되는 파일은 그 지시 파일과 {input} 두 개뿐이다. '
                 'CLAUDE.md, AGENTS.md, docs/, scripts/, findings/ 는 열지 마라. 저장소를 검색하지 마라.')
LIVE_STRATEGIES = ["pbr_value_v1_combined", "pbr_value_v1", "lowmom60_v1", "factor_earnings_yield_v1", "foreign_flow5d_v1"]
STAGES = ["기술 확보", "고객·수주", "생산·양산", "매출 발생", "이익·현금"]
REPORT_RE = re.compile(r"(사업보고서|반기보고서|분기보고서)\s*\((\d{4})\.(\d{2})\)")
REPRT = {("사업보고서", "12"): "11011", ("반기보고서", "06"): "11012", ("분기보고서", "03"): "11013", ("분기보고서", "09"): "11014"}
EVENT_CATS = [("희석·자금조달", r"유상증자|전환사채|신주인수권|교환사채|주식매수선택권|무상증자"),
              ("자사주·배당", r"자기주식|배당"), ("지분 변동", r"최대주주|대량보유"),
              ("계약·투자", r"단일판매|공급계약|타법인|유형자산|신규시설"), ("실적", r"영업\(잠정\)|매출액또는손익|실적"),
              ("기타 주요", r"합병|분할|소송|감자|상호변경|관리종목|불성실|최대주주변경")]


def _dg():
    spec = importlib.util.spec_from_file_location("dg", ROOT / "scripts" / "decode-gemini.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


def eok(v):
    return None if v is None else round(v / 1e8, 1)


_FX = None


def _fx_series():
    """FRED DEXKOUS(원/달러) 일별 — 외화(USD) 보고서 환산용. 로컬 research/strategy-lab/data/market-regime."""
    global _FX
    if _FX is None:
        import pandas as pd
        d = pd.read_parquet(ROOT / "research/strategy-lab/data/market-regime/usdkrw_daily_kr.parquet", columns=["date", "usdKrwLevel"])
        d["date"] = pd.to_datetime(d["date"])
        _FX = d.dropna().set_index("date")["usdKrwLevel"].sort_index()
    return _FX


def fx_avg(start, end):
    """기간 평균 원/달러(손익·현금흐름용)."""
    x = _fx_series()[start:end]
    return float(x.mean()) if len(x) else None


def fx_at(day):
    """기준일 또는 그 이전 마지막 원/달러(재무상태표용)."""
    x = _fx_series()[:day]
    return float(x.iloc[-1]) if len(x) else None


FLOW = ("revenue", "op", "ni", "sga", "ocf")


def to_krw(fin, yy, mm, annual):
    """USD 보고서 fin -> 원화 환산. 손익·현금흐름은 기간 평균, 재무상태표는 기말(당기)·전기말 환율. (환산 근거 dict 반환)"""
    y = int(yy); end = {"03": 31, "06": 30, "09": 30, "12": 31}[mm]
    cur_end = f"{y}-{mm}-{end:02d}"
    r_cur = fx_avg(f"{y}-01-01", cur_end); r_prev = fx_avg(f"{y - 1}-01-01", f"{y - 1}-{mm}-{end:02d}" if not annual else f"{y - 1}-12-31")
    b_cur = fx_at(cur_end); b_prev = fx_at(f"{y - 1}-12-31")
    out = {}
    for k, (a, b) in fin.items():
        rc, rp = (r_cur, r_prev) if k in FLOW else (b_cur, b_prev)
        out[k] = (None if a is None else a * rc, None if b is None else b * rp)
    return out, {"flowAvgCur": round(r_cur, 1), "flowAvgPrev": round(r_prev, 1), "bsCur": round(b_cur, 1), "bsPrev": round(b_prev, 1)}


def pct_change(a, b):
    return None if a is None or b in (None, 0) else (a / b - 1) * 100


# ── DART ─────────────────────────────────────────────────────────
def dart_list(key, corp, days=730):
    end = date.today(); out, page = [], 1
    while True:
        q = {"crtfc_key": key, "corp_code": corp, "bgn_de": (end - timedelta(days=days)).strftime("%Y%m%d"),
             "end_de": end.strftime("%Y%m%d"), "page_no": page, "page_count": 100}
        d = json.load(urllib.request.urlopen("https://opendart.fss.or.kr/api/list.json?" + urllib.parse.urlencode(q), timeout=30))
        if d.get("status") != "000":
            break
        out += d["list"]
        if page >= int(d.get("total_page", 1)):
            break
        page += 1
    return out


def latest_periodic(lst):
    """가장 최근 기간의 정기보고서(정정 포함, 같은 기간이면 최신 접수). -> (row, kind, year, month)"""
    best = None
    for x in lst:
        m = REPORT_RE.search(x["report_nm"])
        if not m:
            continue
        k = (m.group(2) + m.group(3), x["rcept_dt"])
        if best is None or k > best[0]:
            best = (k, x, m.group(1), m.group(2), m.group(3))
    return None if best is None else best[1:]


ACC = {  # 개념 -> (sj, 표준코드들, 이름 정규식)
    "revenue": (("IS", "CIS"), ("ifrs-full_Revenue",), r"^(매출액|수익\(매출액\)|영업수익|매출)$"),
    "op": (("IS", "CIS"), ("dart_OperatingIncomeLoss",), r"^영업이익(\(손실\))?$"),
    "ni": (("IS", "CIS"), ("ifrs-full_ProfitLoss",), r"^(당기|반기|분기)?순이익(\(손실\))?$"),
    "sga": (("IS", "CIS"), ("dart_TotalSellingGeneralAdministrativeExpenses",), r"^판매비와\s*관리비$"),
    "ocf": (("CF",), ("ifrs-full_CashFlowsFromUsedInOperatingActivities",), r"^영업활동(으로\s*인한)?\s*현금흐름$"),
    "inventory": (("BS",), ("ifrs-full_Inventories",), r"^(유동)?\s*재고자산$"),
    "receivables": (("BS",), ("ifrs-full_TradeAndOtherCurrentReceivables", "dart_ShortTermTradeReceivable", "ifrs-full_CurrentTradeReceivables"), r"^매출채권(\s*및\s*기타\s*(유동)?\s*채권)?$"),
    "equity": (("BS",), ("ifrs-full_Equity",), r"^자본\s*총계$"),
    "liabilities": (("BS",), ("ifrs-full_Liabilities",), r"^부채\s*총계$"),
    "cash": (("BS",), ("ifrs-full_CashAndCashEquivalents",), r"^현금및현금성자산$"),
}


def parse_fin(rows, annual):
    """fnlttSinglAcntAll 행 -> {개념: (당기, 전기 동기 또는 전기말)}. 반기·분기 손익은 누적(add) 금액."""
    out = {}
    for k, (sjs, ids, nm) in ACC.items():
        cand = [r for r in rows if r.get("sj_div") in sjs and r.get("account_id") in ids] or \
               [r for r in rows if r.get("sj_div") in sjs and re.match(nm, (r.get("account_nm") or "").strip())]
        if not cand:
            continue
        r = cand[0]
        if r["sj_div"] in ("IS", "CIS") and not annual and num(r.get("thstrm_add_amount")) is not None:
            out[k] = (num(r.get("thstrm_add_amount")), num(r.get("frmtrm_add_amount")))
        else:   # 현금흐름표 전기 동기는 frmtrm_amount 가 비고 add/q 칸에 오는 회사가 있다
            prev = next((num(r.get(c)) for c in ("frmtrm_amount", "frmtrm_add_amount", "frmtrm_q_amount") if num(r.get(c)) is not None), None)
            out[k] = (num(r.get("thstrm_amount")), prev)
    return out


def dart_fin(key, corp, year, reprt):
    for div in ("CFS", "OFS"):
        q = urllib.parse.urlencode({"crtfc_key": key, "corp_code": corp, "bsns_year": year, "reprt_code": reprt, "fs_div": div})
        d = json.load(urllib.request.urlopen(f"https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?{q}", timeout=30))
        if d.get("status") == "000" and d.get("list"):
            return div, d["list"]
    return None, []


# ── 로컬 데이터 ───────────────────────────────────────────────────
def load_universe():
    return {json.loads(l)["ticker"]: json.loads(l) for l in open(ROOT / "data/backfill/universe/a1a/current.jsonl", encoding="utf-8")}


def load_panel(tickers=None):
    import a3e_account_map as amap
    out = {}
    for line in open(ROOT / "research/strategy-lab/data/fundamentals-ext/annual-ext-panel.jsonl", encoding="utf-8"):
        if tickers is not None and line[12:18] not in tickers:
            continue
        rec = json.loads(line)
        if tickers is not None and rec["ticker"] not in tickers:
            continue
        x = amap.extract(rec)
        out.setdefault(rec["ticker"], {})[rec["fiscalYear"]] = {**{k: x.get(k) for k in ("revenue", "op_income", "net_income", "cfo", "equity")}, "fs": rec["fsDiv"]}
    return out


def load_bars(tickers):
    bars = {t: [] for t in tickers}
    for p in sorted(glob.glob(str(ROOT / "data/backfill/price/a2a/[0-9]*.jsonl.gz")))[-3:]:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                t = line[12:18]   # '{"ticker": "000020", ...' — 값은 12번째 글자부터
                if t in bars:
                    bars[t].append(json.loads(line))
    for t in bars:
        bars[t].sort(key=lambda d: d["date"])
    return bars


def load_krx():
    import pandas as pd
    p = sorted(glob.glob(str(ROOT / "research/strategy-lab/data/krx-pbr-history/pbr/*.parquet")))[-1]
    k = pd.read_parquet(p)
    k = k[k["date"] == k["date"].max()].set_index("ticker")
    return str(k["date"].max())[:10], k


def atr14(b):
    tr = [max(b[i]["high"] - b[i]["low"], abs(b[i]["high"] - b[i - 1]["close"]), abs(b[i]["low"] - b[i - 1]["close"])) for i in range(1, len(b))]
    if len(tr) < 15:
        return None
    a = sum(tr[:14]) / 14
    for x in tr[14:]:
        a = (a * 13 + x) / 14
    return a


def selections(t):
    """전략의 가장 최근 리밸런싱일에 이 종목이 들어 있으면 '현재 선정'."""
    on = []
    for sid in LIVE_STRATEGIES:
        p = ROOT / "research/strategy-lab/strategies" / sid / "selection.json"
        if p.exists():
            sel = json.load(open(p, encoding="utf-8"))["selection"]
            latest = max(x["date"] for v in sel.values() for x in v)
            if any(x["date"] == latest for x in sel.get(t, [])):
                on.append(sid)
    return on


def classify_events(lst):
    out, insider = [], {}
    for x in lst:
        nm = x["report_nm"].strip()
        if REPORT_RE.search(nm):
            continue
        if "임원ㆍ주요주주특정증권등소유상황보고서" in nm:
            insider[x["rcept_dt"]] = insider.get(x["rcept_dt"], 0) + 1
            continue
        cat = next((c for c, p in EVENT_CATS if re.search(p, nm)), None)
        if cat:
            out.append([f'{x["rcept_dt"][:4]}-{x["rcept_dt"][4:6]}-{x["rcept_dt"][6:]}', re.sub(r"\s+", " ", nm), cat, x["rcept_no"]])
    for d, n in insider.items():
        out.append([f"{d[:4]}-{d[4:6]}-{d[6:]}", f"임원·주요주주 소유 보고 {n}건", "지분 변동", None])
    out.sort(key=lambda e: e[0], reverse=True)
    return out


def checks(fin, events):
    """재검토 체크리스트 — 기준은 제안값(미검증). 값이 없으면 '확인 불가'로 둔다(0 으로 채우지 않는다)."""
    g = lambda k: fin.get(k, (None, None))
    rev, inv, rec, sga, ocf, ni, op = (g(k) for k in ("revenue", "inventory", "receivables", "sga", "ocf", "ni", "op"))
    eq, li = g("equity"), g("liabilities")
    rg = pct_change(*rev)
    out = []
    def gap(name, item, warn, watch):
        ig = pct_change(*item)
        if ig is None or rg is None:
            out.append([name, f"> {warn}%p", "확인 불가", "pending"]); return
        d = ig - rg
        out.append([name, f"> {warn}%p", f"{ig:+.0f}% vs 매출 {rg:+.0f}%", "warn" if d > warn else "watch" if d > watch else "ok"])
    gap("재고 증가율 − 매출 증가율", inv, 20, 10)
    gap("매출채권 증가율 − 매출 증가율", rec, 20, 10)
    gap("판관비 증가율 − 매출 증가율", sga, 5, 2)
    if ocf[0] is None:
        out.append(["영업현금흐름", "< 0 · 순이익의 50% 미만", "확인 불가", "pending"])
    else:
        r = ocf[0] / ni[0] if ni[0] and ni[0] > 0 else None
        drop = ocf[1] is not None and ocf[1] > 0 and ocf[0] < ocf[1] * 0.2
        st = "warn" if ocf[0] < 0 else ("watch" if (r is not None and r < 0.5) or drop else "ok")
        out.append(["영업현금흐름", "< 0 · 순이익의 50% 미만 · 전년 동기의 20% 미만",
                    f"{eok(ocf[0])}억" + (f" (전년 동기 {eok(ocf[1])}억)" if ocf[1] is not None else "") + (f" · 순이익의 {r * 100:.0f}%" if r is not None else ""), st])
    if op[0] is not None:
        out.append(["영업이익", "적자", f"{eok(op[0])}억 (전년 동기 {eok(op[1])}억)", "warn" if op[0] < 0 else "ok"])
    if eq[0] and li[0] is not None:
        dr = li[0] / eq[0] * 100
        out.append(["부채비율", "> 200% · 100% 주의", f"{dr:.0f}%", "warn" if dr > 200 else "watch" if dr > 100 else "ok"])
    dil = [e for e in events if e[2] == "희석·자금조달" and e[0] >= (date.today() - timedelta(days=365)).isoformat()]
    out.append(["희석 공시(최근 1년)", "발생", f"{len(dil)}건" + (f" · 최근 {dil[0][0]}" if dil else ""), "watch" if dil else "ok"])
    return out


def pick_peers(t, uni, panel_all, n=4):
    sec = uni[t].get("sector")
    def rev(x):
        ys = sorted(y for y in panel_all.get(x, {}) if panel_all[x][y].get("revenue"))
        return panel_all[x][ys[-1]]["revenue"] if ys else None
    r0 = rev(t)
    cands = [(x, rev(x)) for x, u in uni.items() if x != t and u.get("sector") == sec and rev(x)]
    if r0:
        cands.sort(key=lambda c: abs(math.log(c[1] / r0)))
    return [x for x, _ in cands[:n]], sec


def growth(panel_t):
    ys = sorted(y for y in panel_t if panel_t[y].get("revenue"))
    if len(ys) < 2:
        return {}
    a, b = panel_t[ys[-1]], panel_t[ys[-2]]
    return {"fy": ys[-1], "revYoY": round(pct_change(a["revenue"], b["revenue"]), 1),
            "opMargin": round(a["op_income"] / a["revenue"] * 100, 1) if a.get("op_income") is not None else None}


# ── ① prepare ─────────────────────────────────────────────────────
def prepare(tickers, peer_override=None):
    dg = _dg(); key = dg.load_env().get("DART_API_KEY")
    if not key:
        sys.exit("DART_API_KEY 없음(.env)")
    uni = load_universe()
    for t in [t for t in tickers if t not in uni]:
        print(f"{t} 건너뜀: A1 유니버스에 없음", file=sys.stderr)
    tickers = [t for t in tickers if t in uni]
    panel_all = load_panel()
    a5 = {x["t"]: x for x in json.load(open(ROOT / "docs/data/a5-latest.json", encoding="utf-8"))["items"]}
    a5_asof = json.load(open(ROOT / "docs/data/a5-latest.json", encoding="utf-8"))["asOf"]
    live = {r["ticker"]: r for r in json.load(open(ROOT / "docs/data/latest.json", encoding="utf-8"))["results"]}
    peer_override = peer_override or {}
    peers = {t: (peer_override[t], "수동 지정(사업 기준)") if t in peer_override else pick_peers(t, uni, panel_all) for t in tickers}
    bars = load_bars(set(tickers) | {p for v in peers.values() for p in v[0]})
    krx_asof, krx = load_krx()
    tmpl = (HERE / "prompt.md").read_text(encoding="utf-8")
    for t in tickers:
        try:
            u = uni[t]; d = CACHE / t; d.mkdir(parents=True, exist_ok=True)
            lst = dart_list(key, u["corp"])
            rep, kind, yy, mm = latest_periodic(lst)
            text = dg.dart_text(rep["rcept_no"], key)
            body, trunc = dg.business_section(text)
            (d / "business.txt").write_text(body, encoding="utf-8")
            annual = kind == "사업보고서"
            fs, rows = dart_fin(key, u["corp"], yy, REPRT[(kind, mm)])
            fin = parse_fin(rows, annual)
            cur = next((r.get("currency") for r in rows if r.get("currency")), "KRW")
            fxinfo = None
            if cur != "KRW":
                if cur != "USD":
                    raise ValueError(f"통화 {cur} 환산 미지원")
                fin, fxinfo = to_krw(fin, yy, mm, annual)
            lbl = (f"FY{int(yy) - 1}", f"FY{yy}") if annual else (f"{'H1' if mm == '06' else 'Q1' if mm == '03' else '9M'} {int(yy) - 1}",
                                                                   f"{'H1' if mm == '06' else 'Q1' if mm == '03' else '9M'} {yy}")
            events = classify_events(lst)
            b = bars[t]; v = {}
            if b:
                px = b[-1]["close"]; last = b[-250:]
                v = {"price": px, "asOf": b[-1]["date"], "hi52": max(x["high"] for x in last), "lo52": min(x["low"] for x in last)}
                if t in krx.index:
                    r = krx.loc[t]; bps, eps, dps = float(r["BPS"]), float(r["EPS"]), float(r["DPS"])
                    v.update(bps=bps, pbr=round(px / bps, 2) if bps > 0 else None, per=round(px / eps, 1) if eps > 0 else None,
                             divYield=round(dps / px * 100, 2) if px else None, krxAsOf=krx_asof)
            a = atr14(b) if b else None
            pr = []
            for p in [t] + peers[t][0]:
                if not bars.get(p) or p not in krx.index:
                    continue
                px = bars[p][-1]["close"]; bps = float(krx.loc[p]["BPS"])
                pr.append({"ticker": p, "name": uni[p]["name"], "pbr": round(px / bps, 2) if bps > 0 else None, "self": p == t, **growth(panel_all.get(p, {}))})
            ann = panel_all.get(t, {})
            ys = sorted(ann)[-10:]
            if fxinfo:   # 연간 패널도 같은 외화 단위 — 해당 연도 평균 환율로 환산
                ann = {y: {**ann[y], **{k: (None if ann[y].get(k) is None else ann[y][k] * fx_avg(f"{y}-01-01", f"{y}-12-31"))
                                        for k in ("revenue", "op_income", "net_income", "cfo", "equity")}} for y in ys}
            data = {
                "ticker": t, "name": u["name"], "market": u["market"], "sector": u["sector"], "corp": u["corp"],
                "report": {"rcept": rep["rcept_no"], "name": rep["report_nm"].strip(), "kind": kind, "year": yy, "month": mm,
                           "fs": fs, "truncated": trunc, "businessChars": len(body)},
                "currency": {"reported": cur, "converted": "KRW", **fxinfo} if fxinfo else None,
                "period": {"label": list(lbl), **{k: [eok(fin[k][1]), eok(fin[k][0])] for k in ("revenue", "op", "ni", "ocf") if k in fin}},
                "bs": {k: [eok(fin[k][1]), eok(fin[k][0])] for k in ("inventory", "receivables", "equity", "liabilities", "cash") if k in fin},
                "annual": {"years": ys, "revenue": [eok(ann[y].get("revenue")) for y in ys], "op": [eok(ann[y].get("op_income")) for y in ys],
                           "ni": [eok(ann[y].get("net_income")) for y in ys], "ocf": [eok(ann[y].get("cfo")) for y in ys], "fs": [ann[y]["fs"] for y in ys]},
                "price": {**v, "atr": round(a, 1) if a else None, "stop": round(v["price"] - 3 * a) if a and v else None,
                          "target": round(v["price"] + 4.5 * a) if a and v else None,
                          "series": [{"d": x["date"], "c": x["close"]} for x in b[::5] + b[-1:]] if b else []},
                "score": {"a5": {**a5[t], "asOf": a5_asof} if t in a5 else None,
                          "live": {"total": live[t]["totalScore"], "grade": live[t]["grade"]} if t in live else None},
                "strategies": selections(t), "events": events, "checks": checks(fin, events),
                "peers": pr, "peerNote": (f"동종사 {peers[t][1]}" if t in peer_override else
                                          f"동종사 자동 선정: 같은 업종({peers[t][1]}) · 매출 규모 근접 — 사업이 다를 수 있음"),
            }
            json.dump(data, open(d / "data.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            (d / "prompt.md").write_text(tmpl.replace("{TICKER}", t).replace("{INPUT}", rel(d / "business.txt")).replace("{OUTPUT}", rel(d / "extract.json")), encoding="utf-8")
            print(f"{t} {u['name']}: {rep['report_nm'].strip()} ({rep['rcept_no']}) · 원문 {len(body):,}자{' (잘림)' if trunc else ''} · 재무 {fs} {len(fin)}개 개념 · 공시 {len(events)}건")
            print("   OpenCode:", OPENCODE_LINE.format(prompt=rel(d / "prompt.md"), input=rel(d / "business.txt")))
        except Exception as e:   # 한 종목 실패가 전체 배치를 멈추지 않게(353종목 일괄용)
            print(f"{t} 실패: {type(e).__name__} {e}", file=sys.stderr)


def rel(p):
    return str(Path(p).relative_to(ROOT)).replace("\\", "/")


# ── ③ check ───────────────────────────────────────────────────────
def sq(s):
    return re.sub(r"\s+", "", s or "")


def num_in(srcn, v):
    """숫자 v 가 원문(쉼표 제거본)에 숫자 토큰으로 있는가. 음수는 원문이 (148) 로 적어도 절댓값으로 본다."""
    v = abs(float(v))
    forms = {f"{v:g}", f"{v:.2f}", f"{v:.1f}", f"{v:.0f}" if v.is_integer() else f"{v:g}"}
    return any(re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", srcn) for f in forms)


def check_extract(ext, source):
    """인용 원문 대조 + 숫자-인용 대조 + 기간별 부문 비중 합계. -> (요약, 실패 목록)"""
    src = sq(source); bad = []; n_ok = n_all = 0
    def q(obj, where, nums=()):
        nonlocal n_ok, n_all
        if not isinstance(obj, dict) or not obj.get("quote"):
            return
        n_all += 1
        if sq(obj["quote"]) not in src:
            bad.append([where, "인용이 원문에 없음", obj["quote"][:80]]); return
        n_ok += 1
        qq = obj["quote"].replace(",", "")
        for v in nums:
            if v is not None and not any(c in qq for c in {f"{v:g}", f"{float(v):.2f}", f"{float(v):.1f}", str(int(v)) if float(v).is_integer() else "∅"}):
                bad.append([where, f"숫자 {v:g} 가 인용에 없음", obj["quote"][:80]])
    for i, s in enumerate(ext.get("segments") or []):
        q(s, f"segments[{i}] {s.get('name')}", (s.get("share_pct"),))
    q(ext.get("export"), "export", ((ext.get("export") or {}).get("domestic_pct"), (ext.get("export") or {}).get("overseas_pct")))
    q(ext.get("top_customer"), "top_customer", ((ext.get("top_customer") or {}).get("max_single_share_pct"),))
    for i, c in enumerate(ext.get("capacity") or []):
        q(c, f"capacity[{i}]", (c.get("utilization_pct"),))
    q(ext.get("order_backlog"), "order_backlog")
    q(ext.get("rnd"), "rnd", ((ext.get("rnd") or {}).get("ratio_pct"),))
    q(ext.get("patents_registered"), "patents", ((ext.get("patents_registered") or {}).get("count"),))
    for i, g in enumerate(ext.get("growth_drivers") or []):
        q(g, f"growth[{i}] {g.get('name')}")
    # 값 대조 — 인용 형식과 별개로, 모델이 옮긴 숫자 자체가 원문에 있는가(행 병합·계산으로 인용이 탈락해도 값은 맞을 수 있다)
    srcn = source.replace(",", ""); vals = []; calc_keys = []
    for s in ext.get("segments") or []:
        if s.get("revenue") is not None:
            vals.append(num_in(srcn, s["revenue"]))
    for name, keys in (("export", ("domestic_pct", "overseas_pct")), ("top_customer", ("max_single_share_pct",)),
                       ("rnd", ("ratio_pct", "headcount")), ("patents_registered", ("count",)), ("order_backlog", ("amount",))):
        obj = ext.get(name) or {}
        r = [num_in(srcn, obj[k]) for k in keys if obj.get(k) is not None]
        vals += r
        if not all(r):
            calc_keys.append(name)   # 원문에 그대로 없는 값 — 모델이 합산·환산한 것(지시문은 계산을 금지)
    vals += [num_in(srcn, c["utilization_pct"]) for c in ext.get("capacity") or [] if c.get("utilization_pct") is not None]
    calc = sum(1 for s in ext.get("segments") or [] if s.get("share_pct") is not None and not num_in(srcn, s["share_pct"]))
    sums = {}
    for s in ext.get("segments") or []:
        if s.get("share_pct") is not None:
            sums[s.get("period")] = sums.get(s.get("period"), 0) + float(s["share_pct"])
    for p, v in sums.items():
        if abs(v - 100) > 2:
            bad.append([f"segments {p}", f"비중 합계 {v:.1f}% (100% 아님 — 소계 중복·누락)", ""])
    return {"quotesOk": n_ok, "quotes": n_all, "valuesOk": sum(vals), "values": len(vals), "sharesCalc": calc, "calc": calc_keys, "shareSums": {k: round(v, 1) for k, v in sums.items()}}, bad


def check(tickers):
    for t in tickers:
        d = CACHE / t
        p = d / "extract.json"
        if not p.exists():
            print(f"{t}: extract.json 없음 — OpenCode 미실행"); continue
        raw = p.read_text(encoding="utf-8")
        m = re.search(r"\{.*\}", raw, re.S)
        ext = json.loads(m.group(0)) if m else {}
        summ, bad = check_extract(ext, (d / "business.txt").read_text(encoding="utf-8"))
        res = {"model": ext.get("model"), **summ, "problems": bad}
        json.dump(res, open(d / "check.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{t}: 인용 {summ['quotesOk']}/{summ['quotes']} · 값 {summ['valuesOk']}/{summ['values']} 원문에 있음 · 비중 계산값 {summ['sharesCalc']} · 문제 {len(bad)}건 · 비중 합계 {summ['shareSums']}")
        for b in bad:
            print("   -", b)


# ── ⑤ render ──────────────────────────────────────────────────────
def mix_from(ext):
    """기간별 부문 비중. 비율 칸이 없는 공시는 같은 기간 부문 매출로 비중을 계산한다(표시 전용)."""
    per, rev = {}, {}
    for s in ext.get("segments") or []:
        k = s.get("period") or "-"
        if s.get("share_pct") is not None:
            per.setdefault(k, {})[s.get("name")] = float(s["share_pct"])
        elif s.get("revenue") is not None and float(s["revenue"]) > 0:
            rev.setdefault(k, {})[s.get("name")] = float(s["revenue"])
    for k, v in rev.items():
        if k not in per:
            tot = sum(v.values())
            per[k] = {n: round(x / tot * 100, 2) for n, x in v.items()}
    per = {k: v for k, v in per.items() if 95 <= sum(v.values()) <= 105}   # 합이 100 근처가 아니면(행 중복·계산 오류) 그리지 않는다
    def order(p):   # 연도(없으면 '제N기') 순, 같은 해 안에서는 전기·전반기 < 연간 < 당기·반기·분기
        p = p or ""
        y = re.search(r"(20\d{2})", p) or re.search(r"제\s*(\d+)\s*기", p)
        sub = 2 if re.search(r"당|반기|분기", p) else 0
        if re.search(r"전(기|반기|분기)", p):
            sub = -1
        return (int(y.group(1)) if y else 0, sub)
    keep = sorted(per, key=order)[-4:]          # 최근 4개 기간만
    short = lambda p: re.sub(r"\s+", " ", re.sub(r"\(.*?\)", "", p)).strip() or p
    cats = []
    for k in keep:
        for c in per[k]:
            if c not in cats:
                cats.append(c)
    return {"cats": cats, "periods": {short(k): [per[k].get(c, 0) for c in cats] for k in keep}} if per else None


def facts_from(ext, calc=()):
    tag = lambda k: " · 모델 계산값" if k in calc else ""
    f = []
    e = ext.get("export") or {}
    if e.get("domestic_pct") is not None:
        f.append(["내수 · 수출", f"내수 {e['domestic_pct']:g}% · 수출 {e.get('overseas_pct') or 0:g}% ({e.get('period') or ''})" + tag("export")])
    c = ext.get("top_customer") or {}
    f.append(["최대 단일 고객", "미공시" if c.get("max_single_share_pct") is None else f"{c['max_single_share_pct']:g}%" + (" · 사명 비공개" if c.get("names_disclosed") is False else "") + tag("top_customer")])
    cap = [x for x in ext.get("capacity") or [] if x.get("utilization_pct") is not None]
    if cap:
        f.append(["가동률", " · ".join(f"{x.get('period')} {x['utilization_pct']:g}%" for x in cap)])
    ob = ext.get("order_backlog") or {}
    if ob.get("exists") is not None:
        f.append(["수주잔고", (("있음" + (f" {ob['amount']:,.0f}{ob.get('unit') or ''}" if ob.get("amount") else "")) if ob["exists"] else "없음(단기 발주·프로젝트)") + (tag("order_backlog") if ob.get("exists") else "")])
    r = ext.get("rnd") or {}
    if r.get("ratio_pct") is not None or r.get("headcount") is not None:
        f.append(["연구개발", " · ".join(x for x in [f"매출 대비 {r['ratio_pct']:g}%" if r.get("ratio_pct") is not None else "", f"인력 {r['headcount']:g}명" if r.get("headcount") is not None else ""] if x) + tag("rnd")])
    pt = ext.get("patents_registered") or {}
    if pt.get("count") is not None:
        f.append(["등록 특허", f"{pt['count']:g}건" + tag("patents_registered")])
    return f


TP_FILE = CACHE / "_tp-history.jsonl"   # VM state/tp-history.jsonl 사본(개인 열람 — 저장소 금지, 이 캐시는 gitignore)


def tp_sync():
    """VM 의 목표가 기록을 캐시로 복사한다(ssh stock-new — 작업 VM)."""
    import subprocess
    r = subprocess.run(["ssh", "stock-new", "cat ~/collector-venv/autotrader/state/tp-history.jsonl"], capture_output=True, check=True)
    TP_FILE.write_bytes(r.stdout)
    print(f"목표가 기록 {len(r.stdout.splitlines())}줄 -> {TP_FILE}")


def tp_cards(uni):
    """종목명 -> 티커로 이어 붙인 증권사 목표가 카드 데이터. 이름이 둘 이상의 티커에 걸리면 버린다."""
    if not TP_FILE.exists():
        return {}
    names = {}
    for t, u in uni.items():
        names.setdefault(u["name"], []).append(t)
    alias = {"현대차": "현대자동차"}   # 채널이 줄여 쓰는 이름 — 발견되는 대로 추가
    by = {}
    for l in TP_FILE.read_text(encoding="utf-8").splitlines():
        r = json.loads(l)
        ts = names.get(alias.get(r["name"], r["name"]))
        if ts and len(ts) == 1:
            by.setdefault(ts[0], []).append(r)
    out = {}
    for t, rs in by.items():
        daily = sorted((r for r in rs if r["kind"] == "daily"), key=lambda r: (r["day"], r["pid"]), reverse=True)
        latest = {}
        for r in daily:
            latest.setdefault(r["broker"], r)       # 증권사별 가장 최근 한 줄
        tps = [r["tp"] for r in latest.values()]
        mon = sorted((r for r in rs if r["kind"] == "month"), key=lambda r: r["day"], reverse=True)
        chg = {k: sum(1 for r in daily if r["tpChg"] == k) for k in ("상향", "하향", "신규")}
        out[t] = {"since": min(r["day"] for r in rs),
                  "rows": [[r["day"], r["broker"], f"{r['opinion']}({r['opinionChg']})" if r.get("opinionChg") else r["opinion"], r["tp"], r["tpChg"]] for r in daily[:14]],
                  "n": len(latest), "avg": round(sum(tps) / len(tps)) if tps else None, "max": max(tps) if tps else None, "min": min(tps) if tps else None,
                  "chg": chg, "month": ({k: mon[0].get(k) for k in ("day", "n", "tp", "upside")} if mon else None)}
    return out


GEM_DIR = ROOT / "docs" / "data" / "decode"
GEM_LABEL = {"A_사업구조": "사업 구조", "A_고객": "주요 고객", "A_시장지위": "시장 지위", "A_원재료": "원재료", "A_주요계약": "주요 계약", "C_전망": "회사 전망", "E_위험": "위험 요인"}


def gemini_for(t):
    p = GEM_DIR / f"{t}.json"
    return json.load(open(p, encoding="utf-8")) if p.exists() else {}


def gemini_facts(g):
    out, seen = [], {}
    for i in g["items"]:
        lb = GEM_LABEL.get(i["section"])
        if lb and seen.get(lb, 0) < 2:
            seen[lb] = seen.get(lb, 0) + 1
            out.append([lb, i["claim"]])
    return out + [["요약 · 위험", x] for x in g.get("insights") or []]


def render(tickers, out):
    comps = []
    tpc = tp_cards(load_universe())
    held = json.load(open(CACHE / "_held.json", encoding="utf-8")) if (CACHE / "_held.json").exists() else {}
    nm = {"pbr_value_v1": "PBR", "pbr_value_v1_combined": "PBR 결합", "lowmom60_v1": "저모멘텀", "factor_earnings_yield_v1": "이익수익률", "foreign_flow5d_v1": "외국인수급"}
    for t in tickers:
        d = CACHE / t
        if not (d / "data.json").exists():
            print(f"{t} 건너뜀: prepare 결과 없음", file=sys.stderr); continue
        data = json.load(open(d / "data.json", encoding="utf-8"))
        ext = json.loads(re.search(r"\{.*\}", (d / "extract.json").read_text(encoding="utf-8"), re.S).group(0)) if (d / "extract.json").exists() else {}
        chk = json.load(open(d / "check.json", encoding="utf-8")) if (d / "check.json").exists() else {}
        jd = json.load(open(d / "judgment.json", encoding="utf-8")) if (d / "judgment.json").exists() else {}
        gem = gemini_for(t) if not jd.get("drivers") else {}
        drivers = jd.get("drivers") or [[g.get("name"), g.get("stage_candidate") or 1, (g.get("evidence") or "")] for g in ext.get("growth_drivers") or []]
        by = "Claude 판단" if jd.get("drivers") else "OpenCode 후보 · 미확정"
        facts = facts_from(ext, chk.get("calc") or ()) + (jd.get("facts") or [])
        extract = {"model": ext.get("model"), **{k: chk.get(k) for k in ("quotesOk", "quotes", "valuesOk", "values")}, "problems": len(chk.get("problems") or [])}
        if gem and not ext:   # 판단·추출이 없으면 제미나이 서술로 채운다 — 성장 동력은 단계 없이(Flash-Lite 의 단계 판정은 부풀려져 쓰지 않는다)
            drivers = [[i["claim"], None, ""] for i in gem["items"] if i["section"] == "B_성장동력"]
            by = "제미나이 서술 · 단계 미판정"
            facts = gemini_facts(gem)
            extract = {"model": gem["model"], "quotesOk": gem["kept"], "quotes": gem["kept"] + gem["dropped"], "problems": gem["dropped"]}
        many = len(tickers) > 12   # 일괄 화면은 크기를 줄인다
        if many:
            data = {**data, "eventsMore": max(len(data["events"]) - 14, 0), "events": data["events"][:14]}
        comps.append({**data, "summary": jd.get("summary") or (gem or {}).get("summary") or "판단 미작성 — OpenCode 추출만 표시",
                      "mix": mix_from(ext), "drivers": drivers, "driversBy": by, "facts": facts, "extract": extract, "tp": tpc.get(t),
                      "held": [nm.get(x, x) for x in held.get(t, [])], "judged": bool(jd.get("drivers"))})
    tpl = (HERE / "template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/null", json.dumps({"stages": STAGES, "companies": comps, "generated": date.today().isoformat(),
                                                                "tpSince": min((json.loads(l)["day"] for l in TP_FILE.read_text(encoding="utf-8").splitlines()), default=None) if TP_FILE.exists() else None}, ensure_ascii=False))
    Path(out).write_text(html, encoding="utf-8")
    print(f"화면 -> {out} ({len(comps)}종목)")


# ── selftest ─────────────────────────────────────────────────────
def selftest():
    src = "가. 매출\n천연소재 | 9,187 | 34.37%\n바이오소재 | 7,239 | 27.08%\n기타 | 1,000 | 38.55%\n수주잔고는 해당사항이 없습니다."
    ext = {"segments": [{"name": "천연", "period": "P", "share_pct": 34.37, "quote": "천연소재 | 9,187 | 34.37%"},
                        {"name": "바이오", "period": "P", "share_pct": 27.08, "quote": "바이오소재 | 7,239 | 27.08%"},
                        {"name": "기타", "period": "P", "share_pct": 38.55, "quote": "기타 | 1,000 | 38.55%"}],
           "order_backlog": {"exists": False, "quote": "수주잔고는 해당사항이 없습니다."},
           "rnd": {"ratio_pct": 5.0, "quote": "연구개발비 비율 5%"}}
    s, bad = check_extract(ext, src)
    assert s["quotesOk"] == 4 and s["quotes"] == 5, s
    assert len(bad) == 1 and bad[0][0] == "rnd", bad
    ext["segments"][2]["share_pct"] = 30.0; ext["segments"][2]["quote"] = "기타 | 1,000 | 38.55%"
    _, bad = check_extract(ext, src)
    assert any("숫자 30" in b[1] for b in bad) and any("비중 합계" in b[1] for b in bad), bad
    ext2 = {"segments": [{"name": "A", "period": "P", "revenue": 1054693, "share_pct": 50.5, "quote": "x"}, {"name": "B", "period": "P", "revenue": -148, "quote": "x"},
                         {"name": "C", "period": "P", "revenue": 999, "quote": "x"}]}
    sm, _ = check_extract(ext2, "열 | 소 계 | 1,054,693 | 기타 | (148)")
    assert (sm["valuesOk"], sm["values"], sm["sharesCalc"]) == (2, 3, 1), sm   # 음수 (148)은 값 일치 · 999 는 원문에 없음 · 비중 50.5 는 계산값
    rows = [{"sj_div": "CIS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액", "thstrm_amount": "10", "thstrm_add_amount": "30", "frmtrm_add_amount": "20"},
            {"sj_div": "BS", "account_id": "-표준계정코드 미사용-", "account_nm": "재고자산", "thstrm_amount": "5", "frmtrm_amount": "4"}]
    f = parse_fin(rows, annual=False)
    assert f["revenue"] == (30.0, 20.0) and f["inventory"] == (5.0, 4.0), f
    ck = checks({"revenue": (130.0, 100.0), "inventory": (160.0, 100.0)}, [])
    assert ck[0][3] == "warn" and ck[1][2] == "확인 불가", ck
    usd = {"revenue": (100.0, 50.0), "equity": (10.0, 8.0)}
    k, info = to_krw(usd, "2026", "06", False)
    assert abs(k["revenue"][0] - 100 * info["flowAvgCur"]) < 10 and abs(k["revenue"][1] - 50 * info["flowAvgPrev"]) < 10, k   # info 는 소수 1자리 반올림   # 손익은 기간 평균
    assert abs(k["equity"][0] - 10 * info["bsCur"]) < 10 and abs(k["equity"][1] - 8 * info["bsPrev"]) < 10, k                   # 재무상태표는 기말
    assert 800 < info["flowAvgCur"] < 2500 and 800 < info["bsPrev"] < 2500, info
    print("selftest ok")


def brief(tickers):
    """판단 칸을 쓰기 위한 압축 보기(종목당 ~2천 토큰) — data.json 전체 대신 이것만 읽는다."""
    from collections import Counter
    for t in tickers:
        d = CACHE / t
        if not (d / "data.json").exists():
            continue
        c = json.load(open(d / "data.json", encoding="utf-8"))
        ext = json.loads(re.search(r"\{.*\}", (d / "extract.json").read_text(encoding="utf-8"), re.S).group(0)) if (d / "extract.json").exists() else {}
        chk = json.load(open(d / "check.json", encoding="utf-8")) if (d / "check.json").exists() else {}
        p, pr, a = c["period"], c["price"], c["annual"]
        print(f"## {t} {c['name']} | {c['sector']} | {c['report']['name']}")
        print(f"기간 {p['label']} 매출 {p.get('revenue')} 영업 {p.get('op')} 순이익 {p.get('ni')} 영업CF {p.get('ocf')} (억)")
        print(f"연간 {a['years'][-4:]} 매출 {a['revenue'][-4:]} 영업 {a['op'][-4:]} 순이익 {a['ni'][-4:]}")
        print(f"재무 자본 {c['bs'].get('equity')} 부채 {c['bs'].get('liabilities')} 현금 {c['bs'].get('cash')} | 주가 {pr['price']} 52주 {pr.get('lo52')}~{pr.get('hi52')} PBR {pr.get('pbr')} PER {pr.get('per')} 배당 {pr.get('divYield')}")
        a5, lv = c["score"]["a5"], c["score"]["live"]
        print(f"점수 A5 {a5 and (a5['f'], a5['r'])} 라이브 {lv and (lv['total'], lv['grade'])} 선정 {c['strategies']}")
        print("검사 " + " / ".join(f"{x[0]}:{x[2]}[{x[3]}]" for x in c["checks"] if x[3] != "ok"))
        print("동종 " + " ".join(f"{x['name']}(PBR {x['pbr']} 성장 {x.get('revYoY')} 이익률 {x.get('opMargin')})" for x in c["peers"] if not x["self"]))
        cnt = Counter(e[2] for e in c["events"] if e[0] >= (date.today().replace(year=date.today().year - 1)).isoformat())
        print(f"공시 1년 {dict(cnt)}")
        if ext:
            segs = ext.get("segments") or []
            lastp = segs[-1]["period"] if segs else None
            print(f"[추출 {chk.get('quotesOk')}/{chk.get('quotes')}] 부문(" + str(lastp) + ") " + " · ".join(f"{x['name']} {x['revenue']}{x.get('unit') or ''} {x.get('share_pct')}%" for x in segs if x["period"] == lastp))
            for k in ("export", "top_customer", "order_backlog", "rnd", "patents_registered"):
                v = {a: b for a, b in (ext.get(k) or {}).items() if a != "quote"}
                print(f"  {k} {v}")
            for g in ext.get("growth_drivers") or []:
                print(f"  동력 {g.get('name')} | {g.get('evidence')} | 후보 {g.get('stage_candidate')}")
        g = gemini_for(t)
        if g:
            print("제미나이 요약 " + (g.get("summary") or "")[:200])
            for x in g.get("insights") or []:
                print("  위험·전망 " + x[:150])
        print()


def expand(tickers, shard=None, missing=False):
    """'@kr' = 관심종목 KR 전체(코스피200+코스닥150). --missing 은 data.json 이 이미 있는 종목을 뺀다. --shard i/n 은 병렬 실행용."""
    out = []
    for t in tickers:
        if t == "@held":   # 모의투자 보유 종목 — VM data/paper/*_positions.json 의 OPEN 을 {티커: [전략]} 로 저장해 둔 캐시
            out += list(json.load(open(CACHE / "_held.json", encoding="utf-8")))
        else:
            out += [x["code"] for x in json.load(open(ROOT / "config/watchlist.json", encoding="utf-8"))["tickers"] if x["market"] == "KR"] if t == "@kr" else [t]
    out = list(dict.fromkeys(out))   # '@kr @held' 처럼 겹쳐 지정해도 한 번씩만
    if missing:
        out = [t for t in out if not (CACHE / t / "data.json").exists()]
    if shard:
        i, n = map(int, shard.split("/")); out = out[i::n]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["prepare", "check", "render", "brief", "tp-sync"])
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--out", default=str(CACHE / "decode.html"))
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--missing", action="store_true", help="prepare: data.json 이 이미 있는 종목은 건너뜀")
    ap.add_argument("--shard", help="i/n — 티커 목록을 n 등분한 i 번째만(병렬 실행)")
    ap.add_argument("--peers", action="append", default=[], help="동종사 수동 지정: 티커=동종1,동종2 (여러 번)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    tk = expand(a.tickers, a.shard, a.missing and a.cmd == "prepare")
    {"prepare": lambda: prepare(tk, {k: v.split(",") for k, v in (x.split("=") for x in a.peers)}), "check": lambda: check(tk), "render": lambda: render(tk, a.out), "brief": lambda: brief(tk), "tp-sync": tp_sync}[a.cmd]()


if __name__ == "__main__":
    main()
