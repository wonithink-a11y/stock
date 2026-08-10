"""probe-t1-minute.py — T1 수집 신뢰성 정찰 (MN-1.0 §6.1, 7일)

T0는 **API가 무엇을 주는가**를 한 번에 쟀다. T1은 **같은 것을 반복해도 같은가**를
잰다. 이건 한 번의 호출로 알 수 없고 며칠이 걸린다.

이 스크립트가 아닌 것
    수집이 아니다. Raw 네임스페이스에 쓰지 않는다.
    manifest를 만들지 않는다 - manifest는 '인수 조건을 통과했다'는 뜻이고(교훈43),
    정찰 산출물에 그것을 찍으면 그 뜻이 무너진다. 대신 (종목,날짜) 단위 rows
    sha256을 남긴다. 어느 종목이 갈렸는지 조각 파일보다 정확히 지목한다.

잴 수 없는 것을 재는 척하지 않는다
    dayVerdict는 전 종목을 봐야 나온다(교훈73). 표본 10종목으로는 '전부 비었다'가
    휴장인지 그 열이 모두 정지인지 못 가린다. 그러므로 계산하지 않고 그날 Broad
    수집의 manifest에서 읽어 참조로 기록한다. 없으면 미측정이다.

임계를 미리 정하지 않는다
    비교 '방법'은 여기서 고정한다 - 7개 필드 완전일치 · rows sha256 · 다른 필드 지목.
    '며칠 안에 몇 %까지 갈려도 정상인가'라는 '임계'는 7일 뒤에 정한다.
    뒤집힐 수 없게 설계된 정찰은 돌릴 이유가 없다(교훈51).

두 축을 잰다
    즉시 재실행   같은 실행 안에서 두 번 부른다 - 전송 흔들림과 데이터 변화를 가른다
    일자 간 재실행 어제 받은 (종목,날짜)를 오늘 다시 받는다 - §4가 말한 '버전'이
                  실제로 얼마나 자주 갈리는지

사용:
    python3 scripts/probe-t1-minute.py
    python3 scripts/probe-t1-minute.py --dry-run     표본과 대상만 보여준다
    python3 scripts/probe-t1-minute.py --report      쌓인 관측을 요약한다
    python3 scripts/probe-t1-minute.py --selftest
"""

import argparse
import glob
import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

REPO = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))
SCHEMA_VERSION = "T1-1.0"

# 표본이 밟아야 하는 축. 리터럴 목록으로 고정한다 - '몇 개'로 적으면 하나가
# 빠져도 참으로 읽힌다(교훈59). 못 채운 축은 미측정으로 남긴다(교훈50·57).
REQUIRED_AXES = ["대형주", "소형주", "거래정지이력", "신규상장", "액면분할이력"]


def load_collector():
    spec = importlib.util.spec_from_file_location(
        "collect_minute_kis", REPO / "scripts" / "collect-minute-kis.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def now_kst():
    return datetime.now(KST)


def stamp():
    return now_kst().strftime("%Y-%m-%dT%H:%M:%S+09:00")


def t1_dir():
    return Path(os.environ.get("MINUTE_T1_DIR")
                or (REPO / "data" / "minute" / "_t1")).expanduser()


def safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


# ---------------------------------------------------------------- 관측 해시

def rows_sha(rows):
    """관측 단위 해시. 정렬을 고정해 조회 순서가 해시를 흔들지 않게 한다.

    parquet 파일 해시가 아니라 값의 해시다. 파일은 압축·조각 구성에 따라
    달라지지만 값은 그렇지 않다 - 재현성은 값의 성질이지 파일의 성질이 아니다.
    """
    body = "\n".join(
        "%s %s %d %d %d %d %d" % (r["ticker"], r["ts"], r["open"], r["high"],
                                  r["low"], r["close"], r["volume"])
        for r in sorted(rows, key=lambda x: (x["ticker"], x["ts"])))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def compare_rows(a, b):
    """두 관측을 대조한다. '같다/다르다'로 끝내지 않고 어디가 갈렸는지 남긴다.

    필드별로 세는 이유는 축이 다르기 때문이다 - volume만 갈리면 정정 체결이고,
    가격이 통째로 비율만큼 갈리면 수정주가다. 한 칸에 넣으면 둘이 섞인다(교훈67).
    """
    PRICES = ("open", "high", "low", "close")
    ka = {(r["ticker"], r["ts"]): r for r in a}
    kb = {(r["ticker"], r["ts"]): r for r in b}
    only_a = sorted(set(ka) - set(kb))
    only_b = sorted(set(kb) - set(ka))
    fields = {}
    changed = []
    # 수정주가 판정은 '비율이 정확히 같은가'로 하면 절대 안 걸린다 - 가격은
    # 호가단위로 반올림되므로 105 -> 52는 0.5가 아니라 0.4952다. 그렇다고
    # 임의의 허용오차를 두면 그것이 곧 임계다(교훈51).
    # 반올림 자체가 주는 상한을 쓴다: 정수 v로 관측된 값의 참값은 [v-0.5, v+0.5]
    # 안에 있으므로 비율은 [(v-0.5)/p, (v+0.5)/p] 안에 있다. 이 구간들이 모두
    # 겹치면 '단일 비율 하나로 설명된다'가 성립한다. 유도된 경계이지 취향이 아니다.
    lo, hi = 0.0, float("inf")
    all4 = 0
    for k in sorted(set(ka) & set(kb)):
        ra, rb = ka[k], kb[k]
        diff = [f for f in PRICES + ("volume",) if ra[f] != rb[f]]
        if not diff:
            continue
        changed.append({"key": list(k), "fields": diff,
                        "before": {f: ra[f] for f in diff},
                        "after": {f: rb[f] for f in diff}})
        for f in diff:
            fields[f] = fields.get(f, 0) + 1
        # 분할은 네 가격을 모두 옮긴다. 하나만 바뀐 것은 정정이지 재조정이 아니다.
        if all(f in diff for f in PRICES):
            all4 += 1
            for f in PRICES:
                if ra[f]:
                    lo = max(lo, (rb[f] - 0.5) / float(ra[f]))
                    hi = min(hi, (rb[f] + 0.5) / float(ra[f]))

    consistent = all4 > 0 and lo <= hi
    rng = [round(lo, 6), round(hi, 6)] if consistent else None
    return {
        "identical": not (only_a or only_b or changed),
        "rowsBefore": len(a), "rowsAfter": len(b),
        "missingInSecond": [list(k) for k in only_a[:10]],
        "addedInSecond": [list(k) for k in only_b[:10]],
        "missingCount": len(only_a), "addedCount": len(only_b),
        "changedCount": len(changed),
        "changedFields": fields,
        "samples": changed[:5],
        # 측정값을 남긴다. 구간이지 점이 아닌 것이 사실에 가깝다.
        "rowsWithAllPricesChanged": all4,
        "priceRatioRange": rng,
        "looksLikeAdjustment": bool(consistent and not (lo <= 1.0 <= hi)),
    }


# ---------------------------------------------------------------- 표본

def pick_sample(M, raw_root, universe_dir=None, state_dir=None):
    """표본은 의도적으로 고른다(§6.1). 무작위 5종목은 갈리는 축을 못 밟는다.

    고른 이유를 함께 남긴다. 나중에 '왜 이 종목인가'를 되짚을 수 없으면
    결과의 일반화 범위를 말할 수 없다.
    """
    chosen, axes = [], {}
    unmeasured = []

    def take(ticker, axis, why):
        if not ticker or any(c["ticker"] == ticker for c in chosen):
            return False
        chosen.append({"ticker": ticker, "axis": axis, "why": why})
        axes[axis] = ticker
        return True

    # 대형주 · 소형주 — 유니버스 스냅샷의 거래대금
    rows = []
    d = Path(universe_dir or (REPO / "data" / "backfill" / "minute" / "universe"))
    snaps = sorted(d.glob("*.jsonl")) if d.exists() else []
    if snaps:
        for line in safe(lambda: snaps[-1].read_text(encoding="utf-8"), "").splitlines():
            if line.strip():
                r = safe(lambda l=line: json.loads(l))
                if r:
                    rows.append(r)
    rows.sort(key=lambda r: r.get("turnoverEok") or 0, reverse=True)
    if rows:
        for r in rows[:2]:
            take(r["ticker"], "대형주",
                 "거래대금 상위 %.0f억 (%s)" % (r.get("turnoverEok") or 0, snaps[-1].name))
        for r in [x for x in rows if (x.get("turnoverEok") or 0) > 0][-2:]:
            take(r["ticker"], "소형주",
                 "거래대금 하위 %.2f억" % (r.get("turnoverEok") or 0))
    else:
        unmeasured.append("대형주·소형주 — 유니버스 스냅샷이 없다")

    # 거래정지 이력 — Broad 수집 상태에서 HALT가 실제로 난 종목을 쓴다.
    # 추측이 아니라 우리가 관측한 사실에서 고른다.
    halted = []
    sd = Path(state_dir or (Path(raw_root) / "_state"))
    for p in sorted(sd.glob("state-*.json"))[-5:] if sd.exists() else []:
        st = safe(lambda p=p: json.loads(p.read_text(encoding="utf-8"))) or {}
        for tk, v in (st.get("symbols") or {}).items():
            if v.get("gapReason") == "HALT":
                halted.append((tk, p.name))
    if halted:
        take(halted[0][0], "거래정지이력",
             "Broad 수집에서 HALT 관측 (%s)" % halted[0][1])
    else:
        unmeasured.append("거래정지이력 — 수집 상태에 HALT가 없다")

    # 신규상장 — A1a의 listedAt 최신
    a1a = [r for r in M.read_a1a() if r.get("listedAt")]
    a1a.sort(key=lambda r: r["listedAt"], reverse=True)
    if a1a:
        take(a1a[0]["ticker"], "신규상장", "상장일 " + a1a[0]["listedAt"])
    else:
        unmeasured.append("신규상장 — A1a에 listedAt이 없다")

    # 액면분할 이력 — 확보 수단이 없다.
    # A2a는 adjusted=true라 분할이 이미 반영돼 불연속이 남지 않고, 분할 원장도 없다.
    # 잴 수 없는 것을 통과로 적지 않는다(교훈50).
    unmeasured.append(
        "액면분할이력 — 표본 확보 수단이 없다. A2a는 수정주가라 불연속이 남지 "
        "않고 분할 원장도 없다. 7일 안에 분할이 없으면 '수정주가 변경 없음'은 "
        "확인이 아니라 미관측이다(§6.1)")

    missing = [a for a in REQUIRED_AXES if a not in axes]
    return chosen, unmeasured, missing


def target_dates(M, ctx, raw_root, back=3):
    """대상 날짜. 재현성은 '같은 날짜를 다시 받는가'라 날짜를 고정해야 한다.

    이미 Broad로 받은 날을 쓴다. 그래야 Broad manifest의 dayVerdict를 참조로
    끌어올 수 있고, T1이 새 호출로 없던 날을 만들지 않는다.
    """
    got = sorted(p.name.split("=")[1]
                 for p in Path(raw_root).glob("date=*") if "=" in p.name)
    return got[-back:] if got else []


# ---------------------------------------------------------------- 실행

def read_day_verdict(manifest_dir, date):
    """그날의 dayVerdict를 Broad manifest에서 읽어온다. 계산하지 않는다.

    표본 열 종목으로 날짜 단위 판정을 흉내 내면 그건 측정이 아니라 추측이다.
    """
    p = Path(manifest_dir) / (date + ".json")
    m = safe(lambda: json.loads(p.read_text(encoding="utf-8")))
    if not m:
        return None, "미측정 — 그날 Broad manifest가 없다"
    return m.get("dayVerdict"), "broad-manifest"


def observe(M, transport, ticker, date, pol, ctx):
    """한 관측. 호출 수와 결과를 함께 남긴다."""
    calls = {"n": 0}
    inner = transport

    class Counting:
        def fetch(self, tk, sent, hour, p):
            calls["n"] += 1
            return inner.fetch(tk, sent, hour, p)

    t0 = time.time()
    o = M.collect_symbol_day(Counting(), ticker, date, pol, ctx)
    rows = list(o.rows)
    return {
        "ticker": ticker, "date": date,
        "requestedAt": stamp(),
        "elapsedSec": round(time.time() - t0, 2),
        "calls": calls["n"], "attempts": o.attempts,
        "status": o.status,
        "rows": len(rows),
        "gapReason": o.gap_reason,
        "failureClass": o.failure_class,
        "sha256": rows_sha(rows) if rows else None,
        "firstTs": rows[0]["ts"] if rows else None,
        "lastTs": rows[-1]["ts"] if rows else None,
        "_rows": rows,
    }


def prior_runs(d):
    out = []
    for p in sorted(Path(d).glob("t1-*.json")):
        r = safe(lambda p=p: json.loads(p.read_text(encoding="utf-8")))
        if r:
            out.append((p.name, r))
    return out


def run(M, args, out=print):
    pol = M.load_policy()
    ctx = M.load_context()
    raw, state, mandir = M.env_paths(pol)
    outdir = t1_dir()

    sample, unmeasured, missing_axes = pick_sample(M, raw, state_dir=state)
    dates = target_dates(M, ctx, raw, back=args.dates)

    out("")
    out("  T1 수집 신뢰성 정찰   " + stamp())
    out("  표본 " + str(len(sample)) + "종목 · 대상 " + str(len(dates)) + "일 · 출력 "
        + str(outdir))
    for s in sample:
        out("    " + s["ticker"] + "  " + s["axis"].ljust(12) + s["why"])
    for u in unmeasured:
        out("    [미측정] " + u)
    if not dates:
        out("  [중단] 대상 날짜가 없다 - Broad 수집물이 " + str(raw) + "에 없다")
        return 2, None
    out("  대상 날짜 " + ", ".join(dates))
    out("")

    if args.dry_run:
        out("  --dry-run: 부르지 않았다")
        return 0, None

    if not sample:
        out("  [중단] 표본이 비었다")
        return 2, None

    key, sec = M.credentials()
    token, how = M.get_token(key, sec)
    tr = M.KisTransport(key, sec, token)

    run_id = now_kst().strftime("%Y%m%dT%H%M%S")
    obs, repeats = [], []
    for s in sample:
        for d in dates:
            a = observe(M, tr, s["ticker"], d, pol, ctx)
            # 즉시 재실행 — 전송 흔들림과 데이터 변화를 가른다.
            # 첫 날짜에만 한다. 전부 하면 호출이 두 배가 되는데 얻는 것은 같다.
            if d == dates[-1]:
                b = observe(M, tr, s["ticker"], d, pol, ctx)
                cmp_ = compare_rows(a["_rows"], b["_rows"])
                cmp_.update({"ticker": s["ticker"], "date": d,
                             "shaA": a["sha256"], "shaB": b["sha256"]})
                repeats.append(cmp_)
                obs.append({k: v for k, v in b.items() if k != "_rows"})
            obs.append({k: v for k, v in a.items() if k != "_rows"})
            a["axis"] = s["axis"]

    # --- 일자 간 대조 --------------------------------------------------------
    # 어제 이 스크립트가 남긴 관측과 오늘 것을 (종목,날짜)로 맞춰 본다.
    cross = []
    for name, prev in prior_runs(outdir):
        idx = {}
        for o in prev.get("observations") or []:
            if o.get("sha256"):
                idx[(o["ticker"], o["date"])] = o
        for o in obs:
            k = (o["ticker"], o["date"])
            if k in idx and o.get("sha256"):
                p = idx[k]
                cross.append({
                    "ticker": o["ticker"], "date": o["date"],
                    "prevRun": name, "prevRequestedAt": p.get("requestedAt"),
                    "prevSha": p["sha256"], "sha": o["sha256"],
                    "identical": p["sha256"] == o["sha256"],
                    "prevRows": p.get("rows"), "rows": o.get("rows"),
                })

    verdicts = {}
    for d in dates:
        v, src = read_day_verdict(mandir, d)
        verdicts[d] = {"dayVerdict": v, "source": src}

    gaps = {}
    for o in obs:
        if o.get("gapReason"):
            gaps[o["gapReason"]] = gaps.get(o["gapReason"], 0) + 1

    report = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "startedAt": stamp(),
        "host": os.environ.get("HOSTNAME") or "unknown",
        "policyVersion": pol["version"],
        "collectionContractHash": M.sha256_bytes(
            json.dumps(pol["collectionContract"], sort_keys=True,
                       ensure_ascii=False).encode("utf-8")),
        "tokenSource": how,
        "sample": sample,
        "sampleAxesMissing": missing_axes,
        "unmeasured": unmeasured,
        "targetDates": dates,
        "symbolCount": len(sample),
        "requestCount": sum(o.get("calls") or 0 for o in obs),
        "observationCount": len(obs),
        "okCount": sum(1 for o in obs if o["status"] == "OK"),
        "gapCount": sum(1 for o in obs if o["status"] == "GAP"),
        "unresolvedCount": sum(1 for o in obs if o["status"] == "UNRESOLVED"),
        "gapReasons": gaps,
        "dayVerdicts": verdicts,
        "observations": obs,
        "immediateRepeat": repeats,
        "crossRun": cross,
        "reproducibilityMethod": {
            "note": "비교 '방법'만 확정한다. '며칠 안에 몇 %까지 갈려도 정상인가'는 "
                    "7일 측정 뒤에 정한다 - 지금 임계를 박으면 그 임계에 맞는 답만 "
                    "나온다(교훈51).",
            "unit": "(ticker, date)",
            "fields": ["ticker", "ts", "open", "high", "low", "close", "volume"],
            "equality": "전 필드 완전일치. 허용 오차 없음",
            "hash": "rows sha256 — (ticker, ts) 정렬 후 값 직렬화",
            "adjustmentSignal": "가격 넷이 한 비율로 갈리면 수정주가 재조정",
            "thresholdDecided": False,
        },
        "notAMeasurement": [
            "dayVerdict는 T1이 계산하지 않는다. 전 종목 범위의 값이라 표본으로 "
            "흉내 내면 추측이 된다(교훈73). Broad manifest에서 읽어 참조로만 둔다.",
            "이 산출물은 manifest가 아니다. 인수 조건을 통과했다는 뜻을 담지 않는다.",
        ],
    }

    outdir.mkdir(parents=True, exist_ok=True)
    p = outdir / ("t1-" + run_id + ".json")
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    out("  관측 %d · 호출 %d · OK %d · GAP %d · 미해결 %d"
        % (report["observationCount"], report["requestCount"],
           report["okCount"], report["gapCount"], report["unresolvedCount"]))
    for r in repeats:
        out("  즉시재실행  " + r["ticker"] + " " + r["date"] + "  " +
            ("동일" if r["identical"] else
             "다름 rows %d->%d 변경 %d %s" % (r["rowsBefore"], r["rowsAfter"],
                                            r["changedCount"],
                                            json.dumps(r["changedFields"],
                                                       ensure_ascii=False))))
    if cross:
        same = sum(1 for c in cross if c["identical"])
        out("  일자간대조  %d건 중 동일 %d · 다름 %d"
            % (len(cross), same, len(cross) - same))
        for c in cross:
            if not c["identical"]:
                out("    다름  " + c["ticker"] + " " + c["date"] +
                    "  rows %s->%s  (%s)" % (c["prevRows"], c["rows"],
                                             c["prevRun"]))
    else:
        out("  일자간대조  없음 (첫 실행이다. 내일부터 쌓인다)")
    out("  " + str(p))
    out("")
    return 0, report


def report_only(out=print):
    d = t1_dir()
    runs = prior_runs(d)
    if not runs:
        out("  T1 관측이 없다: " + str(d))
        return 1
    out("")
    out("  T1 누적 요약   실행 " + str(len(runs)) + "회")
    tot = same = 0
    for name, r in runs:
        c = r.get("crossRun") or []
        s = sum(1 for x in c if x["identical"])
        tot += len(c)
        same += s
        out("  %s  관측 %3d · 호출 %4d · 일자간 %d/%d 동일"
            % (r.get("runId"), len(r.get("observations") or []),
               r.get("requestCount") or 0, s, len(c)))
    out("")
    out("  누적 일자간 대조  %d건 중 동일 %d" % (tot, same))
    if tot == 0:
        out("  재현성: 미측정 (대조 쌍이 아직 없다)")
    else:
        out("  재현성: %d/%d = %.4f  ← 임계는 아직 정하지 않았다" %
            (same, tot, same / float(tot)))
    um = sorted({u for _, r in runs for u in (r.get("unmeasured") or [])})
    for u in um:
        out("  [미측정] " + u)
    out("")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", type=int, default=2,
                    help="최근 수집일 중 몇 개를 대상으로 할 것인가")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        p = REPO / "scripts" / "test-probe-t1-minute.py"
        if not p.exists():
            print("테스트 파일이 없다")
            return 1
        spec = importlib.util.spec_from_file_location("t", p)
        t = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(t)
        return t.run_all(sys.modules[__name__])

    if args.report:
        return report_only()

    M = load_collector()
    try:
        code, _ = run(M, args)
    except SystemExit as e:
        print("  [중단] " + str(e))
        return 2
    return code


if __name__ == "__main__":
    sys.exit(main())
