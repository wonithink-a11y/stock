#!/usr/bin/env python3
"""build-eps-ttm.py — 종목별 분기 EPS·TTM PER → docs/data/eps-ttm.json (2026-09-30)

  python scripts/build-eps-ttm.py [--only 005930,035720] [--budget 4000] [--max-minutes 100]
                                  [--cache PATH] [--out PATH] [--no-fetch]

설계: docs/control/종목분석카드-EPS-PER-분해-설계-2026-09-30.md (5종목 시험으로 나온 규칙 전부)
  · 관심종목 KR(config/watchlist.json) 마다 DART fnlttSinglAcntAll 을 분기 보고서(11013·11012·11014)·사업보고서(11011)로 호출.
    최신 분기부터 채우고(호출 예산 --budget 안에서), 받은 값은 data/eps-ttm/quarters.json 에 캐시 → 다음 실행은 새 공시만 부른다.
  · 1분기 = 3개월값 · 2·3분기 = thstrm_amount(3개월) · 4분기 = 사업보고서 EPS − 3분기 누적. 가용일(PIT) = rcept_no 앞 8자리.
  · TTM(t) = t 에 공시된 가장 최근 **연속 4개 분기**의 합. 하나라도 없으면 None(0 이 아니다 — 절대 규칙 1).
  · 기본 EPS 는 계속영업. 중단영업이 있으면 총 EPS 를 따로 남긴다(NAVER 2021 일회성).
  · 액면분할 기준: A3c 분기 발행주식 수의 정수배 점프로 확정, 공시일이 효력 분기 안이면 같은 해 누적 항등식으로 기준을 잇는다.
  · 접수일 − 기간말 > 200일이면 '정정 재공시'(API 는 최신본만 준다 — 원본 EPS 없음)로 표시하고 가용일을 그 접수일로 둔다.
★ 관찰용 — 점수·매매에 쓰지 않는다. docs/data · data/eps-ttm 은 Actions(eps-ttm.yml)만 쓴다(절대 규칙 4 취지).
"""
import argparse
import glob
import gzip
import json
import math
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "eps-ttm.json"
CACHE = ROOT / "data" / "eps-ttm" / "quarters.json"
KST = timezone(timedelta(hours=9))
FIRST_YEAR = 2016
PE = {"11013": (3, 31), "11012": (6, 30), "11014": (9, 30), "11011": (12, 31)}
ORD = ["11013", "11012", "11014", "11011"]
NICE = [2, 3, 4, 5, 10, 20, 50]
SPLIT_TOL = 0.03          # 분기 주식 수 점프가 정수배로 읽히는 상대 오차(시험 5종목에서 정확히 50·5·5.008)
LATE_DAYS = 200           # 접수일 − 기간말 > 이 값이면 정정 재공시
RECHECK_DAYS = 6          # '데이터 없음'(013)을 최근 기간에 한해 다시 묻는 간격
FILING_LAG = 30           # 기간말 + 이 일수가 지나야 공시가 있을 수 있다고 본다
YEARS_SHOWN = 9


def d8(s):
    s = str(s).replace("-", "")
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def num(s):
    try:
        return float(str(s).replace(",", ""))
    except (TypeError, ValueError):
        return None


# ── 파싱 ────────────────────────────────────────────────────────
def _pair(rows):
    q = sum(num(x.get("thstrm_amount")) or 0 for x in rows)
    has = any(num(x.get("thstrm_add_amount")) is not None for x in rows)
    return q, (sum(num(x.get("thstrm_add_amount")) or 0 for x in rows) if has else None)


def parse_eps(eps):
    """주당이익 행 목록 → (q, cum, rule, qc, cumc) | None.  q·cum = 총 EPS, qc·cumc = 계속영업 EPS.
    행 이름이 제각각이다(기본주당이익(손실)·기본주당이익·기본주당순이익·계속영업 기본주당순이익, NAVER 2021~22 는 '계속영업순이익' 에
    작은 금액으로만 들어 있고 2022-1분기에는 오타 '계송영업순이익')."""
    rows = [x for x in eps if "주당" in x.get("account_nm", "") and "희석" not in x.get("account_nm", "")]
    if rows:
        plain = [x for x in rows if "계속" not in x["account_nm"] and "중단" not in x["account_nm"]]
        cont = [x for x in rows if x["account_nm"].startswith("계속영업")]
        use = plain[:1] if plain else rows
        rule = "plain" if plain else "continuing+discontinued"
        q, cum = _pair(use)
        qc, cumc = _pair(cont[:1]) if cont else (q, cum)
    else:
        cont = [x for x in eps if x.get("account_nm", "").startswith("계")
                and (x["account_nm"].endswith("영업순이익") or x["account_nm"].endswith("영업이익"))]
        if not cont:
            return None
        i = eps.index(cont[0])
        use = [cont[0]]
        if i + 1 < len(eps) and eps[i + 1].get("account_nm", "").startswith("중단영업") and num(eps[i + 1].get("thstrm_amount")) is not None:
            use.append(eps[i + 1])
        rule = "fallback"
        q, cum = _pair(use)
        qc, cumc = _pair([cont[0]])
    return q, (cum if cum is not None else q), rule, qc, (cumc if cumc is not None else qc)


# ── 분할 기준 ───────────────────────────────────────────────────
def _snap(m):
    for n in NICE:
        if abs(m / n - 1) < SPLIT_TOL:
            return n
    return None


def split_events(shares):
    """{기간말: 발행주식 수} → [(직전분기말, 확인분기말, 배수)] — 연속 분기 정수배 점프."""
    q = sorted(shares.items())
    out = []
    for (d0, a), (d1, b) in zip(q, q[1:]):
        if a and b / a >= 1.9 and _snap(b / a):
            out.append((d0, d1, _snap(b / a)))
    return out


def _rel(a, b, n):
    if not a or not b:
        return None
    r = a / b
    if abs(r - 1) < 0.05:
        return "same"
    if abs(r / n - 1) < 0.10:
        return "a_n"
    if abs(r * n - 1) < 0.10:
        return "b_n"
    return None


def resolve_basis(F, events):
    """F = {(연도, 코드): {f(date), q, cum, pe(date)}} → ({키: 분할 계수}, [판정 기록]).
    계수 = 이 공시의 EPS 를 **현재 주식 수 기준**으로 바꾸려고 나누는 값(분할 전 기준 공시는 n 배)."""
    fac, notes = {}, []
    for key, x in F.items():
        f_, x["ambn"] = 1.0, None
        for d0, d1, n in events:
            if x["f"] <= d0:
                f_ *= n
            elif x["f"] <= d1:
                x["ambn"] = n
        x["base"] = f_
        if x["ambn"] is None:
            fac[key] = f_
    for _ in range(3):                       # 같은 해 Q1→H1→3Q 누적 항등식으로 기준을 잇는다
        for key, x in F.items():
            if key in fac or x["rc"] == "11011":
                continue
            n, res = x["ambn"], None
            i = ORD.index(x["rc"])
            nxt = F.get((x["y"], ORD[i + 1])) if i <= 1 else None
            prv = F.get((x["y"], ORD[i - 1])) if i >= 1 else None
            if nxt and (x["y"], nxt["rc"]) in fac:
                xv = x["q"] if x["rc"] == "11013" else x["cum"]
                res = {"same": fac[(x["y"], nxt["rc"])], "a_n": fac[(x["y"], nxt["rc"])] * n,
                       "b_n": fac[(x["y"], nxt["rc"])] / n}.get(_rel(xv, nxt["cum"] - nxt["q"], n))
            if res is None and prv and (x["y"], prv["rc"]) in fac:
                pv = prv["q"] if prv["rc"] == "11013" else prv["cum"]
                pb = fac[(x["y"], prv["rc"])]
                res = {"same": pb, "a_n": pb / n, "b_n": pb * n}.get(_rel(pv, x["cum"] - x["q"], n))
            if res is not None:
                fac[key] = res
                notes.append(f"{x['pe']} {x['rc'][-2:]}:누적 사슬")
    for key, x in F.items():                 # 남은 것 — 이웃 분기 크기로 추정(약함). 표시한다
        if key in fac:
            continue
        n = x["ambn"]
        refs = [z["q"] / fac[(z["y"], z["rc"])] for z in sorted(
            (z for z in F.values() if z["rc"] != "11011" and z is not x and (z["y"], z["rc"]) in fac),
            key=lambda z: abs((z["pe"] - x["pe"]).days))[:2] if z["q"]]
        cv = x["q"] / 4 if x["rc"] == "11011" else x["q"]
        if refs and cv:
            cpre = sum(abs(math.log(abs(cv / (x["base"] * n)) / abs(r))) for r in refs)
            cpost = sum(abs(math.log(abs(cv / x["base"]) / abs(r))) for r in refs)
            fac[key] = x["base"] * n if cpre < cpost else x["base"]
            notes.append(f"{x['pe']} {x['rc'][-2:]}:근접값 추정(약함)")
        else:
            fac[key] = x["base"]
            notes.append(f"{x['pe']} {x['rc'][-2:]}:판정불가")
    return fac, notes


# ── 분기 조립·TTM ───────────────────────────────────────────────
def build_quarters(F, fac):
    """→ (Q, QC, annual) — Q[(연도, 분기)] = (EPS, 가용일, 정정여부), QC 는 계속영업, annual = [(가용일, EPS, 계속영업, 연도, 정정)]."""
    for key, x in F.items():
        f_ = fac[key]
        x["qa"], x["cuma"], x["qca"], x["cumca"] = x["q"] / f_, x["cum"] / f_, x["qc"] / f_, x["cumc"] / f_
        x["late"] = (x["f"] - x["pe"]).days > LATE_DAYS
    Q, QC = {}, {}
    for (y, rc), x in F.items():
        qn = {"11013": 1, "11012": 2, "11014": 3}.get(rc)
        if qn:
            Q[(y, qn)] = (x["qa"], x["f"], x["late"])
            QC[(y, qn)] = (x["qca"], x["f"], x["late"])
    for y in {k[0] for k in F}:
        fy, n9 = F.get((y, "11011")), F.get((y, "11014"))
        if fy and n9:
            av, late = max(fy["f"], n9["f"]), fy["late"] or n9["late"]
            Q[(y, 4)] = (fy["qa"] - n9["cuma"], av, late)
            QC[(y, 4)] = (fy["qca"] - n9["cumca"], av, late)
    annual = sorted((x["f"], x["qa"], x["qca"], x["y"], x["late"]) for (y, rc), x in F.items() if rc == "11011")
    return Q, QC, annual


def ttm_at(d, QQ):
    """→ None(공시 없음) | ('gap',) | ('ok', TTM, 가장 오래된 분기 공시 후 경과일 아닌 '최신 공시 후 경과일', 정정포함, 기간라벨 4개)."""
    known = {k: v for k, v in QQ.items() if v[1] <= d}
    if not known:
        return None
    y, qn = max(known)
    keys = []
    for _ in range(4):
        keys.append((y, qn))
        qn -= 1
        if qn == 0:
            y, qn = y - 1, 4
    if not all(k in known for k in keys):
        return ("gap",)
    newest = max(known[k][1] for k in keys)
    return ("ok", sum(known[k][0] for k in keys), (d - newest).days, any(known[k][2] for k in keys), keys)


def attribution(a, b):
    """연말 a→b: ln P = ln EPS + ln PER. 둘 다 EPS>0 일 때만."""
    if a["ttmEps"] and b["ttmEps"] and a["ttmEps"] > 0 and b["ttmEps"] > 0 and a["price"] and b["price"]:
        return {"lnP": math.log(b["price"] / a["price"]), "lnEps": math.log(b["ttmEps"] / a["ttmEps"]),
                "lnPer": math.log(b["per"] / a["per"])}
    return None


def summarize(F, events, year_end_prices, today):
    """한 종목의 캐시된 분기 공시(F) → 출력 항목. year_end_prices = {연도: (날짜문자열, 수정종가)}."""
    if not F:
        return None
    fac, notes = resolve_basis(F, events)
    Q, QC, annual = build_quarters(F, fac)
    ttm, tc = ttm_at(today, Q), ttm_at(today, QC)
    flags = []
    if any(n.endswith("근접값 추정(약함)") or n.endswith("판정불가") for n in notes):
        flags.append("split_uncertain")
    if any(x["late"] for x in F.values()):
        flags.append("restated")
    if any(x["rule"] == "fallback" for x in F.values()):
        flags.append("eps_row_fallback")
    if any(abs(x["q"] - x["qc"]) > 0.02 * max(abs(x["q"]), 1) for x in F.values()):
        flags.append("discontinued_ops")
    item = {"filings": len(F), "asOf": max(x["f"] for x in F.values()).strftime("%Y%m%d"), "flags": flags, "splitNotes": notes}
    if ttm and ttm[0] == "ok":
        item["ttm"] = {"eps": round(ttm[1], 2), "epsCont": round(tc[1], 2) if tc and tc[0] == "ok" else None, "ageDays": ttm[2],
                       "late": ttm[3], "periods": [f"{y}Q{q}" for y, q in sorted(ttm[4])]}
    else:
        item["ttm"] = None
        item["ttmReason"] = "no_filings" if ttm is None else "quarter_gap"      # 분기 결측(정정 재공시로 4분기가 빈 경우 포함)
    if annual:
        f, e, ec, y, late = annual[-1]
        item["annual"] = {"fy": y, "eps": round(e, 2), "epsCont": round(ec, 2), "f": f.strftime("%Y%m%d"), "late": late}
    yearly = []
    for y in sorted(year_end_prices)[-YEARS_SHOWN:]:
        ds, p = year_end_prices[y]
        t = ttm_at(d8(ds), Q)
        te = t[1] if t and t[0] == "ok" else None
        an = [a for a in annual if a[0] <= d8(ds)]
        ae = an[-1][1] if an else None
        yearly.append({"y": y, "d": ds, "price": p, "ttmEps": round(te, 2) if te is not None else None,
                       "per": round(p / te, 2) if te and te > 0 else None,
                       "annEps": round(ae, 2) if ae is not None else None, "annPer": round(p / ae, 2) if ae and ae > 0 else None})
    for a, b in zip(yearly, yearly[1:]):
        b["attr"] = attribution(a, b)
    item["yearly"] = yearly
    return item


# ── 수집 ────────────────────────────────────────────────────────
def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    if os.environ.get("DART_API_KEY"):
        env["DART_API_KEY"] = os.environ["DART_API_KEY"]
    return env


def dart_fnltt(key, corp, y, rc, div):
    q = f"crtfc_key={key}&corp_code={corp}&bsns_year={y}&reprt_code={rc}&fs_div={div}"
    for attempt in range(3):
        try:
            return json.load(urllib.request.urlopen(f"https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json?{q}", timeout=25))
        except Exception:
            if attempt == 2:
                raise
            time.sleep(4)


def _small(v):
    x = num(v)
    return x is not None and 0 < abs(x) < 1e7


def fetch_entry(key, corp, y, rc):
    """→ (entry, 호출 수). entry = {f, div, q, cum, qc, cumc, rule} | {none: 조회일} | None(오류 — 캐시 안 함).
    CFS 가 없으면(013) OFS 로 한 번 더."""
    calls = 0
    for div in ("CFS", "OFS"):
        d = dart_fnltt(key, corp, y, rc, div)
        calls += 1
        st = d.get("status")
        if st == "020":
            raise RuntimeError("DART 020 일일 한도 초과")
        rows = d.get("list") or []
        if st == "000" and rows:
            eps = [x for x in rows if x.get("sj_div") in ("IS", "CIS")
                   and ("주당" in x.get("account_nm", "") or _small(x.get("thstrm_amount")))]
            pr = parse_eps(eps)
            f = str(rows[0].get("rcept_no") or "")[:8]
            if not pr or not re.fullmatch(r"\d{8}", f):
                return {"none": datetime.now(KST).strftime("%Y%m%d"), "why": "no_eps_row"}, calls
            return {"f": f, "div": div, "q": pr[0], "cum": pr[1], "qc": pr[3], "cumc": pr[4], "rule": pr[2]}, calls
        if st != "013":
            return None, calls
    return {"none": datetime.now(KST).strftime("%Y%m%d")}, calls


def plan_tasks(cache, targets, today):
    """아직 안 받은 (종목, 연도, 코드) — 최신 기간부터. 없음(013) 결과는 최근 기간만 RECHECK_DAYS 마다 다시 묻는다."""
    out = []
    for t in targets:
        for y in range(FIRST_YEAR, today.year + 1):
            for rc in ORD:
                m, dd = PE[rc]
                pe = date(y, m, dd)
                if pe + timedelta(days=FILING_LAG) > today:
                    continue
                e = (cache.get(t) or {}).get(f"{y}|{rc}")
                if e and "f" in e:
                    continue
                if e and "none" in e:
                    recent = (today - pe).days <= 240
                    if not recent or (today - d8(e["none"])).days < RECHECK_DAYS:
                        continue
                out.append((pe, t, y, rc))
    out.sort(key=lambda z: (-z[0].toordinal(), z[1]))
    return out


def run_fetch(tasks, cache, key, corp, budget, max_minutes, workers, save):
    """계획된 조회를 스레드 `workers` 개로 병렬 수집한다 → (받은 건, 호출 수, 오류 수).
    예산은 **제출 시점**에 지킨다(작업당 최대 2콜 — CFS 없으면 OFS 한 번 더). 캐시·카운터는 이 스레드에서만 만진다.
    020(일일 한도)이면 새 제출을 멈추고 이미 나간 것만 받는다. 연속 30건 비정상이면 저장하고 붉어진다."""
    t0 = time.time()
    calls = fetched = errs = bad_run = 0
    stop = False
    it = iter(tasks)
    pending = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        while True:
            while (not stop and len(pending) < workers and calls + 2 * (len(pending) + 1) <= budget + 1
                   and (time.time() - t0) / 60 <= max_minutes):
                task = next(it, None)
                if task is None:
                    break
                _pe, t, y, rc = task
                pending[ex.submit(fetch_entry, key, corp[t], y, rc)] = task
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for f in done:
                _pe, t, y, rc = pending.pop(f)
                try:
                    e, c = f.result()
                except RuntimeError as exc:          # 020 — 이어서 불러 봐야 전부 실패다
                    if not stop:
                        print("  중단:", exc)
                    stop = True
                    continue
                except Exception as exc:             # 네트워크 — 이 건만 건너뛴다(캐시 안 함)
                    errs += 1
                    print(f"  {t} {y} {rc} 실패 {type(exc).__name__}: {str(exc)[:80]}")
                    continue
                calls += c
                bad_run = 0 if e is not None else bad_run + 1
                if bad_run >= 30:                    # 키·소스 사망 — 예산만 태우지 말고 붉어진다(notify-failure)
                    save()
                    raise SystemExit("DART 응답이 연속 30건 비정상 — 중단(받은 것은 저장함)")
                if e is not None:
                    cache.setdefault(t, {})[f"{y}|{rc}"] = e
                    fetched += 1
                    if fetched % 300 == 0:
                        save()
                        print(f"  {fetched}건 · {calls}콜 · {(time.time() - t0) / 60:.1f}분")
    return fetched, calls, errs


def cache_to_F(cache_t):
    F = {}
    for k, e in (cache_t or {}).items():
        if "f" not in e:
            continue
        y, rc = k.split("|")
        y = int(y)
        m, dd = PE[rc]
        F[(y, rc)] = {"y": y, "rc": rc, "f": d8(e["f"]), "pe": date(y, m, dd), "q": e["q"], "cum": e["cum"],
                      "qc": e["qc"], "cumc": e["cumc"], "rule": e["rule"]}
    return F


# ── 입력 데이터 ─────────────────────────────────────────────────
def load_shares(tickers):
    sh = {t: {} for t in tickers}
    for p in glob.glob(str(ROOT / "data/backfill/fundamentals/a3c/20*.jsonl.gz")):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                r = json.loads(line)
                if r.get("ticker") in sh and r.get("scanStatus") == "OK" and r.get("istcTotqy"):
                    pe, av = d8(r["periodEnd"]), d8(r["availableFrom"])
                    if r["reprtCode"] == "11011" and (av - pe).days > 120:
                        continue                   # 정정 재공시로 접수일이 몇 년 밀린 사업보고서 행은 시점이 틀리다
                    sh[r["ticker"]][pe] = r["istcTotqy"]
    return sh


def load_fy_month(tickers):
    """{종목: 결산월} — A3 사업보고서 기간말(최신 연도 우선). 12월 결산만 다룬다(분기 라벨·정정 판정이 달력 분기를 가정한다)."""
    out = {}
    for p in sorted(glob.glob(str(ROOT / "data/backfill/fundamentals/a3/20*.jsonl.gz")), reverse=True):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                i = line.find('"ticker": "')
                if i < 0 or line[i + 11:i + 17] not in tickers:
                    continue
                r = json.loads(line)
                if r["ticker"] not in out and r.get("periodEnd"):
                    out[r["ticker"]] = int(r["periodEnd"].replace("-", "")[4:6])
    return out


def load_year_end_prices(tickers):
    """{종목: {연도: (YYYYMMDD, 수정종가)}} — A2a 일봉(수정주가)의 연말 마지막 거래일."""
    best = {t: {} for t in tickers}
    for p in sorted(glob.glob(str(ROOT / "data/backfill/price/a2a/20*.jsonl.gz"))):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                i = line.find('"ticker": "')
                if i < 0 or line[i + 11:i + 17] not in best:
                    continue
                r = json.loads(line)
                if not r.get("close"):
                    continue
                ds = r["date"].replace("-", "")
                cur = best[r["ticker"]].get(int(ds[:4]))
                if not cur or ds > cur[0]:
                    best[r["ticker"]][int(ds[:4])] = (ds, r["close"])
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--budget", type=int, default=15000, help="이번 실행의 DART 호출 상한")
    ap.add_argument("--max-minutes", type=float, default=100)
    ap.add_argument("--workers", type=int, default=6, help="병렬 스레드 수(DART 호출) — 8스레드 초당 ≈25콜이 오류 없이 돌았다(2026-10-01 로컬 시험)")
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    today = datetime.now(KST).date()
    wl = json.loads((ROOT / "config" / "watchlist.json").read_text(encoding="utf-8"))
    names = {t["code"]: t.get("name") for t in wl["tickers"] if (t.get("market") or "KR") == "KR"}
    if a.only:
        names = {t: names.get(t) for t in a.only.split(",")}
    corp = {}
    for line in (ROOT / "data" / "backfill" / "dart" / "corpcode.jsonl").read_text(encoding="utf-8").splitlines():
        j = json.loads(line)
        corp[j.get("ticker")] = j.get("corp")
    fy = load_fy_month(set(names))
    skipped = {t: ("no_corp" if not corp.get(t) else "fy_unknown" if t not in fy else "non_december_fy")
               for t in names if not corp.get(t) or fy.get(t) != 12}
    targets = [t for t in names if t not in skipped]
    cp = Path(a.cache)
    cache = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}

    tasks = plan_tasks(cache, targets, today)
    print(f"대상 {len(targets)}종목 · 남은 조회 {len(tasks)}건 · 예산 {a.budget}콜")
    if tasks and not a.no_fetch:
        key = load_env().get("DART_API_KEY")
        if not key:
            raise SystemExit("DART_API_KEY 가 필요하다")
        def save():
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(cache, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        t0 = time.time()
        fetched, calls, errs = run_fetch(tasks, cache, key, corp, a.budget, a.max_minutes, a.workers, save)
        print(f"수집 {fetched}건 · {calls}콜 · 오류 {errs} · {time.time() - t0:.0f}초 · 스레드 {a.workers}")
        save()

    shares = load_shares(targets)
    ye = load_year_end_prices(targets)
    items, missing = {}, 0
    for t in targets:
        it = summarize(cache_to_F(cache.get(t)), split_events(shares[t]), ye[t], today)
        if it:
            it["name"] = names.get(t)
            items[t] = it
        else:
            missing += 1
    for t, why in skipped.items():
        items[t] = {"name": names.get(t), "ttm": None, "ttmReason": why, "flags": [], "filings": 0}
    left = len(plan_tasks(cache, targets, today))
    out = {"updatedAt": datetime.now(KST).isoformat(timespec="seconds"), "count": len(items), "pending": left,
           "note": ("TTM = 공시된 최근 연속 4개 분기 EPS 합(계속영업 기준이 기본). 연간 EPS 는 최대 12개월 묵은 값이라 비교용으로만 둔다. "
                    "flags: split_uncertain=액면분할 기준 판정이 약함 · restated=정정 재공시로 원본 없음(그 구간 TTM 결측 가능) · "
                    "discontinued_ops=중단영업 일회성이 총 EPS 에 섞임 · eps_row_fallback=주당이익 행 이름이 비표준. 관찰용 — 점수·매매에 쓰지 않는다."),
           "items": items}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"saved: {a.out} · 종목 {len(items)} · 12월 결산 아님·코드 없음 {len(skipped)} · 공시 없음 {missing} · 남은 조회 {left}")


if __name__ == "__main__":
    sys.exit(main())
