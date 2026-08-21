#!/usr/bin/env python3
"""A8 — 종목별 일별 공매도(거래·잔고) 원자료

A1a(현재 상장 유니버스)의 종목별 일별 공매도 거래량·거래대금·잔고수량·잔고금액을
KRX(pykrx)에서 받아 연도별로 저장한다. 정의는
config/policies/shortSelling.v1.json(SS-1.0)이다.

정찰(2026-08-21~22, probe-shorting-krx 워크플로 run 32502926508)의 결론이 이
수집기의 전제다:
  - A4(수급)를 뚫은 것과 같은 KRX_ID/KRX_PW 로그인 세션으로 공매도도 열린다
    (data-source-availability.md 2026-08-22 갱신 - 이전엔 "차단"이었다).
  - get_shorting_status_by_date 하나가 [거래량, 잔고수량, 거래대금, 잔고금액]을
    한 호출로 전부 준다 - get_shorting_balance_by_date는 이 함수의 부분집합
    (값 대조로 확인, 잔고수량/잔고금액이 완전히 동일)이라 별도 수집 안 한다.
    A4(4콜/종목)와 달리 종목당 1콜.
  - collectFrom(2016-01-04)은 A4 값을 잠정 재사용한 것뿐 - 공매도 데이터 자체의
    가용 시작일은 anchor로 확인된 적이 없다(정책 파일의 ★ 표시 참고). 스모크가
    이걸 확인하는 게 본수집 GO의 전제조건이다.

build-supply-demand-a4.py를 골격으로 재사용한다(같은 구조: chk/warn/_abort →
fetch 레이어 → run_shard → validate(스트리밍) → run_finalize → main). A4와
다른 점: 종목당 1콜뿐이라 4-way 카테고리 교차검증(categoryKeySetViolations)과
시장청산조건(marketClearingViolations) 검사가 없다 - 애초에 카테고리 구조 자체가
없다(flat 4필드).

  --shard N --shards M   후보 부분집합 수집 → _shards_a8/shard-N.jsonl (커밋 안 함)
  --finalize             병합 → 검증 → 연도 분할 → gzip
  --limit N               스모크 테스트용. 진단에 smokeTest 플래그가 박힌다
  --anchor YYYY-MM-DD     스모크 전용 - 이 날짜 하나로 정찰종목의 응답 유무만 확인
                          하고 즉시 종료한다(collectFrom 실제 시작일 확인용)

입력:
  config/policies/shortSelling.v1.json
  data/backfill/universe/a1a/current.jsonl   대상 종목 (A1a)
  data/backfill/calendar.json                거래일 (A0.5)
출력:
  data/backfill/shortSelling/a8/{YYYY}.jsonl.gz
  data/backfill/shortSelling/a8/_diagnostics.json
"""
import argparse
import glob
import json
import os
import re
import sys
import time
from datetime import timedelta, timezone

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = "config/policies/shortSelling.v1.json"
UNIVERSE = "data/backfill/universe/a1a/current.jsonl"
CALENDAR = "data/backfill/calendar.json"
KST = timezone(timedelta(hours=9))

TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FIELDS = ["ticker", "date", "shortVolume", "shortBalanceShares", "shortValue", "shortBalanceValue"]
# pykrx 실제 컬럼명(한글, 정찰 실측 2026-08-21) -> 우리 필드명
COLUMN_MAP = {
    "거래량": "shortVolume", "잔고수량": "shortBalanceShares",
    "거래대금": "shortValue", "잔고금액": "shortBalanceValue",
}

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
def records_from_df(ticker, df):
    """get_shorting_status_by_date 응답 DataFrame(날짜 인덱스, 한글 컬럼 4개)을
    (ticker,date) 레코드 리스트로 변환한다 - 순수 함수라 네트워크 없이
    테스트 가능하다(이 파일 하단 self-test 참고)."""
    if df is None or df.empty:
        return None, "empty", None
    missing_cols = set(COLUMN_MAP) - set(df.columns.astype(str))
    if missing_cols:
        return None, "exception", f"기대한 컬럼 누락: {sorted(missing_cols)}"

    records = []
    for ts, row in df.iterrows():
        d = str(ts)[:10]
        rec = {"ticker": ticker, "date": d}
        for kr_col, field in COLUMN_MAP.items():
            rec[field] = int(row[kr_col])
        records.append(rec)
    return records, "ok", None


def fetch_one(stock_mod, ticker, frm, to):
    """(records, kind, error)를 돌려준다. kind는 'ok' | 'empty' | 'exception'."""
    try:
        df = stock_mod.get_shorting_status_by_date(frm, to, ticker)
    except Exception as e:  # noqa: BLE001
        return None, "exception", f"{type(e).__name__}: {e}"
    return records_from_df(ticker, df)


def _environment():
    try:
        from importlib.metadata import version
        pykrx_ver = version("pykrx")
    except Exception:  # noqa: BLE001
        pykrx_ver = "unknown"
    return {"pykrx": pykrx_ver, "python": sys.version.split()[0]}


def _import_pykrx_stock():
    """pykrx는 import 시점에 KRX 로그인을 무조건 시도한다(A4와 동일 재시도 패턴)."""
    last_err = None
    for attempt in range(4):
        try:
            from pykrx import stock
            return stock
        except Exception as e:  # noqa: BLE001
            last_err = e
            wait = 30 * (attempt + 1)
            print(f"  pykrx import/KRX 로그인 실패(시도 {attempt + 1}/4, {wait}초 대기): "
                  f"{type(e).__name__}: {e}")
            time.sleep(wait)
    raise last_err


def run_anchor_check(pol, anchor_date):
    """스모크 전용 - collectFrom 실제 시작일을 확인하기 위해 정찰종목만으로
    특정 날짜 하나의 응답 유무를 본다. data/backfill/에 아무것도 안 쓴다."""
    stock = _import_pykrx_stock()
    d = anchor_date.replace("-", "")
    print(f"anchor 확인 — {anchor_date}")
    for pt in pol["source"]["probeTickers"]:
        records, kind, err = fetch_one(stock, pt, d, d)
        n = len(records) if records else 0
        print(f"  {pt}: {kind} ({n}행) {err or ''}")
    return 0


def run_shard(shard, shards, pol, limit):
    stock = _import_pykrx_stock()

    src = pol["source"]
    shard_dir = pol["output"]["shardDir"]
    diag_path = f"{shard_dir}/_diagnostics-shard-{shard}.json"
    diag = {"stage": "A8", "mode": "shard", "shard": shard, "shards": shards,
            "shortSellingPolicy": pol["version"], "environment": _environment()}
    if limit:
        diag["smokeTest"] = True

    cand = load_jsonl(UNIVERSE)
    cal = load_json(CALENDAR)
    frm = pol["collectFrom"].replace("-", "")
    to = cal["tradingDays"][-1].replace("-", "")

    tickers = sorted(x["ticker"] for x in cand)
    mine = [t for i, t in enumerate(tickers) if i % shards == shard]
    if limit:
        mine = mine[:limit]
    print(f"A8 샤드 {shard}/{shards} — {len(mine)}종목 · 구간 {frm}~{to}")

    probes = []
    for pt in src["probeTickers"]:
        _, kind, err = fetch_one(stock, pt, to, to)
        probes.append({"ticker": pt, "ok": kind == "ok", "kind": kind, "error": err})
    diag["probes"] = probes
    if not any(p["ok"] for p in probes):
        _abort("정찰 전건 실패 — 수집 경로가 막혔다", diag, diag_path)
    print(f"  정찰 {sum(1 for p in probes if p['ok'])}/{len(probes)} 통과")

    cb = pol["circuitBreaker"]
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


# ── 검증 (스트리밍, A4와 동일 이유 - OOM 회피) ───────────────────
def stream_validate_and_route(shard_files, cand, cal, pol, diag, scratch_dir):
    a = pol["acceptance"]
    cal_idx = {d: i for i, d in enumerate(cal["tradingDays"])}
    candidate_tickers = {x["ticker"] for x in cand}

    print("\n[인수 조건 — 스트리밍 1단계: 검증 + 연도 라우팅]")

    inject = os.environ.get("A8_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    os.makedirs(scratch_dir, exist_ok=True)
    year_writers = {}

    seen_keys = set()
    dup_count = 0
    date_viol = 0
    bad_tk = set()
    by_ticker = set()
    row_count = 0
    min_date = max_date = None

    for p in shard_files:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                x = json.loads(line)
                row_count += 1
                d, tk = x.get("date"), x.get("ticker")

                if not DATE_RE.match(d or "") or d not in cal_idx:
                    date_viol += 1
                if not TICKER_RE.match(tk or ""):
                    bad_tk.add(tk)

                key = (tk, d)
                if key in seen_keys:
                    dup_count += 1
                else:
                    seen_keys.add(key)

                by_ticker.add(tk)
                if min_date is None or d < min_date:
                    min_date = d
                if max_date is None or d > max_date:
                    max_date = d

                y = (d or "0000")[:4]
                fh = year_writers.get(y)
                if fh is None:
                    fh = open(f"{scratch_dir}/{y}.jsonl", "a", encoding="utf-8", newline="\n")
                    year_writers[y] = fh
                fh.write(json.dumps({k: x[k] for k in FIELDS}, ensure_ascii=False) + "\n")

    for fh in year_writers.values():
        fh.close()

    diag["rowCount"] = row_count
    diag["actualDataFrom"] = min_date
    diag["actualDataTo"] = max_date
    diag["dateContractViolations"] = date_viol
    chk(date_viol == a["dateContractViolations"],
        f"date 계약(YYYY-MM-DD·캘린더 안) 위반 {date_viol}건")

    diag["tickerContractViolations"] = len(bad_tk)
    chk(len(bad_tk) == a["tickerContractViolations"],
        f"ticker 계약 [0-9A-Z]{{6}} (위반 {len(bad_tk)}종목)")

    chk(dup_count == a["duplicateKeys"], f"(ticker,date) 중복 {dup_count}건")

    tickers_with_data = len(by_ticker)
    total_candidates = len(candidate_tickers)
    rate = tickers_with_data / max(total_candidates, 1)
    diag["candidateCount"] = total_candidates
    diag["tickersWithData"] = tickers_with_data
    diag["tickersWithDataRate"] = round(rate, 4)
    warn(rate >= a["minTickersWithDataWarn"],
         f"데이터 확보 종목 {tickers_with_data}/{total_candidates} "
         f"({rate*100:.1f}%) >= {a['minTickersWithDataWarn']*100:.0f}%")

    from_d = pol["collectFrom"]
    to_d = cal["tradingDays"][-1]
    expected_days = sum(1 for d in cal["tradingDays"] if from_d <= d <= to_d)
    total_expected = expected_days * max(tickers_with_data, 1)
    missing_rate = 1 - (row_count / total_expected) if total_expected else 1
    diag["expectedDaysPerTicker"] = expected_days
    diag["missingRate"] = round(missing_rate, 5)
    warn(missing_rate <= a["missingRateWarn"],
         f"누락률 {missing_rate*100:.2f}% <= {a['missingRateWarn']*100:.0f}% "
         f"(신규상장 등으로 상장 전 구간이 항상 '누락'으로 잡히는 단순 계산)")

    unresolved_rate = diag.get("unresolvedCount", 0) / max(total_candidates, 1)
    diag["unresolvedRate"] = round(unresolved_rate, 4)
    warn(unresolved_rate <= a["unresolvedRateWarn"],
         f"UNRESOLVED 비율 {unresolved_rate*100:.2f}% <= {a['unresolvedRateWarn']*100:.0f}% "
         f"({diag.get('unresolvedCount', 0)}/{total_candidates})")

    return sorted(year_writers.keys())


# ── finalize ───────────────────────────────────────────────────
def run_finalize(pol):
    out_dir = pol["output"]["dir"]
    shard_dir = pol["output"]["shardDir"]
    diag_path = f"{out_dir}/_diagnostics.json"
    diag = {"stage": "A8", "mode": "finalize", "shortSellingPolicy": pol["version"],
            "environment": _environment()}

    shard_files = sorted(glob.glob(f"{shard_dir}/shard-*.jsonl"))
    if not shard_files:
        _abort(f"{shard_dir}에 샤드 산출물이 없다 — 수집 잡을 먼저 돌려라", diag, diag_path)
    diag["shardFiles"] = [os.path.basename(p) for p in shard_files]
    diag["shardCount"] = len(shard_files)
    print(f"[1/3] 샤드 {len(shard_files)}개 발견 — 스트리밍 검증·라우팅 시작")

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

    scratch_dir = f"{shard_dir}/_year_scratch"
    for old in glob.glob(f"{scratch_dir}/*.jsonl"):
        os.remove(old)
    years_found = stream_validate_and_route(shard_files, cand, cal, pol, diag, scratch_dir)
    if diag["rowCount"] == 0:
        _abort("병합 결과 0행", diag, diag_path)
    diag["rowCountAfterValidation"] = diag["rowCount"]
    print(f"[2/3] 구간 — 캘린더 {diag['calendarStart']}~{diag['calendarEnd']} / "
          f"실측 {diag['actualDataFrom']}~{diag['actualDataTo']} · "
          f"빈 응답 {empty_n} · 예외/UNRESOLVED {exc_n} · 총 {diag['rowCount']}행")

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
        for f2 in glob.glob(f"{scratch_dir}/*.jsonl"):
            os.remove(f2)
        return 1

    print("\n[3/3] 연도별 정렬 · gzip")
    for old in glob.glob(f"{out_dir}/*.jsonl.gz"):
        os.remove(old)

    import gzip
    years = {}
    total_rows = 0
    for y in years_found:
        year_rows = load_jsonl(f"{scratch_dir}/{y}.jsonl")
        year_rows.sort(key=lambda x: (x["date"], x["ticker"]))
        path = f"{out_dir}/{y}.jsonl.gz"
        raw = "\n".join(
            json.dumps(x, ensure_ascii=False, sort_keys=True) for x in year_rows
        ).encode("utf-8") + b"\n"
        with open(path, "wb") as f:
            with gzip.GzipFile(fileobj=f, mode="wb", mtime=pol["output"]["gzipMtime"]) as gz:
                gz.compresslevel = pol["output"]["gzipCompressLevel"]
                gz.write(raw)
        gz_bytes = os.path.getsize(path)
        years[y] = {"rows": len(year_rows), "rawBytes": len(raw), "gzBytes": gz_bytes}
        total_rows += len(year_rows)
        print(f"  {y}.jsonl.gz  {len(year_rows):>9}행  "
              f"{len(raw)/1e6:6.1f}MB → {gz_bytes/1e6:5.1f}MB")
        os.remove(f"{scratch_dir}/{y}.jsonl")

    diag["years"] = years
    diag["totalGzBytes"] = sum(v["gzBytes"] for v in years.values())

    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{out_dir} — 연도 {len(years)}개 · {total_rows}행 · "
          f"{diag['totalGzBytes']/1e6:.1f}MB")
    return 0


# ── self-test (네트워크 없이) ─────────────────────────────────────
def _selftest() -> int:
    import pandas as pd

    ok = True

    def check(cond, label):
        nonlocal ok
        print(("  OK  " if cond else "  FAIL") + "  " + label)
        ok = ok and cond

    idx = pd.to_datetime(["2026-08-13", "2026-08-14"])
    df = pd.DataFrame(
        [[1159290, 6932423, 316732482250, 1861355575500],
         [1688352, 7387185, 421892486750, 1828328287500]],
        index=idx, columns=["거래량", "잔고수량", "거래대금", "잔고금액"],
    )

    records, kind, err = records_from_df("005930", df)
    check(kind == "ok" and err is None, "records_from_df: 정상 변환")
    check(records is not None and len(records) == 2, "records_from_df: 2행 생성")
    if records:
        r0 = records[0]
        check(r0["ticker"] == "005930" and r0["date"] == "2026-08-13",
              "records_from_df: ticker/date")
        check(r0["shortVolume"] == 1159290 and r0["shortBalanceShares"] == 6932423
              and r0["shortValue"] == 316732482250 and r0["shortBalanceValue"] == 1861355575500,
              "records_from_df: 값·필드명 매핑(정찰 실측값 재현)")

    # 컬럼 누락 → exception
    bad_df = pd.DataFrame([[1, 2]], index=idx[:1], columns=["거래량", "잔고수량"])
    _, kind2, err2 = records_from_df("005930", bad_df)
    check(kind2 == "exception" and err2, "records_from_df: 컬럼 누락 → exception")

    # 빈 응답 → empty
    empty_df = pd.DataFrame(columns=["거래량", "잔고수량", "거래대금", "잔고금액"])
    _, kind3, _ = records_from_df("000000", empty_df)
    check(kind3 == "empty", "records_from_df: 빈 응답 → empty")

    print("\n" + ("전체 통과" if ok else "실패 있음"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int)
    ap.add_argument("--shards", type=int)
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="스모크 테스트용. 진단에 smokeTest 플래그가 박힌다")
    ap.add_argument("--anchor", type=str, default="",
                    help="이 날짜(YYYY-MM-DD) 하나로 정찰종목 응답 유무만 확인하고 종료")
    ap.add_argument("--selftest", action="store_true",
                    help="네트워크 없이 records_from_df 로직만 검증한다")
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

    if args.anchor:
        return run_anchor_check(pol, args.anchor)
    if args.finalize:
        return run_finalize(pol)
    if args.shard is None:
        print("--shard N --shards M 또는 --finalize 또는 --anchor 중 하나가 필요하다")
        return 1
    shards = args.shards or pol["shards"]
    if not (0 <= args.shard < shards):
        print(f"--shard는 0 이상 {shards} 미만이어야 한다")
        return 1
    return run_shard(args.shard, shards, pol, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
