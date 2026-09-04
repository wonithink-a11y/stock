#!/usr/bin/env python3
"""A4 — 종목별 일별 수급(외국인·기관·개인 매수/매도) 원자료

A1a(현재 상장 유니버스)의 종목별 일별 매수/매도 금액·수량을 KRX(pykrx)에서 받아
연도별로 저장한다. 정의는 config/policies/supplyDemand.v1.json(SD-1.1)이다.

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
    KRX_ID/KRX_PW가 설정된 경우). 그 로그인 응답이 가끔 빈 본문으로 온다.

    실측(2026-08-17): 16샤드 동시 시작 1차 시도는 전부 즉시 실패했다. 몇 분 뒤
    재실행(동시 시작)은 16개 전부 성공했다. 짧은 재시도(10~30초 간격, 4회)를
    추가한 다음 실행은 16개가 거의 같은 순간에 재시도를 반복하며 전부 실패했다
    — 순간 부하가 몰리면 KRX 쪽이 수 분 단위로 막히는 것으로 보인다. 그래서
    (1) 워크플로가 샤드 시작을 20초씩 벌리고 (2) 여기 백오프도 늘려서, 재시도가
    또 다른 동시 부하가 되지 않게 한다."""
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


def run_shard(shard, shards, pol, limit, start=None):
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
    # ★ SD-1.1 — start가 있으면 증분 수집(마지막 수집일 다음날부터만). 없으면
    # 정책의 collectFrom(전체, 최초 백필과 동일 동작) - run_finalize()의 연도별
    # 병합이 두 경우 다 안전하다(기존 파일과 키 단위로 합친다).
    frm = (start or sd["collectFrom"]).replace("-", "")
    diag["collectFrom"] = start or sd["collectFrom"]
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


# ── 검증 (스트리밍) ────────────────────────────────────────────
# 전량(약 2,578종목 x 10.6년 ≈ 585만 행, 중첩 딕셔너리)을 한 번에 메모리에
# 올리면 GitHub Actions 러너가 OOM으로 죽는다(실측 2026-08-17, "runner has
# received a shutdown signal" — finalize가 [1/3] 로그도 못 찍고 죽었다).
# 그래서 검증과 연도 라우팅을 같은 스트리밍 패스에서 한다 — 레코드를 다 읽고
# 버리지, 리스트에 쌓지 않는다. 전역 검사(중복 키 등)는 가벼운 집합/카운터로만
# 유지한다. 연도별 정렬은 2단계(연도별 스크래치 파일 → 그 파일만 로드해 정렬 후
# gzip)로 미룬다 — 한 해치(약 53만 행)는 메모리에 올려도 안전하다.
def stream_validate_and_route(shard_files, cand, cal, pol, diag, scratch_dir):
    a = pol["acceptance"]
    cal_days = cal["tradingDays"]
    cal_idx = {d: i for i, d in enumerate(cal_days)}
    candidate_tickers = {x["ticker"] for x in cand}

    print("\n[인수 조건 — 스트리밍 1단계: 검증 + 연도 라우팅]")

    inject = os.environ.get("A4_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    os.makedirs(scratch_dir, exist_ok=True)
    year_writers = {}

    seen_keys = set()
    dup_count = 0
    date_viol = 0
    bad_tk = set()
    key_mismatch = 0
    clearing_viol = 0
    clearing_sample = []
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

                keysets = {frozenset(x[f2].keys())
                           for f2 in ("buyAmount", "sellAmount", "buyVolume", "sellVolume")}
                if len(keysets) > 1:
                    key_mismatch += 1

                buy_a, sell_a = x["buyAmount"], x["sellAmount"]
                buy_v, sell_v = x["buyVolume"], x["sellVolume"]
                cats = [k for k in buy_a if k != "전체"]
                diff_a = sum(buy_a.get(k, 0) - sell_a.get(k, 0) for k in cats)
                diff_v = sum(buy_v.get(k, 0) - sell_v.get(k, 0) for k in cats)
                if diff_a != 0 or diff_v != 0:
                    clearing_viol += 1
                    if len(clearing_sample) < 10:
                        clearing_sample.append({"ticker": tk, "date": d,
                                                "diffAmount": diff_a, "diffVolume": diff_v})

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

    diag["categoryKeySetViolations"] = key_mismatch
    chk(key_mismatch == a["categoryKeySetViolations"],
        f"카테고리 키 집합 불일치 {key_mismatch}행")

    diag["marketClearingViolations"] = clearing_viol
    diag["marketClearingViolationSample"] = clearing_sample
    chk(clearing_viol == a["marketClearingViolations"],
        f"시장 청산 조건(카테고리 합 매수-매도=0) 위반 {clearing_viol}행")

    tickers_with_data = len(by_ticker)
    total_candidates = len(candidate_tickers)
    rate = tickers_with_data / max(total_candidates, 1)
    diag["candidateCount"] = total_candidates
    diag["tickersWithData"] = tickers_with_data
    diag["tickersWithDataRate"] = round(rate, 4)
    warn(rate >= a["minTickersWithDataWarn"],
         f"데이터 확보 종목 {tickers_with_data}/{total_candidates} "
         f"({rate*100:.1f}%) >= {a['minTickersWithDataWarn']*100:.0f}%")

    # ★ SD-1.1 — 증분 실행이면 이번 실행이 실제로 요청한 구간(diag의
    # shardCollectFrom, run_finalize가 샤드 진단에서 미리 모아둠)을 분모로
    # 쓴다. pol["collectFrom"](정책의 전체 시작일 2016-01-04)을 그대로 쓰면
    # 3주치만 수집한 증분 실행이 "10년 중 3주만 있다 = 거의 100% 누락"으로
    # 오탐한다.
    shard_from = (diag.get("shardCollectFrom") or [None])[0]
    from_d = shard_from or pol["collectFrom"]
    to_d = cal_days[-1]
    expected_days = sum(1 for d in cal_days if from_d <= d <= to_d)
    total_expected = expected_days * max(tickers_with_data, 1)
    missing_rate = 1 - (row_count / total_expected) if total_expected else 1
    diag["expectedDaysPerTicker"] = expected_days
    diag["missingRateFrom"] = from_d
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

    return sorted(year_writers.keys())


def merge_year_rows(existing_rows, new_rows):
    """기존 연도 파일 행 + 새로 수집한 행을 (ticker,date) 키로 병합한다.
    겹치면 new_rows(방금 수집)가 이긴다 - 재수집이 더 최신 값일 수 있다는
    전제(예: 정정 공시로 뒤늦게 바뀐 수급). 순수 함수라 네트워크 없이
    테스트 가능하다(이 파일 하단 self-test 참고). 정렬은 output.sortKey와
    동일하게 (date, ticker)."""
    by_key = {(r["ticker"], r["date"]): r for r in existing_rows}
    for r in new_rows:
        by_key[(r["ticker"], r["date"])] = r
    return sorted(by_key.values(), key=lambda x: (x["date"], x["ticker"]))


def merge_and_write_year(out_dir, year, new_rows, output_pol):
    """out_dir/{year}.jsonl.gz가 있으면 읽어 new_rows와 병합해서 다시 쓰고,
    없으면(신규 연도) new_rows만 쓴다. out_dir의 다른 연도 파일은 절대 열지도
    지우지도 않는다 - 이 함수가 손대는 건 정확히 이 한 파일뿐이다(증분
    수집의 안전성이 전부 이 경계에 달려있다). 네트워크 없이 tempdir로
    테스트 가능하다(이 파일 하단 self-test 참고)."""
    import gzip
    path = f"{out_dir}/{year}.jsonl.gz"
    existing_rows = []
    if os.path.exists(path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            existing_rows = [json.loads(line) for line in f if line.strip()]
    year_rows = merge_year_rows(existing_rows, new_rows)
    raw = "\n".join(
        json.dumps(x, ensure_ascii=False, sort_keys=True) for x in year_rows
    ).encode("utf-8") + b"\n"
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "wb") as f:
        with gzip.GzipFile(fileobj=f, mode="wb", mtime=output_pol["gzipMtime"]) as gz:
            gz.compresslevel = output_pol["gzipCompressLevel"]
            gz.write(raw)
    gz_bytes = os.path.getsize(path)
    return {"rows": len(year_rows), "newRows": len(new_rows),
            "existingRowsBeforeMerge": len(existing_rows),
            "rawBytes": len(raw), "gzBytes": gz_bytes}


# ── finalize ───────────────────────────────────────────────────
def run_finalize(pol):
    out_dir = pol["output"]["dir"]
    shard_dir = pol["output"]["shardDir"]
    diag_path = f"{out_dir}/_diagnostics.json"
    diag = {"stage": "A4", "mode": "finalize", "supplyDemandPolicy": pol["version"],
            "environment": _environment()}
    # ★ SD-1.1 — 증분 실행에서는 actualDataFrom이 이번 구간의 시작일로만 잡혀
    # 전체 데이터셋의 실제 시작일(2016년대)을 잃어버린다. 덮어쓰기 전에 이전
    # diagnostics의 actualDataFrom을 미리 읽어 더 이른 쪽을 남긴다.
    prev_actual_from = None
    if os.path.exists(diag_path):
        prev_actual_from = load_json(diag_path).get("actualDataFrom")

    shard_files = sorted(glob.glob(f"{shard_dir}/shard-*.jsonl"))
    if not shard_files:
        _abort(f"{shard_dir}에 샤드 산출물이 없다 — 수집 잡을 먼저 돌려라", diag, diag_path)
    diag["shardFiles"] = [os.path.basename(p) for p in shard_files]
    diag["shardCount"] = len(shard_files)
    print(f"[1/3] 샤드 {len(shard_files)}개 발견 — 스트리밍 검증·라우팅 시작")

    empty_n = exc_n = unresolved_n = 0
    unresolved_all = []
    shard_collect_from = set()
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
        shard_collect_from.add(sd_diag.get("collectFrom"))
    diag["emptyCount"] = empty_n
    diag["exceptionCount"] = exc_n
    diag["unresolvedCount"] = unresolved_n
    # ★ SD-1.1 — 이번 실행이 증분(start override)인지 전량(정책 collectFrom
    # 그대로)인지 manifest에서 바로 알 수 있게 남긴다. 샤드마다 다른 값이면
    # (워크플로 버그로) 섞여 들어온 것이라 그대로 기록해 드러낸다.
    diag["shardCollectFrom"] = sorted(x for x in shard_collect_from if x)
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
    # validate()는 이 버전에서도 행을 걸러내지 않는다(A2b와 달리 품질 제외가 없다) —
    # 위반이 있으면 FAIL로 전체를 막을 뿐, 통과 시엔 전량을 그대로 쓴다.
    diag["rowCountAfterValidation"] = diag["rowCount"]
    diag["actualDataFromThisRun"] = diag["actualDataFrom"]
    if prev_actual_from and prev_actual_from < diag["actualDataFrom"]:
        diag["actualDataFrom"] = prev_actual_from
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

    print("\n[3/3] 연도별 병합 · 정렬 · gzip (스크래치 파일 하나씩만 메모리에 올린다)")
    # ★ SD-1.1 — years_found에 없는 연도의 기존 파일은 절대 건드리지 않는다.
    # 옛 방식(out_dir의 *.jsonl.gz를 전량 삭제 후 이번 샤드 데이터로만 재생성)은
    # 증분 수집(예: 최근 3주치만) 시 그 3주가 속한 연도 말고는 shard 데이터가
    # 없으므로 나머지 9년치가 전부 사라진다 — 증분을 붙이기 전에 발견해서 고쳤다.
    # years_found에 있는 연도만 merge_and_write_year()로 기존+신규를 병합한다
    # (전량 재수집일 때도 새 값이 겹치는 키를 그대로 덮어써서 결과가 동일하다).
    years = {}
    total_rows = 0
    for y in years_found:
        new_rows = load_jsonl(f"{scratch_dir}/{y}.jsonl")
        years[y] = merge_and_write_year(out_dir, y, new_rows, pol["output"])
        total_rows += years[y]["rows"]
        print(f"  {y}.jsonl.gz  기존 {years[y]['existingRowsBeforeMerge']:>9}행 + "
              f"신규 {years[y]['newRows']:>7}행 → 병합 {years[y]['rows']:>9}행  "
              f"{years[y]['rawBytes']/1e6:6.1f}MB → {years[y]['gzBytes']/1e6:5.1f}MB")
        os.remove(f"{scratch_dir}/{y}.jsonl")

    diag["years"] = years
    diag["totalGzBytes"] = sum(v["gzBytes"] for v in years.values())
    # 이번에 안 건드린 연도까지 포함한 전체 데이터셋 현황(디컴프레션 없이 파일
    # 크기만) - 증분 실행에서 "누적 전체가 지금 몇 개 연도·몇 바이트인가"를 알 수
    # 있게 한다.
    all_gz = sorted(glob.glob(f"{out_dir}/*.jsonl.gz"))
    diag["yearsInDataset"] = [os.path.basename(p)[:4] for p in all_gz]
    diag["totalGzBytesAllYears"] = sum(os.path.getsize(p) for p in all_gz)

    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{out_dir} — 연도 {len(years)}개 · {total_rows}행 · "
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

    # merge_year_rows: 증분 병합 로직 (SD-1.1)
    existing = [
        {"ticker": "005930", "date": "2026-08-01", "buyAmount": {"전체": 1}},
        {"ticker": "005930", "date": "2026-08-14", "buyAmount": {"전체": 2}},
        {"ticker": "000660", "date": "2026-08-14", "buyAmount": {"전체": 3}},
    ]
    new = [
        {"ticker": "005930", "date": "2026-08-14", "buyAmount": {"전체": 99}},  # 겹침 - 새 값이 이겨야 함
        {"ticker": "005930", "date": "2026-08-15", "buyAmount": {"전체": 4}},
    ]
    merged = merge_year_rows(existing, new)
    check(len(merged) == 4, "merge_year_rows: 겹치는 키는 하나로 합쳐진다(3+2-1=4)")
    check([r["date"] for r in merged] == sorted(r["date"] for r in merged),
          "merge_year_rows: date 오름차순 정렬")
    dup = next(r for r in merged if r["ticker"] == "005930" and r["date"] == "2026-08-14")
    check(dup["buyAmount"]["전체"] == 99, "merge_year_rows: 겹치는 키는 새 값(new_rows)이 이긴다")
    unchanged = next(r for r in merged if r["ticker"] == "000660")
    check(unchanged["buyAmount"]["전체"] == 3, "merge_year_rows: 안 겹치는 기존 행은 그대로 보존")
    check(merge_year_rows([], []) == [], "merge_year_rows: 둘 다 빈 입력이면 빈 출력")
    check(merge_year_rows(existing, []) == sorted(existing, key=lambda x: (x["date"], x["ticker"])),
          "merge_year_rows: 신규 없이 기존만 있으면 기존을 정렬만 해서 돌려준다(최초 백필 재실행과 동일 안전성)")

    # merge_and_write_year: 실제 파일 I/O(tempdir) - 다른 연도 파일을 안 건드리는지까지 검증
    import gzip
    import tempfile
    output_pol = {"gzipMtime": 0, "gzipCompressLevel": 6}
    with tempfile.TemporaryDirectory() as tmp:
        untouched_path = f"{tmp}/2020.jsonl.gz"
        untouched_rows = [{"ticker": "005930", "date": "2020-01-02", "buyAmount": {"전체": 7}}]
        with open(untouched_path, "wb") as f:
            with gzip.GzipFile(fileobj=f, mode="wb", mtime=0) as gz:
                gz.write(("\n".join(json.dumps(r, sort_keys=True) for r in untouched_rows) + "\n").encode())

        r1 = merge_and_write_year(tmp, "2026", existing, output_pol)
        check(r1["existingRowsBeforeMerge"] == 0, "merge_and_write_year: 신규 연도는 기존 0행에서 시작")
        check(r1["rows"] == len(existing), "merge_and_write_year: 첫 실행은 새로 받은 행 수 그대로")

        r2 = merge_and_write_year(tmp, "2026", new, output_pol)
        check(r2["existingRowsBeforeMerge"] == len(existing), "merge_and_write_year: 두 번째 실행은 첫 실행 결과를 읽어온다")
        check(r2["rows"] == 4, "merge_and_write_year: 재실행 결과도 겹치는 키가 하나로 합쳐진다")

        with gzip.open(untouched_path, "rt", encoding="utf-8") as f:
            still_there = [json.loads(line) for line in f if line.strip()]
        check(still_there == untouched_rows,
              "merge_and_write_year: 안 건드린 연도(2020) 파일은 바이트 단위로 그대로 남는다")

    print("\n" + ("전체 통과" if ok else "실패 있음"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int)
    ap.add_argument("--shards", type=int)
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="스모크 테스트용. 진단에 smokeTest 플래그가 박힌다")
    ap.add_argument("--start", type=str, default=None,
                    help="YYYY-MM-DD. 이 날짜부터만 수집한다(증분) - 비우면 정책의 "
                         "collectFrom(전체, 최초 백필과 동일)")
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
    return run_shard(args.shard, shards, pol, args.limit, args.start)


if __name__ == "__main__":
    raise SystemExit(main())
