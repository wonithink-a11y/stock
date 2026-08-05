#!/usr/bin/env python3
"""A2a — 현재 상장분 일봉 가격 (BF-1.1)

A1a가 확정한 2,579종목의 수정주가 일봉을 KRX에서 받아 연도별로 나눠 저장한다.
정의는 config/policies/price.v1.json(PR-1.0)이 단일 산출점이다.

두 모드로 돈다. 실행 축(샤드)과 저장 축(연도)을 분리하기 위해서다 —
샤드 수를 바꿔도 산출물 바이트가 바뀌지 않으므로 manifest 해시가 불변이고,
하류 재실행이 강제되지 않는다.

  --shard N --shards M   종목 부분집합 수집 → _shards/shard-N.jsonl (중간 산출, 커밋 안 함)
  --finalize             전 샤드 병합 → 정렬 → 연도 분할 → gzip → 인수 조건 → 산출

입력:
  config/policies/price.v1.json
  data/backfill/universe/a1a/current.jsonl   대상 종목 (A1a)
  data/backfill/calendar.json                기대 거래일 (A0.5)
출력:
  data/backfill/price/a2a/{YYYY}.jsonl.gz
  data/backfill/price/a2a/_diagnostics.json

KRX 개별종목 일봉은 '오늘 기준 약 3,000거래일' 롤링 윈도우다. 캘린더 시작일보다
실제 확보 시작일이 뒤일 수 있고 매일 밀린다. 그래서 actualDataFrom을 실행 시점에
측정해 남기고 누락률은 그 기준으로 잰다 — calendarStart 기준으로 재면 시작 구간이
영원히 누락으로 잡힌다.
"""
import argparse
import glob
import gzip
import io
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

POLICY = "config/policies/price.v1.json"
UNIVERSE = "data/backfill/universe/a1a/current.jsonl"
CALENDAR = "data/backfill/calendar.json"
OUT_DIR = "data/backfill/price/a2a"
SHARD_DIR = "data/backfill/price/_shards"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FIELDS = ["ticker", "date", "open", "high", "low", "close", "volume"]

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
    """실패해도 진단은 남긴다(교훈39). 중단 경로도 산출이다."""
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
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def environment(pol):
    """실제 실행 버전을 남긴다. 정책은 '요구 버전', 여기는 '실행 버전' —
    같은 정책인데 결과가 달라진 이유는 이 둘의 차이에서만 나온다."""
    try:
        from importlib.metadata import version
        pykrx_ver = version("pykrx")
    except Exception:  # noqa: BLE001
        pykrx_ver = "unknown"
    return {
        "pykrx": pykrx_ver,
        "pykrxRequired": pol["source"]["requiredVersion"],
        "python": sys.version.split()[0],
    }


# ── 수집 ───────────────────────────────────────────────────────
def fetch_one(stock, ticker, frm, to, pol):
    """빈 결과도 실패로 본다(교훈38). pykrx는 예외 대신 빈 DataFrame을 돌려주는
    경로가 있어, 그것을 성공으로 기록하면 구간이 조용히 누락된다."""
    last = None
    for i in range(pol["retryAttempts"]):
        try:
            df = stock.get_market_ohlcv_by_date(
                frm, to, ticker, adjusted=pol["source"]["adjusted"])
            if df is not None and not df.empty:
                return df, None
            last = "빈 응답"
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        if i < pol["retryAttempts"] - 1:
            time.sleep(pol["retryBackoffBase"] ** i)
    return None, last


def to_records(ticker, df):
    out = []
    for idx, r in df.iterrows():
        out.append({
            "ticker": ticker,
            "date": idx.strftime("%Y-%m-%d"),
            "open": int(r["시가"]),
            "high": int(r["고가"]),
            "low": int(r["저가"]),
            "close": int(r["종가"]),
            "volume": int(r["거래량"]),
        })
    return out


def run_shard(shard, shards, pol, limit):
    from pykrx import stock

    diag_path = f"{SHARD_DIR}/_diagnostics-shard-{shard}.json"
    diag = {"stage": "A2a", "mode": "shard", "shard": shard, "shards": shards,
            "pricePolicy": pol["version"], "environment": environment(pol)}
    if limit:
        # 스모크 테스트는 산출물을 만들 수 있지만, verify-diagnostics가 이 플래그를
        # 보고 거부한다. 통과를 만드는 우회로가 되지 않는 한 방향 훅이다.
        diag["smokeTest"] = True

    uni = load_jsonl(UNIVERSE)
    cal = load_json(CALENDAR)
    days = cal["tradingDays"]
    frm = pol["collectFrom"].replace("-", "")
    to = days[-1].replace("-", "")

    tickers = sorted(x["ticker"] for x in uni)
    # 라운드로빈 분배 — 연속 구간으로 자르면 신규상장이 뒤쪽 샤드에 몰려
    # 샤드별 소요가 크게 갈린다.
    mine = [t for i, t in enumerate(tickers) if i % shards == shard]
    if limit:
        mine = mine[:limit]
    print(f"A2a 샤드 {shard}/{shards} — {len(mine)}종목 · 구간 {frm}~{to} · "
          f"pykrx {diag['environment']['pykrx']}")

    # 정찰 2회(교훈32) — 경로가 막혔으면 2,579회를 돌리지 않고 즉시 중단한다
    probes = []
    for pt in pol["probeTickers"]:
        df, err = fetch_one(stock, pt, to, to, pol)
        probes.append({"ticker": pt, "ok": df is not None, "error": err})
    diag["probes"] = probes
    if not any(p["ok"] for p in probes):
        _abort("정찰 전건 실패 — 수집 경로가 막혔다", diag, diag_path)
    print(f"  정찰 {sum(1 for p in probes if p['ok'])}/{len(probes)} 통과")

    rows, failed, empty, consec = [], [], [], 0
    t0 = time.time()
    for i, tk in enumerate(mine, 1):
        df, err = fetch_one(stock, tk, frm, to, pol)
        if df is None:
            # 빈 응답과 조회 실패를 여기서 가르지 않는다. 상장일이 창구 밖인 정상
            # 공백일 수 있어, 판정은 finalize가 기대 거래일과 대조해서 한다.
            empty.append({"ticker": tk, "reason": err})
            consec += 1
            if consec >= pol["circuitBreakerConsecutiveFailures"]:
                diag.update(rowCount=len(rows), emptyTickers=empty)
                _abort(f"연속 실패 {consec}건 — 루프 도중 경로가 막혔다", diag, diag_path)
        else:
            rows.extend(to_records(tk, df))
            consec = 0
        if i % 200 == 0:
            print(f"  {i}/{len(mine)} · {len(rows)}행 · {time.time()-t0:.0f}s")
        time.sleep(pol["requestSleepSeconds"])

    diag.update(tickerCount=len(mine), rowCount=len(rows),
                emptyTickers=empty, elapsedSeconds=round(time.time() - t0, 1))

    os.makedirs(SHARD_DIR, exist_ok=True)
    with open(f"{SHARD_DIR}/shard-{shard}.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{SHARD_DIR}/shard-{shard}.jsonl — {len(rows)}행 "
          f"({len(mine)}종목 중 무응답 {len(empty)}건, {diag['elapsedSeconds']}s)")
    return 0


# ── finalize ───────────────────────────────────────────────────
def write_gz(path, records, pol):
    """gzip mtime을 0으로 고정한다. 기본값(현재 시각)이면 내용이 같아도 매 실행
    바이트가 달라져 manifest 해시가 '재수집 여부 판정' 기능을 잃는다."""
    o = pol["output"]
    buf = io.BytesIO()
    for x in records:
        buf.write((json.dumps(x, ensure_ascii=False) + "\n").encode("utf-8"))
    raw = buf.getvalue()
    with open(path, "wb") as fh:
        gz = gzip.GzipFile(filename="", mode="wb", fileobj=fh,
                           compresslevel=o["gzipCompressLevel"], mtime=o["gzipMtime"])
        gz.write(raw)
        gz.close()
    return len(raw), os.path.getsize(path)


def write_year_gz(year, rows, pol):
    return write_gz(f"{OUT_DIR}/{year}.jsonl.gz",
                    [{k: x[k] for k in FIELDS} for x in rows], pol)


def find_violations(by_ticker, cal_idx, pol, diag):
    """±50% 위반을 '비교 가능한 쌍'에서만 찾는다.

    비교 가능 = 양쪽 다 체결이 있었고(volume>0) 캘린더상 인접 거래일이다.
    거래량 0인 행의 종가는 체결가가 아니라 거래정지 중 기준가 표기이므로, 그것을
    실제 체결가와 비교하는 것은 품질 검사가 아니라 서로 다른 의미의 값을 비교하는 것이다.
    임계는 그대로 두고 비교 대상만 정정한다 — 완화가 아니다.
    """
    dc = pol["dailyChange"]
    limit = pol["acceptance"]["dailyChangeAbsMax"]
    zero_vol = susp_gap = comparable = 0
    viol = defaultdict(list)

    for tk, xs in by_ticker.items():
        for i in range(1, len(xs)):
            a_, b_ = xs[i - 1], xs[i]
            if dc["requireBothVolumePositive"] and (a_["volume"] == 0 or b_["volume"] == 0):
                zero_vol += 1
                continue
            ia, ib = cal_idx.get(a_["date"]), cal_idx.get(b_["date"])
            if dc["requireAdjacentTradingDay"] and (ia is None or ib is None or ib - ia != 1):
                susp_gap += 1
                continue
            comparable += 1
            if a_["close"] > 0 and abs(b_["close"] / a_["close"] - 1) > limit:
                # 3거래일 안에 직전 수준으로 돌아오면 1일 오표기, 머물면 수정주가 미적용.
                base = a_["close"]
                fwd = [xs[j]["close"] for j in range(i + 1, min(i + 1 + dc["transientReturnDays"], len(xs)))]
                transient = any(abs(c / base - 1) < dc["transientReturnTolerance"] for c in fwd)
                viol[tk].append({
                    "date": b_["date"], "prevDate": a_["date"],
                    "prevClose": base, "close": b_["close"],
                    "change": round(b_["close"] / base - 1, 4),
                    "kind": "TRANSIENT_PRICE_SPIKE" if transient else "UNADJUSTED_CORPORATE_ACTION",
                })

    # 카운터를 diag에 직접 쓰지 않는다 — 이 함수는 잔여 위반 확인을 위해 제외 후
    # 부분집합으로 한 번 더 호출되고, 그때 전체 기준 관측치가 조용히 덮이기 때문이다.
    # 무엇을 기록할지는 호출부가 정한다.
    return viol, {"zeroVolumeTransitions": zero_vol,
                  "suspendedGapTransitions": susp_gap,
                  "comparableTransitions": comparable}


def build_exclusions(viol, uni_by_ticker, by_ticker):
    """종목 단위로 제외한다. 어느 행이 틀렸는지 단정하는 것은 추정이므로
    행 단위로 도려내지 않는다 — '모르면 제외하고 추정하지 않는다'."""
    out = []
    for tk, vs in sorted(viol.items()):
        kinds = {v["kind"] for v in vs}
        # 한 종목에 둘 다 있으면 더 무거운 쪽(수정주가 미적용)을 사유로 남긴다.
        reason = ("UNADJUSTED_CORPORATE_ACTION"
                  if "UNADJUSTED_CORPORATE_ACTION" in kinds else "TRANSIENT_PRICE_SPIKE")
        u = uni_by_ticker.get(tk, {})
        out.append({
            "ticker": tk,
            "name": u.get("name"),
            "market": u.get("market"),
            "reason": reason,
            "violationCount": len(vs),
            "rowsDropped": len(by_ticker.get(tk, [])),
            "violations": vs[:20],
        })
    return out


def validate(rows, uni, cal, pol, diag):
    """반환값은 (남길 행, 품질 제외 목록)이다."""
    a = pol["acceptance"]
    print("\n[인수 조건]")

    inject = os.environ.get("A2A_FAIL_INJECTION", "").strip()
    if inject:
        diag["failInjection"] = inject
        chk(False, f"[FAIL INJECTION] {inject} — 게이트 검증용 강제 실패")

    # 날짜 계약 · 가격 불변식
    bad_date = [x for x in rows if not DATE_RE.match(x["date"] or "")]
    chk(len(bad_date) == a["dateContractViolations"], f"date 계약 YYYY-MM-DD (위반 {len(bad_date)}건)")
    nonpos = [x for x in rows if x["close"] <= 0]
    chk(len(nonpos) == a["closeNonPositive"], f"close > 0 (위반 {len(nonpos)}건)")
    hl = [x for x in rows if x["high"] < x["low"]]
    chk(len(hl) == a["highLowOrderViolations"], f"high >= low (위반 {len(hl)}건)")

    keys = {(x["ticker"], x["date"]) for x in rows}
    dup = len(rows) - len(keys)
    chk(dup == a["duplicateKeys"], f"(ticker,date) 중복 {dup}건")

    cal_days = cal["tradingDays"]
    cal_idx = {d: i for i, d in enumerate(cal_days)}
    # 캘린더 밖 날짜가 0이어야 기대 모델이 성립한다. PR-1.0에서 누락률이 음수로
    # 나왔을 때 이 값이 0임을 확인해 원인을 상류(A0.5)가 아니라 기대 모델로 좁혔다.
    off_cal = [x for x in rows if x["date"] not in cal_idx]
    diag["datesNotInCalendar"] = len(off_cal)
    diag["datesNotInCalendarSample"] = sorted({x["date"] for x in off_cal})[:20]
    chk(len(off_cal) == a["datesNotInCalendar"], f"캘린더 밖 날짜 {len(off_cal)}행")

    by_ticker = defaultdict(list)
    for x in rows:
        by_ticker[x["ticker"]].append(x)
    for xs in by_ticker.values():
        xs.sort(key=lambda x: x["date"])

    uni_by_ticker = {x["ticker"]: x for x in uni}

    # ── 품질 제외 ──────────────────────────────────────────────
    viol, stats = find_violations(by_ticker, cal_idx, pol, diag)
    # 전이 관측치는 '수집된 전체' 기준으로 남긴다. 제외 종목의 거래정지 이력도
    # 수집이 무엇을 만났는지를 말해주는 사실이다.
    diag.update(stats)
    excluded = build_exclusions(viol, uni_by_ticker, by_ticker)
    ex_set = {e["ticker"] for e in excluded}
    diag["qualityExcluded"] = excluded
    diag["qualityExcludedCount"] = len(excluded)
    diag["qualityExcludedByReason"] = dict(Counter(e["reason"] for e in excluded))

    ex_rate = len(ex_set) / max(len(by_ticker), 1)
    diag["qualityExcludedRate"] = round(ex_rate, 5)
    # 위반 종목을 자동 제외하기만 하면 게이트가 영원히 통과한다. 이 상한이 안전핀이다 —
    # 제외가 급증하면 종목 문제가 아니라 소스 문제다.
    chk(ex_rate <= a["qualityExcludedRateMax"],
        f"품질 제외율 {ex_rate*100:.2f}% <= {a['qualityExcludedRateMax']*100:.0f}% "
        f"({len(ex_set)}종목 / {len(by_ticker)}) {diag['qualityExcludedByReason']}")

    kept = {tk: xs for tk, xs in by_ticker.items() if tk not in ex_set}
    residual, kept_stats = find_violations(kept, cal_idx, pol, diag)
    # 산출물(제외 후)에 남는 전이 규모 — A5가 returnTransition으로 실제 걷어낼 양이다.
    diag["keptZeroVolumeTransitions"] = kept_stats["zeroVolumeTransitions"]
    diag["keptComparableTransitions"] = kept_stats["comparableTransitions"]
    chk(len(residual) == a["residualDailyChangeViolations"],
        f"제외 후 잔여 ±{a['dailyChangeAbsMax']*100:.0f}% 위반 {len(residual)}종목")

    chk(len(kept) >= a["minTickersWithData"],
        f"데이터 확보 종목 {len(kept)} >= {a['minTickersWithData']} "
        f"(유니버스 {len(uni)} − 품질 제외 {len(ex_set)})")

    # ── 기대 모델 — 기준은 listedAt이 아니라 실제 최초 거래일 ──────
    # listedAt은 '현재 시장의 상장일'이지 최초 상장일이 아니다. 이전상장 종목은
    # 상장일보다 10년 앞선 가격이 정상적으로 존재한다(실측 86종목).
    first_traded = {tk: xs[0]["date"] for tk, xs in by_ticker.items()}
    before_listed = sum(1 for tk, xs in by_ticker.items() for x in xs
                        if (uni_by_ticker.get(tk, {}).get("listedAt") or "") > x["date"])
    diag["rowsBeforeListedAt"] = before_listed
    diag["tickersWithRowsBeforeListedAt"] = sum(
        1 for tk, xs in by_ticker.items()
        if (uni_by_ticker.get(tk, {}).get("listedAt") or "") > xs[0]["date"])

    fetch_fail = [tk for tk in uni_by_ticker if tk not in by_ticker]
    diag["fetchFailedTickers"] = fetch_fail[:200]
    chk(len(fetch_fail) == a["tickerFetchFail"], f"데이터 0행인 종목 {len(fetch_fail)}건")
    warn(len(fetch_fail) / max(len(uni_by_ticker), 1) < a["emptyTickerRateWarn"],
         f"정상 공백 후보 {len(fetch_fail)}건")

    expected = {tk: sum(1 for d in cal_days if d >= first_traded[tk]) for tk in kept}
    total_exp = sum(expected.values())
    total_got = sum(len(v) for v in kept.values())
    rate = 1 - (total_got / total_exp) if total_exp else 1
    diag["expectedRows"] = total_exp
    diag["missingRate"] = round(rate, 5)
    # PR-1.3에서 WARN → FAIL 승격. 임계 0.01은 그대로이고 등급만 올렸다 —
    # 첫 수집 실측 0.056%로 18배 여유가 확인됐다. 이 값이 튀면 수집 실패다.
    chk(rate <= a["missingRateMax"],
        f"거래일 누락률 {rate*100:.3f}% <= {a['missingRateMax']*100:.0f}% "
        f"(기대 {total_exp} / 실측 {total_got}) — 종목별 실제 최초 거래일 기준")

    worst = sorted(
        ({"ticker": tk, "firstTraded": first_traded[tk], "expected": expected[tk],
          "got": len(kept[tk]), "missingRate": round(1 - len(kept[tk]) / expected[tk], 4)}
         for tk in kept if expected[tk] > 0),
        key=lambda x: -x["missingRate"])
    # 종목별은 WARN으로 남긴다. 전체 지표는 파이프라인 건전성을, 이쪽은 개별 종목의
    # 거래 특성을 잰다 — 장기 거래정지가 여기 그대로 잡히므로 FAIL로 올리면
    # 정상 시장 상태가 파이프라인을 막는다(실측: 오상헬스케어 64.4% / 한주라이트메탈 49.5%,
    # 각각 1,932·1,455거래일 정지).
    over = [w for w in worst if w["missingRate"] > a["perTickerMissingRateWarn"]]
    diag["perTickerMissingWorst"] = worst[:50]
    diag["perTickerMissingOver"] = over[:50]
    warn(not over,
         f"종목별 누락률 {a['perTickerMissingRateWarn']*100:.0f}% 초과 {len(over)}종목 "
         f"{[w['ticker'] for w in over[:5]]} (장기 거래정지 가능 — 정상 시장 상태)")

    # ── 롤링 윈도우 앞단 잘림 — 관측만 한다(게이트 아님) ───────────
    # 전체 최소 날짜로 재면 극단값 2종목이 1,471종목의 손실을 가린다.
    trunc = []
    for tk, xs in by_ticker.items():
        # 상장 자체가 늦은 종목과 구분하려면 listedAt보다 뒤에서 시작한 경우만 센다
        lst = uni_by_ticker.get(tk, {}).get("listedAt") or cal_days[0]
        start = max(lst, cal_days[0])
        if xs[0]["date"] > start:
            miss = sum(1 for d in cal_days if start <= d < xs[0]["date"])
            if miss:
                trunc.append({"ticker": tk, "firstTraded": xs[0]["date"], "missing": miss})
    trunc.sort(key=lambda x: -x["missing"])
    diag["frontTruncatedTickers"] = len(trunc)
    diag["frontTruncatedTickerDays"] = sum(t["missing"] for t in trunc)
    diag["frontTruncatedWorst"] = trunc[:20]
    print(f"  ..    앞단 잘림 {len(trunc)}종목 / {diag['frontTruncatedTickerDays']}종목-거래일 "
          f"(관측 전용 — 워밍업 구간이라 게이트 아님)")

    keep_rows = [x for x in rows if x["ticker"] not in ex_set]
    return keep_rows, excluded


def run_finalize(pol):
    diag_path = f"{OUT_DIR}/_diagnostics.json"
    diag = {"stage": "A2a", "mode": "finalize", "pricePolicy": pol["version"],
            "environment": environment(pol)}

    shard_files = sorted(glob.glob(f"{SHARD_DIR}/shard-*.jsonl"))
    if not shard_files:
        _abort(f"{SHARD_DIR}에 샤드 산출물이 없다 — 수집 잡을 먼저 돌려라", diag, diag_path)

    rows = []
    for p in shard_files:
        rows.extend(load_jsonl(p))
    diag["shardFiles"] = [os.path.basename(p) for p in shard_files]
    diag["shardCount"] = len(shard_files)
    diag["rowCount"] = len(rows)
    print(f"[1/3] 샤드 {len(shard_files)}개 병합 — {len(rows)}행")

    if not rows:
        _abort("병합 결과 0행", diag, diag_path)

    # 샤드 스모크 테스트가 하나라도 섞이면 전체를 스모크로 표시한다.
    # 부분 수집물이 정상 산출로 승격되는 경로를 막는다.
    for p in shard_files:
        d = f"{SHARD_DIR}/_diagnostics-{os.path.basename(p).replace('.jsonl','')}.json"
        if os.path.exists(d) and load_json(d).get("smokeTest"):
            diag["smokeTest"] = True

    uni = load_jsonl(UNIVERSE)
    cal = load_json(CALENDAR)
    diag["calendarStart"] = cal["tradingDays"][0]
    diag["calendarEnd"] = cal["tradingDays"][-1]
    diag["actualDataFrom"] = min(x["date"] for x in rows)
    diag["actualDataTo"] = max(x["date"] for x in rows)
    # 전체 최소 날짜는 롤링 손실 지표로 쓰지 않는다 — 장기 거래정지 이력 종목 2개가
    # 캘린더 첫날에 닿아 1,471종목의 실제 손실을 통째로 가렸다(2026-08-05 실측).
    # 손실은 validate()에서 종목별로 잰다(frontTruncated*, 관측 전용).
    print(f"[2/3] 구간 — 캘린더 {diag['calendarStart']}~{diag['calendarEnd']} / "
          f"실측 {diag['actualDataFrom']}~{diag['actualDataTo']}")

    rows, excluded = validate(rows, uni, cal, pol, diag)
    diag["rowCountAfterExclusion"] = len(rows)

    os.makedirs(OUT_DIR, exist_ok=True)
    diag["acceptanceFails"] = list(fails)
    diag["acceptanceWarns"] = list(warns)
    diag["acceptancePassed"] = not fails
    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    if warns:
        print(f"\nWARN {len(warns)}건 (실패 아님, 확인 필요):")
        for w in warns:
            print(f"  - {w}")

    # 인수 조건 실패 시 산출물을 쓰지 않는다(교훈43).
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

    # 이전 실행의 잔재를 남기지 않는다 — 유니버스가 줄면 빈 연도 파일이 남아
    # 디렉터리 해시가 사실과 달라진다.
    for old in glob.glob(f"{OUT_DIR}/*.jsonl.gz"):
        os.remove(old)

    years = {}
    for y in sorted(by_year):
        raw, gz = write_year_gz(y, by_year[y], pol)
        years[y] = {"rows": len(by_year[y]), "rawBytes": raw, "gzBytes": gz}
        print(f"  {y}.jsonl.gz  {len(by_year[y]):>7}행  "
              f"{raw/1e6:6.1f}MB → {gz/1e6:5.1f}MB")
    diag["years"] = years

    # 품질 제외 목록도 gzip으로 쓴다 — manifest 디렉터리 해시가 targetExt '.jsonl.gz'로
    # 걸리므로, 평문으로 두면 제외 목록이 manifest 밖에 남는다.
    qx = pol["qualityExclusion"]["file"]
    _, qx_bytes = write_gz(f"{OUT_DIR}/{qx}", excluded, pol)
    print(f"  {qx}  {len(excluded):>7}종목  {qx_bytes/1e3:5.1f}KB  "
          f"{diag['qualityExcludedByReason']}")

    diag["totalGzBytes"] = sum(v["gzBytes"] for v in years.values()) + qx_bytes
    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{OUT_DIR} — 연도 {len(years)}개 + 제외 1개 · {len(rows)}행 · "
          f"{diag['totalGzBytes']/1e6:.1f}MB")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int)
    ap.add_argument("--shards", type=int)
    ap.add_argument("--finalize", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="스모크 테스트용. 진단에 smokeTest 플래그가 박히고 CI가 거부한다")
    args = ap.parse_args()

    if not os.path.exists(POLICY):
        print(f"{POLICY} 없음 — PR-1.0 정책 파일이 필요하다")
        return 1
    pol = load_json(POLICY)

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
