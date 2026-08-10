"""probe-minute-coverage.py — 분봉 캔들 커버리지 정찰 (Core Universe 하한 산정용)

질문: 거래대금 구간별로 1분 캔들이 얼마나 채워지는가.

왜 필요한가:
    KIS 분봉은 거래량 0인 분을 응답에 넣지 않는다(T0 실측). 얇은 종목은
    분봉이 듬성듬성해서 분 단위 지표가 정의되지 않거나 조용히 왜곡된다.
    Core Universe의 유동성 하한을 임의의 숫자가 아니라 이 측정에서 정한다.

범위:
    분봉 전용 선정 기준만 다룬다. A1/A2 장기 Universe 정책을 건드리지 않는다.
    정찰이므로 재시도·resume·manifest를 넣지 않는다.

입력: .env · data/backfill/price/a2a/2026.jsonl.gz · universe/a1a/current.jsonl
출력: data/backfill/_probe-minute-coverage.json

분모 주의(교훈48): 커버리지 분모를 381로 박지 않는다. 그 날짜의 정규장 분이
    반휴장 등으로 다르면 전 구간이 함께 왜곡된다. 표본 최대 관측치를 분모로
    쓰고 381과 대조해 기록한다.
"""

import gzip
import importlib.util
import json
import statistics as st
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "backfill" / "_probe-minute-coverage.json"
A2A = REPO / "data" / "backfill" / "price" / "a2a" / "2026.jsonl.gz"
A1A = REPO / "data" / "backfill" / "universe" / "a1a" / "current.jsonl"

# T0 정찰과 호출부를 공유한다. 같은 계약을 두 벌 두지 않는다(교훈44).
_spec = importlib.util.spec_from_file_location(
    "probe_minute_kis", REPO / "scripts" / "probe-minute-kis.py")
K = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(K)

DATES = ["2026-08-03", "2026-07-01"]   # 하루만 재면 그날의 특이성과 구분되지 않는다
PER_BUCKET = 20
WORKERS = 4                            # 1차 실행이 6에서 EGW00201(유량초과)을 냈다
NOMINAL_MINUTES = 381                  # T0 실측(005930). 분모가 아니라 대조값이다

# 억원 단위 하한. 위에서부터 닫힌 구간으로 가른다.
BUCKETS = [
    ("A_500억이상", 500, None),
    ("B_200_500억", 200, 500),
    ("C_100_200억", 100, 200),
    ("D_50_100억", 50, 100),
    ("E_20_50억", 20, 50),
    ("F_5_20억", 5, 20),
    ("G_5억미만", 0, 5),
]


def say(m=""):
    print(m, flush=True)


def classify(err):
    """실패의 원인을 세는 자리에서 가른다(교훈67). 대응이 전부 다르다.

    빈응답     그 날짜에 데이터가 없다. 거래정지·상장전. 재수집해도 같다
    일자대체   API가 다른 날짜를 줬다. 게이트가 잡은 것이며 사실은 '없음'이다
    유량초과   EGW00201. 기다렸다 다시 부르면 된다
    기타       모르는 것은 '못 한다'가 아니라 '아직 모른다'다(교훈56)
    """
    if not err:
        return "없음"
    if err.get("dateHonored") is False:
        return "일자대체"
    if str(err.get("msgCd", "")).startswith("EGW"):
        return "유량초과"
    if err.get("rtCd") == "0" and err.get("rows") == 0:
        return "빈응답"
    return "기타:" + str(err.get("msgCd"))


def load_market():
    m = {}
    if A1A.exists():
        for line in A1A.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
                m[r["ticker"]] = r.get("market")
            except Exception:
                pass
    return m


def load_turnover():
    """종목별 최근 60거래일 거래대금 중앙값(원)."""
    rows = defaultdict(list)
    with gzip.open(A2A, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            rows[r["ticker"]].append((r["date"], r["close"] * r["volume"]))
    med = {}
    for tk, v in rows.items():
        v.sort()
        tail = [x[1] for x in v[-60:]]
        if len(tail) >= 20:
            med[tk] = st.median(tail)
    return med


def pick(turnover, market):
    """구간별 표본. 구간 안에서 고르게 뽑는다 - 위쪽만 뽑으면 구간을 대표하지 않는다."""
    out = {}
    for name, lo, hi in BUCKETS:
        cand = [tk for tk, v in turnover.items()
                if v >= lo * 1e8 and (hi is None or v < hi * 1e8)]
        cand.sort(key=lambda t: turnover[t], reverse=True)
        if not cand:
            out[name] = []
            continue
        step = max(1, len(cand) // PER_BUCKET)
        sel = cand[::step][:PER_BUCKET]
        out[name] = [{"ticker": t, "turnoverEok": round(turnover[t] / 1e8, 1),
                      "market": market.get(t)} for t in sel]
    return out


def collect_day(ticker, date):
    """하루 전량. 반환: (시각집합, 호출수, 거부사유)."""
    times, calls, cursor = {}, 0, "153000"
    for _ in range(8):
        r = K.call_minute(ticker, date, hour=cursor)
        calls += 1
        if not K.ok(r):
            # 요청 일자가 응답에 없으면 실패다. rt_cd=0이어도 그렇다(교훈81).
            return times, calls, {"rtCd": r.get("rtCd"), "msgCd": r.get("msgCd"),
                                  "rows": r.get("rows"),
                                  "dateHonored": r.get("dateHonored")}
        got = [x for x in r["output2"]
               if x.get("stck_bsop_date") == K.compact(date)]
        if not got:
            break
        new = 0
        for x in got:
            k = x["stck_cntg_hour"]
            if k not in times:
                times[k] = int(x.get("cntg_vol", 0))
                new += 1
        mn = min(x["stck_cntg_hour"] for x in got)
        if new == 0 or mn == cursor:
            break
        cursor = mn
    return times, calls, None


def session_of(hhmmss):
    h = int(hhmmss[:2]) * 60 + int(hhmmss[2:4])
    if h < 9 * 60 + 30:
        return "개장30분"
    if h >= 15 * 60:
        return "마감30분"
    return "중반"


def measure(item, date):
    tk = item["ticker"]
    t0 = time.time()
    times, calls, err = collect_day(tk, date)
    rec = {"ticker": tk, "date": date, "turnoverEok": item["turnoverEok"],
           "market": item["market"], "calls": calls,
           "elapsed": round(time.time() - t0, 2)}
    if err is not None:
        rec["error"] = err
        rec["candles"] = 0
        return rec
    keys = sorted(times)
    rec["candles"] = len(keys)
    if keys:
        rec["first"] = keys[0]
        rec["last"] = keys[-1]
        rec["zeroVolCandles"] = sum(1 for k in keys if times[k] == 0)
        per = defaultdict(int)
        for k in keys:
            per[session_of(k)] += 1
        rec["bySession"] = dict(per)
        # 최장 연속 결측(분). 09:00~15:30 격자에서 15:20~15:29를 뺀다.
        # 그 10분은 종가 단일가 구간이라 캔들이 제도상 없다. 격자에 두면
        # 모든 종목이 최장결측 10분의 바닥값을 갖게 되어 지표가 죽는다 -
        # 제도상 부재와 실제 결측을 섞으면 안 된다(교훈48).
        grid = []
        for mnt in range(9 * 60, 15 * 60 + 31):
            if 15 * 60 + 20 <= mnt <= 15 * 60 + 29:
                continue
            grid.append("%02d%02d00" % (mnt // 60, mnt % 60))
        miss, run, worst = 0, 0, 0
        for g in grid:
            if g in times:
                run = 0
            else:
                miss += 1
                run += 1
                worst = max(worst, run)
        rec["gridMissing"] = miss
        rec["longestGapMin"] = worst
    return rec


def main():
    if not K.KEY or not K.SECRET:
        raise SystemExit("KIS 키가 없다")
    started = time.time()
    say()
    say("  분봉 캔들 커버리지 정찰 — " + K.stamp())
    say()
    K.get_token()

    market = load_market()
    turnover = load_turnover()
    samples = pick(turnover, market)
    for name, lo, hi in BUCKETS:
        say("  " + name.ljust(14) + str(len(samples[name])) + "종목")

    jobs = [(it, d) for name, _, _ in BUCKETS
            for it in samples[name] for d in DATES]
    say()
    say("  측정 " + str(len(jobs)) + "건 (종목 " +
        str(sum(len(v) for v in samples.values())) + " x 일자 " +
        str(len(DATES)) + ")")

    results = []
    done = [0]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for r in ex.map(lambda a: measure(*a), jobs):
            results.append(r)
            done[0] += 1
            if done[0] % 25 == 0:
                say("    " + str(done[0]) + "/" + str(len(jobs)))

    # --- 분모를 정한다. 상수가 아니라 관측에서 얻는다 ---------------------
    per_date_max = {}
    for d in DATES:
        vals = [r["candles"] for r in results if r["date"] == d and r["candles"]]
        per_date_max[d] = max(vals) if vals else 0

    by_ticker = {r["ticker"]: r for r in results}
    bucket_of = {}
    for name, _, _ in BUCKETS:
        for it in samples[name]:
            bucket_of[it["ticker"]] = name

    summary = {}
    for name, _, _ in BUCKETS:
        rs = [r for r in results if bucket_of.get(r["ticker"]) == name]
        # 실패는 커버리지 0이 아니다. 섞으면 실패율이 데이터 품질로 둔갑한다
        # (교훈57). 분자에서 빼고 따로 센다.
        good = [r for r in rs if not r.get("error")]
        fails = [r for r in rs if r.get("error")]
        okc = sorted((r["candles"] / (per_date_max.get(r["date"])
                                      or NOMINAL_MINUTES)) for r in good)
        if not okc:
            summary[name] = {"표본": 0, "측정실패": len(fails),
                             "실패유형": dict(Counter(
                                 classify(r["error"]) for r in fails))}
            continue
        n = len(okc)
        summary[name] = {
            "표본": n,
            "측정실패": len(fails),
            "측정실패율": round(len(fails) / len(rs), 3),
            "실패유형": dict(Counter(classify(r["error"]) for r in fails)),
            "커버리지중앙값": round(st.median(okc), 4),
            "커버리지p10": round(okc[max(0, int(n * 0.1) - 1)], 4),
            "커버리지최소": round(okc[0], 4),
            "커버리지90이상비율": round(sum(1 for c in okc if c >= 0.9) / n, 3),
            "커버리지95이상비율": round(sum(1 for c in okc if c >= 0.95) / n, 3),
            "최장결측중앙값분": st.median([r.get("longestGapMin", 0) for r in good]),
            "호출중앙값": st.median([r["calls"] for r in good]),
            "거래대금중앙값억": round(st.median(
                [r["turnoverEok"] for r in good]), 1),
        }

    # --- 하한 제안 : 데이터가 정한다 ---------------------------------------
    # 기준은 두 개다. 중앙값이 아니라 p10을 본다 -
    # 표본의 절반이 좋아도 나머지 절반이 구멍이면 신호가 종목마다 다른 뜻이 된다.
    floor = None
    for name, lo, hi in BUCKETS:
        s = summary.get(name, {})
        if s.get("표본") and s.get("커버리지중앙값", 0) >= 0.95 \
                and s.get("커버리지p10", 0) >= 0.80:
            floor = {"구간": name, "하한억": lo,
                     "근거": {"중앙값": s["커버리지중앙값"], "p10": s["커버리지p10"]}}
        else:
            break

    # --- 인수 조건 ----------------------------------------------------------
    acceptance = []

    def check(name, passed, detail):
        acceptance.append({"항목": name, "통과": bool(passed), "실측": detail})

    min_n = min((summary[b[0]].get("표본", 0) for b in BUCKETS), default=0)
    check("AC1 구간별 표본 20이상(=일자2 x 종목10 이상)", min_n >= 20,
          {"최소표본": min_n})
    # 일자대체는 '없어야 하는 것'이 아니라 '잡아야 하는 것'이다. 거래정지
    # 종목에서 실제로 나온다. 인수 조건은 발생 0이 아니라 분류·제외를 본다.
    bad_date = [r for r in results
                if (r.get("error") or {}).get("dateHonored") is False]
    check("AC2 일자대체 응답이 성공으로 집계되지 않음",
          all(r["candles"] == 0 for r in bad_date),
          {"발생": len(bad_date),
           "종목": [r["ticker"] + "/" + r["date"] for r in bad_date]})
    fail_rate = sum(1 for r in results if r.get("error")) / max(1, len(results))
    check("AC2b 측정 실패율 5% 미만", fail_rate < 0.05,
          {"실패율": round(fail_rate, 4),
           "유형": dict(Counter(classify(r.get("error"))
                              for r in results if r.get("error")))})
    check("AC3 두 일자 모두 측정됨",
          all(per_date_max.get(d) for d in DATES), per_date_max)
    check("AC4 분모가 T0 실측 381과 일치",
          all(v == NOMINAL_MINUTES for v in per_date_max.values()),
          {"일자별최대캔들": per_date_max, "대조값": NOMINAL_MINUTES})
    check("AC5 커버리지 단조성(거래대금이 크면 커버리지가 크거나 같다)",
          all(summary[BUCKETS[i][0]].get("커버리지중앙값", 0)
              >= summary[BUCKETS[i + 1][0]].get("커버리지중앙값", 0) - 0.02
              for i in range(len(BUCKETS) - 1)
              if summary[BUCKETS[i][0]].get("표본")
              and summary[BUCKETS[i + 1][0]].get("표본")),
          {"구간별중앙값": {b[0]: summary[b[0]].get("커버리지중앙값")
                       for b in BUCKETS}})
    check("AC6 하한 제안이 도출됨", floor is not None, floor)

    out = {
        "schemaVersion": "PROBE-MINCOV-1.0",
        "probe": "minute-coverage",
        "startedAt": K.stamp(),
        "elapsedSeconds": round(time.time() - started, 1),
        "범위": "분봉 전용 선정 기준. A1/A2 장기 Universe 정책과 무관하다",
        "일자": DATES,
        "분모": {"방식": "표본 최대 관측 캔들수", "일자별": per_date_max,
               "대조값(T0 실측)": NOMINAL_MINUTES},
        "구간정의억": [{"이름": b[0], "하한": b[1], "상한": b[2]} for b in BUCKETS],
        "표본": samples,
        "구간요약": summary,
        "하한제안": floor,
        "acceptance": acceptance,
        "acceptancePassed": all(a["통과"] for a in acceptance),
        "callCount": sum(r["calls"] for r in results),
        "측정": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(out, ensure_ascii=False, indent=2))

    say()
    say("  구간            표본   중앙값   p10    >=0.9   호출   거래대금")
    for name, _, _ in BUCKETS:
        s = summary[name]
        if not s.get("표본"):
            continue
        say("  " + name.ljust(14) +
            str(s["표본"]).rjust(4) +
            ("%8.3f" % s["커버리지중앙값"]) +
            ("%7.3f" % s["커버리지p10"]) +
            ("%8.2f" % s["커버리지90이상비율"]) +
            ("%7.1f" % s["호출중앙값"]) +
            ("%9.1f억" % s["거래대금중앙값억"]))
    say()
    say("  하한 제안: " + (json.dumps(floor, ensure_ascii=False)
                       if floor else "없음"))
    say("  인수조건: " + ("통과" if out["acceptancePassed"] else "실패"))
    for a in acceptance:
        if not a["통과"]:
            say("    FAIL " + a["항목"] + " " +
                json.dumps(a["실측"], ensure_ascii=False)[:160])
    say("  호출 " + str(out["callCount"]) + "회 · " +
        str(out["elapsedSeconds"]) + "초")
    say("  " + str(OUT.relative_to(REPO)))
    say()


if __name__ == "__main__":
    main()
