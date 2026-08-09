"""collect-minute-kis.py — 분봉 Collector v1 (KIS 주식일별분봉조회)

계약: docs/MN-1.0-분봉Raw저장계약.md · 정책: config/policies/minute.v1.json

v1의 범위는 '메커니즘'이다. 정책 값은 policy의 pendingT1 블록에 격리되어 있고
T1(§6.1) 뒤에 승격한다. 메커니즘과 정책을 분리하는 이유는 되돌릴 수 있는 쪽과
없는 쪽이 다르기 때문이다 — 정책은 나중에 고치면 되고, 못 받은 하루는 못 고친다.

들어 있는 것
    요청일자 게이트(P0) · rt_cd 검사 · EGW00201 재시도 · exponential backoff
    resume · manifest · gapReason 분류 · parquet writer · 스키마 검증 · 인수 조건

들어 있지 않은 것
    빈 응답 재시도 횟수의 확정  · 거래정지 재수집 여부 · 최종 rate limit 정책
    이 셋은 T1 결과가 있어야 정할 수 있다. pendingT1에 보수적 기본값으로 있다.

두 축을 섞지 않는다
    gapReason     왜 시장 데이터가 없는가  (HALT · PRE_LIST · HOLIDAY · EMPTY ...)
    failureClass  왜 수집이 실패했는가      (RATE_LIMIT · NETWORK · DATE_MISMATCH ...)
    섞으면 일시적 장애가 영구 결손으로 기록되고, 재수집 없이는 되돌릴 수 없다.

네트워크는 transport 하나로만 나간다. 테스트는 그것을 갈아끼워 실호출 없이 돈다.

사용:
    python scripts/collect-minute-kis.py --date 2026-08-03 --tickers 005930,000660
    python scripts/collect-minute-kis.py --date 2026-08-03 --universe broad
    python scripts/collect-minute-kis.py --date 2026-08-03 --universe broad --resume
    python scripts/collect-minute-kis.py --selftest      # 네트워크 없이 인수 조건 검증
"""

import argparse
import hashlib
import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO / "config" / "policies" / "minute.v1.json"
CALENDAR_PATH = REPO / "data" / "backfill" / "calendar.json"
KST = timezone(timedelta(hours=9))
BASE = "https://openapi.koreainvestment.com:9443"
PATH_MIN = "/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice"

SCHEMA = ["ticker", "ts", "open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------- 기본

def now_kst():
    return datetime.now(KST)


def stamp():
    return now_kst().strftime("%Y-%m-%dT%H:%M:%S+09:00")


def compact(date):
    return "".join(c for c in str(date) if c.isdigit())


def dashed(yyyymmdd):
    s = compact(yyyymmdd)
    return s[:4] + "-" + s[4:6] + "-" + s[6:8]


def load_policy(path=None):
    return json.loads(Path(path or POLICY_PATH).read_text(encoding="utf-8"))


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def policy_hash(pol):
    return sha256_bytes(json.dumps(pol, sort_keys=True, ensure_ascii=False)
                        .encode("utf-8"))


# ---------------------------------------------------------------- 결과 타입

class Outcome:
    """한 (ticker, date)의 수집 결과.

    셋 중 하나다. 이 셋을 섞지 않는 것이 이 모듈의 핵심이다.
      OK          캔들을 받았다
      GAP         받을 것이 없다는 사실을 확인했다 (gapReason)
      UNRESOLVED  아직 모른다. 재시도가 소진됐거나 조회하지 않았다 (failureClass)
    """

    def __init__(self, ticker, date, status, rows=None, gap_reason=None,
                 failure_class=None, attempts=0, detail=None):
        self.ticker = ticker
        self.date = date
        self.status = status
        self.rows = rows or []
        self.gap_reason = gap_reason
        self.failure_class = failure_class
        self.attempts = attempts
        self.detail = detail or {}

    def to_state(self):
        d = {"ticker": self.ticker, "status": self.status,
             "attempts": self.attempts}
        if self.status == "OK":
            d["rows"] = len(self.rows)
        if self.gap_reason:
            d["gapReason"] = self.gap_reason
        if self.failure_class:
            d["failureClass"] = self.failure_class
        if self.detail:
            d["detail"] = self.detail
        return d


# ---------------------------------------------------------------- transport

class KisTransport:
    """실제 KIS 호출. 이 클래스만 네트워크를 안다.

    테스트는 이것과 같은 fetch() 시그니처를 가진 가짜를 넣는다.
    """

    def __init__(self, app_key, app_secret, token, base=BASE):
        self.app_key = app_key
        self.app_secret = app_secret
        self.token = token
        self.base = base

    def fetch(self, ticker, sent_date, hour, pol):
        import requests
        cc = pol["collectionContract"]
        try:
            r = requests.get(
                self.base + PATH_MIN,
                headers={"content-type": "application/json",
                         "authorization": "Bearer " + self.token,
                         "appkey": self.app_key, "appsecret": self.app_secret,
                         "tr_id": pol["trId"], "custtype": "P"},
                params={"FID_COND_MRKT_DIV_CODE": cc["marketDivCode"],
                        "FID_INPUT_ISCD": ticker,
                        "FID_INPUT_HOUR_1": hour,
                        "FID_INPUT_DATE_1": sent_date,
                        "FID_PW_DATA_INCU_YN": cc["pastDataFlag"],
                        "FID_FAKE_TICK_INCU_YN": cc["fakeTickFlag"]},
                timeout=20)
        except Exception as e:
            return {"transportError": type(e).__name__}
        out = {"http": r.status_code}
        try:
            out["body"] = r.json()
        except Exception:
            out["bodyNotJson"] = True
        return out


# ---------------------------------------------------------------- 분류

def classify_response(resp, sent_date, pol):
    """응답 하나를 (kind, failure_class) 로 가른다.

    kind: OK · EMPTY · DATE_MISMATCH · FAIL
    성공 판정은 rt_cd만으로 하지 않는다(교훈81).
    """
    gate = pol["successGate"]

    if resp.get("transportError"):
        return "FAIL", "NETWORK"
    if resp.get("bodyNotJson"):
        return "FAIL", "HTTP_ERROR"

    http = resp.get("http")
    if http is not None and http != 200:
        return "FAIL", "HTTP_ERROR"

    body = resp.get("body") or {}
    msg_cd = str(body.get("msg_cd") or "")
    if msg_cd in pol["retry"]["retryableMsgCodes"]:
        return "FAIL", "RATE_LIMIT"

    if str(body.get("rt_cd")) != gate["requireRtCd"]:
        return "FAIL", "API_ERROR"

    out2 = body.get("output2") or []
    if not out2:
        return "EMPTY", None

    if gate["requireRequestedDateInResponse"]:
        dates = {str(r.get("stck_bsop_date")) for r in out2}
        if sent_date not in dates:
            # 오류가 아니라 '그 날짜에 데이터가 없다'는 증거다.
            return "DATE_MISMATCH", "DATE_MISMATCH"

    return "OK", None


def resolve_gap_reason(kind, ticker, date, ctx):
    """결손의 사유를 확정한다. 응답을 본 자리에서 남긴다(교훈75).

    ctx: {"tradingDays": set, "listedAt": {ticker: 'YYYY-MM-DD'},
          "delistedAt": {ticker: 'YYYY-MM-DD'}}
    """
    if date not in ctx.get("tradingDays", set()) and ctx.get("tradingDays"):
        return "HOLIDAY"
    listed = (ctx.get("listedAt") or {}).get(ticker)
    if listed and date < listed:
        return "PRE_LIST"
    delisted = (ctx.get("delistedAt") or {}).get(ticker)
    if delisted and date >= delisted:
        return "DELISTED"
    if kind == "DATE_MISMATCH":
        # 상장 중이고 영업일인데 그 날짜가 없다 = 거래정지가 가장 그럴듯하다.
        # 단정하지 않고 라벨만 남긴다 - 확정은 상장/정지 원장이 생긴 뒤다.
        return "HALT"
    return "EMPTY"


# ---------------------------------------------------------------- 수집

def collect_symbol_day(transport, ticker, date, pol, ctx, sleeper=time.sleep,
                       rnd=random.random):
    """한 종목의 하루. 커서를 돌려 전량을 모은다.

    재시도는 '메커니즘'이라 여기 있고, 몇 번 돌지는 policy가 정한다.
    """
    cc = pol["collectionContract"]
    rt = pol["retry"]
    sent = compact(date)
    cursor = cc["cursorSeed"]
    seen = {}
    attempts = 0
    pages = 0

    while pages < 12:
        kind = fclass = None
        for attempt in range(1, rt["maxAttempts"] + 1):
            attempts += 1
            resp = transport.fetch(ticker, sent, cursor, pol)
            kind, fclass = classify_response(resp, sent, pol)
            if kind != "FAIL":
                break
            retryable = (
                (fclass == "RATE_LIMIT")
                or (fclass == "NETWORK" and rt["retryOnTransport"])
                or (fclass == "HTTP_ERROR" and rt["retryOnHttp5xx"])
                or (fclass == "API_ERROR" and rt["defaultUnknownRetryable"])
            )
            if not retryable or attempt >= rt["maxAttempts"]:
                break
            delay = min(rt["backoffBaseSeconds"] * (2 ** (attempt - 1)),
                        rt["backoffMaxSeconds"])
            delay *= 1.0 + rt["jitterRatio"] * (rnd() * 2 - 1)
            sleeper(max(0.0, delay))

        if kind == "FAIL":
            if seen:
                # 일부는 받았다. 부분 성공을 성공으로 쓰지 않는다 -
                # 하루가 온전하지 않으면 미해결이다.
                return Outcome(ticker, date, "UNRESOLVED", attempts=attempts,
                               failure_class=fclass,
                               detail={"partialRows": len(seen), "pages": pages})
            return Outcome(ticker, date, "UNRESOLVED", attempts=attempts,
                           failure_class=fclass)

        if kind in ("EMPTY", "DATE_MISMATCH"):
            if seen:
                break            # 앞 페이지까지가 그 날의 전부다
            reason = resolve_gap_reason(kind, ticker, date, ctx)
            return Outcome(ticker, date, "GAP", gap_reason=reason,
                           attempts=attempts,
                           failure_class=("DATE_MISMATCH"
                                          if kind == "DATE_MISMATCH" else None))

        body = None
        # kind == OK
        resp_body = resp.get("body") or {}
        body = [r for r in (resp_body.get("output2") or [])
                if str(r.get("stck_bsop_date")) == sent]
        pages += 1
        new = 0
        for r in body:
            h = str(r.get("stck_cntg_hour"))
            if h not in seen:
                seen[h] = r
                new += 1
        if not body:
            break
        mn = min(str(r.get("stck_cntg_hour")) for r in body)
        if new == 0 or mn == cursor:
            break
        cursor = mn

    if not seen:
        return Outcome(ticker, date, "GAP",
                       gap_reason=resolve_gap_reason("EMPTY", ticker, date, ctx),
                       attempts=attempts)

    rows = []
    d = dashed(date)
    for h in sorted(seen):
        r = seen[h]
        rows.append({
            "ticker": ticker,
            "ts": d + "T" + h[:2] + ":" + h[2:4] + "+09:00",
            "open": int(r["stck_oprc"]), "high": int(r["stck_hgpr"]),
            "low": int(r["stck_lwpr"]), "close": int(r["stck_prpr"]),
            "volume": int(r.get("cntg_vol", 0)),
        })
    return Outcome(ticker, date, "OK", rows=rows, attempts=attempts)


# ---------------------------------------------------------------- 검증

def validate_rows(rows, date, pol):
    """스키마·중복·일자를 본다. 위반을 말하고 복구는 말하지 않는다(교훈74)."""
    v = []
    d = dashed(date)
    keys = set()
    for i, r in enumerate(rows):
        if list(r.keys()) != SCHEMA:
            v.append({"row": i, "why": "schemaMismatch", "got": list(r.keys())})
            continue
        if not str(r["ts"]).startswith(d):
            v.append({"row": i, "why": "dateMismatch", "ts": r["ts"]})
        k = (r["ticker"], r["ts"])
        if k in keys:
            v.append({"row": i, "why": "duplicateKey", "key": list(k)})
        keys.add(k)
        if not (r["low"] <= r["open"] <= r["high"]
                and r["low"] <= r["close"] <= r["high"]):
            v.append({"row": i, "why": "ohlcInconsistent", "key": list(k)})
        if r["volume"] < 0:
            v.append({"row": i, "why": "negativeVolume", "key": list(k)})
    return v


def acceptance(outcomes, rows, date, pol):
    """하루치가 인수 조건을 통과했는가. 실패면 parquet를 쓰지 않는다."""
    acc = pol["acceptance"]
    n = len(outcomes)
    unresolved = [o for o in outcomes if o.status == "UNRESOLVED"]
    checks = []

    def add(name, passed, detail):
        checks.append({"항목": name, "통과": bool(passed), "실측": detail})

    rate = (len(unresolved) / n) if n else 0.0
    add("미해결 비율 상한", rate <= acc["maxUnresolvedRate"],
        {"미해결": len(unresolved), "전체": n, "비율": round(rate, 4),
         "상한": acc["maxUnresolvedRate"]})

    viol = validate_rows(rows, date, pol)
    add("스키마·중복·일자 위반 0", len(viol) == 0,
        {"위반": len(viol), "샘플": viol[:3]})

    add("모든 행이 요청 일자", all(str(r["ts"]).startswith(dashed(date))
                              for r in rows), {"행": len(rows)})

    unknown_gap = [o.gap_reason for o in outcomes
                   if o.status == "GAP"
                   and o.gap_reason not in pol["gapReason"]["values"]]
    add("gapReason이 계약 안의 값", not unknown_gap, {"미등록": unknown_gap[:5]})

    return checks, all(c["통과"] for c in checks)


# ---------------------------------------------------------------- 저장

def write_parquet(rows, date, out_root):
    """minute/date=YYYY-MM-DD/part-000.parquet. pyarrow가 없으면 알린다."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        return None, "pyarrow 없음 — Collector 착수 전 설치한다(MN-1.0 §1.1)"

    d = dashed(date)
    out_dir = Path(out_root) / ("date=" + d)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "part-000.parquet"
    table = pa.table({k: [r[k] for r in rows] for k in SCHEMA})
    pq.write_table(table, path, compression="zstd")
    return path, None


def build_manifest(date, outcomes, rows, pol, sha, checks, passed,
                   raw_path, run):
    gaps = {}
    for o in outcomes:
        if o.status == "GAP":
            gaps[o.gap_reason] = gaps.get(o.gap_reason, 0) + 1
    unresolved = {}
    for o in outcomes:
        if o.status == "UNRESOLVED":
            unresolved[o.failure_class] = unresolved.get(o.failure_class, 0) + 1
    return {
        "schemaVersion": "MN-1.0",
        "date": dashed(date),
        "rows": len(rows),
        "symbols": len(outcomes),
        "sha256": sha,
        "rawPath": str(raw_path) if raw_path else None,
        "source": pol["source"],
        "endpoint": pol["endpoint"],
        "adjusted": pol["adjusted"],
        "market": pol["market"],
        "requestedAt": stamp(),
        "createdAt": stamp(),
        "policyVersion": pol["version"],
        "policyHash": policy_hash(pol),
        "gapReasons": gaps,
        "unresolved": unresolved,
        "acceptance": checks,
        "acceptancePassed": passed,
        "execution": {
            "runId": run.get("runId"),
            "runAttempt": run.get("runAttempt"),
            "workflow": run.get("workflow"),
            "host": run.get("host"),
        },
    }


# ---------------------------------------------------------------- resume

def state_path(root, date):
    return Path(root) / ("state-" + dashed(date) + ".json")


def load_state(root, date, pol):
    p = state_path(root, date)
    if not p.exists():
        return None
    st = json.loads(p.read_text(encoding="utf-8"))
    # 재개 호환의 기준은 '이 값이 달랐다면 어제 다른 레코드가 나왔는가'뿐이다.
    # 정책 version 문자열이 아니라 collectionContract 해시를 본다(교훈55).
    mine = sha256_bytes(json.dumps(pol["collectionContract"], sort_keys=True,
                                   ensure_ascii=False).encode("utf-8"))
    if st.get("contractHash") != mine:
        return {"incompatible": True, "storedHash": st.get("contractHash"),
                "currentHash": mine}
    return st


def save_state(root, date, pol, done):
    p = state_path(root, date)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "date": dashed(date),
        "contractHash": sha256_bytes(
            json.dumps(pol["collectionContract"], sort_keys=True,
                       ensure_ascii=False).encode("utf-8")),
        "updatedAt": stamp(),
        "symbols": done,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                 encoding="utf-8", newline="\n")


# ---------------------------------------------------------------- 실행

def run_day(transport, tickers, date, pol, ctx, out_root, state_root,
            resume=False, run=None, sleeper=time.sleep, progress=None):
    run = run or {}
    done = {}
    if resume:
        st = load_state(state_root, date, pol)
        if st and st.get("incompatible"):
            raise SystemExit("resume 불가: collectionContract가 바뀌었다. "
                             "이미 모은 것을 다시 쓸 수 없다")
        if st:
            done = st.get("symbols") or {}

    todo = [t for t in tickers if done.get(t, {}).get("status") != "OK"
            and done.get(t, {}).get("status") != "GAP"]

    outcomes = []
    for t in tickers:
        prev = done.get(t)
        if prev and prev.get("status") in ("OK", "GAP"):
            outcomes.append(Outcome(t, date, prev["status"],
                                    gap_reason=prev.get("gapReason"),
                                    attempts=prev.get("attempts", 0),
                                    detail={"fromState": True}))

    conc = pol["concurrency"]["initial"]
    results = []
    if todo:
        with ThreadPoolExecutor(max_workers=max(1, conc)) as ex:
            for o in ex.map(lambda t: collect_symbol_day(
                    transport, t, date, pol, ctx, sleeper=sleeper), todo):
                results.append(o)
                if progress:
                    progress(len(results), len(todo))

    # resume 상태는 쓰는 시점에 강제한다. 읽는 시점의 발견보다 안전하다(교훈73).
    for o in results:
        done[o.ticker] = o.to_state()
        outcomes.append(o)
    save_state(state_root, date, pol, done)

    rows = []
    for o in outcomes:
        rows.extend(o.rows)
    rows.sort(key=lambda r: (r["ticker"], r["ts"]))

    checks, passed = acceptance(outcomes, rows, date, pol)
    raw_path, err = (None, None)
    sha = None
    if passed:
        raw_path, err = write_parquet(rows, date, out_root)
        if raw_path:
            sha = sha256_bytes(Path(raw_path).read_bytes())
    man = build_manifest(date, outcomes, rows, pol, sha, checks, passed,
                         raw_path, run)
    if err:
        man["writerError"] = err
    return {"outcomes": outcomes, "rows": rows, "manifest": man,
            "acceptancePassed": passed, "writerError": err}


def load_context():
    ctx = {"tradingDays": set(), "listedAt": {}, "delistedAt": {}}
    if CALENDAR_PATH.exists():
        try:
            ctx["tradingDays"] = set(
                json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))["tradingDays"])
        except Exception:
            pass
    a1a = REPO / "data" / "backfill" / "universe" / "a1a" / "current.jsonl"
    if a1a.exists():
        for line in a1a.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                if r.get("listedAt"):
                    ctx["listedAt"][r["ticker"]] = r["listedAt"]
            except Exception:
                pass
    return ctx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--tickers")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--out", default=str(REPO / "data" / "minute"))
    ap.add_argument("--state", default=str(REPO / "data" / "minute" / "_state"))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())

    if not args.date or not args.tickers:
        ap.error("--date 와 --tickers 가 필요하다 (또는 --selftest)")

    pol = load_policy()
    env = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    key = os.environ.get("KIS_APP_KEY") or env.get("KIS_APP_KEY")
    sec = os.environ.get("KIS_APP_SECRET") or env.get("KIS_APP_SECRET")
    if not key or not sec:
        raise SystemExit("KIS 키가 없다")

    cache = REPO / ".token_cache_kis.json"
    if not cache.exists():
        raise SystemExit("토큰 캐시가 없다. probe-minute-kis.py를 먼저 돌린다")
    token = json.loads(cache.read_text(encoding="utf-8"))["accessToken"]

    tr = KisTransport(key, sec, token)
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    res = run_day(tr, tickers, args.date, pol, load_context(),
                  args.out, args.state, resume=args.resume,
                  run={"host": os.environ.get("COMPUTERNAME", "local")},
                  progress=lambda i, n: print("  %d/%d" % (i, n), flush=True))

    man = res["manifest"]
    print(json.dumps({k: man[k] for k in
                      ("date", "rows", "symbols", "gapReasons", "unresolved",
                       "acceptancePassed")}, ensure_ascii=False, indent=2))
    if not res["acceptancePassed"]:
        for c in man["acceptance"]:
            if not c["통과"]:
                print("  FAIL " + c["항목"] + " " +
                      json.dumps(c["실측"], ensure_ascii=False)[:160])
        return 1
    mdir = Path(pol["output"]["manifestDir"])
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / (dashed(args.date) + ".json")).write_text(
        json.dumps(man, ensure_ascii=False, indent=2),
        encoding="utf-8", newline="\n")
    return 0


def selftest():
    """네트워크 없이 인수 조건을 검증한다. 이 파일 하나로 돌아간다."""
    mod = sys.modules[__name__]
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "test_collect_minute", REPO / "scripts" / "test-collect-minute-kis.py")
    if not Path(spec.origin).exists():
        print("테스트 파일이 없다")
        return 1
    t = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t)
    return t.run_all(mod)


if __name__ == "__main__":
    sys.exit(main())
