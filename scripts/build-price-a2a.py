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
from collections import defaultdict

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
def write_year_gz(year, rows, pol):
    """gzip mtime을 0으로 고정한다. 기본값(현재 시각)이면 내용이 같아도 매 실행
    바이트가 달라져 manifest 해시가 '재수집 여부 판정' 기능을 잃는다."""
    o = pol["output"]
    buf = io.BytesIO()
    for x in rows:
        buf.write((json.dumps({k: x[k] for k in FIELDS}, ensure_ascii=False) + "\n")
                  .encode("utf-8"))
    raw = buf.getvalue()
    path = f"{OUT_DIR}/{year}.jsonl.gz"
    with open(path, "wb") as fh:
        gz = gzip.GzipFile(filename="", mode="wb", fileobj=fh,
                           compresslevel=o["gzipCompressLevel"], mtime=o["gzipMtime"])
        gz.write(raw)
        gz.close()
    return len(raw), os.path.getsize(path)


def validate(rows, uni, cal, pol, diag):
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

    # 일간 ±50% — 국내 가격제한폭이 상하 30%라 구조적으로 불가능한 변동이다.
    # 목적은 '개발자가 수정주가를 안 썼는가'가 아니라 '소스가 수정주가를 정상 제공했는가'다
    # (adjusted=false 경로는 pykrx 1.2.8에서 죽어 있어 실수할 여지가 없다).
    by_ticker = defaultdict(list)
    for x in rows:
        by_ticker[x["ticker"]].append(x)
    jumps = []
    for tk, xs in by_ticker.items():
        xs.sort(key=lambda x: x["date"])
        for i in range(1, len(xs)):
            prev, cur = xs[i - 1]["close"], xs[i]["close"]
            if prev > 0 and abs(cur / prev - 1) > a["dailyChangeAbsMax"]:
                jumps.append({"ticker": tk, "date": xs[i]["date"],
                              "prevClose": prev, "close": cur,
                              "change": round(cur / prev - 1, 4)})
    diag["dailyChangeViolations"] = jumps[:200]
    diag["dailyChangeViolationCount"] = len(jumps)
    chk(len(jumps) == a["dailyChangeViolations"],
        f"일간 종가 변동 ±{a['dailyChangeAbsMax']*100:.0f}% 초과 {len(jumps)}건 (수정주가 미적용 탐지)")

    chk(len(by_ticker) >= a["minTickersWithData"],
        f"데이터 확보 종목 {len(by_ticker)} >= {a['minTickersWithData']} (유니버스 {len(uni)})")

    # 조회 실패 — 기대 거래일이 0인 종목(상장일이 창구 밖)은 정상 공백이므로 제외한다
    listed = {x["ticker"]: x["listedAt"] for x in uni}
    data_from = diag["actualDataFrom"]
    days = [d for d in cal["tradingDays"] if d >= data_from]
    expected = {}
    for tk, lst in listed.items():
        start = lst if lst and lst > data_from else data_from
        expected[tk] = sum(1 for d in days if d >= start)

    hard_fail = [tk for tk in listed
                 if expected[tk] > 0 and tk not in by_ticker]
    diag["fetchFailedTickers"] = hard_fail[:200]
    chk(len(hard_fail) == a["tickerFetchFail"],
        f"기대 거래일이 있는데 데이터 0행인 종목 {len(hard_fail)}건")

    legit_empty = [tk for tk in listed if expected[tk] == 0]
    diag["expectedEmptyTickers"] = legit_empty
    warn(len(legit_empty) / max(len(listed), 1) < a["emptyTickerRateWarn"],
         f"정상 공백(상장일이 수집 창구 밖) {len(legit_empty)}건")

    # 누락률 — PR-1.0에서는 WARN이다. 거래정지 구간에 KRX가 행을 주는지 실측한 적이
    # 없어, FAIL로 걸면 정당한 데이터가 파이프라인을 막는다. 실측 1회 후 PR-1.1에서 승격.
    total_exp = sum(expected[tk] for tk in listed)
    total_got = sum(len(v) for v in by_ticker.values())
    rate = 1 - (total_got / total_exp) if total_exp else 1
    diag["expectedRows"] = total_exp
    diag["missingRate"] = round(rate, 5)
    warn(rate <= a["missingRateWarn"],
         f"거래일 누락률 {rate*100:.3f}% (기대 {total_exp} / 실측 {total_got}) "
         f"— actualDataFrom {data_from} 기준")

    worst = sorted(
        ({"ticker": tk, "expected": expected[tk], "got": len(by_ticker.get(tk, [])),
          "missingRate": round(1 - len(by_ticker.get(tk, [])) / expected[tk], 4)}
         for tk in listed if expected[tk] > 0),
        key=lambda x: -x["missingRate"])
    over = [w for w in worst if w["missingRate"] > a["perTickerMissingRateWarn"]]
    diag["perTickerMissingWorst"] = worst[:50]
    warn(not over, f"종목별 누락률 {a['perTickerMissingRateWarn']*100:.0f}% 초과 {len(over)}종목")


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
    diag["rollingWindowLoss"] = sum(1 for d in cal["tradingDays"]
                                    if d < diag["actualDataFrom"])
    print(f"[2/3] 구간 — 캘린더 {diag['calendarStart']}~{diag['calendarEnd']} / "
          f"실측 {diag['actualDataFrom']}~{diag['actualDataTo']} "
          f"(롤링 윈도우로 소실된 앞 구간 {diag['rollingWindowLoss']}거래일)")

    validate(rows, uni, cal, pol, diag)

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
    diag["totalGzBytes"] = sum(v["gzBytes"] for v in years.values())
    with open(diag_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(diag, f, ensure_ascii=False, indent=2)

    print(f"\n{OUT_DIR} — {len(years)}개 연도 파일 · {len(rows)}행 · "
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
