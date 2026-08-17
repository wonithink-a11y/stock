#!/usr/bin/env python3
"""A4 — 종목별 일별 수급(외국인·기관·개인 매수/매도) 원자료

A1a(현재 상장 유니버스)의 종목별 일별 매수/매도 금액·수량을 KRX(pykrx)에서 받아
연도별로 저장한다. 정의는 config/policies/supplyDemand.v1.json(SD-1.0)이다.

3차에 걸친 정찰(세션 2026-08-17)의 결론이 이 수집기의 전제다:
  - KIS(inquire-investor)는 최근 ~30거래일 고정창만 주고 날짜 파라미터가 없어
    백필에 못 쓴다. KRX(pykrx get_market_trading_value_by_date/_volume_by_date)만
    2016~현재를 종목당 단일 호출로 받아온다(실측 6.78초/10.6년).
  - 순매수는 저장하지 않는다 — 매수-매도=순매수 항등식이 12/12 카테고리 전건
    성립함을 정찰로 확인했으므로 조회 시점에 유도한다(교훈75).
  - 12개 투자자구분(금융투자·보험·투신·사모·은행·기타금융·연기금·기타법인·개인·
    외국인·기타외국인·전체)을 코드에 하드코딩하지 않는다 — pykrx가 실제로 돌려준
    컬럼 집합을 그대로 저장한다.

build-price-a2b.py를 골격으로 재사용한다(같은 구조: chk/warn/_abort → fetch 레이어 →
run_shard → validate → run_finalize → main). 다른 점 셋:
  1. 소스가 pykrx(로그인 세션)이지 KIS(토큰)가 아니다 — 토큰 캐시가 없다.
  2. 종목 하나에 4콜(금액 매수/매도·수량 매수/매도)이 필요하고, 넷이 같은 날짜
     인덱스를 돌려주는지 자체 정합성 검사가 있다(categoryKeySetViolations).
  3. exitAt 개념이 없다 — 대상이 A1b(폐지)가 아니라 A1a(현재 상장)다.

  --shard N --shards M   후보 부분집합 수집 → _shards_a4/shard-N.jsonl (커밋 안 함)
  --finalize             병합 → 검증 → 연도 분할 → gzip
  --limit N              스모크 테스트용. 진단에 smokeTest 플래그가 박힌다

입력:
  config/policies/supplyDemand.v1.json
  data/backfill/universe/a1a/current.jsonl   대상 종목 (A1a)
  data/backfill/calendar.json                거래일 (A0.5)
출력:
  data/backfill/supplyDemand/a4/{YYYY}.jsonl.gz
  data/backfill/supplyDemand/a4/_diagnostics.json
"""
import argparse
import glob
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = "config/policies/supplyDemand.v1.json"
UNIVERSE = "data/backfill/universe/a1a/current.jsonl"
CALENDAR = "data/backfill/calendar.json"
KST = timezone(timedelta(hours=9))

TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FIELDS = ["ticker", "date", "buyAmount", "sellAmount", "buyVolume", "sellVolume"]
MEASURES = [("buyAmount", "value", "매수"), ("sellAmount", "value", "매도"),
            ("buyVolume", "volume", "매수"), ("sellVolume", "volume", "매도")]

fails, warns = [], []


def chk(cond, msg):
    print(("  OK  " if cond else "  FAIL") + "  " + msg)
    if not cond:
        fails.append(msg)


def warn(cond, msg):
    print(("  OK  " if cond else "  WARN") + "  " + msg)
    if not cond:
        warns.append(msg)


def _abort(reason, diag, path, extra=None):
    """실패해도 진단은 남긴다(교훈39)."""
    diag.update({"aborted": True, "abortReason": reason, **(extra or {})})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)
    print(f"\n중단: {reason}")
    sys.exit(2)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


# ── 수집 (KRX/pykrx) ───────────────────────────────────────────
def merge_dfs(ticker, dfs):
    """4개 DataFrame(buyAmount/sellAmount/buyVolume/sellVolume, 날짜 인덱스)을
    (ticker,date) 레코드 리스트로 합친다. 날짜 인덱스가 넷 다 같아야 한다 —
    순수 함수라 네트워크 없이 테스트 가능하다(이 파일 하단 self-test 참고)."""
    if any(df is None or df.empty for df in dfs.values()):
        if all(df is None or df.empty for df in dfs.values()):
            return None, "empty", None
        return None, "exception", "일부 측정치만 빈 응답 — 부분 응답은 병합하지 않는다"

    indices = {field: {str(d)[:10] for d in df.index} for field, df in dfs.items()}
    all_dates = set.union(*indices.values())
    if any(idx != all_dates for idx in indices.values()):
        mism = {f: sorted(all_dates ^ idx)[:5] for f, idx in indices.items() if idx != all_dates}
        return None, "exception", f"4개 호출의 날짜 인덱스 불일치: {mism}"

    records = []
    for d in sorted(all_dates):
        ts = [t for t in dfs["buyAmount"].index if str(t)[:10] == d][0]
        rec = {"ticker": ticker, "date": d}
        for field in dfs:
            row = dfs[field].loc[ts]
            rec[field] = {str(k): int(v) for k, v in row.items()}
        records.append(rec)
    return records, "ok", None


def fetch_one(stock_mod, ticker, frm, to):
    """(records, kind, error)를 돌려준다. kind는 'ok' | 'empty' | 'exception'.

    종목당 4콜(금액 매수/매도·수량 매수/매도). 하나라도 예외이거나 넷의 날짜
    인덱스가 어긋나면 그 종목 전체를 exception으로 분류한다(부분 병합은 하지
    않는다 — 날짜별로 카테고리가 섞인 레코드보다 재시도가 낫다)."""
    try:
        dfs = {}
        for field, kind_fn, side in MEASURES:
            fn = getattr(stock_mod, f"get_market_trading_{kind_fn}_by_date")
            dfs[field] = fn(frm, to, ticker, on=side, detail=True)
    except Exception as e:  # noqa: BLE001
        return None, "exception", f"{type(e).__name__}: {e}"
    return merge_dfs(ticker, dfs)


def _environment():
    try:
        from importlib.metadata import version
        pykrx_ver = version("pykrx")
    except Exception:  # noqa: BLE001
        pykrx_ver = "unknown"
    return {"pykrx": pykrx_ver, "python": sys.version.split()[0]}


def _import_pykrx_stock():
    """pykrx는 import 시점에 KRX 로그인을 무조건 시도한다(모듈 최상위 부작용,
    KRX_ID/KRX_PW가 설정된 경우). 그 로그인 응답이 가끔 빈 본문으로 온다
    (실측 2026-08-17, 16샤드 동시 실행 1회차 — 재시도만으로 해소됨, 진짜
    동시 로그인 한도가 아니라 KRX 쪽 일시적 응답 불량으로 보인다). 여기서
    막힌 채 3~4시간짜리 본수집 전체를 날리지 않도록 재시도한다."""
    last_err = None
    for attempt in range(4):
        try:
            from pykrx import stock
            return stock
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"  pykrx import/KRX 로그인 실패(시도 {attempt + 1}/4): "
                  f"{type(e).__name__}: {e}")
            time.sleep(10 * (attempt + 1))
    raise last_err


def run_shard(shard, shards, pol, limit):
    stock = _import_pykrx_stock()

    sd = pol
    src = sd["source"]
    shard_dir = sd["output"]["shardDir"]
    diag_path = f"{shard_dir}/_diagnostics-shard-{shard}.json"
    diag = {"stage": "A4", "mode": "shard", "shard": shard, "shards": shards,
            "supplyDemandPolicy": pol["version"], "environment": _environment()}
    if limit:
        diag["smokeTest"] = True

    cand = load_jsonl(UNIVERSE)
    cal = load_json(CALENDAR)
    frm = sd["collectFrom"].replace("-", "")
    to = cal["tradingDays"][-1].replace("-", "")

    tickers = sorted(x["ticker"] for x in cand)
    mine = [t for i, t in enumerate(tickers) if i % shards == shard]
    if limit:
        mine = mine[:limit]
    print(f"A4 샤드 {shard}/{shards} — {len(mine)}종목 · 구간 {frm}~{to}")

    probes = []
    for pt in src["probeTickers"]:
        _, kind, err = fetch_one(stock, pt, to, to)
        probes.append({"ticker": pt, "ok": kind == "ok", "kind": kind, "error": err})
    diag["probes"] = probes
    if not any(p["ok"] for p in probes):
        _abort("정찰 전건 실패 — 수집 경로가 막혔다", diag, diag_path)
    print(f"  정찰 {sum(1 for p in probes if p['ok'])}/{len(probes)} 통과")

    cb = sd["circuitBreaker"]
    rows, empty, exc, unresolved, consec_exc = [], [], [], [], 0
    t0 = time.time()

    for i, tk in enumerate(mine):
        records, kind, err = fetch_one(stock, tk, frm, to)
        if kind == "ok":
            rows.extend(records)
            consec_exc = 0
        elif kind == "empty":
            empty.append(tk)
            consec_exc = 0
        else:
            exc.append({"ticker": tk, "error": err})
            unresolved.append({"ticker": tk, "reason": err})
            consec_exc += 1
            if consec_exc >= cb["consecutiveExceptions"]:
                diag.update(rowCount=len(rows), emptyTickers=empty, exceptionTickers=exc,
                            unresolved=unresolved)
                _abort(f"연속 예외 {consec_exc}건 — 루프 도중 경로가 막혔다", diag, diag_path)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(mine)} · {len(rows)}행 · 빈 응답 {len(empty)} · "
                  f"예외 {len(exc)} · {time.time()-t0:.0f}s")

    diag.update(tickerCount=len(mine), rowCount=len(rows),
                emptyTickers=empty, emptyCount=len(empty),
                exceptionTickers=exc, exceptionCount=len(exc),
                unresolved=unresolved, unresolvedCount=len(unresolved),
                elapsedSeconds=round(time.time() - t0, 1))

    os.makedirs(shard_dir, exist_ok=True)
    with open(f"{shard_dir}/shard-{shard}.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{shard_dir}/shard-{shard}.jsonl — {len(rows)}행 "
          f"({len(mine)}종목 중 빈 응답 {len(empty)} · 예외/UNRESOLVED {len(exc)}, "
          f"{diag['elapsedSeconds']}s)")
    return 0


# ── 검증 ───────────────────────────────────────────────────────
def validate(rows, cand, cal, pol, diag):
    """반환값은 (남길 행,)이다 — A2b와 달리 품질 제외·exitAt이 없다."""
    a = pol["acceptance"]
    print("\n[인수 조건]")

    inject = os.environ.get("A4_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    cal_days = cal["tradingDays"]
    cal_idx = {d: i for i, d in enumerate(cal_days)}
    date_viol = {id(x) for x in rows if not DATE_RE.match(x["date"] or "") or x["date"] not in cal_idx}
    diag["dateContractViolations"] = len(date_viol)
    chk(len(date_viol) == a["dateContractViolations"],
        f"date 계약(YYYY-MM-DD·캘린더 안) 위반 {len(date_viol)}건")

    bad_tk = sorted({x["ticker"] for x in rows if not TICKER_RE.match(x["ticker"] or "")})
    diag["tickerContractViolations"] = len(bad_tk)
    chk(len(bad_tk) == a["tickerContractViolations"],
        f"ticker 계약 [0-9A-Z]{{6}} (위반 {len(bad_tk)}종목)")

    dup = len(rows) - len({(x["ticker"], x["date"]) for x in rows})
    chk(dup == a["duplicateKeys"], f"(ticker,date) 중복 {dup}건")

    # 4개 측정치의 카테고리 키 집합이 레코드 안에서 일치하는지 — fetch_one이
    # 이미 4콜 사이 날짜 인덱스는 맞췄지만, 카테고리 키까지 맞는지는 여기서 확인한다.
    key_mismatch = 0
    for x in rows:
        keys = [frozenset(x[f].keys()) for f in ("buyAmount", "sellAmount", "buyVolume", "sellVolume")]
        if len(set(keys)) > 1:
            key_mismatch += 1
    diag["categoryKeySetViolations"] = key_mismatch
    chk(key_mismatch == a["categoryKeySetViolations"],
        f"카테고리 키 집합 불일치 {key_mismatch}행")

    # 시장 청산 조건 — 순매수를 저장하지 않으므로, 카테고리 합계 매수-매도가
    # 0인지로 항등식을 대신 검사한다(3차 정찰에서 12/12 카테고리 실측 확인).
    clearing_viol = 0
    clearing_sample = []
    for x in rows:
        buy_a, sell_a = x["buyAmount"], x["sellAmount"]
        buy_v, sell_v = x["buyVolume"], x["sellVolume"]
        cats = [k for k in buy_a if k != "전체"]
        diff_a = sum(buy_a.get(k, 0) - sell_a.get(k, 0) for k in cats)
        diff_v = sum(buy_v.get(k, 0) - sell_v.get(k, 0) for k in cats)
        if diff_a != 0 or diff_v != 0:
            clearing_viol += 1
            if len(clearing_sample) < 10:
                clearing_sample.append({"ticker": x["ticker"], "date": x["date"],
                                        "diffAmount": diff_a, "diffVolume": diff_v})
    diag["marketClearingViolations"] = clearing_viol
    diag["marketClearingViolationSample"] = clearing_sample
    chk(clearing_viol == a["marketClearingViolations"],
        f"시장 청산 조건(카테고리 합 매수-매도=0) 위반 {clearing_viol}행")

    # ── 커버리지 (WARN) ────────────────────────────────────────
    by_ticker = defaultdict(list)
    for x in rows:
        by_ticker[x["ticker"]].append(x)
    tickers_with_data = len(by_ticker)
    total_candidates = len(cand)
    rate = tickers_with_data / max(total_candidates, 1)
    diag["candidateCount"] = total_candidates
    diag["tickersWithData"] = tickers_with_data
    diag["tickersWithDataRate"] = round(rate, 4)
    warn(rate >= a["minTickersWithDataWarn"],
         f"데이터 확보 종목 {tickers_with_data}/{total_candidates} "
         f"({rate*100:.1f}%) >= {a['minTickersWithDataWarn']*100:.0f}%")

    from_d = pol["collectFrom"]
    to_d = cal_days[-1]
    expected_days = sum(1 for d in cal_days if from_d <= d <= to_d)
    total_expected = expected_days * max(tickers_with_data, 1)
    total_got = len(rows)
    missing_rate = 1 - (total_got / total_expected) if total_expected else 1
    diag["expectedDaysPerTicker"] = expected_days
    diag["missingRate"] = round(missing_rate, 5)
    warn(missing_rate <= a["missingRateWarn"],
         f"누락률 {missing_rate*100:.2f}% <= {a['missingRateWarn']*100:.0f}% "
         f"(신규상장 등으로 상장 전 구간이 항상 '누락'으로 잡히는 단순 계산 — "
         f"상장일 보정은 다음 버전 과제)")

    unresolved_rate = diag.get("unresolvedCount", 0) / max(total_candidates, 1)
    diag["unresolvedRate"] = round(unresolved_rate, 4)
    warn(unresolved_rate <= a["unresolvedRateWarn"],
         f"UNRESOLVED 비율 {unresolved_rate*100:.2f}% <= {a['unresolvedRateWarn']*100:.0f}% "
         f"({diag.get('unresolvedCount', 0)}/{total_candidates})")

    return rows


# ── finalize ───────────────────────────────────────────────────
def run_finalize(pol):
    out_dir = pol["output"]["dir"]
    shard_dir = pol["output"]["shardDir"]
    diag_path = f"{out_dir}/_diagnostics.json"
    diag = {"stage": "A4", "mode": "finalize", "supplyDemandPolicy": pol["version"],
            "environment": _environment()}

    shard_files = sorted(glob.glob(f"{shard_dir}/shard-*.jsonl"))
    if not shard_files:
        _abort(f"{shard_dir}에 샤드 산출물이 없다 — 수집 잡을 먼저 돌려라", diag, diag_path)

    rows = []
    for p in shard_files:
        rows.extend(load_jsonl(p))
    diag["shardFiles"] = [os.path.basename(p) for p in shard_files]
    diag["shardCount"] = len(shard_files)
    diag["rowCount"] = len(rows)
    print(f"[1/3] 샤드 {len(shard_files)}개 병합 — {len(rows)}행")

    if not rows:
        _abort("병합 결과 0행", diag, diag_path)

    empty_n = exc_n = unresolved_n = 0
    unresolved_all = []
    for p in shard_files:
        d = f"{shard_dir}/_diagnostics-{os.path.basename(p).replace('.jsonl', '')}.json"
        if not os.path.exists(d):
            _abort(f"샤드 진단 없음: {d} — 커버리지 분모를 셀 수 없다", diag, diag_path)
        sd_diag = load_json(d)
        if sd_diag.get("smokeTest"):
            diag["smokeTest"] = True
        empty_n += sd_diag.get("emptyCount", 0)
        exc_n += sd_diag.get("exceptionCount", 0)
        unresolved_n += sd_diag.get("unresolvedCount", 0)
        unresolved_all.extend(sd_diag.get("unresolved", []))
    diag["emptyCount"] = empty_n
    diag["exceptionCount"] = exc_n
    diag["unresolvedCount"] = unresolved_n
    diag["unresolved"] = unresolved_all

    cand = load_jsonl(UNIVERSE)
    cal = load_json(CALENDAR)
    diag["calendarStart"] = cal["tradingDays"][0]
    diag["calendarEnd"] = cal["tradingDays"][-1]
    diag["actualDataFrom"] = min(x["date"] for x in rows)
    diag["actualDataTo"] = max(x["date"] for x in rows)
    print(f"[2/3] 구간 — 캘린더 {diag['calendarStart']}~{diag['calendarEnd']} / "
          f"실측 {diag['actualDataFrom']}~{diag['actualDataTo']} · "
          f"빈 응답 {empty_n} · 예외/UNRESOLVED {exc_n}")

    rows = validate(rows, cand, cal, pol, diag)
    diag["rowCountAfterValidation"] = len(rows)

    os.makedirs(out_dir, exist_ok=True)
    diag["acceptanceFails"] = list(fails)
    diag["acceptanceWarns"] = list(warns)
    diag["acceptancePassed"] = not fails
    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    if warns:
        print(f"\nWARN {len(warns)}건 (실패 아님, 확인 필요):")
        for w in warns:
            print(f"  - {w}")

    if fails:
        print(f"\n인수 조건 {len(fails)}건 실패 — 산출물을 쓰지 않는다")
        for x in fails:
            print(f"  - {x}")
        return 1

    print("\n[3/3] 연도 분할 · gzip")
    rows.sort(key=lambda x: (x["date"], x["ticker"]))
    by_year = defaultdict(list)
    for x in rows:
        by_year[x["date"][:4]].append(x)

    for old in glob.glob(f"{out_dir}/*.jsonl.gz"):
        os.remove(old)

    import gzip
    years = {}
    for y in sorted(by_year):
        path = f"{out_dir}/{y}.jsonl.gz"
        raw = "\n".join(
            json.dumps({k: x[k] for k in FIELDS}, ensure_ascii=False, sort_keys=True)
            for x in by_year[y]
        ).encode("utf-8") + b"\n"
        with open(path, "wb") as f:
            with gzip.GzipFile(fileobj=f, mode="wb", mtime=pol["output"]["gzipMtime"]) as gz:
                gz.compresslevel = pol["output"]["gzipCompressLevel"]
                gz.write(raw)
        gz_bytes = os.path.getsize(path)
        years[y] = {"rows": len(by_year[y]), "rawBytes": len(raw), "gzBytes": gz_bytes}
        print(f"  {y}.jsonl.gz  {len(by_year[y]):>9}행  "
              f"{len(raw)/1e6:6.1f}MB → {gz_bytes/1e6:5.1f}MB")
    diag["years"] = years
    diag["totalGzBytes"] = sum(v["gzBytes"] for v in years.values())

    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{out_dir} — 연도 {len(years)}개 · {len(rows)}행 · "
          f"{diag['totalGzBytes']/1e6:.1f}MB")
    return 0


# ── self-test (네트워크 없이, 교훈: 비트리비얼 로직은 실행 가능한 검증을 남긴다) ──
def _selftest() -> int:
    import pandas as pd

    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  OK  " if cond else "  FAIL") + "  " + label)
        ok = ok and cond

    idx = pd.to_datetime(["2026-08-13", "2026-08-14"])
    cats = ["금융투자", "개인", "외국인", "전체"]

    def mk(vals):
        return pd.DataFrame(vals, index=idx, columns=cats)

    buy_a = mk([[100, 50, 60, 210], [10, 20, 30, 60]])
    sell_a = mk([[80, 70, 60, 210], [15, 10, 35, 60]])
    buy_v = mk([[1, 2, 3, 6], [4, 5, 6, 15]])
    sell_v = mk([[2, 1, 3, 6], [5, 4, 6, 15]])

    records, kind, err = merge_dfs("005930", {
        "buyAmount": buy_a, "sellAmount": sell_a, "buyVolume": buy_v, "sellVolume": sell_v,
    })
    check(kind == "ok" and err is None, "merge_dfs: 정상 병합")
    check(records is not None and len(records) == 2, "merge_dfs: 2행 생성")
    if records:
        r0 = records[0]
        check(r0["ticker"] == "005930" and r0["date"] == "2026-08-13", "merge_dfs: ticker/date")
        check(r0["buyAmount"] == {"금융투자": 100, "개인": 50, "외국인": 60, "전체": 210},
              "merge_dfs: buyAmount 값·키 보존")

    # 날짜 인덱스 불일치 → exception
    buy_a2 = mk([[100, 50, 60, 210], [10, 20, 30, 60]])
    buy_a2.index = pd.to_datetime(["2026-08-13", "2026-08-15"])  # 하루 어긋남
    _, kind2, err2 = merge_dfs("005930", {
        "buyAmount": buy_a2, "sellAmount": sell_a, "buyVolume": buy_v, "sellVolume": sell_v,
    })
    check(kind2 == "exception" and err2, "merge_dfs: 날짜 인덱스 불일치 → exception")

    # 전부 빈 응답 → empty
    empty_df = pd.DataFrame(columns=cats)
    _, kind3, _ = merge_dfs("000000", {
        "buyAmount": empty_df, "sellAmount": empty_df, "buyVolume": empty_df, "sellVolume": empty_df,
    })
    check(kind3 == "empty", "merge_dfs: 전부 빈 응답 → empty")

    # validate()의 시장 청산 조건 검사를 직접 재현 — 매수-매도 카테고리 합이 0이 아니면 위반.
    good_row = {"buyAmount": {"a": 100, "b": 50, "전체": 150},
                "sellAmount": {"a": 90, "b": 60, "전체": 150}}
    bad_row = {"buyAmount": {"a": 100, "b": 50, "전체": 150},
               "sellAmount": {"a": 90, "b": 50, "전체": 140}}
    for label, row, expect_zero in (("정상 행", good_row, True), ("위반 행", bad_row, False)):
        cats2 = [k for k in row["buyAmount"] if k != "전체"]
        diff = sum(row["buyAmount"].get(k, 0) - row["sellAmount"].get(k, 0) for k in cats2)
        check((diff == 0) == expect_zero, f"시장 청산 조건 — {label}")

    print("\n" + ("전체 통과" if ok else "실패 있음"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int)
    ap.add_argument("--shards", type=int)
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="스모크 테스트용. 진단에 smokeTest 플래그가 박힌다")
    ap.add_argument("--selftest", action="store_true",
                    help="네트워크 없이 merge_dfs·시장청산조건 로직만 검증한다")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    if not os.path.exists(POLICY):
        print(f"{POLICY} 없음 — 정책 파일이 필요하다")
        return 1
    pol = load_json(POLICY)
    if "source" not in pol or "output" not in pol:
        print(f"{POLICY}에 source/output 블록이 없다")
        return 1

    if args.finalize:
        return run_finalize(pol)
    if args.shard is None:
        print("--shard N --shards M 또는 --finalize 중 하나가 필요하다")
        return 1
    shards = args.shards or pol["shards"]
    if not (0 <= args.shard < shards):
        print(f"--shard는 0 이상 {shards} 미만이어야 한다")
        return 1
    return run_shard(args.shard, shards, pol, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
